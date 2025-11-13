import json, sys

def to_bool(v): return "TRUE" if v else "FALSE"

def convert(inp_json, out_txt):
    with open(inp_json, "r", encoding="utf-8") as f:
        items = json.load(f)
    if isinstance(items, dict) and "cookies" in items:
        items = items["cookies"]

    lines = ["# Netscape HTTP Cookie File"]
    for c in items:
        domain = c.get("domain") or ""        # keep leading dot if present
        tail = "TRUE" if domain.startswith(".") else "FALSE"
        path = c.get("path") or "/"
        secure = to_bool(c.get("secure", False))
        # support common expiry fields
        exp = 0
        for key in ("expirationDate", "expires", "expiry"):
            v = c.get(key)
            if v:
                try:
                    exp = int(float(v))
                    break
                except Exception:
                    pass
        name = c.get("name") or ""
        value = c.get("value") or ""
        lines.append("\t".join([domain, tail, path, secure, str(exp), name, value]))

    with open(out_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python cookie_json_to_netscape.py cookies.json cookies.txt")
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2])
