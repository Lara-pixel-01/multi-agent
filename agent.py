import os
import operator
import time
from dataclasses import dataclass
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, END

import llm
import memory
import tools
import validators

ROUTER_MODEL = "ministral-3:3b"
SMALL_CODER = "ministral-3:3b"
BIG_MODEL = "qwen3.5:4b"
VERIFIER_MODEL = "qwen2.5-coder:7b"
JUDGE_MODEL = VERIFIER_MODEL
REVIEWER_MODEL = "qwen3.5:4b"
PLANNER_MODEL = "qwen3.5:4b"
BASE = os.path.dirname(os.path.abspath(__file__))


@dataclass(frozen=True)
class Config:
    name: str = "full"
    multiagent: bool = True
    planner_agent: bool = True
    force_agent_for_simple: bool = False
    use_router: bool = True
    use_planner: bool = True
    use_validator: bool = True
    use_verifier: bool = True
    use_judge: bool = False
    memory_mode: str = "full"
    save_lessons: bool = True
    max_retries: int = 3
    fixed_model: str = ""
    coder_max_loops: int = 4
    reviewer_max_loops: int = 3
    planner_max_loops: int = 3


def solo(name, model):
    return Config(name, multiagent=False, planner_agent=False, force_agent_for_simple=False,
                  use_router=False, use_planner=False, use_validator=False,
                  use_verifier=False, memory_mode="none", save_lessons=False, max_retries=0, fixed_model=model)


PRESETS = {c.name: c for c in [
    Config("full"),
    Config("full_agents", force_agent_for_simple=True),
    Config("full_no_planner_agent", planner_agent=False),
    Config("full_pipeline", multiagent=False, planner_agent=False),
    Config("full_judge", multiagent=False, planner_agent=False, use_judge=True),
    Config("baseline", multiagent=False, planner_agent=False, use_router=False, use_planner=False,
           use_validator=False, use_verifier=False, memory_mode="none", save_lessons=False,
           max_retries=0, fixed_model=BIG_MODEL),
    Config("naive_retry", multiagent=False, planner_agent=False, use_router=False, use_planner=False,
           use_validator=False, use_verifier=False, memory_mode="none", save_lessons=False,
           max_retries=3, fixed_model=BIG_MODEL),
    solo("solo_ministral", "ministral-3:3b"),
    solo("solo_qwen25coder", "qwen2.5-coder:7b"),
    solo("solo_phi4mini", "phi4-mini:latest"),
    solo("solo_granite", "granite4.2:3b"),
    solo("solo_nemotron", "nemotron-3-nano:4b"),
    solo("solo_qwen3", "qwen3:4b"),
    Config("no_router", use_router=False),
    Config("no_planner", use_planner=False),
    Config("graph_memory", memory_mode="graph"),
    Config("no_verifier", use_verifier=False),
    Config("no_validator", use_validator=False),
    Config("no_knowledge", memory_mode="none"),
    Config("vector_memory", memory_mode="vector"),
    Config("pageindex_memory", memory_mode="pageindex"),
]}


class State(TypedDict):
    task: str
    reference: str
    memory: str
    reviewer_memory: str
    planner_memory: str
    route: str
    coder_model: str
    plan: str
    code: str
    result: str
    problems: str
    validation_failed: bool
    review: str
    test_file: str
    passed: bool
    retries: int
    failed_before: bool
    last_failure: str
    messages: Annotated[list, operator.add]


RUN = {}


def reset_run():
    RUN.clear()
    RUN.update({"timings": {}, "validation_failures": 0, "plan_valid": None, "plan_valid_first_try": None,
                "router_fallback": False, "hints_sanitized": 0, "memory_chars": 0, "timed_out": False,
                "memory_fallback": False, "lesson_saved": False, "path": [], "judge_rejections": 0,
                "coder_loops": 0, "reviewer_tool_calls": 0, "reviewer_rejections": 0,
                "planner_tool_calls": 0, "planner_loops": 0})
    llm.CALLS.clear()
    tools.reset_stats()


