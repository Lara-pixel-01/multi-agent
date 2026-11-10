import json
import os
import subprocess
import time

import psutil
import requests
from prometheus_client import REGISTRY, start_http_server
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, HistogramMetricFamily

BASE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE, "eval-results")
RUN_LOG = os.path.join(LOG_DIR, "run-log.jsonl")
CALL_LOG = os.path.join(LOG_DIR, "llm-calls.jsonl")
TOOL_LOG = os.path.join(LOG_DIR, "tool-calls.jsonl")
ALERT_LOG = os.path.join(LOG_DIR, "alerts.log")
EVAL_LOG = os.path.join(LOG_DIR, "eval-run-log.jsonl")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
BUCKETS = [30, 60, 120, 180, 300, 600]


def read_jsonl(path):
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        pass
    except OSError:
        pass
    return rows


def gpu_numbers():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=4).stdout
        a, b, c = [float(x) for x in out.strip().splitlines()[0].split(",")]
        return a, b, c
    except Exception:
        return None


class AgentCollector:
    def collect(self):
        runs = read_jsonl(RUN_LOG)
        c = CounterMetricFamily("agent_runs", "Agent runs by result", labels=["status"])
        passed = sum(1 for r in runs if r.get("passed"))
        errors = sum(1 for r in runs if r.get("error"))
        c.add_metric(["passed"], passed)
        c.add_metric(["failed"], len(runs) - passed - errors)
        c.add_metric(["error"], errors)
        yield c
        for name, doc, key in [("agent_retries", "Retries used", None),
                               ("agent_escalations", "Small model failed, big model took over", "escalated"),
                               ("agent_validation_failures", "Bad outputs stopped by the validator", "validation_failures"),
                               ("agent_prompt_tokens", "Prompt tokens", "prompt_tokens"),
                               ("agent_generated_tokens", "Generated tokens", "generated_tokens")]:
            m = CounterMetricFamily(name, doc)
            if key is None:
                m.add_metric([], sum(max(int(r.get("attempts", 1)) - 1, 0) for r in runs))
            else:
                m.add_metric([], sum(int(r.get(key) or 0) for r in runs))
            yield m
        counts, total = [0] * len(BUCKETS), 0.0
        for r in runs:
            s = float(r.get("seconds") or 0)
            total += s
            for i, b in enumerate(BUCKETS):
                if s <= b:
                    counts[i] += 1
        buckets = [(str(b), counts[i]) for i, b in enumerate(BUCKETS)] + [("+Inf", len(runs))]
        yield HistogramMetricFamily("agent_run_seconds", "Seconds per run", buckets=buckets, sum_value=total)
        if runs:
            last = runs[-1]
            for name, val in [("agent_last_run_seconds", float(last.get("seconds") or 0)),
                              ("agent_last_run_attempts", float(last.get("attempts") or 0)),
                              ("agent_last_run_passed", 1.0 if last.get("passed") else 0.0)]:
                g = GaugeMetricFamily(name, name)
                g.add_metric([], val)
                yield g
        calls = read_jsonl(CALL_LOG)
        by_model = {}
        for r in calls:
            d = by_model.setdefault(r.get("model", "?"), [0, 0.0, 0])
            d[0] += 1
            d[1] += float(r.get("seconds") or 0)
            d[2] += int(r.get("generated_tokens") or 0)
        for name, doc, idx in [("agent_llm_calls", "Model calls", 0), ("agent_llm_seconds", "Seconds spent in model calls", 1),
                               ("agent_llm_generated_tokens", "Tokens generated", 2)]:
            m = CounterMetricFamily(name, doc, labels=["model"])
            for model, d in by_model.items():
                m.add_metric([model], d[idx])
            yield m
        tcalls = read_jsonl(TOOL_LOG)
        tm = CounterMetricFamily("agent_tool_calls", "Tool calls", labels=["tool", "status"])
        seen = {}
        for r in tcalls:
            k = (r.get("tool", "?"), r.get("status", "?"))
            seen[k] = seen.get(k, 0) + 1
        for (tool, status), n in seen.items():
            tm.add_metric([tool, status], n)
        yield tm
        evals = read_jsonl(EVAL_LOG)
        by_design = {}
        for r in evals:
            d = by_design.setdefault(r.get("design", "?"), {"n": 0, "ok": 0, "attempts": 0, "seconds": 0.0, "tokens": 0})
            d["n"] += 1
            d["ok"] += 1 if r.get("passed") else 0
            d["attempts"] += int(r.get("attempts") or 0)
            d["seconds"] += float(r.get("seconds") or 0)
            d["tokens"] += int(r.get("tokens") or 0)
        er = CounterMetricFamily("agent_eval_runs", "Evaluation runs by design and result", labels=["design", "status"])
        pr = GaugeMetricFamily("agent_eval_pass_rate", "Share of evaluation runs that passed", labels=["design"])
        es = CounterMetricFamily("agent_eval_seconds", "Seconds spent in evaluation runs", labels=["design"])
        et = CounterMetricFamily("agent_eval_tokens", "Tokens used in evaluation runs", labels=["design"])
        for design, d in by_design.items():
            er.add_metric([design, "passed"], d["ok"])
            er.add_metric([design, "failed"], d["n"] - d["ok"])
            pr.add_metric([design], d["ok"] / d["n"])
            es.add_metric([design], d["seconds"])
            et.add_metric([design], d["tokens"])
        yield er
        yield pr
        yield es
        yield et
        am = CounterMetricFamily("agent_alerts", "Alerts raised")
        try:
            with open(ALERT_LOG, encoding="utf-8") as f:
                am.add_metric([], sum(1 for _ in f))
        except OSError:
            am.add_metric([], 0)
        yield am

        for name, val in [("system_cpu_percent", psutil.cpu_percent(interval=None)),
                          ("system_ram_used_gb", round(psutil.virtual_memory().used / 1e9, 2))]:
            g = GaugeMetricFamily(name, name)
            g.add_metric([], val)
            yield g
        gpu = gpu_numbers()
        if gpu:
            for name, val in zip(["gpu_utilization_percent", "gpu_memory_used_mib", "gpu_memory_total_mib"], gpu):
                g = GaugeMetricFamily(name, name)
                g.add_metric([], val)
                yield g
        up = GaugeMetricFamily("ollama_up", "1 if Ollama answers")
        vram = GaugeMetricFamily("ollama_model_vram_bytes", "GPU memory used by a loaded model", labels=["model"])
        size = GaugeMetricFamily("ollama_model_size_bytes", "Total size of a loaded model", labels=["model"])
        try:
            ps = requests.get(f"{OLLAMA_URL}/api/ps", timeout=3).json()
            up.add_metric([], 1)
            for m in ps.get("models", []):
                vram.add_metric([m.get("name", "?")], float(m.get("size_vram", 0)))
                size.add_metric([m.get("name", "?")], float(m.get("size", 0)))
        except Exception:
            up.add_metric([], 0)
        yield up
        yield vram
        yield size


if __name__ == "__main__":
    REGISTRY.register(AgentCollector())
    start_http_server(8000, addr="0.0.0.0")
    print("Metrics are available at http://localhost:8000/metrics  (leave this window open, Ctrl+C stops it)")
    while True:
        time.sleep(3600)
