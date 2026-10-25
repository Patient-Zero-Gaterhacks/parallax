"""The website's "Am I protected?" playground (/#try) with the REAL extension, and without it.

With the extension: the banner turns green, every hidden-attack trap reaches "Caught" (except the look-alike
link, a known miss: on live pages a look-alike link alone is info) and the control card stays "No false alarm".
Without it (plain Chromium): the banner is red and the no-install panel scans the attack lab's resume.pdf as a
threat. Serves frontend/dist from the real API server (uvicorn), building it if
needed. Needs Playwright + Chromium; skips otherwise.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "extension"
ok = []


def check(n, c, d=""):
    ok.append(bool(c)); print(f"[{'PASS' if c else 'FAIL'}] {n} {d}")


try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("[SKIP] playwright not installed"); sys.exit(0)

dist = ROOT / "frontend/dist"
if not (dist / "index.html").exists():
    subprocess.run(["npm", "run", "build"], cwd=ROOT / "frontend", capture_output=True)
if not (dist / "index.html").exists():
    print("[SKIP] frontend/dist missing and `npm run build` failed"); sys.exit(0)

with socket.socket() as s:
    s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
env = {k: v for k, v in os.environ.items() if k not in ("PARALLAX_ML_TRANSFORMER", "GEMINI_API_KEY", "GOOGLE_API_KEY", "PARALLAX_PUBLIC")}
env["PARALLAX_SITE_DIR"] = str(dist)
server = subprocess.Popen([sys.executable, "-m", "uvicorn", "parallax.server:app", "--port", str(port), "--log-level", "warning"],
                          cwd=ROOT, env=env)
BASE = f"http://127.0.0.1:{port}"
for _ in range(100):
    try:
        urllib.request.urlopen(BASE + "/health", timeout=1); break
    except OSError:
        time.sleep(0.2)


def chips(page):
    return {el.get_attribute("data-trap"): (el.query_selector("[data-chip]").text_content() or "").strip()
            for el in page.query_selector_all("[data-trap]")}


try:
    with sync_playwright() as p, tempfile.TemporaryDirectory() as tmp:
        # ---- with the extension ----
        try:
            ctx = p.chromium.launch_persistent_context(tmp, headless=True, channel="chromium",
                                                       args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"])
            sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker", timeout=10000)
        except Exception as e:
            ctx = None; print(f"[SKIP] extension part: Chromium can't load extensions here ({e})")
        if ctx:
            helper = ctx.new_page()
            helper.goto(f"chrome-extension://{sw.url.split('/')[2]}/scan.html")
            helper.evaluate("async u => chrome.storage.local.set({ server: u })", BASE)
            pg = ctx.pages[0]
            pg.goto(BASE + "/#try")
            t0, c = time.time(), {}
            while time.time() - t0 < 45:
                c = chips(pg)
                if c and all(v.startswith(("Caught", "Missed")) for k, v in c.items() if k != "PX-CONTROL") \
                        and c.get("PX-CONTROL") in ("No false alarm", "False alarm"):
                    break
                pg.wait_for_timeout(500)
            banner = pg.query_selector("[data-testid=banner]")
            check("with the extension: banner is green (protected)", banner and banner.get_attribute("data-status") == "on",
                  (banner.text_content() or "")[:90] if banner else "")
            # KNOWN MISS, shown as "Missed" on the page: on live pages a look-alike link alone is info, not a
            # caution (real sites are full of redirect/tracking links), so the extension doesn't report it.
            KNOWN_MISS = {"PX-TRAP-09"}
            for code, chip in sorted(c.items()):
                if code in KNOWN_MISS:
                    check(f"trap {code} (look-alike link): known miss, shown as Missed", chip == "Missed", f"({chip})")
                    print(f"   [KNOWN MISS] {code}: a look-alike link alone is info on live pages, so it isn't reported")
                elif code != "PX-CONTROL":
                    check(f"trap {code} caught", chip.startswith("Caught"), f"({chip})")
            check("control card: no false alarm", c.get("PX-CONTROL") == "No false alarm", f"({c.get('PX-CONTROL')})")
            print("   scoreboard:", pg.text_content("[data-testid=scoreboard]"))
            check("other pages of the site get no playground messages (only data-parallax)",
                  pg.evaluate("""async () => { location.hash = ''; await new Promise(r => setTimeout(r, 300));
                    return !document.querySelector('meta[name=parallax-playground]') && document.documentElement.dataset.parallax === 'on'; }"""))
            ctx.close()

        # ---- without the extension ----
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(BASE + "/#try")
        pg.wait_for_timeout(4000)
        banner = pg.query_selector("[data-testid=banner]")
        check("without the extension: banner is red (not protected)", banner and banner.get_attribute("data-status") == "none",
              (banner.text_content() or "")[:80] if banner else "")
        c = chips(pg)
        check("without the extension: every card says Not protected", c and all(v == "Not protected" for v in c.values()), json.dumps(c)[:120])
        pdf = Path(tmp, "resume.pdf")
        pdf.write_bytes(urllib.request.urlopen(BASE + "/lab/resume.pdf").read())
        pg.set_input_files("[data-testid=file-input]", str(pdf))
        pg.wait_for_selector("[data-verdict]", timeout=20000)
        v = pg.get_attribute("[data-verdict]", "data-verdict")
        check("no-install panel: resume.pdf scans as a threat", v == "threat", f"({v}) {pg.text_content('[data-testid=scan-result]')[:100]}")
        b.close()
finally:
    server.kill()

print("\nALL PASS" if all(ok) else "\nSOME CHECKS FAILED")
sys.exit(0 if all(ok) else 1)
