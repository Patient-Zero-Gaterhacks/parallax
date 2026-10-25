"""Fake mailbox, wallet and memory used by the demo and tests."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..gap.html_gap import analyze_html
from .engine import PRIVATE, TRUSTED, UNTRUSTED, V


@dataclass
class World:
    inbox: dict
    private: dict = field(default_factory=lambda: {"bank_statements": "Statement Sep: balance $8,214.55 ..."})
    sent: list = field(default_factory=list)
    paid: list = field(default_factory=list)
    memory: list = field(default_factory=list)
    shown: list = field(default_factory=list)

    def tools(self):
        def search_inbox(query: V):
            ids = [i for i, m in self.inbox.items() if query.data.lower() in (m["from"] + m["subject"]).lower()]
            return V(ids, frozenset({TRUSTED}), ["your inbox index"])

        def read_email(id: V):
            mid = id.data[0] if isinstance(id.data, list) else id.data
            m = self.inbox[mid]
            gap = analyze_html(m["html"])
            hidden_text = " ".join(s.text for s in gap["hidden"])
            # Labeled untrusted as a whole; the UNSEEN label is added per
            # field by the reader's dual extraction.
            return V({"full": gap["visible_text"] + " " + hidden_text, "visible": gap["visible_text"],
                      "hidden": gap["hidden"], "from": m["from"], "id": mid},
                     frozenset({UNTRUSTED}), [f"email from {m['from']}"])

        def get_private(kind: V):
            return V(self.private[kind.data], frozenset({PRIVATE, TRUSTED}), [f"your {kind.data}"])

        def show_user(text: V):
            self.shown.append((text.data, sorted(text.labels)))
            return V(None)

        def reply_email(id: V, body: V):
            mid = id.data[0] if isinstance(id.data, list) else id.data
            self.sent.append((self.inbox[mid]["from"], body.data))
            return V(True)

        def send_email(to: V, subject: V, body: V):
            self.sent.append((to.data, body.data))
            return V(True)

        def forward_email(id: V, to: V):
            self.sent.append((to.data, f"FWD {id.data}"))
            return V(True)

        def pay(payee: V, amount: V):
            self.paid.append((payee.data, amount.data))
            return V(True)

        def save_memory(fact: V):
            self.memory.append((fact.data, "unverified" if UNTRUSTED in fact.labels else "verified"))
            return V(True)

        def open_link(url: V):
            return V(True)

        return {k: v for k, v in locals().items() if k != "self" and callable(v)}
