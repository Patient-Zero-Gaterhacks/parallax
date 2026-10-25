"""One scanner, one verdict format, for every kind of input.

    scan_html(html)      email bodies and saved pages
    scan_eml(bytes)      raw emails, including PDF/Word attachments
    scan_pdf(path)
    scan_docx(path)
    scan_url(url)        hidden text on the page + AI-targeted cloaking
    scan_file(path)      picks the right one from the file type

Verdicts:
    threat   hidden text that talks to an AI, adds facts you can't see
             (addresses, links, amounts, phone numbers), smuggles text in
             invisible Unicode, or a page that shows AI different content
    caution  hidden text whose purpose isn't clear
    clean    nothing hidden, or only harmless hidden text (preheaders,
             spacers, scanned-PDF text layers, screen-reader labels)
"""

from __future__ import annotations

import email
import email.policy
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .detect import default_detectors
from .gap.cloak import check_url
from .gap.docx_gap import analyze_docx
from .gap.html_gap import analyze_html
from .gap.pdf_gap import analyze_pdf

FACT_PATTERNS = {
    "email address": r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+",
    "link": r"https?://[^\s<>\"')]+|\bwww\.[^\s<>\"')]+|\b[a-z0-9][a-z0-9-]{2,}\.(?:com|net|org|io|co|info|biz|xyz|app|online|site|top|us)\b",
    "amount": r"\$\s?[\d,]+(?:\.\d\d)?",
    "phone number": r"\+?\d[\d\-\s().]{8,}\d",
}


def facts(text: str) -> dict[str, set]:
    """Addresses, links, amounts and phone numbers in the text, normalized for comparing."""
    out = {}
    for kind, pat in FACT_PATTERNS.items():
        if kind == "phone number":   # compare on the last 10 digits
            out[kind] = {re.sub(r"\D", "", v)[-10:] for v in re.findall(pat, text)}
        else:
            out[kind] = {v.lower().rstrip(".,") for v in re.findall(pat, text)}
    return out


@dataclass
class Finding:
    text: str
    where: list[str]
    level: str                      # threat | caution | info
    why: list[str] = field(default_factory=list)
    detectors: dict = field(default_factory=dict)


@dataclass
class Report:
    kind: str
    verdict: str
    headline: str
    findings: list[Finding] = field(default_factory=list)
    visible_text: str = ""
    ai_only_text: str = ""
    children: list = field(default_factory=list)   # attachments

    def to_dict(self):
        return asdict(self)


def _judge(spans, visible: str, detectors, long_passage_caution: bool = True) -> list[Finding]:
    seen_facts = facts(visible)
    out = []
    for s in spans:
        why = []
        votes = {d.name: d(s.text) for d in detectors} if s.text.strip() else {}
        flagged = [n for n, v in votes.items() if v.flagged]
        if flagged:
            why.append("talks to an AI (" + ", ".join(flagged) + ")")
        new = {k: v - seen_facts[k] for k, v in facts(s.text).items()}
        new = {k: v for k, v in new.items() if v}
        for k, v in new.items():
            why.append(f"adds a hidden {k}: {', '.join(sorted(v))}")
        if any("Unicode tag payload" in r for r in s.reasons):
            why.append("text smuggled in invisible Unicode")
        long_hidden = long_passage_caution and len(s.text.split()) >= 25
        unsure = [n for n, v in votes.items() if getattr(v, "unsure", False)]
        is_comment = any("comment" in r.lower() for r in s.reasons)
        if why:
            level = "threat"
        elif (unsure or long_hidden) and not is_comment:
            level = "caution"
            why.append(f"might be instructing an AI ({', '.join(unsure)})" if unsure
                       else "a long passage you can't see")
        else:
            level = "info"
        out.append(Finding(s.text, s.reasons, level, why,
                           {n: {"flagged": v.flagged, "detail": v.detail, "unsure": getattr(v, "unsure", False)}
                            for n, v in votes.items()}))
    return out


