"""Real Chromium + the extension: "Show on page" must make every red and yellow finding readable, and
clicking it again must put the page back exactly as it was.

Pages: tests/fixtures/finder_gaps.html (18 hiding tricks, including markup an AI reads but the page never
shows) and tests/fixtures/parent_hidden.html (text hidden by a parent or grandparent: display:none, opacity,
text-fill, scale(0), screen-reader-only class, visibility, clip-path, off-screen, zero height, transparent
color, font-size 0). Before the fix only the text's own element was revealed, so parent-hidden text stayed
hidden, and markup findings had nothing to show. Skips without Playwright/Chromium.
"""
import json
import re
import socket
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"
PAGES = {
    "finder_gaps.html": [f"exfil-{a}.xyz" for a in ["m1", "j1", "a1", "t1", "r1", "d1", "f1", "c1", "c2", "c3", "c4",
                                                     "c5", "s1", "s2", "s3", "s4", "s5"]] + ["paypal-account-review-l1.xyz"],
    "parent_hidden.html": [f"exfil-p{i}.xyz" for i in range(1, 13)],
}
ok = []


def check(n, c, d=""):
    ok.append(bool(c)); print(f"[{'PASS' if c else 'FAIL'}] {n} {d}")


class Stub(BaseHTTPRequestHandler):
    """Serves the fixtures and answers /classify: instructions to an AI are red, a lookalike link is yellow."""
    def log_message(self, *a):
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "*")

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def do_GET(self):
        name = self.path.lstrip("/")
        if name in PAGES:
            body, kind = (FIXTURES / name).read_bytes(), "text/html"
        else:
            body, kind = json.dumps({"ok": True, "public": True, "detectors": ["patterns"]}).encode(), "application/json"
        self.send_response(200); self._cors(); self.send_header("Content-Type", kind)
        self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        spans = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))))["spans"]
        out = []
        for s in spans:
            level = ("threat" if re.search(r"ignore (all )?previous", s["text"]) else
                     "caution" if any("link text shows" in r for r in s["reasons"]) else "info")
            out.append({"text": s["text"], "where": s["reasons"], "level": level,
                        "why": ["talks to an AI (patterns)"] if level == "threat" else [], "detectors": {}})
        body = json.dumps({"findings": out}).encode()
        self.send_response(200); self._cors(); self.send_header("Content-Type", "application/json")
        self.end_headers(); self.wfile.write(body)


# The page without our panel (the card changes as you click it).
SNAPSHOT = """() => { const c = document.documentElement.cloneNode(true);
  c.querySelectorAll('#parallax-panel').forEach(n => n.remove()); return c.outerHTML; }"""

# For each marker: "text" if the attack text itself is readable, "label" if a visible label shows it,
# otherwise why not. Readable = checkVisibility, no clipping (clip, clip-path or a zero-size box), mostly
# opaque, font >= 6px, an opaque text color/fill that stands out from the background, real size, and on the page.
READABLE = """(markers) => {
  // any CSS color (rgb, hsl, oklch...) -> [r, g, b, a], by painting one pixel
  const ctx = document.createElement('canvas').getContext('2d', { willReadFrequently: true });
  const rgba = c => { ctx.clearRect(0, 0, 1, 1); ctx.fillStyle = '#000'; ctx.fillStyle = c || 'transparent'; ctx.fillRect(0, 0, 1, 1);
    const d = ctx.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255]; };
  const alpha = c => { const v = rgba(c); return v ? v[3] : 1; };
  const lum = v => { const f = x => (x /= 255) <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4;
    return 0.2126 * f(v[0]) + 0.7152 * f(v[1]) + 0.0722 * f(v[2]); };
  const why = el => {
    if (!el.checkVisibility({ visibilityProperty: true, opacityProperty: true })) return 'checkVisibility';
    let op = 1;
    for (let a = el; a && a.nodeType === 1; a = a.parentElement) {
      const s = getComputedStyle(a); op *= parseFloat(s.opacity);
      if (s.clipPath !== 'none' || (s.clip && s.clip !== 'auto')) return 'clipped by <' + a.tagName.toLowerCase() + '>';
      const ar = a.getBoundingClientRect();
      if (a !== el && s.overflow !== 'visible' && (ar.width <= 1 || ar.height <= 1)) return 'inside a zero-size box';
    }
    if (op < 0.5) return 'see-through';
    const s = getComputedStyle(el);
    if (parseFloat(s.fontSize) < 6) return 'font ' + s.fontSize;
    if (alpha(s.color) < 0.5 || alpha(s.webkitTextFillColor) < 0.5) return 'transparent color';
    let bg = null;
    for (let a = el; a && a.nodeType === 1 && !bg; a = a.parentElement) { const b = rgba(getComputedStyle(a).backgroundColor); if (b && b[3] > 0.5) bg = b; }
    const fg = rgba(s.color), l1 = lum(fg), l2 = lum(bg || [255, 255, 255]);
    if ((Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05) < 1.5) return 'same color as the background';
    const r = document.createRange(); r.selectNodeContents(el); const b = r.getBoundingClientRect();
    if (b.width <= 1 || b.height <= 1) return 'no size';
    if (b.right + scrollX <= 0 || b.bottom + scrollY <= 0 || b.left + scrollX >= document.documentElement.clientWidth) return 'off the page';
    return '';
  };
  const out = {};
  for (const m of markers) {
    out[m] = 'not in the page';
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) {
      if (!n.nodeValue.includes(m) || n.parentElement.closest('#parallax-panel')) continue;
      const el = n.parentElement, problem = why(el);
      if (!problem) { out[m] = el.closest('.parallax-label, .parallax-label-box') ? 'label' : 'text'; break; }
      out[m] = 'still hidden: ' + problem;
    }
  }
  return out;
}"""

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("[SKIP] playwright not installed"); sys.exit(0)

sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; sock.close()
httpd = ThreadingHTTPServer(("127.0.0.1", port), Stub)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
srv = f"http://127.0.0.1:{port}"
ext = str(ROOT / "extension")
with sync_playwright() as p, tempfile.TemporaryDirectory() as prof:
    try:
        ctx = p.chromium.launch_persistent_context(prof, headless=True, channel="chromium", viewport={"width": 1280, "height": 800},
                                                   args=[f"--disable-extensions-except={ext}", f"--load-extension={ext}"])
    except Exception as e:
        print(f"[SKIP] can't load the extension in Chromium: {e}"); sys.exit(0)
    sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker", timeout=15000)
    eid = sw.url.split("/")[2]
    ep = ctx.new_page(); ep.goto(f"chrome-extension://{eid}/popup.html")
    ep.evaluate(f"chrome.storage.local.set({{server: '{srv}'}})")
    for name, markers in PAGES.items():
        pg = ctx.new_page(); pg.goto(f"{srv}/{name}")
        pg.wait_for_selector("#parallax-panel .px-pill", timeout=15000)
        pg.wait_for_timeout(2500)   # let the server's answer replace the quick offline verdict
        before = pg.evaluate(SNAPSHOT)
        hidden_before = pg.evaluate(READABLE, markers)
        check(f"{name}: attacks start hidden", not any(v == "text" for v in hidden_before.values()),
              str({m: v for m, v in hidden_before.items() if v == "text"}))
        pg.click("#parallax-panel .px-pill")
        pg.click("#parallax-panel .px-btn:has-text('Show on page')"); pg.wait_for_timeout(500)
        shown = pg.evaluate(READABLE, markers)
        bad = {m: v for m, v in shown.items() if v not in ("text", "label")}
        check(f"{name}: Show on page makes all {len(markers)} attacks readable (text or label)", not bad, str(bad))
        if name == "finder_gaps.html":
            labelled = sorted(m for m, v in shown.items() if v == "label")
            want = sorted(f"exfil-{a}.xyz" for a in ["m1", "j1", "a1", "t1", "r1", "d1", "f1", "s5"]) + ["paypal-account-review-l1.xyz"]
            check(f"{name}: markup findings (alt, title, aria, data-*, hidden field, meta, JSON-LD, template, link) get labels",
                  labelled == sorted(want), str(labelled))
        pg.click("#parallax-panel .px-btn:has-text('Hide again')"); pg.wait_for_timeout(300)
        after = pg.evaluate(SNAPSHOT)
        i = next((i for i, (x, y) in enumerate(zip(before + " ", after + " ")) if x != y), 0)
        check(f"{name}: clicking again restores the page exactly", after == before,
              "" if after == before else f"(before: {before[i - 80:i + 80]!r}\n after: {after[i - 80:i + 80]!r})")
        pg.close()
    ctx.close()
httpd.shutdown()
print("\nALL PASS" if all(ok) else "\nSOME CHECKS FAILED")
sys.exit(0 if all(ok) else 1)
