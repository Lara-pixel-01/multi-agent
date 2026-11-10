import contextlib
import json
import os
import time
from datetime import datetime

import requests

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
BASE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE, "eval-results")
os.makedirs(LOG_DIR, exist_ok=True)
CALL_LOG = os.path.join(LOG_DIR, "llm-calls.jsonl")

NUM_CTX = {"qwen3.5:4b": 8192, "ministral-3:3b": 4096, "qwen2.5-coder:7b": 4096}
DEFAULT_CTX = 4096
TEMPERATURE = 0.3
MAX_RETRIES = 2
RETRY_BACKOFF = 2.0

CALLS = []
LOG_CALLS = True

try:
    from opentelemetry import trace as _otel_trace
    _tracer = _otel_trace.get_tracer("coding-agent")
except Exception:
    _tracer = None


def _span(name):
    if _tracer is None:
        return contextlib.nullcontext()
    return _tracer.start_as_current_span(name)


def clip(text, limit=1500):
    text = text or ""
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + "\n...[shortened]...\n" + text[-half:]


def _post_chat(payload):
    last_err = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=300)
            if r.status_code != 200:
                last_err = RuntimeError(f"Ollama HTTP {r.status_code}: {r.text[:200]}")
            else:
                data = r.json()
                if "message" not in data:
                    last_err = RuntimeError(f"Ollama error: {str(data)[:200]}")
                else:
                    return data
        except requests.exceptions.RequestException as e:
            last_err = RuntimeError(f"Could not reach Ollama: {e}")
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_BACKOFF * (attempt + 1))
    raise last_err


def _record(role, model, seconds, data, text):
    stats = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "role": role,
        "model": model,
        "seconds": round(seconds, 2),
        "load_seconds": round(data.get("load_duration", 0) / 1e9, 2),
        "prompt_tokens": data.get("prompt_eval_count", 0),
        "generated_tokens": data.get("eval_count", 0),
    }
    eval_s = data.get("eval_duration", 0) / 1e9
    stats["tokens_per_second"] = round(stats["generated_tokens"] / eval_s, 1) if eval_s > 0 else 0
    CALLS.append(stats)
    if LOG_CALLS:
        try:
            with open(CALL_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(stats) + "\n")
        except OSError:
            pass
    return stats


def ask(model, prompt, role=""):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "options": {"temperature": TEMPERATURE, "num_ctx": NUM_CTX.get(model, DEFAULT_CTX)},
    }
    started = time.time()
    with _span(f"llm.{role or model}") as span:
        data = _post_chat(payload)
        text = data["message"].get("content", "") or ""
        seconds = time.time() - started
        stats = _record(role, model, seconds, data, text)
        if span is not None:
            span.set_attribute("openinference.span.kind", "LLM")
            span.set_attribute("llm.model_name", model)
            span.set_attribute("llm.token_count.prompt", stats["prompt_tokens"])
            span.set_attribute("llm.token_count.completion", stats["generated_tokens"])
            span.set_attribute("llm.token_count.total", stats["prompt_tokens"] + stats["generated_tokens"])
            span.set_attribute("input.value", prompt[:3000])
            span.set_attribute("output.value", text[:3000])
    return text


def ask_with_tools(model, messages, tools, role="tool_loop"):
    payload = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "stream": False,
        "think": False,
        "options": {"temperature": TEMPERATURE, "num_ctx": NUM_CTX.get(model, DEFAULT_CTX)},
    }
    started = time.time()
    with _span(f"llm.{role}") as span:
        data = _post_chat(payload)
        msg = data["message"]
        content = msg.get("content", "") or ""
        raw_calls = msg.get("tool_calls") or []
        normalized = []
        for c in raw_calls:
            fn = c.get("function") or {}
            args = fn.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            if not isinstance(args, dict):
                args = {}
            normalized.append({"function": {"name": fn.get("name", ""), "arguments": args}})
        seconds = time.time() - started
        stats = _record(role, model, seconds, data, content)
        if span is not None:
            span.set_attribute("openinference.span.kind", "LLM")
            span.set_attribute("llm.model_name", model)
            span.set_attribute("llm.token_count.prompt", stats["prompt_tokens"])
            span.set_attribute("llm.token_count.completion", stats["generated_tokens"])
            span.set_attribute("llm.tool_calls",
                               json.dumps([c["function"]["name"] for c in normalized]))
            span.set_attribute("input.value", json.dumps(messages[-1:])[:3000])
            span.set_attribute("output.value", content[:3000])
    return content, normalized, data