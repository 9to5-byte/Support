#!/usr/bin/env python3
# convert_html_to_md.py
import re
import sys
from pathlib import Path
from bs4 import BeautifulSoup

# ---------- regex cleaners for post-processing ----------
# TOC block like:
# TOC START
#  ...
# TOC END
TOC_BLOCK_RE   = re.compile(r'(?is)^\s*TOC START.*?TOC END\s*$', re.MULTILINE)
# DokuWiki section edit metadata lines:
# EDIT{"target":"section", ...}
EDIT_LINE_RE   = re.compile(r'(?im)^\s*EDIT\{.*?\}\s*$')
# Backlink line:
# [Start page](...)
START_PAGE_RE  = re.compile(r'(?im)^\s*\[Start page\]\(.*?\)\s*$')
# Lone "html" line sometimes emitted by exporter
HTML_LINE_RE   = re.compile(r'(?im)^\s*html\s*$')
# Bare page-id / namespace line e.g. "clients:acceptanceinsert"
PAGE_ID_RE     = re.compile(r'(?im)^\s*[a-z0-9_:-]{3,}\s*$')

# Invisible chars to normalize (BOM, zero-width, NBSP, etc.)
INVISIBLES = {
    "\ufeff": "",   # BOM
    "\u200b": "",   # zero-width space
    "\u200e": "",   # LRM
    "\u200f": "",   # RLM
    "\xa0":  " ",   # NBSP -> space
}

def _strip_invisibles(s: str) -> str:
    for bad, repl in INVISIBLES.items():
        s = s.replace(bad, repl)
    return s

def post_clean(markdown_text: str) -> str:
    """
    Remove wiki export artifacts (TOC, EDIT{}, Start page, stray 'html', page-id lines),
    normalize whitespace, and return clean Markdown.
    """
    # 1) Normalize invisible chars first so regex matches reliably
    s = _strip_invisibles(markdown_text)

    # 2) Drop TOC blocks and EDIT{...} lines
    s = TOC_BLOCK_RE.sub("", s)
    s = EDIT_LINE_RE.sub("", s)

    # 3) Remove 'Start page' backlink lines everywhere
    s = START_PAGE_RE.sub("", s)

    # 4) Remove stray 'html' lines from exporter
    s = HTML_LINE_RE.sub("", s)

    # 5) Drop bare page-id lines like 'clients:acceptancebrowser'
    #    when immediately followed (skipping blanks AND start-page lines) by a heading.
    #    Also, if such a line appears near the very top (first few non-empty lines), drop it.
    lines = s.splitlines()
    cleaned = []
    i = 0
    nonempty_seen = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped:
            nonempty_seen += 1

        if PAGE_ID_RE.match(stripped):
            # Heuristic: if within first 5 non-empty lines, drop outright
            if nonempty_seen <= 5:
                i += 1
                continue

            # Look ahead: skip blank lines and any '[Start page](...)' lines
            j = i + 1
            while j < len(lines):
                nxt = _strip_invisibles(lines[j]).strip()
                if not nxt:
                    j += 1
                    continue
                if START_PAGE_RE.match(nxt):
                    j += 1
                    continue
                break

            if j < len(lines) and lines[j].lstrip().startswith("#"):
                # Next meaningful content is a heading -> drop page-id line
                i += 1
                continue

        cleaned.append(line)
        i += 1

    s = "\n".join(cleaned)

    # 6) Collapse multiple blank lines and trim trailing spaces
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = "\n".join(ln.rstrip() for ln in s.splitlines())
    return s.strip()


