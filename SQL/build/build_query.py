# ingest/build_index.py
import os, re, json, math, asyncio
import pandas as pd
from pathlib import Path
import csv

import httpx, yaml, numpy as np
from tqdm import tqdm
from pypdf import PdfReader
from markdown_it import MarkdownIt
from bs4 import BeautifulSoup

# Optional DOCX support (won't crash if python-docx isn't installed)
try:
    from docx import Document  # pip install python-docx
    DOCX_ENABLED = True
except Exception:
    Document = None
    DOCX_ENABLED = False

# FAISS (CPU)
import faiss


# ---------------- Config ----------------
CFG = yaml.safe_load(Path("config/app.yaml").read_text(encoding="utf-8"))

DOCS_DIR = Path(CFG["paths"]["docs_dir"])
INDEX_DIR = Path(CFG["paths"]["index_dir"])
INDEX_DIR.mkdir(parents=True, exist_ok=True)

OLLAMA_URL = CFG["ollama"]["url"].rstrip("/")
EMBED_MODEL = CFG["ollama"]["embed_model"]

CHUNK_TOKENS = int(CFG["retrieval"]["chunk_tokens"])
CHUNK_OVERLAP = int(CFG["retrieval"]["chunk_overlap"])


# ---------------- Utilities ----------------
def chunk_text(text: str, chunk_tokens: int = 700, overlap: int = 120):
    """
    Very simple char-based window approximating tokens (~4 chars/token).
    """
    if not text:
        return []
    max_chars = chunk_tokens * 4
    overlap_chars = overlap * 4

    out, cur, cur_chars = [], [], 0
    for w in text.split():
        if cur_chars + len(w) + 1 > max_chars:
            chunk = " ".join(cur).strip()
            if chunk:
                out.append(chunk)
            tail = chunk[-overlap_chars:] if chunk else ""
            cur = ([tail] if tail else [])
            cur_chars = len(tail)
        cur.append(w)
        cur_chars += len(w) + 1
    if cur:
        out.append(" ".join(cur).strip())
    return [c for c in out if c]


# ---------------- Loaders ----------------
def load_txt(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")

def load_md(path: Path) -> str:
    md = path.read_text(encoding="utf-8", errors="ignore")
    html = MarkdownIt().render(md)
    return BeautifulSoup(html, "lxml").get_text("\n")

def load_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    pages = []
    for p in reader.pages:
        try:
            pages.append(p.extract_text() or "")
        except Exception:
            pages.append("")
    return "\n".join(pages)

def load_html(path: Path) -> str:
    html = path.read_text(encoding="utf-8", errors="ignore")
    return BeautifulSoup(html, "lxml").get_text("\n")

def load_docx(path: Path) -> str:
    if not DOCX_ENABLED:
        return ""  # silently skip if python-docx is not installed
    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs)

def load_csv(path: Path) -> str:
    # Convert CSV to a markdown-like table for the LLM
    try:
        with open(path, "r", encoding="utf-8", errors="ignore", newline="") as f:
            sample = f.read(2048)
            f.seek(0)
            # detect delimiter (comma/semicolon/tab)
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            reader = csv.reader(f, dialect)
            rows = []
            max_rows = 5000  # safety cap
            for i, row in enumerate(reader):
                if i == 0:
                    header = [c.strip() for c in row]
                    rows.append("| " + " | ".join(header) + " |")
                    rows.append("| " + " | ".join("---" for _ in header) + " |")
                else:
                    rows.append("| " + " | ".join(c.strip() for c in row) + " |")
                if i >= max_rows:
                    rows.append(f"... ({i+1} rows, truncated)")
                    break
            return "\n".join(rows)
    except Exception:
        # fallback raw text
        return path.read_text(encoding="utf-8", errors="ignore")

SQL_STRIP_COMMENTS = True  # or move to app.yaml if you like

def split_sql_statements(s: str) -> list[str]:
    out, buf, in_s, in_d = [], [], False, False
    for ch in s:
        if ch == "'" and not in_d:  in_s = not in_s
        elif ch == '"' and not in_s: in_d = not in_d
        if ch == ";" and not in_s and not in_d:
            out.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf: out.append("".join(buf).strip())
    return [x for x in out if x]

def load_sql(path: Path) -> str:
    s = path.read_text(encoding="utf-8", errors="ignore")
    if SQL_STRIP_COMMENTS:
        s = re.sub(r"--[^\n]*", "", s)                 # line comments
        s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)    # block comments
    stmts = split_sql_statements(s)
    return "\n;\n".join(stmts)