def load(relative_path):
    with open(os.path.join(BASE, relative_path), encoding="utf-8-sig") as f:
        return f.read()


def split_files(text):
    files, current = {}, None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("FILE:"):
            current = s[5:].strip()
            files[current] = []
        elif current and not (s.startswith("```") or s in ("---", "***", "___")):
            files[current].append(line)
    return {name: "\n".join(lines) + "\n" for name, lines in files.items()}


def timed(name, fn):
    def wrapper(state):
        started = time.time()
        RUN["path"].append(name)
        try:
            return fn(state)
        finally:
            RUN["timings"][name] = RUN["timings"].get(name, 0) + time.time() - started
    return wrapper


def _cfg_key(cfg):
    return (cfg.name, cfg.multiagent, cfg.planner_agent, cfg.force_agent_for_simple,
            cfg.use_router, cfg.use_planner, cfg.use_validator, cfg.use_verifier, cfg.use_judge,
            cfg.memory_mode, cfg.save_lessons, cfg.max_retries, cfg.fixed_model,
            cfg.coder_max_loops, cfg.reviewer_max_loops, cfg.planner_max_loops)


def _last_msg(state, to, mtype):
    for m in reversed(state.get("messages") or []):
        if m.get("to") == to and m.get("type") == mtype:
            return m.get("content", "")
    return None


