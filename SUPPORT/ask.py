#!/usr/bin/env python3
# SUPPORT/ask.py
import argparse, json, os, sys, re, logging
from pathlib import Path
import httpx
import numpy as np
import faiss

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

ROOT = Path(__file__).resolve().parents[1]  # repo root: C:\support-agent\SUPPORT -> parents[1] = C:\support-agent
APP_YAML = ROOT / "config" / "app.yaml"     # optional (not required)

# ---- project config: index folders + site bases ----
PROJECTS = {
    "dependq": {
        "index_dir": ROOT / "SUPPORT" / "index" / "dependq",
        "site_base": "https://hub.percival.ee/docs/dependq/doku.php?id=",
    },
    "revenue": {
        "index_dir": ROOT / "SUPPORT" / "index" / "revenue",
        "site_base": "https://hub.percival.ee/docs/revenue/doku.php?id=",
    },
    "regard": {
        "index_dir": ROOT / "SUPPORT" / "index" / "regard_depend",
        "site_base": "https://hub.percival.ee/docs/regard_depend/doku.php?id=",
    },
    "hubble": {
        "index_dir": ROOT / "SUPPORT" / "index" / "hubble",
        "site_base": "https://hub.percival.ee/docs/hubble/doku.php?id=",
    },
}

OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
EMBED_MODEL = os.getenv("EMBED_MODEL", "bge-m3")            # must match build
LLM_MODEL   = os.getenv("LLM_MODEL",   "llama2:13b-chat")   # your chat model

# ---------- helpers ----------
def ensure_files(idxdir: Path):
    req = ["chunks.faiss", "corpus.jsonl"]
    missing = [f for f in req if not (idxdir / f).exists()]
    if missing:
        raise FileNotFoundError(f"Missing files in {idxdir}: {', '.join(missing)}")

def load_index_and_corpus(idxdir: Path):
    ensure_files(idxdir)
    index = faiss.read_index(str(idxdir / "chunks.faiss"))
    corpus = []
    with (idxdir / "corpus.jsonl").open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            try:
                j = json.loads(line)
                # expected keys from your builder: id, file, title, headings, text, project
                corpus.append(j)
            except Exception:
                continue
    if len(corpus) != index.ntotal:
        logging.warning(f"[WARN] corpus size ({len(corpus)}) != index.ntotal ({index.ntotal})")
    return index, corpus

def ollama_embed_texts(texts, model=EMBED_MODEL, url=OLLAMA_URL, timeout=300.0):
    """Embed a list of strings with Ollama /api/embed."""
    if not texts:
        return np.zeros((0, 1), dtype=np.float32)
    payload = {"model": model, "input": texts}
    with httpx.Client(timeout=timeout) as client:
        r = client.post(f"{url}/api/embed", json=payload)
        if r.status_code != 200:
            raise RuntimeError(f"Embed error {r.status_code}: {r.text}")
        data = r.json()
        embs = data.get("embeddings")
        if not embs or not embs[0]:
            raise RuntimeError("Empty embeddings returned from Ollama.")
        return np.asarray(embs, dtype=np.float32)

def ollama_generate(prompt, model=LLM_MODEL, url=OLLAMA_URL, temperature=0.2, max_tokens=512, timeout=600.0):
    """Call Ollama /api/generate (non-stream) and return the full response text."""
    payload = {
        "model": model,
        "prompt": prompt,
        "options": {"temperature": temperature},
        "stream": False
    }
    with httpx.Client(timeout=timeout) as client:
        r = client.post(f"{url}/api/generate", json=payload)
        if r.status_code != 200:
            raise RuntimeError(f"Generate error {r.status_code}: {r.text}")
        data = r.json()
        return data.get("response", "")

def make_url(project_key: str, src_file: str) -> str:
    """
    Map a markdown filename (e.g., 'client_alertnew.md' or 'clients_acceptanceinsert.md')
    to a DokuWiki id path and full URL.
    Rule: strip '.md', replace the FIRST '_' with ':'   (namespace:name).
    """
    name = src_file
    if name.lower().endswith(".md"):
        name = name[:-3]
    # Replace first '_' with ':'
    id_part = name.replace("_", ":", 1)
    base = PROJECTS[project_key]["site_base"]
    return f"{base}{id_part}"

