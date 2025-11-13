# scripts/convert_raw_to_text.py
import re, sys
from pathlib import Path
from bs4 import BeautifulSoup

# --- filters ---
BREADC_PAT = re.compile(r'^\s*home\s*/\s*.+', re.I)          # "Home / Revenue / ... "
BACKLINK_PAT = re.compile(r'\bBack to List\b', re.I)
OCR_GARBAGE = re.compile(r'^\s*(\[IMAGE .*?\]|OCR_ERROR:.*)$', re.I)

def keep_line(s: str) -> bool:
    if not s or s.isspace(): return False
    if BREADC_PAT.match(s):  return False
    if BACKLINK_PAT.search(s): return False
    if OCR_GARBAGE.match(s): return False
    return True

def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    # remove obvious chrome
    for sel in ["script","style","nav","footer",".breadcrumbs",".toc",".dw__toc"]:
        for n in soup.select(sel): n.decompose()

    lines = []
    for el in soup.find_all(["h1","h2","h3","h4","h5","h6","p","li","pre","code","table","th","td"]):
        txt = el.get_text(" ", strip=True)
        if not txt or not keep_line(txt):
            continue
        if el.name in {"h1","h2","h3"}:
            lines.append("\n" + txt + "\n" + ("-"*len(txt)))
        else:
            lines.append(txt)

    out = "\n".join(lines)
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()

def main():
    if len(sys.argv) < 3:
        print("Usage: python scripts/convert_raw_to_text.py <raw_dir> <converted_dir>")
        sys.exit(1)

    raw_dir = Path(sys.argv[1]); out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)

    html_files = sorted(raw_dir.glob("*.html"))
    if not html_files:
        print(f"[WARN] No HTML files in {raw_dir}")

    for i, html_path in enumerate(html_files, 1):
        stem = html_path.stem
        txt_path = out_dir / f"{stem}.txt"

        html = html_path.read_text(encoding="utf-8", errors="ignore")
        body = html_to_text(html)

        # append OCR sidecar if exists, but filter noisy lines
        ocr_path = raw_dir / f"{stem}.ocr.txt"
        if ocr_path.exists():
            ocr = ocr_path.read_text(encoding="utf-8", errors="ignore")
            ocr_lines = [ln for ln in ocr.splitlines() if keep_line(ln.strip())]
            ocr_clean = "\n".join(ocr_lines).strip()
            if ocr_clean:
                body += "\n\n[OCR]\n" + ocr_clean

        txt_path.write_text(body + "\n", encoding="utf-8")
        print(f"[{i:04d}] -> {txt_path.name}")

if __name__ == "__main__":
    main()