def _report(kind, result, detectors, extra_findings=()) -> Report:
    findings = _judge(result["hidden"], result["visible_text"], detectors) + list(extra_findings)
    levels = {f.level for f in findings}
    verdict = "threat" if "threat" in levels else "caution" if "caution" in levels else "clean"
    n_threat = sum(f.level == "threat" for f in findings)
    headline = {
        "threat": f"{n_threat} hidden instruction{'s' if n_threat != 1 else ''} aimed at AI found",
        "caution": "Contains text you can't see; purpose unclear",
        "clean": "Nothing hidden from you" if not findings
                 else f"Only harmless hidden text ({len(findings)} piece{'s' if len(findings) != 1 else ''}, e.g. preview lines)",
    }[verdict]
    return Report(kind, verdict, headline, findings, result["visible_text"],
                  " ".join(f.text for f in findings if f.level != "info"))


def scan_html(html: str, detectors=None) -> Report:
    return _report("email/html", analyze_html(html), detectors or default_detectors())


def scan_pdf(path: str, detectors=None) -> Report:
    return _report("pdf", analyze_pdf(path), detectors or default_detectors())


def scan_docx(path: str, detectors=None) -> Report:
    return _report("docx", analyze_docx(path), detectors or default_detectors())


def scan_file(path: str, detectors=None) -> Report:
    p = Path(path)
    head = p.read_bytes()[:8]
    suf = p.suffix.lower()
    if head.startswith(b"%PDF") or suf == ".pdf":
        return scan_pdf(path, detectors)
    if head.startswith(b"PK") and suf in (".docx", ""):
        return scan_docx(path, detectors)
    if suf == ".eml":
        return scan_eml(p.read_bytes(), detectors)
    return scan_html(p.read_text(errors="replace"), detectors)


def scan_eml(raw: bytes, detectors=None) -> Report:
    detectors = detectors or default_detectors()
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    body = msg.get_body(preferencelist=("html", "plain"))
    html = body.get_content() if body else ""
    if body and body.get_content_type() == "text/plain":
        html = "<pre>" + html + "</pre>"
    rep = scan_html(html, detectors)
    rep.kind = "email"
    for part in msg.iter_attachments():
        name = part.get_filename() or "attachment"
        data = part.get_payload(decode=True) or b""
        if not data:
            continue
        with tempfile.NamedTemporaryFile(suffix=Path(name).suffix, delete=False) as f:
            f.write(data)
        try:
            child = scan_file(f.name, detectors)
        except Exception as e:  # unreadable attachment: say so, don't crash
            child = Report("unknown", "caution", f"Couldn't read {name}: {e}")
        finally:
            remove_quietly(f.name)
        child.headline = f"{name}: {child.headline}"
        rep.children.append(child)
    worst = ["clean", "caution", "threat"]
    for c in rep.children:
        if worst.index(c.verdict) > worst.index(rep.verdict):
            rep.verdict, rep.headline = c.verdict, c.headline
    return rep


def remove_quietly(path: str):
    try:
        os.remove(path)
    except OSError:
        pass


def scan_url(url: str, client=None, detectors=None) -> Report:
    import httpx
    from .gap.cloak import HUMAN_UA
    detectors = detectors or default_detectors()
    own = client is None
    client = client or httpx.Client(follow_redirects=True, timeout=15)
    try:
        html = client.get(url, headers={"User-Agent": HUMAN_UA}).text
        cloak = check_url(url, client)
    finally:
        if own:
            client.close()
    extra = []
    for agent, d in cloak["agents"].items():
        if d["only_agent"]:
            extra.append(Finding(" ".join(d["only_agent"]), [f"served only to {agent}"], "threat",
                                 [f"page shows {agent} content people don't see"]))
            break  # one finding is enough; the same text usually goes to every agent
    rep = _report("web page", analyze_html(html), detectors, extra)
    if cloak["cloaked_for"]:
        rep.headline = "This page shows AI agents different content: " + ", ".join(cloak["cloaked_for"])
    return rep
