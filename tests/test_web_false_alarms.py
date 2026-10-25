"""Real-browser check: a normal website's menus, cards, animations, tabs and FAQs must not raise threats.

tests/fixtures/realistic_site.html copies patterns real sites use (sticky header, dropdown and mobile
menus with contact details, clickable cards, scroll-reveal fades, collapsed FAQ answers, hidden tabs,
tooltips, carousels, cookie banner, build comment) plus ONE real hidden attack. Before the fix the
extension raised 9 threats on it; only 1 is real. Needs Playwright + Chromium; skips otherwise.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from parallax.detect import PatternDetector, MLDetector  # noqa: E402
from parallax.gap.html_gap import HiddenSpan  # noqa: E402
from parallax.scan import _judge  # noqa: E402

ok = []


def check(n, c, d=""):
    ok.append(bool(c)); print(f"[{'PASS' if c else 'FAIL'}] {n} {d}")


try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("[SKIP] playwright not installed"); sys.exit(0)

with sync_playwright() as p:
    try:
        b = p.chromium.launch()
    except Exception as e:
        print(f"[SKIP] no Chromium: {e}"); sys.exit(0)
    pg = b.new_page(viewport={"width": 1280, "height": 800})
    pg.goto((ROOT / "tests/fixtures/realistic_site.html").as_uri())
    pg.wait_for_timeout(300)
    pg.add_script_tag(content=(ROOT / "extension/detect.js").read_text())
    d = pg.evaluate("""() => {
      const D = window.ParallaxDetect;
      const env = { style: el => getComputedStyle(el), rect: el => el.getBoundingClientRect(),
        viewport: { width: innerWidth, height: innerHeight },
        page: { width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight },
        topAt: (x, y) => document.elementFromPoint(x, y) };
      const { hidden, visible } = D.scanDocument(document, env);
      const links = [...document.querySelectorAll("a[href]")].map(a => a.getAttribute("href").replace(/^(mailto|tel):/i, "")).join(" ");
      return { spans: hidden.map(h => ({ text: h.text, reasons: h.reasons })), known: [location.hostname, links, visible].join(" ") };
    }""")
    b.close()

found = _judge([HiddenSpan(s["text"], s["reasons"]) for s in d["spans"]], d["known"],
               [PatternDetector(), MLDetector()], long_passage_caution=False, web=True)
threats = [f.text for f in found if f.level == "threat"]
cautions = [f.text for f in found if f.level == "caution"]
check("the real hidden attack is a threat", any("Note to the AI assistant" in t for t in threats))
check("nothing else on the page is a threat", len(threats) == 1, json.dumps([t[:50] for t in threats]))
check("at most 1 caution from normal page UI", len(cautions) <= 1, json.dumps([t[:50] for t in cautions]))
check("clickable cards aren't 'covered'", not any("covered" in r for s in d["spans"] for r in s["reasons"]))
check("scroll-reveal sections aren't hidden", not any("Trusted by" in s["text"] for s in d["spans"]))
print("\nALL PASS" if all(ok) else "\nSOME CHECKS FAILED")
sys.exit(0 if all(ok) else 1)
