import json
import os

base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval-results")
log_path = os.path.join(base, "run-log.jsonl")
alert_path = os.path.join(base, "alerts.log")

if not os.path.exists(log_path):
    print("No runs logged yet. Run run_task.py first.")
    raise SystemExit

runs = [json.loads(line) for line in open(log_path, encoding="utf-8") if line.strip()]
n = len(runs)
passed = [r for r in runs if r["passed"]]
first_try = [r for r in passed if r["attempts"] == 1]
secs = sorted(r["seconds"] for r in runs)
alerts = 0
if os.path.exists(alert_path):
    alerts = sum(1 for _ in open(alert_path, encoding="utf-8"))

print(f"Runs logged:               {n}")
print(f"Passed:                    {len(passed)} ({100 * len(passed) // n}%)")
print(f"Passed on first attempt:   {len(first_try)}")
print(f"Average attempts:          {sum(r['attempts'] for r in runs) / n:.2f}")
print(f"Router chose SIMPLE:       {sum(1 for r in runs if r['route'] == 'SIMPLE')}")
print(f"Router chose HARD:         {sum(1 for r in runs if r['route'] == 'HARD')}")
print(f"Escalations (small->big):  {sum(1 for r in runs if r['escalated'])}")
print(f"Seconds per run, average:  {sum(secs) / n:.0f}")
print(f"Seconds per run, slowest:  {secs[-1]:.0f}")
print(f"Alerts raised:             {alerts}")