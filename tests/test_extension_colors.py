"""Real-browser check: the extension reads modern CSS colors (oklch, used by Tailwind v4) correctly.

Before the fix, any oklch() text color was read as black, so light-gray text on a black page
looked "hidden" and normal page text was flagged. Needs Playwright with Chromium
(pip install playwright && playwright install chromium); skips otherwise.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ok = []


def check(n, c, d=""):
    ok.append(bool(c)); print(f"[{'PASS' if c else 'FAIL'}] {n} {d}")


PAGE = """<html><body style="background:#000;margin:0">
<p id="a" style="color:oklch(0.708 0 none)">Visible light gray text on black, Tailwind style.</p>
<div style="background:oklch(1 0 0)"><p id="b" style="color:oklch(0.99 0 0)">Hidden white on white in oklch.</p></div>
<p id="c" style="color:transparent">Transparent text nobody can see.</p>
<p id="d" style="color:lab(70 0 0)">Visible gray in lab color.</p>
</body></html>"""

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("[SKIP] playwright not installed"); sys.exit(0)

with sync_playwright() as p:
    try:
        b = p.chromium.launch()
    except Exception as e:
        print(f"[SKIP] no Chromium: {e}"); sys.exit(0)
    pg = b.new_page()
    pg.set_content(PAGE)
    pg.add_script_tag(content=(ROOT / "extension/detect.js").read_text())
    res = pg.evaluate("""() => {
      const D = window.ParallaxDetect, out = {};
      const env = { style: el => getComputedStyle(el), rect: el => el.getBoundingClientRect(),
        viewport: { width: innerWidth, height: innerHeight },
        page: { width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight },
        topAt: (x, y) => document.elementFromPoint(x, y) };
      for (const id of ["a", "b", "c", "d"]) out[id] = D.assess(document.getElementById(id).firstChild, env);
      return out;
    }""")
    b.close()

check("oklch light gray on black is visible", res["a"] == [], json.dumps(res["a"]))
check("oklch white on white is hidden", any("background" in r for r in res["b"]), json.dumps(res["b"]))
check("transparent text is hidden", any("transparent" in r for r in res["c"]), json.dumps(res["c"]))
check("lab() gray on black is visible", res["d"] == [], json.dumps(res["d"]))
print("\nALL PASS" if all(ok) else "\nSOME CHECKS FAILED")
sys.exit(0 if all(ok) else 1)