# ---------- HTML -> Markdown ----------
def html_to_markdown(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    # Focus on main content if present
    content = soup.find(id="dokuwiki__content")
    if content:
        soup = content

    # Remove obvious chrome / noise
    for sel in ["script", "style", "nav", "header", "footer", "aside",
                ".breadcrumbs", ".dw__toc", ".toc", ".pageId"]:
        for n in soup.select(sel):
            n.decompose()

    # Remove breadcrumbs by text hints
    for t in soup.find_all(string=lambda s: s and ("Trace:" in s or "You are here" in s)):
        p = t.find_parent()
        if p:
            p.decompose()

    # Remove "Back to ..." links
    for a in soup.find_all("a", string=lambda s: s and s.strip().lower().startswith("back to")):
        a.decompose()

    # Remove footer boilerplate like "Driven by DokuWiki"
    for t in soup.find_all(string=lambda s: s and "Driven by DokuWiki" in s):
        p = t.find_parent()
        if p:
            p.decompose()

    # Remove all images/screenshots
    for img in soup.find_all("img"):
        img.decompose()

    def convert_inline(node) -> str:
        if node is None:
            return ""
        if node.name is None:  # text node
            return str(node).replace("\n", " ")
        name = node.name.lower()
        if name in ("strong", "b"):
            return "**" + "".join(convert_inline(c) for c in node.children) + "**"
        if name in ("em", "i"):
            return "*" + "".join(convert_inline(c) for c in node.children) + "*"
        if name == "code":
            if node.find_parent("pre"):
                return "".join(convert_inline(c) for c in node.children)
            return "`" + node.get_text() + "`"
        if name == "a":
            href = node.get("href") or ""
            text = "".join(convert_inline(c) for c in node.children).strip()
            return f"[{text}]({href})" if (href and text) else text
        if name == "br":
            return "\n"
        return "".join(convert_inline(c) for c in node.children)

    md_lines = []

    def process_node(node, indent=0):
        if node is None:
            return
        if getattr(node, "name", None) is None:
            text = str(node).strip()
            if text:
                md_lines.append(" " * indent + text)
            return

        tag = node.name.lower()
        if tag in ("script", "style", "meta", "link", "noscript"):
            return

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            md_lines.append("#" * level + " " + convert_inline(node).strip())
            md_lines.append("")
            return

        if tag == "p":
            text = "".join(convert_inline(c) for c in node.children).strip()
            if text:
                md_lines.append(text)
                md_lines.append("")
            return

        if tag in ("ul", "ol"):
            ordered = (tag == "ol")
            items = [li for li in node.find_all("li", recursive=False)]
            for i, li in enumerate(items, 1):
                prefix = f"{i}. " if ordered else "- "
                sublists = [c for c in li.find_all(["ul", "ol"], recursive=False)]
                if sublists:
                    # text before nested lists
                    parts = []
                    for c in li.contents:
                        if getattr(c, "name", None) in ("ul", "ol"):
                            break
                        parts.append(c)
                    text = "".join(convert_inline(p) for p in parts).strip()
                    md_lines.append(" " * indent + prefix + text)
                    for sub in sublists:
                        process_node(sub, indent + 4)
                else:
                    text = "".join(convert_inline(c) for c in li.children).strip()
                    md_lines.append(" " * indent + prefix + text)
            md_lines.append("")
            return

        if tag == "li":
            text = "".join(convert_inline(c) for c in node.children).strip()
            md_lines.append(" " * indent + "- " + text)
            return

        if tag == "table":
            rows = node.find_all("tr")
            if not rows:
                return
            matrix, header = [], None
            for r in rows:
                cells = []
                for cell in r.find_all(["th", "td"]):
                    txt = "".join(convert_inline(c) for c in cell.children).strip()
                    cells.append(txt.replace("|", r"\|"))
                matrix.append(cells)
                if r.find("th"):
                    header = cells
            cols = max(len(r) for r in matrix)
            if header is None:
                header, data = matrix[0], matrix[1:]
            else:
                data = matrix[1:]
            header += [""] * (cols - len(header))
            md_lines.append("| " + " | ".join(header) + " |")
            md_lines.append("| " + " | ".join(["---"] * cols) + " |")
            for row in data:
                row += [""] * (cols - len(row))
                md_lines.append("| " + " | ".join(row) + " |")
            md_lines.append("")
            return

        if tag == "pre":
            code_text = node.get_text().rstrip("\n")
            lang = ""
            c = node.find("code")
            if c and c.get("class"):
                for cls in c.get("class"):
                    if cls.startswith("language-"):
                        lang = cls.split("language-")[-1]
                        break
                    if cls in ("python", "bash", "json", "java", "cpp", "sql"):
                        lang = cls
                        break
            fence = "```" + (lang if lang else "")
            md_lines.append(fence)
            md_lines.extend(code_text.splitlines())
            md_lines.append("```")
            md_lines.append("")
            return

        if tag == "blockquote":
            before = len(md_lines)
            for c in node.children:
                process_node(c, 0)
            quoted = md_lines[before:]
            md_lines[before:] = []
            for line in quoted:
                md_lines.append(">" if line == "" else ("> " + line))
            md_lines.append("")
            return

        # default: process children
        for c in node.children:
            process_node(c, indent)

    for child in soup.children:
        process_node(child, 0)

    markdown_text = "\n".join(md_lines)
    return post_clean(markdown_text)


# ---------- CLI ----------
def main():
    if len(sys.argv) != 3:
        print("Usage: python convert_html_to_md.py <input_dir> <output_dir>")
        sys.exit(1)

    input_dir = Path(sys.argv[1]).resolve()
    output_dir = Path(sys.argv[2]).resolve()

    if not input_dir.is_dir():
        print(f"[ERROR] Input directory not found: {input_dir}")
        sys.exit(2)

    count = 0
    for html_path in input_dir.rglob("*.html"):
        # Skip any weird OCR-named HTML sidecars, if present
        if html_path.name.endswith(".ocr.html"):
            continue

        html = html_path.read_text(encoding="utf-8", errors="ignore")
        md = html_to_markdown(html)

        rel = html_path.relative_to(input_dir).with_suffix(".md")
        out_path = output_dir / rel
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md + "\n", encoding="utf-8")
        count += 1
        print(f"[OK] {html_path} -> {out_path}")

    if count == 0:
        print("[WARN] No .html files found under input_dir")

if __name__ == "__main__":
    main()
