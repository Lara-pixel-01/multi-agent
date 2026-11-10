import json
import os
import sys
from datetime import datetime
import agent
from notify import alert

os.environ["PHOENIX_COLLECTOR_ENDPOINT"] = "http://localhost:6006"
try:
    from phoenix.otel import register
    register(project_name="coding-agent", auto_instrument=True)
except Exception as e:
    print("(Phoenix tracing is off:", type(e).__name__, ")")


SLOW_SECONDS = 300
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval-results")
os.makedirs(LOG_DIR, exist_ok=True)
RUN_LOG = os.path.join(LOG_DIR, "run-log.jsonl")

args = sys.argv[1:]
reference, config_name = "", "full"
while args and args[0] in ("--ref", "--config") and len(args) >= 2:
    if args[0] == "--ref":
        reference = os.path.abspath(args[1])
    else:
        config_name = args[1]
    args = args[2:]
task = " ".join(args)
if config_name not in agent.PRESETS:
    print("Unknown config. Choose one of:", ", ".join(agent.PRESETS))
    sys.exit(1)
cfg = agent.PRESETS[config_name]

try:
    final, record = agent.run_agent(task, reference, cfg)
    record["time"] = datetime.now().isoformat(timespec="seconds")
    record["error"] = ""
    print("PASSED:", record["passed"])
    print("Attempts:", record["attempts"])
    print("---- test output ----")
    print(final["result"])
except Exception as e:
    record = {"time": datetime.now().isoformat(timespec="seconds"), "config": cfg.name, "task": task[:80],
              "passed": False, "attempts": 0, "seconds": 0, "error": str(e)[:200], "route": "",
              "escalated": False, "prompt_tokens": 0, "generated_tokens": 0, "validation_failures": 0}
    alert(f"run crashed: {e}")

with open(RUN_LOG, "a", encoding="utf-8") as f:
    f.write(json.dumps(record) + "\n")

if not record["passed"] and not record["error"]:
    alert(f"task failed after {record['attempts']} attempts: {task[:60]}")
if record["seconds"] > SLOW_SECONDS:
    alert(f"slow run: {record['seconds']} seconds: {task[:60]}")
