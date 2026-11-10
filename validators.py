import ast
import re

FORBIDDEN_IMPORTS = {
    "os", "subprocess", "socket", "requests", "urllib", "http", "shutil", "ctypes", "pathlib",
    "importlib", "multiprocessing", "threading", "asyncio", "pickle", "builtins", "glob",
    "tempfile", "signal", "inspect", "linecache", "gc", "traceback", "code", "codeop", "runpy",
    "ssl", "smtplib", "ftplib", "webbrowser",
}
HIDDEN_TEST_PREFIXES = ("test_", "conftest")
FORBIDDEN_CALLS = {"eval", "exec", "compile", "open", "__import__", "input", "breakpoint", "exit", "quit"}


def function_name_from_task(task):
    m = re.search(r"\bfunction\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", task or "")
    return m.group(1) if m else ""


def _parse(source, label, problems):
    try:
        return ast.parse(source)
    except SyntaxError as e:
        problems.append(f"{label} has a syntax error on line {e.lineno}: {e.msg}")
        return None


def check_solution(source, expected_name, problems):
    tree = _parse(source, "solution.py", problems)
    if tree is None:
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in FORBIDDEN_IMPORTS or root.startswith(HIDDEN_TEST_PREFIXES):
                    problems.append(f"solution.py imports the forbidden module '{root}'. Use only pure Python.")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in FORBIDDEN_IMPORTS or root.startswith(HIDDEN_TEST_PREFIXES):
                problems.append(f"solution.py imports the forbidden module '{root}'. Use only pure Python.")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
            problems.append(f"solution.py calls the forbidden function '{node.func.id}()'.")
    if expected_name:
        names = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        if expected_name not in names:
            problems.append(f"solution.py must define a top-level function named '{expected_name}'.")


def check_tests(source, expected_name, problems):
    if "pytest" in source:
        problems.append("test_solution.py must not use pytest. Use plain assert statements inside test_ functions.")
    tree = _parse(source, "test_solution.py", problems)
    if tree is None:
        return
    imports_solution = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "") == "solution":
            imports_solution = True
        elif isinstance(node, ast.ImportFrom) or isinstance(node, ast.Import):
            problems.append("test_solution.py may only contain 'from solution import ...'.")
    if not imports_solution:
        problems.append("test_solution.py must start with 'from solution import ...'.")
    for node in tree.body:
        if isinstance(node, ast.Assert):
            problems.append("test_solution.py has an assert outside a test_ function. Move it inside one.")
            break
    tests = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
    if not tests:
        problems.append("test_solution.py needs at least one function whose name starts with test_.")
    real_asserts = 0
    for fn in tests:
        for node in ast.walk(fn):
            if isinstance(node, ast.Assert):
                if isinstance(node.test, ast.Constant):
                    continue
                real_asserts += 1
    if tests and real_asserts == 0:
        problems.append("The tests contain no meaningful assert statements.")
    if expected_name and tests:
        called = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == expected_name
                     for n in ast.walk(tree))
        if not called:
            problems.append(f"The tests never call '{expected_name}'.")


def check_files(files, task):
    problems = []
    for name in ("solution.py", "test_solution.py"):
        if name not in files:
            problems.append(f"The answer has no file called {name}. Use the line 'FILE: {name}' before its code.")
    if not problems:
        expected = function_name_from_task(task)
        check_solution(files["solution.py"], expected, problems)
        check_tests(files["test_solution.py"], expected, problems)
    return {"ok": not problems, "problems": problems}


def route_from_answer(answer):
    for ch in (answer or "").upper():
        if ch in "AB":
            return ("SIMPLE" if ch == "A" else "HARD"), False
    return "HARD", True


def plan_is_valid(plan):
    steps = re.findall(r"^\s*\d+[.)]\s+\S", plan or "", re.M)
    return 2 <= len(steps) <= 6 and "```" not in (plan or "")


def error_line(text):
    lines = [" ".join(line.split()) for line in (text or "").splitlines()]
    for s in lines:
        if "Error:" in s or "AssertionError" in s:
            return s
    for s in lines:
        if s.startswith("E "):
            return s
    return ""


def diagnose(result):
    text = result or ""
    failing = re.findall(r"^FAILED\s+(\S+)", text, re.M)
    if "TIMEOUT" in text:
        category = "timeout"
    elif "VALIDATION FAILED" in text:
        category = "validation"
    elif "Coder did not produce" in text:
        category = "missing_file"
    elif "SyntaxError" in text:
        category = "syntax"
    elif "NameError" in text:
        category = "name"
    elif "ImportError" in text or "ModuleNotFoundError" in text:
        category = "import"
    elif "AssertionError" in text or re.search(r"^E\s+assert", text, re.M):
        category = "assertion"
    elif text.strip():
        category = "other"
    else:
        category = "unknown"
    return {"category": category, "failing_tests": failing, "error": error_line(text)}


def facts_text(result):
    d = diagnose(result)
    parts = [f"Error type: {d['category']}"]
    if d["failing_tests"]:
        parts.append("Failing tests: " + ", ".join(d["failing_tests"][:6]))
    if d["error"]:
        parts.append("First error line: " + d["error"][:200])
    return "\n".join(parts)


def sanitize_hint(hint, result):
    low_hint = (hint or "").lower()
    low_result = (result or "").lower()
    for word in ("docker", "daemon", "api key", "internet connection"):
        if word in low_hint and word not in low_result:
            return facts_text(result), True
    return hint, False


RULES = {
    "syntax": "Generated files must contain only valid Python: close every quote and bracket, and leave out markdown fences and divider lines such as ---.",
    "name": "Import every name a test uses, for example 'from solution import function_name'.",
    "import": "Use only 'from solution import ...' in tests and only the standard library in solutions.",
    "assertion": "Check the function's output against each expected value and every rule in the task, including the return type (list, not tuple).",
    "timeout": "Avoid infinite loops and very slow algorithms: tests are stopped after 60 seconds.",
    "missing_file": "Always write both files, each starting with a 'FILE: name.py' line.",
}


def rule_for(result):
    d = diagnose(result)
    if d["category"] == "validation":
        low = (result or "").lower()
        if "forbidden" in low:
            return "Do not import os, subprocess, socket or similar modules, and do not call open(), eval() or exec(). Use pure Python."
        if "outside a test_ function" in low:
            return "Put every assert inside a function whose name starts with test_."
        if "pytest" in low:
            return "Do not use pytest in tests. Use plain asserts inside test_ functions."
        if "must define" in low:
            return "Define exactly the function name given in the task, at the top level of solution.py."
        return "Follow the file format exactly: two files, each starting with a 'FILE: name.py' line."
    return RULES.get(d["category"], "Read the full test error and fix its cause before changing anything else.")


def judge_verdict(answer):
    for line in (answer or "").splitlines():
        first = line.strip().upper().lstrip("*# ")
        if first:
            return "REJECT" if first.startswith("REJECT") else "APPROVE"
    return "APPROVE"

def reviewer_verdict(answer, tests_passed):
    for line in (answer or "").splitlines():
        up = line.strip().upper()
        if not up:
            continue
        if "APPROVE" in up:
            return "APPROVE"
        if "REJECT" in up:
            return "REJECT"
        if "HINT" in up:
            return "HINT"
        break
    return "APPROVE" if tests_passed else "HINT"
