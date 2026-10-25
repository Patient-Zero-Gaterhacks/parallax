"""The extension must never get stuck on "Scanning..." with a slow server or a page that changes by itself.

Loads the REAL extension in Chromium. A proxy in front of the real server delays /classify by 6 s and
answers one request at a time (Gemma on a laptop). The front page (frontend/dist) updates its attack feed
every 3 s. In one tab: attack lab recipe -> honest -> recipe -> Back -> Forward -> reload -> front page ->
#extension -> back to the front page -> recipe. Every step must have a verdict for the page it's on within
3 s (the quick offline check) and the server's verdict within 15 s; the front page left open for 30 s may
cause at most 2 /classify calls. Needs Playwright + Chromium that can load extensions; skips otherwise.
"""
import functools
import http.server
import os
import socket
import subprocess
import sys
import tempfile
import threading
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


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


# ---- the real server ----
port = free_port()
env = {k: v for k, v in os.environ.items() if k not in ("PARALLAX_ML_TRANSFORMER", "GEMINI_API_KEY", "GOOGLE_API_KEY")}
server = subprocess.Popen([sys.executable, "-m", "uvicorn", "parallax.server:app", "--port", str(port), "--log-level", "warning"],
                          cwd=ROOT, env=env)
SERVER = f"http://127.0.0.1:{port}"
for _ in range(100):
    try:
        urllib.request.urlopen(SERVER + "/health", timeout=1); break
    except OSError:
        time.sleep(0.2)
else:
    server.kill(); print("[FAIL] server didn't start"); sys.exit(1)

# ---- slow proxy: /classify takes 6 s, one at a time ----
classify_calls, one_at_a_time = [], threading.Lock()


class SlowProxy(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _forward(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.command == "POST" and self.path == "/classify":
            classify_calls.append(time.time())
            one_at_a_time.acquire()
            time.sleep(6)
        try:
            req = urllib.request.Request(SERVER + self.path, data=body or None, method=self.command,
                                         headers={"Content-Type": self.headers.get("Content-Type", "application/json")})
            with urllib.request.urlopen(req, timeout=60) as r:
                status, data, ctype = r.status, r.read(), r.headers.get("Content-Type", "application/json")
        except urllib.error.HTTPError as e:
            status, data, ctype = e.code, e.read(), "application/json"
        finally:
            if self.command == "POST" and self.path == "/classify":
                one_at_a_time.release()
        try:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass   # the extension gave up waiting (its 10 s timeout)

    do_GET = do_POST = _forward

    def do_OPTIONS(self):
        self.send_response(204)
        for h, v in (("Access-Control-Allow-Origin", "*"), ("Access-Control-Allow-Methods", "GET, POST"),
                     ("Access-Control-Allow-Headers", "Content-Type")):
            self.send_header(h, v)
        self.end_headers()


proxy = http.server.ThreadingHTTPServer(("127.0.0.1", 0), SlowProxy)
threading.Thread(target=proxy.serve_forever, daemon=True).start()
PROXY = f"http://127.0.0.1:{proxy.server_port}"

# ---- the front page (updates its feed every 3 s) ----
dist = ROOT / "frontend/dist"
if not (dist / "index.html").exists():
    subprocess.run(["npm", "run", "build"], cwd=ROOT / "frontend", check=False, capture_output=True)
if not (dist / "index.html").exists():
    server.kill(); print("[SKIP] frontend/dist missing and `npm run build` failed"); sys.exit(0)
front = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(dist)))
threading.Thread(target=front.serve_forever, daemon=True).start()
FRONT = f"http://127.0.0.1:{front.server_port}/"

try:
    with sync_playwright() as p, tempfile.TemporaryDirectory() as tmp:
        try:
            ctx = p.chromium.launch_persistent_context(tmp, headless=True, channel="chromium",
                                                       args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"])
            sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker", timeout=10000)
        except Exception as e:
            print(f"[SKIP] Chromium can't load the extension here: {e}"); sys.exit(0)
        ext_id = sw.url.split("/")[2]
        tab = ctx.pages[0] if ctx.pages else ctx.new_page()
        helper = ctx.new_page()
        helper.goto(f"chrome-extension://{ext_id}/scan.html")
        helper.evaluate("async u => chrome.storage.local.set({ server: u })", PROXY)
        # the extension has no "tabs" permission: tab URLs are hidden, so pick the tab that isn't this page
        tab_id = helper.evaluate("""async () => { const me = await chrome.tabs.getCurrent();
            return (await chrome.tabs.query({})).filter(t => t.id !== me.id).map(t => t.id)[0]; }""")

        def state():
            return helper.evaluate("""async id => { try { return await chrome.tabs.sendMessage(id, { type: "getState" }); }
                                     catch (e) { return null; } }""", tab_id)

        def step(name, action, want=None, count=None):
            action()
            url, t0 = tab.url, time.time()
            first = final = None
            while time.time() - t0 < 15:
                s = state()
                if s and s.get("page") == url and s.get("verdict"):
                    first = first or (time.time() - t0, s)
                    if s.get("quick") is False:
                        final = (time.time() - t0, s); break
                tab.wait_for_timeout(250)
            check(f"{name}: verdict within 3 s", first and first[0] <= 3,
                  f"({first[0]:.1f}s, {first[1]['verdict']}, quick={first[1].get('quick')})" if first else "(none)")
            got = final and final[1]
            good = bool(got) and (want is None or got["verdict"] == want) and (count is None or got.get("count") == count)
            check(f"{name}: server verdict within 15 s{f' = {want}' if want else ''}{f' ({count})' if count else ''}", good,
                  f"({final[0]:.1f}s, {got['verdict']}, count={got.get('count')})" if final else "(only the quick check)")

        lab = lambda path: (lambda: tab.goto(SERVER + path))  # noqa: E731
        step("recipe", lab("/lab/recipe"), "threat", 2)
        step("honest", lab("/lab/honest"), "clean")
        step("recipe again", lab("/lab/recipe"), "threat", 2)
        step("Back (honest)", tab.go_back, "clean")
        step("Forward (recipe)", tab.go_forward, "threat", 2)
        step("reload (recipe)", tab.reload, "threat", 2)
        step("front page", lambda: tab.goto(FRONT), "threat")
        step("front page #extension", lambda: tab.evaluate("location.hash = 'extension'"))
        step("front page again", lambda: tab.evaluate("location.hash = ''"), "threat")
        step("recipe after the front page", lab("/lab/recipe"), "threat", 2)

        # front page left open 30 s: its feed ticks every 3 s but the hidden text doesn't change
        tab.goto(FRONT)
        n0 = len(classify_calls)
        tab.wait_for_timeout(30000)
        calls = len(classify_calls) - n0
        check("front page open 30 s: at most 2 /classify calls", calls <= 2, f"({calls} calls)")
        s = state()
        check("front page still has a verdict after 30 s", s and s.get("verdict") == "threat",
              f"({s and s.get('verdict')}, quick={s and s.get('quick')})")
        ctx.close()
finally:
    server.kill(); proxy.shutdown(); front.shutdown()

print("\nALL PASS" if all(ok) else "\nSOME CHECKS FAILED")
sys.exit(0 if all(ok) else 1)
