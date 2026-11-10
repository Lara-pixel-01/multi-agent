import glob
import hashlib
import json
import math
import os
import re

import requests

BASE = os.path.dirname(os.path.abspath(__file__))
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = "nomic-embed-text"
LAST_FALLBACK = {"used": False}
MODES = ("none", "full", "vector", "graph", "pageindex")


def _read(path):
    with open(path, encoding="utf-8-sig") as f:
        return f.read()


def _skills(root):
    return [_read(p) for p in sorted(glob.glob(os.path.join(root, "skills", "*", "SKILL.md")))]


def knowledge_text(root=BASE):
    parts = [_read(os.path.join(root, "knowledge", n)) for n in ("SOUL.md", "PROJECT.md", "LESSONS.md")]
    parts.append("# Skills\n" + "\n\n".join(_skills(root)))
    return "\n\n".join(parts)


def fingerprint(root=BASE):
    return hashlib.sha256(knowledge_text(root).encode("utf-8")).hexdigest()[:16]


def build_pdf(root, out_path):
    from fpdf import FPDF
    pdf = FPDF()
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()
    last_level = -1
    for raw in knowledge_text(root).splitlines():
        line = raw.rstrip().encode("latin-1", "replace").decode("latin-1")
        if not line.strip():
            pdf.ln(3)
            continue
        m = re.match(r"^(#+)\s+(.*)$", line)
        if m:
            level = min(len(m.group(1)) - 1, last_level + 1)
            last_level = level
            pdf.set_font("Helvetica", "B", {0: 16, 1: 13}.get(level, 11))
            pdf.start_section(m.group(2), level=level)
            pdf.multi_cell(0, 8, m.group(2), new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.set_font("Helvetica", "", 11)
            pdf.multi_cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    pdf.output(out_path)
    return out_path

def make_chunks(text):
    chunks, heading = [], ""
    for line in text.splitlines():
        s = line.strip()
        if not s or s == "---":
            continue
        if s.startswith("#"):
            heading = s.lstrip("# ").strip()
            continue
        chunks.append(f"{heading}: {s}" if heading else s)
    return chunks

def embed(texts, model=EMBED_MODEL):
    vectors = []
    for i in range(0, len(texts), 32):
        data = requests.post(f"{OLLAMA_URL}/api/embed", json={"model": model, "input": texts[i:i + 32]},
                             timeout=300).json()
        if "embeddings" not in data:
            raise RuntimeError(f"embedding failed: {str(data)[:200]} (run: ollama pull {model})")
        vectors.extend(data["embeddings"])
    return vectors


class VectorMemory:
    def __init__(self, root=BASE):
        self.root = root
        self.chunks, self.matrix, self.fp = [], None, ""

    def is_stale(self):
        return self.matrix is None or self.fp != fingerprint(self.root)

    def build(self):
        import numpy as np
        self.chunks = make_chunks(knowledge_text(self.root))
        m = np.array(embed(self.chunks), dtype="float32")
        self.matrix = m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-9)
        self.fp = fingerprint(self.root)

    def ensure_fresh(self):
        if self.is_stale():
            self.build()

    def retrieve(self, question, k=4):
        import numpy as np
        q = np.array(embed([question])[0], dtype="float32")
        q = q / (np.linalg.norm(q) + 1e-9)
        best = np.argsort(-(self.matrix @ q))[:k]
        return [self.chunks[i] for i in best]


STOPWORDS = set("""the and for with that this are not does should must when what which how why where who into your you can
use used using each every any all have has had its will would may might about only also than then them they their there
these those over under before after from while without work works made make been being was were more most such other""".split())


def keywords(text):
    out = set()
    for w in re.findall(r"[a-z0-9_.]{3,}", text.lower()):
        w = w.strip(".")
        if len(w) > 4 and w.endswith("s"):
            w = w[:-1]
        if w and w not in STOPWORDS:
            out.add(w)
    return out


class GraphMemory:
    def __init__(self, root=BASE):
        self.root = root
        self.chunks, self.kw, self.index, self.idf, self.fp = [], [], {}, {}, ""

    def is_stale(self):
        return not self.chunks or self.fp != fingerprint(self.root)

    def build(self):
        self.chunks = make_chunks(knowledge_text(self.root))
        self.kw = [keywords(c) for c in self.chunks]
        self.index = {}
        for i, words in enumerate(self.kw):
            for w in words:
                self.index.setdefault(w, []).append(i)
        n = len(self.chunks)
        self.idf = {w: math.log((n + 1) / (len(ids) + 0.5)) + 1 for w, ids in self.index.items()}
        self.fp = fingerprint(self.root)

    def ensure_fresh(self):
        if self.is_stale():
            self.build()

    def retrieve(self, question, k=4):
        scores = {}
        for w in keywords(question):
            for i in self.index.get(w, []):
                scores[i] = scores.get(i, 0) + self.idf[w]
        ranked = sorted(scores, key=lambda i: -scores[i])[:k]
        if ranked:
            best = ranked[0]
            near = [j for j in range(len(self.chunks)) if j not in ranked and len(self.kw[best] & self.kw[j]) >= 2]
            near.sort(key=lambda j: -len(self.kw[best] & self.kw[j]))
            ranked += near[:1]
        return [self.chunks[i] for i in ranked]



