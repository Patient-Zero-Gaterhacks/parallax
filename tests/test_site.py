"""The website is served at "/" from PARALLAX_SITE_DIR (default frontend/dist) when it's built; every API
route, the demo and the attack lab still answer as before, and with no built folder "/" is unchanged.
Each case runs in its own process because the server reads its environment once, at import.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ok = []


def check(n, c, d=""):
    ok.append(bool(c)); print(f"[{'PASS' if c else 'FAIL'}] {n} {d}")


PROBE = """
import json, sys; sys.path.insert(0, %r)
from fastapi.testclient import TestClient
from parallax.server import app
c = TestClient(app)
out = {}
for path in ("/", "/index.html", "/assets/app.js", "/health", "/demo", "/lab/recipe", "/gateway/events", "/nope.html"):
    r = c.get(path)
    out[path] = [r.status_code, r.headers.get("content-type", ""), r.text[:300]]
print(json.dumps(out))
""" % str(ROOT)


def probe(**env):
    e = {k: v for k, v in os.environ.items()
         if k not in ("PARALLAX_ML_TRANSFORMER", "GEMINI_API_KEY", "GOOGLE_API_KEY", "PARALLAX_PUBLIC", "PARALLAX_SITE_DIR")}
    e.update(env)
    r = subprocess.run([sys.executable, "-c", PROBE], env=e, capture_output=True, text=True)
    if r.returncode:
        print(r.stderr[-800:])
        return {}
    return json.loads(r.stdout.strip().splitlines()[-1])


with tempfile.TemporaryDirectory() as site:
    Path(site, "index.html").write_text("<!doctype html><title>Parallax site</title><div id='root'>SITE-INDEX</div>"
                                        "<a href='#extension'>Get the extension</a>")
    Path(site, "assets").mkdir()
    Path(site, "assets", "app.js").write_text("console.log('site')")

    r = probe(PARALLAX_SITE_DIR=site)
    check("'/' serves the site's index.html", r.get("/", [0])[0] == 200 and "SITE-INDEX" in r["/"][2], str(r.get("/", ""))[:80])
    check("site assets are served", r.get("/assets/app.js", [0])[0] == 200 and "javascript" in r["/assets/app.js"][1])
    check("/health is still the API", r.get("/health", [0])[0] == 200 and json.loads(r["/health"][2]).get("ok") is True)
    check("/demo is still the demo page", r.get("/demo", [0])[0] == 200 and "SITE-INDEX" not in r["/demo"][2])
    check("/lab/recipe is still the attack lab", r.get("/lab/recipe", [0])[0] == 200 and "banana bread" in r["/lab/recipe"][2])
    check("/gateway/events is still the API (local mode)", r.get("/gateway/events", [0])[0] == 200 and "events" in r["/gateway/events"][2])
    check("unknown file is a 404, not the API", r.get("/nope.html", [0])[0] == 404)

    r = probe(PARALLAX_SITE_DIR=site, PARALLAX_PUBLIC="1")
    check("public mode: '/' serves the site", r.get("/", [0])[0] == 200 and "SITE-INDEX" in r["/"][2])
    check("public mode: /gateway stays off (404), not swallowed by the site",
          r.get("/gateway/events", [0])[0] == 404 and "SITE-INDEX" not in r["/gateway/events"][2])
    check("public mode: /health says public", json.loads(r.get("/health", [0, "", "{}"])[2]).get("public") is True)

r = probe(PARALLAX_SITE_DIR=str(Path(tempfile.gettempdir(), "parallax-no-site-here")))
check("no built folder: '/' behaves as before (404)", r.get("/", [0])[0] == 404, str(r.get("/", ""))[:80])
check("no built folder: /health and /lab/recipe unchanged",
      r.get("/health", [0])[0] == 200 and r.get("/lab/recipe", [0])[0] == 200)

print("\nALL PASS" if all(ok) else "\nSOME CHECKS FAILED")
sys.exit(0 if all(ok) else 1)