def build_app(cfg):
    def recall(state):
        if cfg.multiagent:
            text = memory.coder_context(state["task"], cfg.memory_mode) if cfg.memory_mode != "none" else ""
            rev = memory.reviewer_context(state["task"], cfg.memory_mode) if cfg.memory_mode != "none" else ""
            plan_mem = memory.planner_context(state["task"], cfg.memory_mode) if cfg.memory_mode != "none" else ""
            RUN["memory_chars"] = len(text)
            return {"memory": text, "reviewer_memory": rev, "planner_memory": plan_mem}
        text = memory.get_context(cfg.memory_mode, state["task"]) if cfg.memory_mode != "none" else ""
        RUN["memory_chars"] = len(text)
        RUN["memory_fallback"] = memory.LAST_FALLBACK["used"]
        return {"memory": text, "planner_memory": text}

    def router(state):
        if cfg.use_router:
            answer = llm.ask(ROUTER_MODEL, load("prompts/router.md").replace("{task}", state["task"]), role="router")
            route, fallback = validators.route_from_answer(answer)
            RUN["router_fallback"] = fallback
        else:
            answer, route = "(router off)", "HARD"
        model = cfg.fixed_model or (SMALL_CODER if route == "SIMPLE" else BIG_MODEL)
        print(f"Router answer: {answer.strip()!r} -> {route} -> coder model: {model}")
        return {"route": route, "coder_model": model}

    def after_router(state):
        if state["route"] == "SIMPLE" and not cfg.force_agent_for_simple:
            return "coder"
        if not cfg.use_planner:
            return "coder"
        return "planner"

    def planner_pipeline(state):
        base_prompt = (state.get("memory", "") + "\n\n" + load("prompts/planner.md").replace("{task}", state["task"]))
        plan = llm.ask(PLANNER_MODEL, base_prompt, role="planner")
        first_ok = validators.plan_is_valid(plan)
        RUN["plan_valid_first_try"] = first_ok
        if not first_ok:
            plan = llm.ask(PLANNER_MODEL, base_prompt + "\n\nReply again with only a numbered list of 2 to 6 steps and no code.", role="planner")
        RUN["plan_valid"] = validators.plan_is_valid(plan)
        update = {"plan": plan}
        if cfg.multiagent:
            update["messages"] = [{"from": "planner", "to": "coder", "type": "plan", "content": plan}]
        return update

    def planner_agent(state):
        base_prompt = (state.get("planner_memory", "") + "\n\n"
                       + load("prompts/planner_agent.md").replace("{task}", state["task"]))
        allowed = {"list_files", "read_file", "read_lessons"}
        planner_tools = [s for s in tools.schemas() if s["function"]["name"] in allowed]
        convo = [{"role": "user", "content": base_prompt}]
        plan_text = ""
        tool_calls_made = 0
        loop = 0

        for loop in range(1, cfg.planner_max_loops + 1):
            content, tool_calls, _ = llm.ask_with_tools(PLANNER_MODEL, convo, planner_tools, role=f"planner_loop_{loop}")
            if tool_calls:
                convo.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
                for tc in tool_calls:
                    name = tc["function"]["name"]
                    args = tc["function"].get("arguments") or {}
                    try:
                        result = tools.call(name, **args) if isinstance(args, dict) else tools.call(name)
                        result_str = result if isinstance(result, str) else str(result)
                    except tools.ToolError as e:
                        result_str = f"ERROR: {e}"
                    convo.append({"role": "tool", "content": result_str[:4000]})
                    tool_calls_made += 1
            elif validators.plan_is_valid(content):
                plan_text = content
                break
            else:
                convo.append({"role": "assistant", "content": content})
                convo.append({"role": "user", "content": "Reply with only a numbered list of 2 to 6 steps. No code, no markdown fences."})

        RUN["planner_tool_calls"] += tool_calls_made
        RUN["planner_loops"] += loop
        RUN["plan_valid_first_try"] = bool(plan_text)

        if not plan_text:
            regen_prompt = base_prompt + "\n\nBased on what you found, reply with only a numbered list of 2 to 6 steps. No code."
            plan_text = llm.ask(PLANNER_MODEL, regen_prompt, role="planner_regen")
        RUN["plan_valid"] = validators.plan_is_valid(plan_text)

        print(f"Planner agent: {tool_calls_made} tool calls, {loop} loops, plan_valid={validators.plan_is_valid(plan_text)}")
        update = {"plan": plan_text}
        if cfg.multiagent:
            update["messages"] = [{"from": "planner", "to": "coder", "type": "plan", "content": plan_text}]
        return update

    def planner(state):
        if cfg.planner_agent and cfg.multiagent:
            return planner_agent(state)
        return planner_pipeline(state)

    def coder_pipeline(state):
        model = state.get("coder_model") or BIG_MODEL
        prompt = state.get("memory", "") + "\n\n" + load("prompts/coder.md").replace("{task}", state["task"])
        if state.get("plan"):
            prompt += f"\n\nPlan:\n{state['plan']}\n"
        if state.get("result"):
            prompt += f"\nThe previous attempt failed. Output:\n{llm.clip(state['result'])}\n"
        if state.get("review"):
            prompt += f"\nReviewer hint: {llm.clip(state['review'], 800)}\n"
        print(f"Coder model (pipeline): {model}")
        return {"code": llm.ask(model, prompt, role="coder")}

    def coder_agent(state):
        model = state.get("coder_model") or BIG_MODEL
        base_prompt = state.get("memory", "") + "\n\n" + load("prompts/coder_agent.md").replace("{task}", state["task"])

        plan_msg = _last_msg(state, "coder", "plan")
        if plan_msg:
            print("Coder: read plan from BUS")
            base_prompt += f"\n\nPlan (from planner):\n{plan_msg}\n"
        elif state.get("plan"):
            print("Coder: plan from STATE (bus empty)")
            base_prompt += f"\n\nPlan:\n{state['plan']}\n"

        hint_msg = _last_msg(state, "coder", "hint")
        if hint_msg:
            print("Coder: read hint from BUS")
            base_prompt += f"\n\nReviewer hint: {llm.clip(hint_msg, 800)}\n"
        elif state.get("review"):
            print("Coder: hint from STATE (bus empty)")
            base_prompt += f"\n\nReviewer hint: {llm.clip(state['review'], 800)}\n"

        if state.get("result"):
            base_prompt += f"\nThe previous attempt failed. Output:\n{llm.clip(state['result'])}\n"

        allowed = {"write_file", "read_file", "run_tests", "list_files"}
        coder_tools = [s for s in tools.schemas() if s["function"]["name"] in allowed]
        convo = [{"role": "user", "content": base_prompt}]
        final_code = ""
        content = ""
        loop = 0

        tool_loops = max(1, cfg.coder_max_loops - 1)
        for loop in range(1, tool_loops + 1):
            content, tool_calls, _ = llm.ask_with_tools(model, convo, coder_tools, role=f"coder_loop_{loop}")
            if "FILE:" in content:
                final_code = content
                break
            if tool_calls:
                convo.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
                for tc in tool_calls:
                    name = tc["function"]["name"]
                    args = tc["function"].get("arguments") or {}
                    try:
                        result = tools.call(name, **args) if isinstance(args, dict) else tools.call(name)
                        result_str = result if isinstance(result, str) else str(result)
                    except tools.ToolError as e:
                        result_str = f"ERROR: {e}"
                    convo.append({"role": "tool", "content": result_str[:4000]})
            else:
                convo.append({"role": "assistant", "content": content})
                convo.append({"role": "user",
                              "content": "You have not produced a 'FILE:' answer yet. Either call a tool "
                                         "to inspect the workspace, or output the answer now starting with "
                                         "'FILE: solution.py'."})

        if not final_code:
            loop = cfg.coder_max_loops
            flat = "\n\n".join(f"[{m['role']}]\n{m.get('content', '')}" for m in convo if m.get("content"))
            flat += ("\n\n[user]\nYou are out of tool iterations. Do NOT call any tool. "
                     "Output the final answer NOW in exactly this format:\n"
                     "FILE: solution.py\n<code>\nFILE: test_solution.py\n<code>\n"
                     "No explanations, no markdown fences.")
            final_code = llm.ask(model, flat, role="coder_final")
            print(f"Forced output: has_FILE={'FILE:' in final_code}")

        RUN["coder_loops"] += loop
        print(f"Coder model (agent): {model}  loops: {loop}  has_FILE: {'FILE:' in final_code}")
        update = {"code": final_code, "coder_loops": loop}
        if cfg.multiagent:
            update["messages"] = [{"from": "coder", "to": "reviewer", "type": "review_request",
                                   "content": f"Code ready after {loop} loop(s)."}]
        return update

    def coder(state):
        model = state.get("coder_model") or BIG_MODEL
        route = state.get("route", "")
        use_agent = cfg.multiagent and (model == BIG_MODEL or (route == "SIMPLE" and cfg.force_agent_for_simple))
        if not use_agent:
            return coder_pipeline(state)
       
        if route == "SIMPLE" and model == SMALL_CODER:
            print(f"Force agent on SIMPLE: upgrading {SMALL_CODER} -> {BIG_MODEL}")
            model = BIG_MODEL
        result = coder_agent(state)
        result["coder_model"] = model
        return result

    def validate(state):
        check = validators.check_files(split_files(state["code"]), state["task"])
        if check["ok"]:
            return {"problems": "", "validation_failed": False}
        RUN["validation_failures"] += 1
        text = "VALIDATION FAILED before running any code:\n- " + "\n- ".join(check["problems"])
        print("Validator caught:", "; ".join(check["problems"])[:200])
        return {"problems": text, "validation_failed": True, "result": text, "passed": False, "test_file": ""}

    def executor(state):
        files = split_files(state["code"])
        for name in ("solution.py", "test_solution.py"):
            if name not in files:
                return {"result": f"Coder did not produce {name}", "passed": False, "test_file": ""}
        try:
            tools.call("clear_workspace")
            tools.call("write_file", path="solution.py", content=files["solution.py"])
            tools.call("write_file", path="test_solution.py", content=files["test_solution.py"])
            test_file = "test_solution.py"
            if state.get("reference"):
                with open(state["reference"], encoding="utf-8-sig") as f:
                    tools.call("write_file", path="test_reference.py", content=f.read())
                test_file = "test_reference.py"
            out = tools.call("run_tests", test_file=test_file)
        except tools.ToolError as e:
            return {"result": f"TOOL ERROR: {e}", "passed": False, "test_file": ""}
        if out.get("timed_out"):
            RUN["timed_out"] = True
        return {"result": out["output"], "passed": bool(out["passed"]), "test_file": test_file}

    def verifier_pipeline(state):
        facts = validators.facts_text(state["result"])
        prompt = (load("prompts/verifier.md")
                  .replace("{facts}", facts)
                  .replace("{test_file}", state.get("test_file") or "test_solution.py")
                  .replace("{code}", llm.clip(state["code"], 2500))
                  .replace("{result}", llm.clip(state["result"], 1200)))
        hint = llm.ask(VERIFIER_MODEL, prompt, role="verifier")
        hint, changed = validators.sanitize_hint(hint, state["result"])
        if changed:
            RUN["hints_sanitized"] += 1
        print("Verifier hint:", hint.strip()[:300])
        return {"review": hint}

    def reviewer_agent(state):
        base_prompt = state.get("reviewer_memory", "") + "\n\n" + (
            load("prompts/reviewer.md")
            .replace("{task}", state["task"])
            .replace("{code}", llm.clip(state["code"], 3000))
            .replace("{result}", llm.clip(state.get("result") or "", 1200))
        )
        pending = [m for m in (state.get("messages") or [])
                   if m.get("to") == "reviewer" and m.get("type") == "review_request"]
        if pending:
            print(f"Reviewer: received {len(pending)} review request(s) via bus.")

        allowed = {"read_file", "run_tests", "list_files", "read_lessons"}
        reviewer_tools = [s for s in tools.schemas() if s["function"]["name"] in allowed]
        convo = [{"role": "user", "content": base_prompt}]
        answer = ""
        tool_calls_made = 0

        for loop in range(1, cfg.reviewer_max_loops + 1):
            answer, tool_calls, _ = llm.ask_with_tools(REVIEWER_MODEL, convo, reviewer_tools, role=f"reviewer_loop_{loop}")
            if "VERDICT" in (answer or "").upper():
                break
            if tool_calls:
                convo.append({"role": "assistant", "content": answer, "tool_calls": tool_calls})
                for tc in tool_calls:
                    name = tc["function"]["name"]
                    args = tc["function"].get("arguments") or {}
                    try:
                        result = tools.call(name, **args) if isinstance(args, dict) else tools.call(name)
                        result_str = result if isinstance(result, str) else str(result)
                    except tools.ToolError as e:
                        result_str = f"ERROR: {e}"
                    convo.append({"role": "tool", "content": result_str[:4000]})
                    tool_calls_made += 1
            else:
                convo.append({"role": "assistant", "content": answer})
                convo.append({"role": "user",
                              "content": "Reply with 'VERDICT: APPROVE', 'VERDICT: REJECT', or "
                                         "'VERDICT: HINT' followed by a one-sentence reason."})

        RUN["reviewer_tool_calls"] += tool_calls_made
        verdict = validators.reviewer_verdict(answer, state.get("passed", False))
        if not state.get("passed") and verdict == "APPROVE":
            verdict = "HINT"

        lines = [l for l in (answer or "").strip().splitlines() if l.strip()]
        reason = " ".join(lines[1:])[:400] if len(lines) > 1 else (answer or "").strip()[:400]

        if verdict == "REJECT" and state.get("passed"):
            print(f"Reviewer REJECT downgraded to APPROVE (tests passed): {reason[:120]}")
            verdict = "APPROVE"

        print(f"Reviewer: {verdict} — {reason[:160]}")

        new_messages = [{"from": "reviewer", "to": "supervisor",
                         "type": f"verdict_{verdict.lower()}", "content": reason or (answer or "")[:400]}]
        if verdict == "REJECT" and state.get("passed"):
            RUN["reviewer_rejections"] += 1
            new_messages.append({"from": "reviewer", "to": "coder", "type": "hint", "content": reason})
            return {"passed": False, "result": f"REVIEWER REJECTED: {reason}",
                    "review": reason, "messages": new_messages}
        if verdict == "HINT":
            hint = reason or "See reviewer output."
            new_messages.append({"from": "reviewer", "to": "coder", "type": "hint", "content": hint})
            return {"review": hint, "messages": new_messages}
        return {"messages": new_messages}

    def review(state):
        model = state.get("coder_model") or BIG_MODEL
        if cfg.multiagent and model == BIG_MODEL:
            return reviewer_agent(state)
        return verifier_pipeline(state)

    def judge(state):
        prompt = load("prompts/judge.md").replace("{task}", state["task"]).replace("{code}", llm.clip(state["code"], 3000))
        answer = llm.ask(JUDGE_MODEL, prompt, role="judge")
        if validators.judge_verdict(answer) == "REJECT":
            RUN["judge_rejections"] += 1
            lines = [l for l in answer.strip().splitlines() if l.strip()]
            reason = " ".join(lines[1:])[:400] if len(lines) > 1 else answer.strip()[:400]
            return {"passed": False, "result": f"JUDGE REJECTED: {reason}", "review": reason}
        return {}

    def retry(state):
        update = {"retries": state.get("retries", 0) + 1, "failed_before": True,
                  "last_failure": state.get("result", ""),
                  "review": "" if state.get("validation_failed") else state.get("review", "")}
        if cfg.use_router and state.get("coder_model") == SMALL_CODER:
            update["coder_model"] = BIG_MODEL
            print("Escalating: small model failed, retrying with", BIG_MODEL)
        if cfg.multiagent:
            mtype = "escalation" if "coder_model" in update else "retry"
            update["messages"] = [{"from": "supervisor", "to": "coder", "type": mtype,
                                   "content": f"Attempt {update['retries']}"}]
        return update

    def after_validate(state):
        if not state["validation_failed"]:
            return "executor"
        return "save_lesson" if state.get("retries", 0) >= cfg.max_retries else "retry"

    def after_executor(state):
        model = state.get("coder_model") or BIG_MODEL
        use_reviewer = cfg.multiagent and model == BIG_MODEL
        if state["passed"]:
            if use_reviewer and state.get("retries", 0) < cfg.max_retries:
                return "reviewer"
            if cfg.use_judge and state.get("retries", 0) < cfg.max_retries:
                return "judge"
            return "save_lesson"
        if state.get("retries", 0) >= cfg.max_retries:
            return "save_lesson"
        if use_reviewer:
            return "reviewer"
        return "verifier" if cfg.use_verifier else "retry"

    def after_reviewer(state):
        if state["passed"]:
            return "save_lesson"
        if state.get("retries", 0) >= cfg.max_retries:
            return "save_lesson"
        return "retry"

    def after_judge(state):
        return "save_lesson" if state["passed"] else "retry"

    def save_lesson(state):
        if not (cfg.save_lessons and state.get("passed") and state.get("failed_before")):
            return {}
        if state.get("last_failure", "").startswith(("JUDGE REJECTED", "REVIEWER REJECTED")):
            return {}
        rule = validators.rule_for(state.get("last_failure", ""))
        try:
            outcome = tools.call("add_lesson", text=f"Rule: {rule}")
        except tools.ToolError as e:
            print("Could not save the lesson:", e)
            return {}
        if outcome == "saved":
            RUN["lesson_saved"] = True
        return {}

    g = StateGraph(State)
    g.add_node("recall", timed("memory_recall", recall))
    g.add_node("router", timed("router", router))
    g.add_node("planner", timed("planner", planner))
    g.add_node("coder", timed("coder", coder))
    g.add_node("validate", timed("validator", validate))
    g.add_node("executor", timed("executor", executor))
    g.add_node("retry", retry)
    g.add_node("save_lesson", save_lesson)

    g.set_entry_point("recall")
    g.add_edge("recall", "router")
    g.add_conditional_edges("router", after_router, {"coder": "coder", "planner": "planner"})
    g.add_edge("planner", "coder")

    if cfg.use_validator:
        g.add_edge("coder", "validate")
        g.add_conditional_edges("validate", after_validate,
                                {"executor": "executor", "retry": "retry", "save_lesson": "save_lesson"})
    else:
        g.add_edge("coder", "executor")

    executor_targets = {"save_lesson": "save_lesson", "retry": "retry"}

    if cfg.multiagent:
        g.add_node("reviewer", timed("reviewer", review))
        executor_targets["reviewer"] = "reviewer"
        g.add_conditional_edges("reviewer", after_reviewer, {"save_lesson": "save_lesson", "retry": "retry"})
    elif cfg.use_verifier:
        g.add_node("verifier", timed("verifier", verifier_pipeline))
        executor_targets["verifier"] = "verifier"
        g.add_edge("verifier", "retry")

    if cfg.use_judge:
        g.add_node("judge", timed("judge", judge))
        executor_targets["judge"] = "judge"
        g.add_conditional_edges("judge", after_judge, {"save_lesson": "save_lesson", "retry": "retry"})

    g.add_conditional_edges("executor", after_executor, executor_targets)
    g.add_edge("retry", "coder")
    g.add_edge("save_lesson", END)
    return g.compile()