def load_any(path: Path) -> str:
    """
    Dispatch to the right loader based on file extension.
    Also merges HTML with its .ocr.txt sidecar if present.
    """
    ext = path.suffix.lower()

    if ext in (".txt", ".log"):
        text = load_txt(path)

    elif ext in (".md", ".markdown"):
        text = load_md(path)

    elif ext in (".html", ".htm"):
        text = load_html(path)
        # merge OCR sidecar if it exists (so screenshots become searchable)
        ocr_sidecar = path.with_suffix(".ocr.txt")
        if ocr_sidecar.exists():
            text += "\n\n" + ocr_sidecar.read_text(encoding="utf-8", errors="ignore")

    elif ext == ".pdf":
        text = load_pdf(path)

    elif ext == ".docx":
        text = load_docx(path)  # returns "" if python-docx not installed

    elif ext == ".csv":
        text = load_csv(path)
    
    elif ext == ".sql":
        text = load_sql(path)

    else:
        # last-resort fallback as text (won't crash on unknown types)
        try:
            text = load_txt(path)
        except Exception:
            text = ""

    return text

# ---------------- Embeddings via Ollama ----------------
async def embed_texts(client, texts):
    """
    Super-safe: request one embedding per text.
    Avoids batch quirks where the server returns a single vector for many inputs.
    Returns np.ndarray shape (N, D), float32.
    """
    out = []
    for t in texts:
        r = await client.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": t},
            timeout=120.0,
        )
        r.raise_for_status()
        data = r.json()
        v = data.get("embedding") or (data.get("embeddings", [None])[0])
        if not isinstance(v, list) or not v:
            raise RuntimeError(f"Bad embedding payload: {data}")
        out.append(v)
    return np.array(out, dtype=np.float32)

# ---------------- Main ingest ----------------
async def main():
    if not DOCS_DIR.exists():
        print(f"Docs directory does not exist: {DOCS_DIR}")
        return

    # File discovery
    exts = {".pdf", ".md", ".markdown", ".txt", ".log", ".html", ".htm", ".csv", ".sql"}
    if DOCX_ENABLED:
        exts.add(".docx")

    files = [p for p in DOCS_DIR.rglob("*") if p.is_file() and p.suffix.lower() in exts]
    if not files:
        print(f"No docs found in {DOCS_DIR}. Add PDFs/MD/TXT (and HTML/DOCX) then rerun.")
        return

    # Build chunks
    chunks = []
    for path in files:
        try:
            text = load_any(path)
        except Exception as e:
            print(f"[WARN] Failed to load {path}: {e}")
            continue
        text = re.sub(r"\n{3,}", "\n\n", text)
        parts = chunk_text(text, CHUNK_TOKENS, CHUNK_OVERLAP)
        for idx, ch in enumerate(parts):
            chunks.append(
                {
                    "text": ch,
                    "source": str(path),
                    "chunk_id": f"{path.name}::chunk_{idx}",
                }
            )

    if not chunks:
        print("No text chunks produced (perhaps PDFs are scanned images without OCR?).")
        return

    print(f"Total chunks: {len(chunks)}")

    # Embed in batches
    batch_size = 64
    vecs = []
    async with httpx.AsyncClient() as client:
        for i in tqdm(range(0, len(chunks), batch_size), desc="Embedding"):
            batch_texts = [c["text"] for c in chunks[i : i + batch_size]]
            embs = await embed_texts(client, batch_texts)
            vecs.append(embs)

    X = np.vstack(vecs).astype(np.float32)

    # ---- VALIDATE before normalizing / indexing ----
    if X.ndim != 2 or X.shape[0] != len(chunks) or X.shape[1] == 0:
        raise RuntimeError(
            f"Embeddings bad shape: {X.shape}; chunks={len(chunks)}. "
            f"Check embed model '{EMBED_MODEL}' and server responses."
        )
    print(f"Embeddings OK: N={X.shape[0]} D={X.shape[1]}")

    # Normalize (cosine similarity with inner product index)
    norms = np.linalg.norm(X, axis=1, keepdims=True) + 1e-12
    Xn = X / norms

    dim = Xn.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(Xn)

    # Persist
    faiss.write_index(index, str(INDEX_DIR / "chunks.faiss"))
    with open(INDEX_DIR / "chunks.json", "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False)

    print(f"Saved index to {INDEX_DIR}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())