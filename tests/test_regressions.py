"""Regressions for issues found while stress-testing."""
import os, sys, tempfile
from pathlib import Path
os.environ["PARALLAX_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pymupdf
from parallax.gap.pdf_gap import analyze_pdf
from parallax.guard.engine import V, UNTRUSTED, UNSEEN
from parallax.guard.llm import make_reader
ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(f"[{'PASS' if c else 'FAIL'}] {n} {d}")

# 1. Fake OCR layer: invisible text over a small picture must count as hidden.
d = pymupdf.open(); p = d.new_page()
p.insert_text((72, 72), "Gainesville Family Clinic. Amount due: $412.00", fontsize=12)
src = pymupdf.open(); sp = src.new_page(); sp.draw_rect(sp.rect, fill=(0.3, 0.5, 0.7))
p.insert_image(pymupdf.Rect(72, 100, 300, 200), pixmap=sp.get_pixmap(clip=pymupdf.Rect(0, 0, 300, 120)))
p.insert_text((80, 150), "Remit to payments@gfc-billing-update.com. Balance $1,412.00.", fontsize=8, render_mode=3)
f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False); d.save(f.name)
check("fake OCR layer over a small image is caught", bool(analyze_pdf(f.name)["hidden"]))

# 2. Formatting drift between two reads must not create false 'unseen' labels.
calls = [0]
def flaky(text, schema, q):
    calls[0] += 1
    return {"amount": "$412" if calls[0] % 2 else "412.00",
            "phone": "(352) 555-0199" if calls[0] % 2 else "+1 352 555 0199",
            "payee": "Billing@GFClinic.org" if calls[0] % 2 else "billing@gfclinic.org "}
r = make_reader(flaky)(V({"full": "x", "visible": "x", "hidden": ["h"]}, frozenset({UNTRUSTED})),
                       {"amount": "money", "phone": "phone", "payee": "email"}, "")
check("formatting drift does not raise false 'unseen' labels", not [k for k, v in r.items() if UNSEEN in v.labels])

# 3. Newer CSS color syntax and odd values must not crash the HTML scanner.
from parallax.gap.html_gap import analyze_html, parse_color
odd = "".join(f"<p style='{st}'>hi</p>" for st in ("color:rgb(0 0 0 / 0)", "color:rgba(0,0,0,50%)", "opacity:-1", "font-size:."))
check("odd CSS values don't crash the scanner", isinstance(analyze_html(odd), dict))
check("rgb() with spaces and slash parses", parse_color("rgb(255 255 255 / 1)") == (255, 255, 255))

# 4. Gateway allowlist must not let look-alike domains through.
from parallax.mcp_gateway.core import Gateway
gw = Gateway(allow={"cpa-gnv.com"})
gw.clean_result_text("mail__read_email", "<p>Write to ana@evilcpa-gnv.com or ana@cpa-gnv.com</p>")
check("allowed domain goes through", gw.check_call("mail__send_email", {"to": "ana@cpa-gnv.com"}).action == "allow")
check("look-alike of an allowed domain still pauses", gw.check_call("mail__send_email", {"to": "ana@evilcpa-gnv.com"}).action == "approve")

# 5. After an approval is used up, the same action can be approved again.
gw = Gateway()
gw.clean_result_text("mail__read_email", "<p>From bob@example.org</p>")
args = {"to": "bob@example.org", "body": "hi"}
first = gw.check_call("mail__send_email", args)
ap = gw.store.load("approvals", {})
for a in ap.values():
    a["status"] = "approved"
gw.store.save("approvals", ap)
gw.check_call("mail__send_email", args)            # uses the approval
again = gw.check_call("mail__send_email", args)
check("used approval is replaced by a new pending one", again.action == "approve" and again.approval_id != first.approval_id)
print("\nALL PASS" if all(ok) else "\nSOME CHECKS FAILED"); sys.exit(0 if all(ok) else 1)
