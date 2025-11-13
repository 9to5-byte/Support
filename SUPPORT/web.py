#!/usr/bin/env python3
# SUPPORT/web.py - Web interface for the documentation search system
from flask import Flask, render_template, request, jsonify
import json, logging
from pathlib import Path
import httpx
import numpy as np
import faiss

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = Flask(__name__)

ROOT = Path(__file__).resolve().parents[1]

# Project configuration
PROJECTS = {
    "dependq": {
        "index_dir": ROOT / "SUPPORT" / "index" / "dependq",
        "site_base": "https://hub.percival.ee/docs/dependq/doku.php?id=",
        "name": "DependQ"
    },
    "revenue": {
        "index_dir": ROOT / "SUPPORT" / "index" / "revenue",
        "site_base": "https://hub.percival.ee/docs/revenue/doku.php?id=",
        "name": "Revenue"
    },
    "regard": {
        "index_dir": ROOT / "SUPPORT" / "index" / "regard_depend",
        "site_base": "https://hub.percival.ee/docs/regard_depend/doku.php?id=",
        "name": "Regard"
    },
    "hubble": {
        "index_dir": ROOT / "SUPPORT" / "index" / "hubble",
        "site_base": "https://hub.percival.ee/docs/hubble/doku.php?id=",
        "name": "Hubble"
    },
}

OLLAMA_URL = "http://127.0.0.1:11434"
EMBED_MODEL = "bge-m3"
LLM_MODEL = "llama2:13b-chat"

# Cache for loaded indices
_cache = {}

def load_index_and_corpus(idxdir: Path):
    """Load FAISS index and corpus from directory."""
    cache_key = str(idxdir)
    if cache_key in _cache:
        return _cache[cache_key]

    index = faiss.read_index(str(idxdir / "chunks.faiss"))
    corpus = []
    with (idxdir / "corpus.jsonl").open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            try:
                corpus.append(json.loads(line))
            except Exception:
                continue

    _cache[cache_key] = (index, corpus)
    return index, corpus

def ollama_embed_texts(texts, timeout=30.0):
    """Embed texts using Ollama."""
    if not texts:
        return np.zeros((0, 1), dtype=np.float32)

    payload = {"model": EMBED_MODEL, "input": texts}
    with httpx.Client(timeout=timeout) as client:
        r = client.post(f"{OLLAMA_URL}/api/embed", json=payload)
        if r.status_code != 200:
            raise RuntimeError(f"Embed error {r.status_code}: {r.text}")
        data = r.json()
        embs = data.get("embeddings")
        if not embs or not embs[0]:
            raise RuntimeError("Empty embeddings returned from Ollama.")
        return np.asarray(embs, dtype=np.float32)

def ollama_generate(prompt, timeout=120.0):
    """Generate answer using Ollama."""
    payload = {
        "model": LLM_MODEL,
        "prompt": prompt,
        "options": {"temperature": 0.2},
        "stream": False
    }
    with httpx.Client(timeout=timeout) as client:
        r = client.post(f"{OLLAMA_URL}/api/generate", json=payload)
        if r.status_code != 200:
            raise RuntimeError(f"Generate error {r.status_code}: {r.text}")
        data = r.json()
        return data.get("response", "")

def make_url(project_key: str, src_file: str) -> str:
    """Convert filename to DokuWiki URL."""
    name = src_file
    if name.lower().endswith(".md"):
        name = name[:-3]
    id_part = name.replace("_", ":", 1)
    base = PROJECTS[project_key]["site_base"]
    return f"{base}{id_part}"

def build_prompt(question: str, contexts: list[dict], max_ctx_chars: int = 2600) -> str:
    """Build prompt with context for LLM."""
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
        blocks.append(block)
        total += len(block)

    ctx = "\n\n---\n\n".join(blocks)
    instr = (
        "You are an internal support assistant.\n"
        "Answer the question using ONLY the Context. If the answer is not in the context, say you don't know.\n"
        "Be concise but complete. Do not invent facts. After the answer, list the sources by their [n] labels.\n"
    )
    prompt = f"{instr}\nContext:\n{ctx}\n\nQuestion: {question}\n\nAnswer:"
    return prompt

def dedupe_by_source(hits: list[dict], per_source_cap: int = 2) -> list[dict]:
    """Deduplicate hits by source file."""
    bucket = {}
    out = []
    for h in hits:
        src = h.get("file") or "unknown"
        n = bucket.get(src, 0)
        if n < per_source_cap:
            out.append(h)
            bucket[src] = n + 1
    return out

@app.route('/')
def index():
    """Render the main search interface."""
    return render_template('index.html', projects=PROJECTS)

@app.route('/api/search', methods=['POST'])
def search():
    """Handle search requests."""
    try:
        data = request.json
        question = data.get('question', '').strip()
        project = data.get('project', 'dependq')

        if not question:
            return jsonify({'error': 'Question is required'}), 400

        if project not in PROJECTS:
            return jsonify({'error': f'Invalid project: {project}'}), 400

        # Load index and corpus
        idxdir = PROJECTS[project]["index_dir"]
        index, corpus = load_index_and_corpus(idxdir)

        # Embed query
        logging.info(f"Embedding query for {project}...")
        qvec = ollama_embed_texts([question])

        # Search
        logging.info(f"Searching FAISS ({index.ntotal} vectors)...")
        top_k = 8
        distances, indices = index.search(qvec.astype(np.float32), top_k)

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
        hits = dedupe_by_source(hits, per_source_cap=2)

        if not hits:
            return jsonify({
                'answer': 'No relevant documentation found for your question.',
                'sources': []
            })

        # Build prompt and generate answer
        prompt = build_prompt(question, hits)
        logging.info(f"Generating answer with {LLM_MODEL}...")
        answer = ollama_generate(prompt)

        # Get sources
        used_files = []
        seen = set()
        for h in hits:
            f = h.get("file")
            if f and f not in seen:
                seen.add(f)
                used_files.append(f)

        urls = [make_url(project, f) for f in used_files]
        sources = [{"file": f, "url": u} for f, u in zip(used_files, urls)]

        return jsonify({
            'answer': answer.strip(),
            'sources': sources
        })

    except Exception as e:
        logging.error(f"Search error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint."""
    try:
        # Check Ollama connection
        with httpx.Client(timeout=5.0) as client:
            r = client.get(f"{OLLAMA_URL}/api/tags")
            if r.status_code != 200:
                return jsonify({'status': 'unhealthy', 'error': 'Ollama not responding'}), 503

        return jsonify({
            'status': 'healthy',
            'ollama_url': OLLAMA_URL,
            'embed_model': EMBED_MODEL,
            'llm_model': LLM_MODEL,
            'projects': list(PROJECTS.keys())
        })
    except Exception as e:
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 503

if __name__ == '__main__':
    print("=" * 60)
    print("Starting Documentation Search Web Interface")
    print("=" * 60)
    print(f"Server: http://localhost:5000")
    print(f"Ollama: {OLLAMA_URL}")
    print(f"Projects: {', '.join(PROJECTS.keys())}")
    print("=" * 60)
    app.run(debug=True, host='0.0.0.0', port=5000)