_APPS = {}


def get_app(cfg):
    key = _cfg_key(cfg)
    if key not in _APPS:
        _APPS[key] = build_app(cfg)
    return _APPS[key]


def run_agent(task, reference="", cfg=None):
    cfg = cfg or PRESETS["full"]
    reset_run()
    started = time.time()
    state = {"task": task, "reference": reference, "memory": "", "reviewer_memory": "",
             "planner_memory": "", "route": "", "coder_model": "", "plan": "", "code": "",
             "result": "", "problems": "", "validation_failed": False, "review": "",
             "test_file": "", "passed": False, "retries": 0, "failed_before": False,
             "last_failure": "", "messages": []}
    final = get_app(cfg).invoke(state, {"recursion_limit": 150})
    record = {
        "config": cfg.name,
        "task": task[:80],
        "route": final.get("route", ""),
        "coder_model_final": final.get("coder_model", ""),
        "escalated": bool(cfg.use_router and final.get("route") == "SIMPLE" and final.get("coder_model") == BIG_MODEL),
        "passed": bool(final.get("passed")),
        "attempts": final.get("retries", 0) + 1,
        "seconds": round(time.time() - started, 1),
        "validation_failures": RUN["validation_failures"],
        "plan_valid": RUN["plan_valid"],
        "plan_valid_first_try": RUN["plan_valid_first_try"],
        "router_fallback": RUN["router_fallback"],
        "hints_sanitized": RUN["hints_sanitized"],
        "memory_chars": RUN["memory_chars"],
        "memory_fallback": RUN["memory_fallback"],
        "timed_out": RUN["timed_out"],
        "lesson_saved": RUN["lesson_saved"],
        "llm_calls": len(llm.CALLS),
        "prompt_tokens": sum(c["prompt_tokens"] for c in llm.CALLS),
        "generated_tokens": sum(c["generated_tokens"] for c in llm.CALLS),
        "tool_calls": tools.STATS["calls"],
        "tool_denied": tools.STATS["denied"],
        "tool_errors": tools.STATS["errors"],
        "node_seconds": {k: round(v, 1) for k, v in RUN["timings"].items()},
        "judge_rejections": RUN["judge_rejections"],
        "coder_loops": RUN["coder_loops"],
        "reviewer_tool_calls": RUN["reviewer_tool_calls"],
        "reviewer_rejections": RUN["reviewer_rejections"],
        "planner_tool_calls": RUN["planner_tool_calls"],
        "planner_loops": RUN["planner_loops"],
        "messages_per_run": len(final.get("messages") or []),
        "path": " > ".join(RUN["path"]),
    }
    coord = sum(RUN["timings"].get(k, 0) for k in
                ("memory_recall", "router", "planner", "validator", "verifier", "judge", "reviewer"))
    work = sum(RUN["timings"].get(k, 0) for k in ("coder", "executor"))
    record["coordination_share"] = round(coord / (coord + work), 3) if coord + work > 0 else 0.0
    return final, record