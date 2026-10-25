"""Hiding tricks the finders used to miss, plus harmless look-alikes that must stay quiet.

tests/fixtures/finder_gaps.html has 18 hidden attacks, each tagged with its own domain (exfil-a1.xyz ...):
alt/title/aria-label/data-* attributes, a hidden form field, a meta description, JSON-LD, a lookalike
link, white text in hsl()/oklch(), transparent text (3 ways), scale(0), clip-path, a screen-reader-only
class matched by a compound selector, right:-9999px and <template>. It also has harmless alt text,
JSON-LD with a phone number and links, JSON data attributes, CSRF fields, a desktop-only block, and
dark text in hsl()/oklch(). Checks the Python finder (emails, files, URL scans) and the extension's
finder in real Chromium (skipped if Playwright/Chromium aren't installed).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from parallax.detect import MLDetector, PatternDetector  # noqa: E402
from parallax.gap.html_gap import HiddenSpan, analyze_html  # noqa: E402
from parallax.scan import _judge  # noqa: E402

HTML = (ROOT / "tests/fixtures/finder_gaps.html").read_text()
ATTACKS = ["m1", "j1", "a1", "t1", "r1", "d1", "f1", "l1", "c1", "c2", "c3", "c4", "c5", "s1", "s2", "s3", "s4", "s5"]
NOT_HIDDEN = ["Visit our new location", "starter we have kept alive", "Gluten-free loaves", "Fresh bread every morning"]
DETS = [PatternDetector(), MLDetector()]
ok = []


def check(n, c, d=""):
    ok.append(bool(c)); print(f"[{'PASS' if c else 'FAIL'}] {n} {d}")


def marker(a):
    return f"exfil-{a}.xyz" if a != "l1" else "paypal-account-review-l1.xyz"


def verify(label, spans, visible, web):
    texts = [s["text"] for s in spans]
    missed = [a for a in ATTACKS if not any(marker(a) in t for t in texts)]
    check(f"{label}: finds all {len(ATTACKS)} hidden attacks", not missed, f"missed {missed}")
    wrong = [v for v in NOT_HIDDEN if any(v in t for t in texts)]
    check(f"{label}: visible text (hsl/oklch dark text, desktop-only block) not called hidden", not wrong, str(wrong))
    check(f"{label}: CSRF token / JSON props / short aria label not extracted",
          not any(x in t for t in texts for x in ("a8f3b2c9", '"items"', "Open the navigation menu")))
    found = _judge([HiddenSpan(s["text"], s["reasons"]) for s in spans], visible, DETS,
                   long_passage_caution=not web, web=web)
    lv = {a: next((f.level for f in found if marker(a) in f.text), None) for a in ATTACKS}
    # a lookalike link alone: a caution in emails/files, info on live pages (real sites are full of
    # redirect and tracking links); it's still found, and any detector flag on it escalates
    want_link = "info" if web else "caution"
    bad = {a: l for a, l in lv.items() if l != (want_link if a == "l1" else "threat")}
    check(f"{label}: every attack judged threat (lookalike link: {want_link})", not bad, str(bad))
    noise = [(f.level, f.text[:50]) for f in found
             if f.level != "info" and not any(marker(a) in f.text for a in ATTACKS)]
    check(f"{label}: harmless alt text, JSON-LD phone/links, og:description stay quiet", not noise, json.dumps(noise))


# 1. Python finder (emails, saved pages, /scan/url)
r = analyze_html(HTML)
verify("python", [{"text": s.text, "reasons": s.reasons} for s in r["hidden"]], r["visible_text"], web=False)
check("python: harmless alt text found as markup (judge decides)",
      any(s.reasons[0].startswith("markup: alt text") and "bakers shaping" in s.text for s in r["hidden"]))

# 2. Extension finder in a real browser
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("[SKIP] playwright not installed"); sync_playwright = None
if sync_playwright:
    with sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:
            b = None; print(f"[SKIP] no Chromium: {e}")
        if b:
            pg = b.new_page(viewport={"width": 1280, "height": 800})
            pg.goto((ROOT / "tests/fixtures/finder_gaps.html").as_uri())
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
            verify("extension", d["spans"], d["known"], web=True)

print("\nALL PASS" if all(ok) else "\nSOME CHECKS FAILED")
sys.exit(0 if all(ok) else 1)
