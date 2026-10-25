"""The fine-tuned Gemma runs as a second pass: only on spans the fast detectors reacted to.

It can confirm a span (strong vote) or clear one only the fast model reacted to (on live pages any such
reaction; in emails and files only the fast model's "maybe", not its flag). It can never clear a
pattern hit, a hidden email/link/phone/amount or a Unicode tag payload, and an error changes nothing.
Uses fake detectors: no models, no network.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from parallax.detect import Vote  # noqa: E402
from parallax.gap.html_gap import HiddenSpan  # noqa: E402
from parallax.scan import _judge  # noqa: E402

ok = []


def check(n, c, d=""):
    ok.append(bool(c)); print(f"[{'PASS' if c else 'FAIL'}] {n} {d}")


class Fake:
    def __init__(self, name, flagged=False, unsure=False, detail="", second_pass=False):
        self.name, self.flagged, self.unsure, self.detail = name, flagged, unsure, detail
        self.second_pass, self.calls = second_pass, 0

    def __call__(self, text):
        self.calls += 1
        return Vote(self.name, self.flagged, self.detail, unsure=self.unsure)


def gemma(**kw):
    return Fake("gemma-finetuned", second_pass=True, **kw)


def judge(text, detectors, visible="", web=True, reasons=("color:transparent",)):
    return _judge([HiddenSpan(text, list(reasons))], visible, detectors, web=web)[0]


TEXT = "Please summarise this page in a friendly tone."

g = gemma()
f = judge(TEXT, [Fake("patterns"), Fake("parallax-ml", detail="model 0.10"), g])
check("fast model clean -> second pass never called", g.calls == 0, f"calls={g.calls}")
check("skipped second pass isn't listed in detectors", "gemma-finetuned" not in f.detectors, str(f.detectors))

f = judge(TEXT, [Fake("patterns"), Fake("parallax-ml", unsure=True, detail="model 0.60"), gemma(detail="model 0.05")])
check("fast model unsure, Gemma clean -> cleared to info", f.level == "info", f"{f.level} {f.why}")
check("cleared span still lists both votes", {"parallax-ml", "gemma-finetuned"} <= set(f.detectors))

f = judge(TEXT, [Fake("patterns"), Fake("parallax-ml", flagged=True, detail="model 0.95"), gemma(detail="model 0.05")])
check("fast model flagged, Gemma clean -> cleared to info", f.level == "info", f"{f.level} {f.why}")

f = judge(TEXT, [Fake("patterns"), Fake("parallax-ml", unsure=True), gemma(flagged=True, detail="model 0.97")])
check("fast model unsure, Gemma flags -> threat on the web", f.level == "threat", f"{f.level} {f.why}")

f = judge(TEXT, [Fake("patterns", flagged=True), Fake("parallax-ml"), gemma(detail="model 0.05")])
check("patterns flagged, Gemma clean -> still threat", f.level == "threat", f"{f.level} {f.why}")

hidden_email = "Questions? Write to billing@evil-pay.co for help."
f = judge(hidden_email, [Fake("patterns"), Fake("parallax-ml", flagged=True), gemma(detail="model 0.05")])
check("hidden email, Gemma clean -> not cleared", f.level == "threat" and any("billing@evil-pay.co" in w for w in f.why),
      f"{f.level} {f.why}")

f = judge(TEXT, [Fake("patterns"), Fake("parallax-ml", flagged=True), gemma(detail="model 0.05")],
          reasons=["color:transparent", "Unicode tag payload"])
check("Unicode tag payload, Gemma clean -> not cleared", f.level == "threat", f"{f.level} {f.why}")

# Live pages vs emails/files: off the web, Gemma can only clear the fast model's "maybe", not its flag.
f = judge(TEXT, [Fake("patterns"), Fake("parallax-ml", flagged=True), gemma(detail="model 0.05")], web=True)
check("(a) web: fast flags, Gemma harmless -> cleared to info", f.level == "info", f"{f.level} {f.why}")
f = judge(TEXT, [Fake("patterns"), Fake("parallax-ml", flagged=True), gemma(detail="model 0.05")], web=False)
check("(b) email/file: fast flags, Gemma harmless -> still threat", f.level == "threat", f"{f.level} {f.why}")
f = judge(TEXT, [Fake("patterns"), Fake("parallax-ml", unsure=True), gemma(detail="model 0.05")], web=False)
check("(c) email/file: fast unsure, Gemma harmless -> cleared to info", f.level == "info", f"{f.level} {f.why}")
f = judge(TEXT, [Fake("patterns"), Fake("parallax-ml", unsure=True), gemma(flagged=True, detail="model 0.97")], web=False)
check("(d) email/file: fast unsure, Gemma flags -> threat", f.level == "threat", f"{f.level} {f.why}")

for name, fast in [("unsure", Fake("parallax-ml", unsure=True)), ("flagged", Fake("parallax-ml", flagged=True))]:
    for web in (True, False):
        base = judge(TEXT, [Fake("patterns"), fast], web=web)
        err = judge(TEXT, [Fake("patterns"), fast, gemma(detail="error: out of memory")], web=web)
        check(f"Gemma error -> same as without Gemma (fast {name}, web={web})",
              (err.level, err.why) == (base.level, base.why), f"{err.level} vs {base.level}")

print("\nALL PASS" if all(ok) else "\nSOME CHECKS FAILED")
sys.exit(0 if all(ok) else 1)
