import argparse
import os
import shutil
import time
from datetime import datetime

import memory

BASE = os.path.dirname(os.path.abspath(__file__))

QUESTIONS = [
    ("How should a function avoid changing its input list?", [["copy"]]),
    ("Do intervals that touch, such as [1, 2] and [2, 3], merge?", [["touch"], ["merge"]]),
    ("What happens when a test file uses pytest decorators without importing pytest?", [["crash"]]),
    ("Where should assert statements go in a test file?", [["inside"]]),
    ("Which Python version and libraries does the project use?", [["3.12"], ["standard library"]]),
    ("How much memory does the sandbox have?", [["512"]]),
    ("What does the verifier decide?", [["never"], ["tests decide", "tests"]]),
    ("What should the agent do if a test's expected value looks wrong?", [["by hand"]]),
    ("Which edge cases should every test file cover?", [["empty"], ["single"]]),
    ("What network access does generated code have?", [["no network", "offline"]]),
]


def recall(text, groups):
    if isinstance(text, list):
        text = " ".join(str(t) for t in text)
    low = text.lower()
    hit = [any(w in low for w in g) for g in groups]
    return sum(hit) / len(groups)


def line_relevance(text, groups):
    if isinstance(text, list):
        text = "\n".join(str(t) for t in text)
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return 0.0
    words = [w for g in groups for w in g]
    return sum(any(w in l.lower() for w in words) for l in lines) / len(lines)


def run_mode(name, retriever, build):
    t = time.time()
    build()
    build_s = time.time() - t
    recs, rels, chars, secs = [], [], [], []
    for question, groups in QUESTIONS:
        t = time.time()
        text = retriever(question)
        secs.append(time.time() - t)
        recs.append(recall(text, groups))
        rels.append(line_relevance(text, groups))
        chars.append(len(text))
    n = len(QUESTIONS)
    return (f"| {name} | {100 * sum(recs) / n:.0f}% | {100 * sum(rels) / n:.0f}% | {sum(chars) // n} | "
            f"{sum(secs) / n:.1f} | {build_s:.0f} |")


def stale_test(lines):
    tmp = os.path.join(BASE, "eval-results", "memory-stale-test")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    shutil.copytree(os.path.join(BASE, "knowledge"), os.path.join(tmp, "knowledge"))
    shutil.copytree(os.path.join(BASE, "skills"), os.path.join(tmp, "skills"))
    question = "How much memory does the sandbox have?"
    lines.append("\n## Stale memory test\n")
    lines.append("A fact is changed in a copy of the files (sandbox memory 512 MB -> 1024 MB). "
                 "Each mode is asked the same question before and after it refreshes.\n")
    lines.append("| Mode | Answer before refresh | Stale? | Answer after refresh | Correct? |")
    lines.append("|---|---|---|---|---|")
    modes = {}
    try:
        v = memory.VectorMemory(tmp)
        v.build()
        modes["vector"] = (v.retrieve, v.ensure_fresh)
    except Exception as e:
        lines.append(f"| vector | not available: {str(e)[:60]} | | | |")
    g = memory.GraphMemory(tmp)
    g.build()
    modes["graph"] = (g.retrieve, g.ensure_fresh)
    try:
        p = memory.PageIndexMemory(tmp, store=os.path.join(tmp, "pageindex_store"))
        p.build()
        modes["pageindex"] = (p.retrieve, p.ensure_fresh)
    except Exception as e:
        lines.append(f"| pageindex | not available: {str(e)[:60]} | | | |")
    path = os.path.join(tmp, "knowledge", "PROJECT.md")
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.replace("512 MB", "1024 MB"))
    fresh = memory.knowledge_text(tmp)
    lines.append(f"| full | (reads the files on every call) | {'no' if '1024' in fresh else 'YES'} | "
                 f"{'1024 found' if '1024' in fresh else 'old value'} | {'yes' if '1024' in fresh else 'NO'} |")
    for name, (retrieve, refresh) in modes.items():
        before = retrieve(question)
        stale = "512" in before and "1024" not in before
        refresh()
        after = retrieve(question)
        ok = "1024" in after
        lines.append(f"| {name} | {'old value (512)' if stale else ('new value' if '1024' in before else 'unclear')} | "
                     f"{'YES' if stale else 'no'} | {'1024 found' if ok else 'not found'} | {'yes' if ok else 'NO'} |")
    shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modes", nargs="+", default=["full", "vector", "graph", "pageindex"])
    ap.add_argument("--skip-stale", action="store_true")
    args = ap.parse_args()

    lines = ["# Memory evaluation", f"Run at {datetime.now().isoformat(timespec='seconds')}", "",
             "## Recall on 10 questions\n",
             "| Mode | Recall | Line relevance | Avg characters returned | Avg seconds per question | Setup seconds |",
             "|---|---|---|---|---|---|"]
    if "full" in args.modes:
        lines.append(run_mode("full (load everything)", lambda q: memory.knowledge_text(), lambda: None))
    if "vector" in args.modes:
        try:
            v = memory.VectorMemory()
            lines.append(run_mode("vector (standard RAG, top 3)", v.retrieve, v.build))
        except Exception as e:
            lines.append(f"| vector | not available: {str(e)[:80]} | | | | |")
    if "graph" in args.modes:
        g = memory.GraphMemory()
        lines.append(run_mode("graph (simplified, no model)", g.retrieve, g.build))
    if "pageindex" in args.modes:
        try:
            p = memory.PageIndexMemory()
            lines.append(run_mode("pageindex", p.retrieve, p.ensure_fresh))
        except Exception as e:
            lines.append(f"| pageindex | not available: {str(e)[:80]} | | | | |")
    if not args.skip_stale:
        stale_test(lines)
    text = "\n".join(lines)
    print(text)
    out = os.path.join(BASE, "eval-results")
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"memory-eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print("\nSaved:", path)


if __name__ == "__main__":
    main()
