"""The approval page: only a person clicking the button approves a paused action."""
import os, sys, tempfile
from pathlib import Path
os.environ["PARALLAX_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from parallax.server import app
from parallax.mcp_gateway.core import Gateway
ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(f"[{'PASS' if c else 'FAIL'}] {n} {d}")
gw = Gateway()
gw.clean_result_text("mail__read_email", "<p>From ana@cpa-gnv.com: please send the statement</p>")
d = gw.check_call("mail__send_email", {"to": "ana@cpa-gnv.com", "subject": "s", "body": "b"})
c = TestClient(app)
check("action paused", d.action == "approve")
page = c.get(f"/approve/{d.approval_id}")
check("approval page shows the action", page.status_code == 200 and "ana@cpa-gnv.com" in page.text)
check("merely opening the page does not approve", gw.check_call("mail__send_email", {"to": "ana@cpa-gnv.com", "subject": "s", "body": "b"}).action == "approve")
c.post(f"/approve/{d.approval_id}")
check("clicking Approve lets it through once", gw.check_call("mail__send_email", {"to": "ana@cpa-gnv.com", "subject": "s", "body": "b"}).action == "allow")
check("events endpoint works", c.get("/gateway/events").status_code == 200)
print("\nALL PASS" if all(ok) else "\nSOME CHECKS FAILED"); sys.exit(0 if all(ok) else 1)
