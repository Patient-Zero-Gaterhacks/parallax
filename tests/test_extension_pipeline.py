"""Extension detector (JS, via jsdom) -> server /classify, on the lab pages."""
import json, os, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from parallax.server import app
c = TestClient(app); ok = []
def check(n, cond, d=""):
    ok.append(bool(cond)); print(f"[{'PASS' if cond else 'FAIL'}] {n} {d}")
ext = Path(__file__).resolve().parents[1] / "extension"
def pipeline(path):
    html = c.get(path).text
    f = tempfile.NamedTemporaryFile("w", suffix=".html", delete=False); f.write(html); f.close()
    payload = json.loads(subprocess.check_output(["node", str(ext / "test/dump_spans.js"), f.name],
                         env={**os.environ, "JSDOM_PATH": os.environ.get("JSDOM_PATH", "jsdom")}))
    return payload, c.post("/classify", json=payload).json()["findings"]
p, f = pipeline("/lab/recipe")
check("recipe page: extension finds 2 hidden spans, server rates both threat",
      len(p["spans"]) == 2 and all(x["level"] == "threat" for x in f), f"({[x['why'] for x in f]})")
p, f = pipeline("/lab/honest")
check("honest page: nothing hidden", not p["spans"])
# a realistic page with a collapsed FAQ and a skip link: must stay calm
faq = ("<a href='#main' style='position:absolute;left:-9999px'>Skip to content</a><h1>FAQ</h1>"
       "<details><summary>Refunds</summary><div style='display:none'>" + "Refunds are processed within 5 to 7 business days after we receive the item back in our warehouse and inspect it. " * 2 + "</div></details>")
f2 = tempfile.NamedTemporaryFile("w", suffix=".html", delete=False); f2.write(faq); f2.close()
payload = json.loads(subprocess.check_output(["node", str(ext / "test/dump_spans.js"), f2.name],
                     env={**os.environ, "JSDOM_PATH": os.environ.get("JSDOM_PATH", "jsdom")}))
levels = [x["level"] for x in c.post("/classify", json=payload).json()["findings"]]
check("normal site (skip link + collapsed FAQ): no threat or caution", set(levels) <= {"info"}, f"({levels})")
print("\nALL PASS" if all(ok) else "\nSOME CHECKS FAILED"); sys.exit(0 if all(ok) else 1)
