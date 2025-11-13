# scripts/scrape_dokuwiki_with_ocr.py
import re
import io
import sys
import time
import shutil
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs

import httpx
from bs4 import BeautifulSoup
from PIL import Image
import pytesseract

# ---------- Cookies ----------
def load_netscape_cookies(path: Path) -> httpx.Cookies:
    cookies = httpx.Cookies()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 7:
            continue
        domain, tail, pth, secure, expires, name, value = parts
        # Force broad path so it works for /docs/dependq/ too:
        cookies.set(name, value, domain=domain, path="/")
    return cookies

# ---------- URL helpers ----------
def make_abs(base: str, href: str) -> str:
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return urljoin(base, href)
    return urljoin(base, href)

def same_host(a: str, b: str) -> bool:
    return urlparse(a).netloc == urlparse(b).netloc

# ---------- Network helper (simple retry) ----------
def get_with_retry(client: httpx.Client, url: str, **kw) -> httpx.Response:
    for attempt in range(5):
        try:
            r = client.get(url, **kw)
            r.raise_for_status()
            return r
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (429, 500, 502, 503, 504):
                time.sleep(1.2 * (attempt + 1))
                continue
            raise
        except httpx.HTTPError:
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"Failed after retries: {url}")

# ---------- Index-page parsing & crawl ----------
def parse_index_page(html: str, base: str, namespace: str):
    """
    From an 'index' page (do=index), find:
      - content page ids within namespace (NOT ending with :index)
      - child index urls (links still pointing to do=index within namespace or pagination)
    """
    soup = BeautifulSoup(html, "lxml")
    page_ids = []
    child_index_urls = []

    for a in soup.find_all("a", href=True):
        href = make_abs(base, a["href"])
        up = urlparse(href)
        if "doku.php" not in up.path:
            continue
        qs = parse_qs(up.query)

        page_id = (qs.get("id") or [None])[0]
        do_val  = (qs.get("do") or [None])[0]

        # namespace filter
        if page_id and not page_id.startswith(namespace):
            continue

        # deeper index pages (sub-namespaces, pagination)
        if do_val == "index":
            if same_host(base, href):
                child_index_urls.append(href)
            continue

        # exportable content pages
        if page_id and page_id.startswith(namespace) and not page_id.endswith(":index"):
            page_ids.append(page_id)

    # de-duplicate preserving order
    seen = set(); uniq_ids = []
    for pid in page_ids:
        if pid not in seen:
            uniq_ids.append(pid); seen.add(pid)

    seenu = set(); uniq_child = []
    for u in child_index_urls:
        if u not in seenu:
            uniq_child.append(u); seenu.add(u)

    return uniq_ids, uniq_child

def crawl_namespace(start_index_url: str, namespace: str, client: httpx.Client):
    """
    BFS crawl starting at start_index_url (must be do=index).
    Follows nested do=index + pagination within same host.
    Returns ordered unique list of page ids.
    """
    base = f"{urlparse(start_index_url).scheme}://{urlparse(start_index_url).netloc}"
    queue = [start_index_url]
    seen_index = set()
    collected_ids = []

    while queue:
        url = queue.pop(0)
        if url in seen_index:
            continue
        seen_index.add(url)

        try:
            r = get_with_retry(client, url)
        except Exception as e:
            print(f"[WARN] index fetch failed: {url} ({e})")
            continue

        ids, child_indexes = parse_index_page(r.text, base, namespace)

        for pid in ids:
            if pid not in collected_ids:
                collected_ids.append(pid)

        for ci in child_indexes:
            if ci not in seen_index and ci not in queue:
                queue.append(ci)

    return collected_ids

# ---------- OCR ----------
def ocr_image_bytes(img_bytes: bytes) -> str:
    try:
        im = Image.open(io.BytesIO(img_bytes))
        return pytesseract.image_to_string(im)
    except Exception as e:
        return f"[OCR_ERROR: {e}]"

# ---------- Main ----------
def sanitize_filename(page_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", page_id)

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="Dokuwiki index URL (?do=index)")
    ap.add_argument("--namespace", default="clients:", help="Namespace prefix to include (default: clients:)")
    ap.add_argument("--out", default="docs", help="Output folder (default: docs)")
    ap.add_argument("--cookies", default="cookies.txt", help="Netscape cookie file (default: cookies.txt)")
    ap.add_argument("--timeout", type=float, default=45.0)
    args = ap.parse_args()

    out_dir = Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)
    img_dir = out_dir / "dokuwiki_files"; img_dir.mkdir(parents=True, exist_ok=True)

    cookies_file = Path(args.cookies)
    if not cookies_file.exists():
        print(f"[ERROR] cookies file not found: {cookies_file}")
        sys.exit(1)

    if not shutil.which("tesseract"):
        print("[WARN] Tesseract binary not found on PATH. OCR will likely be empty. Install Tesseract and rerun.")

    cookies = load_netscape_cookies(cookies_file)
    base = f"{urlparse(args.start).scheme}://{urlparse(args.start).netloc}"

    # NOTE: If your wiki exports from another path (e.g., '/doku.php'), change here:
    start_path = urlparse(args.start).path
    EXPORT_PATH = start_path if start_path.endswith("doku.php") else "/doku.php"

    with httpx.Client(cookies=cookies, timeout=args.timeout, follow_redirects=True) as client:
        print(f"[INFO] Crawling namespace '{args.namespace}' from: {args.start}")
        page_ids = crawl_namespace(args.start, args.namespace, client)
        print(f"[INFO] Found {len(page_ids)} pages.")

        for i, pid in enumerate(page_ids, 1):
            print(f"[{i:04d}/{len(page_ids)}] {pid}")

            # 1) export HTML (clean page content)
            export_url = urljoin(base, EXPORT_PATH)
            try:
                html_res = get_with_retry(client, export_url, params={"id": pid, "do": "export_xhtml"})
            except Exception as e:
                print(f"   [WARN] export failed: {pid} ({e})")
                continue

            stem = sanitize_filename(pid)
            html_path = out_dir / f"{stem}.html"
            html_path.write_text(html_res.text, encoding="utf-8")

            # 2) parse HTML to find images
            soup = BeautifulSoup(html_res.text, "lxml")
            imgs = soup.find_all("img")
            ocr_chunks = []
            for img in imgs:
                src = img.get("src") or ""
                if not src:
                    continue
                img_url = make_abs(base, src)

                # choose a filename (prefer media= query if present)
                up = urlparse(img_url)
                qs = parse_qs(up.query)
                media_name = (qs.get("media") or [Path(up.path).name])[0]
                media_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", media_name)
                local_img_path = img_dir / media_name

                # download image
                try:
                    ir = get_with_retry(client, img_url)
                    local_img_path.write_bytes(ir.content)
                except Exception as e:
                    print(f"   [WARN] image download failed: {img_url} ({e})")
                    continue

                # OCR it
                text = ocr_image_bytes(ir.content).strip()
                if text:
                    ocr_chunks.append(f"[IMAGE {media_name}] {text}")

            # 3) write sidecar OCR text (if any)
            if ocr_chunks:
                (out_dir / f"{stem}.ocr.txt").write_text(
                    "\n\n".join(ocr_chunks) + "\n", encoding="utf-8"
                )

if __name__ == "__main__":
    main()