class PageIndexMemory:
    def __init__(self, root=BASE, store=None):
        self.root = root
        self.store = store or os.path.join(root, "pageindex_store")
        self.state_path = os.path.join(self.store, "state.json")
        self._client_obj = None
        os.makedirs(self.store, exist_ok=True)

    def _state(self):
        try:
            with open(self.state_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _client(self):
        if self._client_obj is None:
            from pageindex import PageIndexClient
            backend = {"api_base": OLLAMA_URL}
            self._client_obj = PageIndexClient(
                index={"model": "ollama_chat/ministral-3:3b", "backend": backend,
                       "storage_path": os.path.join(self.store, "index")},
                chat={"model": "ollama_chat/qwen3.5:4b", "backend": backend})
        return self._client_obj

    def is_stale(self):
        st = self._state()
        return not st.get("doc_id") or st.get("fingerprint") != fingerprint(self.root)

    def build(self):
        pdf = build_pdf(self.root, os.path.join(self.store, "knowledge.pdf"))
        doc_id = self._client().submit_document(pdf)["doc_id"]
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump({"doc_id": doc_id, "fingerprint": fingerprint(self.root)}, f)

    def ensure_fresh(self):
        if self.is_stale():
            self.build()

    def retrieve(self, question, k=None):
        doc_id = self._state()["doc_id"]
        short = question + " Answer in at most 5 short bullet points, with no preamble."
        return [str(self._client().chat(short, doc_id=doc_id))]

_INSTANCES = {}

def _notes(mode, query, root=BASE):
    if mode == "vector":
        mem = _INSTANCES.setdefault(("vector", root), VectorMemory(root))
    elif mode == "graph":
        mem = _INSTANCES.setdefault(("graph", root), GraphMemory(root))
    elif mode == "pageindex":
        mem = _INSTANCES.setdefault(("pageindex", root), PageIndexMemory(root))
        mem.ensure_fresh()
        return mem.retrieve(query)
    else:
        raise ValueError(f"unknown retrieval mode '{mode}'")
    mem.ensure_fresh()
    return mem.retrieve(query)


def _retrieved_block(mode, query, root=BASE):
    try:
        notes = _notes(mode, query, root)
        LAST_FALLBACK["used"] = False
        return "# Relevant notes from memory\n" + "\n\n".join(notes)[:2500]
    except Exception as e:
        print(f"(memory mode '{mode}' failed: {type(e).__name__}: {str(e)[:120]}. Using the full files instead.)")
        LAST_FALLBACK["used"] = True
        return "# Memory (full files, retrieval failed)\n" + knowledge_text(root)


def get_context(mode, task):
    LAST_FALLBACK["used"] = False
    if mode == "none":
        return ""
    if mode == "full":
        return knowledge_text()
    return _retrieved_block(mode, f"Rules and lessons for this coding task: {task}")


def coder_context(task, mode="full", root=BASE):
    LAST_FALLBACK["used"] = False
    if mode == "none":
        return ""
    if mode == "full":
        project = _read(os.path.join(root, "knowledge", "PROJECT.md"))
        lessons = _read(os.path.join(root, "knowledge", "LESSONS.md"))
        return "\n\n".join([project, "# Skills\n" + "\n\n".join(_skills(root)), lessons])
    return _retrieved_block(mode, f"Rules, conventions and past mistakes for this coding task: {task}", root)


def reviewer_context(task, mode="full", root=BASE):
    LAST_FALLBACK["used"] = False
    if mode == "none":
        return ""
    if mode == "full":
        return "\n\n".join(_read(os.path.join(root, "knowledge", n)) for n in ("PROJECT.md", "LESSONS.md"))
    return _retrieved_block(mode, f"Common mistakes and expected behaviour for this task: {task}", root)


def planner_context(task, mode="full", root=BASE):
    LAST_FALLBACK["used"] = False
    if mode == "none":
        return ""
    if mode == "full":
        project = _read(os.path.join(root, "knowledge", "PROJECT.md"))
        return "\n\n".join([project, "# Skills\n" + "\n\n".join(_skills(root))])
    return _retrieved_block(mode, f"Conventions and skills relevant to planning this task: {task}", root)