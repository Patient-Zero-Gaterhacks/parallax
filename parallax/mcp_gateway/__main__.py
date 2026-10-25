"""Run the Parallax MCP gateway, or manage approvals.

  python -m parallax.mcp_gateway --config gateway.json     # MCP server over stdio
  python -m parallax.mcp_gateway status
  python -m parallax.mcp_gateway approve <id>              # approve a paused action
  python -m parallax.mcp_gateway approve-tool <server/tool>  # accept a changed tool

gateway.json:
  {
    "servers": {"mail": {"command": "python", "args": ["-m", "parallax.mcp_gateway.demo_mail_server"]}},
    "sinks": [], "readonly": [], "allow": ["cpa-gnv.com"]
  }

Claude Desktop (claude_desktop_config.json) / Cursor (mcp.json):
  {"mcpServers": {"parallax": {"command": "python",
     "args": ["-m", "parallax.mcp_gateway", "--config", "/full/path/gateway.json"]}}}
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack

from .core import Gateway, Store


def cli_status():
    st = Store()
    print(json.dumps({"pending_actions": [a for a in st.load("approvals", {}).values() if a["status"] == "pending"],
                      "changed_tools": st.load("pending_tools", {}),
                      "recent_events": st.load("events", [])[-10:]}, indent=1))


def cli_approve(aid: str):
    st = Store()
    ap = st.load("approvals", {})
    for a in ap.values():
        if a["id"] == aid and a["status"] == "pending":
            a["status"] = "approved"
            st.save("approvals", ap)
            print(f"Approved {a['tool']} {json.dumps(a['args'])}. Ask the assistant to try again.")
            return
    print("No pending action with that id.")


def cli_approve_tool(key: str):
    st = Store()
    pending = st.load("pending_tools", {})
    if key not in pending:
        print("No changed tool with that name. Changed tools:", list(pending))
        return
    approved = st.load("approved_tools", {})
    approved[key] = pending.pop(key)["hash"]
    st.save("approved_tools", approved)
    st.save("pending_tools", pending)
    print(f"Approved the new version of {key}. Restart or reconnect your MCP client.")


async def serve(config_path: str):
    from mcp import ClientSession, types
    from mcp.client.stdio import StdioServerParameters, stdio_client
    from mcp.server.lowlevel import Server
    from mcp.server.stdio import stdio_server

    with open(config_path) as f:
        cfg = json.load(f)
    gw = Gateway(sinks=set(cfg.get("sinks", [])), readonly=set(cfg.get("readonly", [])),
                 allow=set(cfg.get("allow", [])))
    async with AsyncExitStack() as stack:
        upstream: dict[str, ClientSession] = {}
        for name, spec in cfg["servers"].items():
            params = StdioServerParameters(command=spec["command"], args=spec.get("args", []),
                                           env={**os.environ, **spec.get("env", {})})
            read, write = await stack.enter_async_context(stdio_client(params))
            sess = await stack.enter_async_context(ClientSession(read, write))
            await sess.initialize()
            upstream[name] = sess

        routes: dict[str, tuple[str, str, dict]] = {}   # exposed name -> (server, tool, annotations)

        async def list_tools(ctx, params):
            routes.clear()
            exposed = []
            for sname, sess in upstream.items():
                res = await sess.list_tools()
                raw = [t.model_dump(by_alias=False) for t in res.tools]
                for t in gw.filter_tools(sname, raw):
                    ex = f"{sname}__{t['name']}"
                    ann = t.get("annotations") or {}
                    routes[ex] = (sname, t["name"], ann if isinstance(ann, dict) else {})
                    exposed.append(types.Tool(name=ex, description=t.get("description"),
                                              input_schema=t["input_schema"]))
            exposed.append(types.Tool(
                name="parallax__report", description="Show what Parallax blocked, paused or removed in this session.",
                input_schema={"type": "object", "properties": {}}))
            return types.ListToolsResult(tools=exposed)

        async def call_tool(ctx, params):
            name, args = params.name, params.arguments or {}
            if name == "parallax__report":
                return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(gw.events[-20:], indent=1))])
            if name not in routes:
                await list_tools(ctx, None)
            if name not in routes:
                return types.CallToolResult(is_error=True, content=[types.TextContent(
                    type="text", text=f"Parallax: tool {name} is not available (it may be quarantined).")])
            sname, tname, ann = routes[name]
            d = gw.check_call(name, args, ann)
            if d.action != "allow":
                gw.log("action_" + d.action, tool=name, reasons=d.reasons, approval=d.approval_id)
                return types.CallToolResult(is_error=True, content=[types.TextContent(type="text", text=gw.explain(d, name))])
            res = await upstream[sname].call_tool(tname, args)
            out = []
            for c in getattr(res, "content", []) or []:
                if getattr(c, "type", "") == "text":
                    cleaned, _ = gw.clean_result_text(name, c.text)
                    out.append(types.TextContent(type="text", text=cleaned))
                else:
                    out.append(c)
            return types.CallToolResult(content=out, is_error=getattr(res, "is_error", False))

        server = Server("parallax-gateway", version="0.1.0",
                        instructions="Parallax checks tools, tool results and actions for hidden instructions.",
                        on_list_tools=list_tools, on_call_tool=call_tool)
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())


def main():
    ap = argparse.ArgumentParser(prog="parallax.mcp_gateway")
    ap.add_argument("cmd", nargs="?", default="serve", choices=["serve", "status", "approve", "approve-tool"])
    ap.add_argument("target", nargs="?")
    ap.add_argument("--config", default=os.environ.get("PARALLAX_GATEWAY_CONFIG", "gateway.json"))
    a = ap.parse_args()
    if a.cmd == "status":
        cli_status()
    elif a.cmd == "approve":
        cli_approve(a.target)
    elif a.cmd == "approve-tool":
        cli_approve_tool(a.target)
    else:
        asyncio.run(serve(a.config))


if __name__ == "__main__":
    sys.exit(main())
