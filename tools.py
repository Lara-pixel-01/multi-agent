import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.join(BASE, "workspace")
LESSONS_PATH = os.path.join(BASE, "knowledge", "LESSONS.md")
LOG_DIR = os.path.join(BASE, "eval-results")
TOOL_LOG = os.path.join(LOG_DIR, "tool-calls.jsonl")
os.makedirs(WORKSPACE, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

SANDBOX_IMAGE = "agent-sandbox"
FILE_RE = re.compile(r"^[A-Za-z0-9_]+\.py$")
TEST_RE = re.compile(r"^test_[A-Za-z0-9_]*\.py$")
MAX_CONTENT = 60000
WORKSPACE_MOUNT = "ro"
LOG_TOOLS = True

REGISTRY = {}
STATS = {"calls": 0, "ok": 0, "denied": 0, "errors": 0}


class ToolError(Exception):
    pass


class PermissionDenied(ToolError):
    pass


def reset_stats():
    for k in STATS:
        STATS[k] = 0


def register(name, description, parameters, required=(), check=None):
    def deco(fn):
        REGISTRY[name] = {"description": description, "parameters": parameters,
                          "required": list(required), "check": check, "fn": fn}
        return fn
    return deco


def schemas():
    out = []
    for name, t in REGISTRY.items():
        out.append({"type": "function", "function": {
            "name": name, "description": t["description"],
            "parameters": {"type": "object", "properties": t["parameters"], "required": t["required"]}}})
    return out


def validate(name, args):
    if name not in REGISTRY:
        raise ToolError(f"unknown tool '{name}'")
    tool = REGISTRY[name]
    if not isinstance(args, dict):
        raise ToolError("arguments must be an object")
    for key in args:
        if key not in tool["parameters"]:
            raise ToolError(f"unknown argument '{key}' for {name}")
    for key in tool["required"]:
        if key not in args:
            raise ToolError(f"missing argument '{key}' for {name}")
    for key, value in args.items():
        if not isinstance(value, str):
            raise ToolError(f"argument '{key}' must be text")
    if tool["check"]:
        tool["check"](args)


def _log(entry):
    if not LOG_TOOLS:
        return
    try:
        with open(TOOL_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def call(name, **args):
    started = time.time()
    status, error = "ok", ""
    STATS["calls"] += 1
    try:
        validate(name, args)
        return REGISTRY[name]["fn"](**args)
    except PermissionDenied as e:
        status, error = "denied", str(e)
        STATS["denied"] += 1
        raise
    except ToolError as e:
        status, error = "error", str(e)
        STATS["errors"] += 1
        raise
    except Exception as e:
        status, error = "error", str(e)
        STATS["errors"] += 1
        raise ToolError(str(e)) from e
    finally:
        if status == "ok":
            STATS["ok"] += 1
        _log({"time": datetime.now().isoformat(timespec="seconds"), "tool": name, "status": status,
              "error": error[:200], "seconds": round(time.time() - started, 3),
              "args": {k: (v[:60] if isinstance(v, str) else v) for k, v in args.items()}})



def _check_filename(args, key="path", pattern=FILE_RE):
    value = args[key]
    if not pattern.match(value):
        raise PermissionDenied(f"'{value}' is not an allowed file name. Only plain names such as solution.py are allowed.")


def _check_write(args):
    _check_filename(args)
    if len(args["content"]) > MAX_CONTENT:
        raise PermissionDenied("content is too large")


def _check_test_file(args):
    _check_filename(args, "test_file", TEST_RE)


def _check_lesson(args):
    if len(args["text"]) > 300:
        raise PermissionDenied("a lesson may have at most 300 characters")



@register("write_file", "Write a Python file into the workspace folder.",
          {"path": {"type": "string", "description": "File name such as solution.py"},
           "content": {"type": "string", "description": "The complete file text"}},
          ["path", "content"], _check_write)
def write_file(path, content):
    with open(os.path.join(WORKSPACE, path), "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    return f"wrote {len(content)} characters to {path}"


@register("read_file", "Read a Python file from the workspace folder.",
          {"path": {"type": "string", "description": "File name such as solution.py"}},
          ["path"], _check_filename)
def read_file(path):
    full = os.path.join(WORKSPACE, path)
    if not os.path.exists(full):
        raise ToolError(f"{path} does not exist")
    with open(full, encoding="utf-8") as f:
        return f.read()[:20000]


@register("list_files", "List the Python files in the workspace folder.", {}, [])
def list_files():
    return sorted(n for n in os.listdir(WORKSPACE) if FILE_RE.match(n))


@register("clear_workspace", "Delete every Python file in the workspace folder.", {}, [])
def clear_workspace():
    count = 0
    for name in os.listdir(WORKSPACE):
        if FILE_RE.match(name):
            os.remove(os.path.join(WORKSPACE, name))
            count += 1
    shutil.rmtree(os.path.join(WORKSPACE, "__pycache__"), ignore_errors=True)
    return count


def docker_runner(test_file):
    cmd = ["docker", "run", "--rm", "--network", "none", "--read-only", "--tmpfs", "/tmp",
           "--memory", "512m", "--cpus", "1", "--pids-limit", "128", "--cap-drop", "ALL",
           "--security-opt", "no-new-privileges", "-e", "PYTHONDONTWRITEBYTECODE=1",
           "-v", f"{WORKSPACE}:/work:{WORKSPACE_MOUNT}", SANDBOX_IMAGE,
           "timeout", "60", "python", "-m", "pytest", "-q", "-p", "no:cacheprovider", test_file]
    started = time.time()
    try:
        run = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=120)
    except subprocess.TimeoutExpired:
        return {"passed": False, "timed_out": True, "seconds": round(time.time() - started, 1),
                "output": "TIMEOUT: the tests did not finish in 120 seconds."}
    output = run.stdout + run.stderr
    timed_out = run.returncode == 124
    if timed_out:
        output += "\nTIMEOUT: the tests did not finish in 60 seconds (possible infinite loop)."
    return {"passed": run.returncode == 0, "timed_out": timed_out,
            "seconds": round(time.time() - started, 1), "output": output}


RUNNER = docker_runner


@register("run_tests", "Run a test file inside the locked sandbox (no internet, limited memory).",
          {"test_file": {"type": "string", "description": "Test file name such as test_solution.py"}},
          ["test_file"], _check_test_file)
def run_tests(test_file):
    if not os.path.exists(os.path.join(WORKSPACE, test_file)):
        raise ToolError(f"{test_file} does not exist in the workspace")
    return RUNNER(test_file)


@register("read_lessons", "Read the saved lessons from earlier runs.", {}, [])
def read_lessons():
    with open(LESSONS_PATH, encoding="utf-8-sig") as f:
        return f.read()


@register("add_lesson", "Save one short lesson (at most 300 characters) for future runs.",
          {"text": {"type": "string", "description": "The lesson as one sentence"}},
          ["text"], _check_lesson)
def add_lesson(text):
    text = " ".join(text.split())
    with open(LESSONS_PATH, encoding="utf-8-sig") as f:
        existing = f.read()
    if text[:50] in existing:
        return "already recorded"
    with open(LESSONS_PATH, "a", encoding="utf-8") as f:
        f.write("\n- " + text + "\n")
    return "saved"
