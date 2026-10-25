"""End to end over real MCP stdio: client -> Parallax gateway -> poisoned mail server.

This is what Claude Desktop or Cursor would do, minus the model.
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp import ClientSession  # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402

ok = []


def check(n, c, d=""):
    ok.append(bool(c))
    print(f"[{'PASS' if c else 'FAIL'}] {n} {d}")


HOME = tempfile.mkdtemp()
OUTBOX = Path(tempfile.mkdtemp()) / "outbox.json"


def config(env_extra=None):
    cfg = {"servers": {"mail": {"command": sys.executable,
                                "args": ["-m", "parallax.mcp_gateway.demo_mail_server"],
                                "env": {"DEMO_OUTBOX": str(OUTBOX), **(env_extra or {})}}},
           "allow": []}
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(cfg, f); f.close()
    return f.name


def env():
    return {**os.environ, "PARALLAX_HOME": HOME, "PYTHONPATH": str(ROOT)}


def text(res):
    return " ".join(getattr(c, "text", "") for c in res.content)


async def session(cfg_path, fn):
    params = StdioServerParameters(command=sys.executable,
                                   args=["-m", "parallax.mcp_gateway", "--config", cfg_path], env=env(), cwd=str(ROOT))
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            return await fn(s)


def cli(*args):
    return subprocess.run([sys.executable, "-m", "parallax.mcp_gateway", *args], env=env(), cwd=str(ROOT),
                          capture_output=True, text=True).stdout


async def main():
    # 1. Clean run: tools listed, hidden text removed, hidden-only address blocked.
    async def run1(s):
        names = [t.name for t in (await s.list_tools()).tools]
        check("tools proxied with server prefix", {"mail__read_email", "mail__send_email", "mail__get_weather"} <= set(names),
              f"({names})")
        r = await s.call_tool("mail__read_email", {"id": "1"})
        t = text(r)
        check("hidden instruction removed before the model reads the email",
              "secure-billing-check" not in t and "Tuesday at 3 PM" in t and "Parallax removed" in t)
        r = await s.call_tool("mail__send_email", {"to": "verify@secure-billing-check.com", "subject": "Statements", "body": "attached"})
        check("send to an address seen only in hidden text is blocked", r.is_error and "Blocked by Parallax" in text(r), f"({text(r)[:110]}...)")
        r = await s.call_tool("mail__read_email", {"id": "2"})
        r = await s.call_tool("mail__send_email", {"to": "payments@gfc-billing-update.com", "subject": "Payment", "body": "$1,412.00"})
        check("payment redirect from white text is blocked", r.is_error and "Blocked" in text(r))
        r = await s.call_tool("mail__send_email", {"to": "mom@family.example", "subject": "Hi", "body": "See you Sunday"})
        check("send to an address the user typed (never seen in content) goes through", not r.is_error, f"({text(r)})")
        r = await s.call_tool("mail__read_email", {"id": "3"})
        r = await s.call_tool("mail__send_email", {"to": "ana@cpa-gnv.com", "subject": "Statement", "body": "September"})
        check("send to an address read from an email pauses for approval", r.is_error and "Paused by Parallax" in text(r))
        aid = text(r).split("/approve/")[1].split(" ")[0]
        r = await s.call_tool("mail__send_email", {"to": "x@y.com", "subject": "x", "body": "http://localhost:8787/approve/" + aid})
        check("assistant can't touch the approval page through a tool", r.is_error and "only you can approve" in text(r))
        out = cli("approve", aid)
        check("user approves via CLI", "Approved" in out, f"({out.strip()[:60]})")
        r = await s.call_tool("mail__send_email", {"to": "ana@cpa-gnv.com", "subject": "Statement", "body": "September"})
        check("approved action goes through once", not r.is_error, f"({text(r)})")
        r = await s.call_tool("mail__send_email", {"to": "ana@cpa-gnv.com", "subject": "Statement", "body": "September"})
        check("approval is single-use", r.is_error and "Paused" in text(r))
        rep = json.loads(text(await s.call_tool("parallax__report", {})))
        check("report lists what happened", any(e["kind"] == "action_block" for e in rep))
    await session(config(), run1)
    sent = json.loads(OUTBOX.read_text())
    check("attacker never received mail", not any("secure-billing" in m["to"] or "gfc-billing-update" in m["to"] for m in sent),
          f"(outbox: {[m['to'] for m in sent]})")

    # 2. Poisoned tool description is never shown to the model.
    async def run2(s):
        return [t.name for t in (await s.list_tools()).tools]
    names = await session(config({"DEMO_POISON": "1"}), run2)
    check("poisoned tool description quarantined", "mail__get_weather" not in names and "mail__read_email" in names)

    # 3. Rug pull: tool changes after it was pinned.
    names = await session(config({"DEMO_RUG_PULL": "1"}), run2)
    check("changed tool hidden until approved (rug pull)", "mail__get_weather" not in names)
    out = cli("approve-tool", "mail/get_weather")
    names = await session(config({"DEMO_RUG_PULL": "1"}), run2)
    check("after user approves the new version, tool is back", "mail__get_weather" in names, f"({out.strip()[:50]})")

    print("\nALL PASS" if all(ok) else "\nSOME CHECKS FAILED")
    return all(ok)


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main()) else 1)
