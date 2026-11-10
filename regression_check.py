import argparse
import json
import os
import statistics
from dataclasses import replace
from datetime import datetime

import agent
import llm
import tools
from notify import alert
from tasks import TASKS

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "eval-results")
BASELINE_PATH = os.path.join(OUT, "regression-baseline.json")
HISTORY_PATH = os.path.join(OUT, "regression-history.jsonl")
CHECK_TASKS = ["is_even", "clamp", "merge_intervals", "find_pair"]


def measure():
    llm.LOG_CALLS = False
    tools.LOG_TOOLS = False
    cfg = replace(agent.PRESETS["full"], save_lessons=False)    # a check must not change the memory
    rows = []
    for t in [t for t in TASKS if t["name"] in CHECK_TASKS]:
        print(f"\n##### regression task {t['name']} #####")
        try:
            _, rec = agent.run_agent(t["task"], os.path.join(BASE, t["ref"]), cfg)
        except Exception as e:
            print("ERROR:", e)
            rec = {"passed": False, "seconds": 0, "prompt_tokens": 0, "generated_tokens": 0}
        rows.append(rec)
    return {
        "time": datetime.now().isoformat(timespec="seconds"),
        "passed": sum(1 for r in rows if r["passed"]),
        "tasks": len(rows),
        "median_seconds": round(statistics.median(r["seconds"] for r in rows), 1),
        "avg_tokens": round(statistics.mean(r["prompt_tokens"] + r["generated_tokens"] for r in rows)),
    }


def compare(now, base):
    problems = []
    if now["passed"] < base["passed"]:
        problems.append(f"only {now['passed']} of {now['tasks']} tasks passed (baseline {base['passed']})")
    if base["median_seconds"] > 0 and now["median_seconds"] > 1.5 * base["median_seconds"]:
        problems.append(f"median time {now['median_seconds']} s is over 1.5x the baseline {base['median_seconds']} s")
    if base["avg_tokens"] > 0 and now["avg_tokens"] > 1.5 * base["avg_tokens"]:
        problems.append(f"average tokens {now['avg_tokens']} is over 1.5x the baseline {base['avg_tokens']}")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", action="store_true")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    now = measure()
    with open(HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(now) + "\n")
    print("\nResult:", now)
    if args.init or not os.path.exists(BASELINE_PATH):
        with open(BASELINE_PATH, "w", encoding="utf-8") as f:
            json.dump(now, f)
        print("Saved as the new baseline.")
        return
    with open(BASELINE_PATH, encoding="utf-8") as f:
        base = json.load(f)
    problems = compare(now, base)
    if problems:
        alert("regression check got worse: " + "; ".join(problems))
    else:
        print("No regression: results are at least as good as the baseline from", base["time"])


if __name__ == "__main__":
    main()