def build_prompt(question: str, contexts: list[dict], max_ctx_chars: int = 2600) -> str:
    """
    contexts: list of dicts {text, file, title, headings}
    We trim to fit a safe prompt size, and annotate sources.
    """
    blocks = []
    total = 0
    for i, c in enumerate(contexts, 1):
        title = c.get("title") or ""
        heads = " > ".join(c.get("headings") or [])
        header = f"[{i}] {title}" + (f" — {heads}" if heads else "")
        body = c["text"].strip().replace("\n\n", "\n")
        block = f"{header}\n{body}"
        if total + len(block) > max_ctx_chars and blocks:
            break
        blocks.append(block); total += len(block)

    ctx = "\n\n---\n\n".join(blocks)
    instr = (
        "You are an internal support assistant.\n"
        "Answer the question using ONLY the Context. If the answer is not in the context, say you don't know.\n"
        "Be concise but complete. Do not invent facts. After the answer, list the sources by their [n] labels.\n"
    )
    prompt = f"{instr}\nContext:\n{ctx}\n\nQuestion: {question}\n\nAnswer:"
    return prompt

def search(index, query_vec: np.ndarray, top_k: int) -> tuple[np.ndarray, np.ndarray]:
    # Safety: ensure query dim matches index
    d_index = index.d
    if query_vec.ndim == 1:
        query_vec = query_vec.reshape(1, -1)
    d_query = query_vec.shape[1]
    if d_query != d_index:
        raise RuntimeError(f"Query embedding dim {d_query} != index dim {d_index}. "
                           f"Check EMBED_MODEL; it must match the model used to build the index.")
    # Inner-product search
    return index.search(query_vec.astype(np.float32), top_k)

def dedupe_by_source(hits: list[dict], per_source_cap: int = 2) -> list[dict]:
    bucket = {}
    out = []
    for h in hits:
        src = h.get("file") or "unknown"
        n = bucket.get(src, 0)
        if n < per_source_cap:
            out.append(h)
            bucket[src] = n + 1
    return out

def ask_question(project: str, question: str, topk: int = 8, per_source_cap: int = 2) -> dict:
    """
    Ask a question and get an answer with sources.

    Returns:
        dict with keys: answer, sources (list of URLs), error (if any)
    """
    try:
        if project not in PROJECTS:
            return {"error": f"Unknown project: {project}"}

        idxdir = PROJECTS[project]["index_dir"]
        ensure_files(idxdir)
        index, corpus = load_index_and_corpus(idxdir)

        logging.info(f"Embedding query with '{EMBED_MODEL}' via Ollama…")
        qvec = ollama_embed_texts([question])

        logging.info(f"Searching FAISS ({index.ntotal} vectors)…")
        distances, indices = search(index, qvec, topk)

        # Collect hits
        hits = []
        for pos in indices[0]:
            if pos < 0 or pos >= len(corpus):
                continue
            rec = corpus[pos]
            hits.append({
                "id": rec.get("id"),
                "file": rec.get("file"),
                "title": rec.get("title"),
                "headings": rec.get("headings"),
                "text": rec.get("text")
            })

        # Deduplicate
        hits = dedupe_by_source(hits, per_source_cap=per_source_cap)
        if not hits:
            return {"answer": "No relevant context found.", "sources": []}

        # Build prompt for LLM
        prompt = build_prompt(question, hits)

        logging.info(f"Generating answer with '{LLM_MODEL}' via Ollama…")
        answer = ollama_generate(prompt)

        # Compose source URL list from used files
        used_files = []
        seen = set()
        for h in hits:
            f = h.get("file")
            if f and f not in seen:
                seen.add(f)
                used_files.append(f)

        urls = [make_url(project, f) for f in used_files]

        return {
            "answer": answer.strip(),
            "sources": urls
        }
    except Exception as e:
        logging.error(f"Error in ask_question: {e}")
        return {"error": str(e)}

# ---------- main ----------
def main():
    ap = argparse.ArgumentParser(description="Ask questions against project docs (FAISS + Ollama).")
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--dependq", action="store_true")
    grp.add_argument("--revenue", action="store_true")
    grp.add_argument("--regard",  action="store_true")
    grp.add_argument("--hubble",  action="store_true")
    ap.add_argument("question", type=str, help="Your question")
    ap.add_argument("-k", "--topk", type=int, default=8, help="Top-K chunks to retrieve")
    ap.add_argument("--per-source-cap", type=int, default=2, help="Max chunks per source file")
    args = ap.parse_args()

    project = "dependq" if args.dependq else "revenue" if args.revenue else "regard" if args.regard else "hubble"

    result = ask_question(project, args.question, topk=args.topk, per_source_cap=args.per_source_cap)

    if "error" in result:
        print(f"Error: {result['error']}")
        sys.exit(1)

    print("\n" + result["answer"])
    if result.get("sources"):
        print("\nSources:")
        for i, url in enumerate(result["sources"], 1):
            print(f"{i}. {url}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logging.error(e)
        sys.exit(1)
