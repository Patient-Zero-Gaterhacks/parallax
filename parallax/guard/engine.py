"""Layer 2: the action guard. Based on Google DeepMind's CaMeL design (2025).

  * The planner sees only the user's request and the tool list. It writes
    the plan before any email, document or page is read, so text inside
    that content can't change what the assistant decides to do.
  * The reader reads untrusted content but has no tools. It can only fill
    in the fields (schema) the plan asked for.
  * Every value carries labels saying where it came from, and the labels
    follow the value through the plan.
  * The policy checks the labels at every action that sends, pays, shares,
    remembers or opens something, and either blocks it or asks the user.

Even if the reader is completely fooled, the worst it can do is put a wrong
value in a field, and that value reaches the action labeled "untrusted" or
"unseen", where the policy stops it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

# Labels
USER = "user"            # typed by the user in this request
TRUSTED = "trusted"      # the user's own data or a known contact
UNTRUSTED = "untrusted"  # anything read from outside: email body, page, doc
UNSEEN = "unseen"        # depends on content the user can't see (layer 1)
PRIVATE = "private"      # sensitive data (statements, IDs, medical)
SENDER = "sender"        # the From address of an email (fine to reply to)


@dataclass
class V:
    data: Any
    labels: frozenset = field(default_factory=frozenset)
    why: list = field(default_factory=list)   # human-readable provenance

    def __repr__(self):
        return f"V({self.data!r}, {sorted(self.labels)})"


def join(*vals: V) -> tuple[frozenset, list]:
    labels, why = frozenset(), []
    for v in vals:
        labels |= v.labels
        why += v.why
    return labels, why


# Policy
SINKS = {"send_email", "forward_email", "reply_email", "pay", "save_memory", "open_link"}


@dataclass
class Decision:
    action: str            # "allow" | "confirm" | "block"
    reasons: list[str]


def policy(tool: str, args: dict[str, V], request: str, contacts: set[str]) -> Decision:
    reasons, worst = [], "allow"

    def raise_to(level, msg):
        nonlocal worst
        order = ["allow", "confirm", "block"]
        if order.index(level) > order.index(worst):
            worst = level
        reasons.append(msg)

    def named_in_request(s: str) -> bool:
        return bool(s) and s.lower() in request.lower()

    if tool in ("send_email", "forward_email"):
        to = args["to"]
        if UNSEEN in to.labels:
            raise_to("block", f"The address {to.data} comes from text hidden from you.")
        elif USER in to.labels or named_in_request(str(to.data)):
            pass
        elif UNTRUSTED in to.labels and to.data not in contacts:
            raise_to("confirm", f"The address {to.data} came from a message, not from you, "
                                "and isn't in your contacts.")
        payload = [v for k, v in args.items() if k != "to"]
        if any(PRIVATE in v.labels for v in payload) and not (USER in to.labels or named_in_request(str(to.data))):
            raise_to("confirm", f"This would send private information to {to.data}.")
    elif tool == "reply_email":
        # Replying to the sender of the email the user asked about is the
        # normal case; the body is still checked for private data.
        if any(PRIVATE in v.labels for v in args.values()):
            raise_to("confirm", "The reply would include private information.")
        if UNSEEN in args.get("body", V("")).labels:
            raise_to("block", "The reply text depends on content hidden from you.")
    elif tool == "pay":
        payee, amount = args["payee"], args["amount"]
        for name, v in (("payee", payee), ("amount", amount)):
            if UNSEEN in v.labels:
                raise_to("block", f"The {name} ({v.data}) comes from text hidden from you.")
            elif UNTRUSTED in v.labels:
                raise_to("confirm", f"The {name} ({v.data}) was read from a document, not typed by you.")
    elif tool == "save_memory":
        fact = args["fact"]
        if UNSEEN in fact.labels:
            raise_to("block", "This 'fact' comes from text hidden from you.")
        elif UNTRUSTED in fact.labels:
            raise_to("confirm", "This would be remembered from an outside source; "
                                "it will be stored as unverified unless you confirm.")
    elif tool == "open_link":
        url = args["url"]
        if UNSEEN in url.labels:
            raise_to("block", "This link only appears in content hidden from you.")
        elif UNTRUSTED in url.labels and not url.data.startswith("https://"):
            raise_to("confirm", "This link is not secure (no https).")
    return Decision(worst, reasons)


# Runtime
REF = re.compile(r"^\$(\w+)(?:\.(\w+))?$")


class Blocked(Exception):
    pass


@dataclass
class Runtime:
    tools: dict[str, Callable[..., V]]
    reader: Callable[[V, dict, str], dict[str, V]]   # (content, schema, question) -> fields
    request: str
    contacts: set
    confirm: Callable[[str, Decision], bool] = lambda tool, d: False
    log: list = field(default_factory=list)
    enforce: bool = True   # False = the unprotected assistant, for side-by-side demos

    def _resolve(self, arg, env) -> V:
        if isinstance(arg, str):
            m = REF.match(arg)
            if m:
                v = env[m.group(1)]
                if m.group(2):
                    return v[m.group(2)] if isinstance(v, dict) else V(v.data[m.group(2)], v.labels, v.why)
                return v
        # A literal written by the planner. The planner only saw the user's
        # request, so a literal counts as the user's own words.
        return V(arg, frozenset({USER}), ["typed in your request"])

    def run(self, plan: list[dict]) -> dict:
        env: dict[str, Any] = {}
        for step in plan:
            sid, tool = step["id"], step["tool"]
            args = {k: self._resolve(a, env) for k, a in step.get("args", {}).items()}
            if tool == "extract":
                env[sid] = self.reader(args["source"], step["schema"], step.get("question", ""))
                self.log.append((sid, "extract", "ok", list(step["schema"])))
                continue
            if tool in SINKS and not self.enforce:
                self.log.append((sid, tool, "done (no checks)", []))
            elif tool in SINKS:
                d = policy(tool, args, self.request, self.contacts)
                if d.action == "block" or (d.action == "confirm" and not self.confirm(tool, d)):
                    self.log.append((sid, tool, d.action, d.reasons))
                    raise Blocked(f"{tool}: {d.action}: " + " ".join(d.reasons))
                self.log.append((sid, tool, "allowed" if d.action == "allow" else "confirmed", d.reasons))
            env[sid] = self.tools[tool](**args)
        return env
