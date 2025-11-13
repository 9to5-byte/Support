# scripts/scrape_dokuwiki.py
import re
import os
import sys
import argparse
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs, urlunparse, urlencode

import httpx
from bs4 import BeautifulSoup

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

# ---------- Discovery ----------
def parse_index_page(html: str, base: str, namespace: str):
    """
    From an 'index' page (do=index), find:
      - content page ids within namespace (NOT ending with :index)
      - child index urls (links still pointing to do=index within namespace)
    Also include pagination ('next') index links when present.
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

        # Skip links that are not within the target namespace
        if page_id and not page_id.startswith(namespace):
            continue

        # Collect deeper index pages to crawl (namespace trees + pagination)
        if do_val == "index":
            # (1) child namespace indexes (e.g., clients:sub:ns &do=index)
            if page_id and page_id.startswith(namespace):
                if same_host(base, href):
                    child_index_urls.append(href)
                continue
            # (2) some Dokuwiki skins add pagination links without id change
            if same_host(base, href):
                child_index_urls.append(href)
            continue

        # Real content pages (exportable)
        if page_id and page_id.startswith(namespace) and not page_id.endswith(":index"):
            page_ids.append(page_id)

    # de-dupe but preserve order
    seen = set()
    uniq_ids = []
    for pid in page_ids:
        if pid not in seen:
            uniq_ids.append(pid); seen.add(pid)

    # same for child index urls
    seen_u = set()
    uniq_child = []
    for u in child_index_urls:
        if u not in seen_u:
            uniq_child.append(u); seen_u.add(u)

    return uniq_ids, uniq_child

def crawl_namespace(start_index_url: str, namespace: str, client: httpx.Client):
    """
    Breadth-first crawl starting at start_index_url (must be do=index).
    Follows deeper do=index links + pagination within the same host.
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
            r = client.get(url)
            r.raise_for_status()
        except httpx.HTTPError as e:
            print(f"[WARN] index fetch failed: {url} ({e})")
            continue

        ids, child_indexes = parse_index_page(r.text, base, namespace)

        # append ids in the order discovered (no duplicates)
        for pid in ids:
            if pid not in collected_ids:
                collected_ids.append(pid)

        # enqueue new index pages
        for ci in child_indexes:
            if ci not in seen_index and ci not in queue:
                queue.append(ci)

    return collected_ids

# ---------- Main ----------
def sanitize_filename(page_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", page_id) + ".html"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True,
                    help="A Dokuwiki index URL, e.g. https://host/docs/rd/doku.php?id=clients:ns&do=index")
    ap.add_argument("--namespace", default="clients:",
                    help="Dokuwiki namespace prefix to include (default: clients:)")
    ap.add_argument("--out", default="docs", help="Output folder")
    ap.add_argument("--cookies", default="cookies.txt", help="Netscape cookie file")
    ap.add_argument("--timeout", type=float, default=30.0)
    args = ap.parse_args()

    out_dir = Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)

    cookies_file = Path(args.cookies)
    if not cookies_file.exists():
        print(f"[ERROR] cookies file not found: {cookies_file}")
        sys.exit(1)

    cookies = load_netscape_cookies(cookies_file)
    base = f"{urlparse(args.start).scheme}://{urlparse(args.start).netloc}"

    with httpx.Client(cookies=cookies, timeout=args.timeout, follow_redirects=True) as client:
        print(f"[INFO] Crawling namespace '{args.namespace}' from: {args.start}")
        page_ids = crawl_namespace(args.start, args.namespace, client)
        print(f"[INFO] Discovered {len(page_ids)} pages in namespace.")

        start_path = urlparse(args.start).path           
        export_url = urljoin(base, start_path)
        for i, pid in enumerate(page_ids, 1):
            try:
                rr = client.get(export_url, params={"id": pid, "do": "export_xhtml"})
                rr.raise_for_status()
                fn = sanitize_filename(pid)
                (out_dir / fn).write_text(rr.text, encoding="utf-8")
                print(f"[{i:04d}/{len(page_ids)}] saved {fn}")
            except httpx.HTTPError as e:
                print(f"[WARN] failed {pid}: {e}")

if __name__ == "__main__":
    main()
