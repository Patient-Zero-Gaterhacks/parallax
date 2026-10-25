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
from .gap.html_gap import MARKUP, _base, analyze_html
from .gap.pdf_gap import analyze_pdf

FACT_PATTERNS = {
    "email address": r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+",
    "link": r"https?://[^\s<>\"')]+|\bwww\.[^\s<>\"')]+|\b[a-z0-9][a-z0-9-]{2,}\.(?:com|net|org|io|co|info|biz|xyz|app|online|site|top|us)\b",
    "amount": r"\$\s?[\d,]+(?:\.\d\d)?",
    # needs phone-like grouping (555-555-0199, (555) 555 0199, +1 555.555.0199); bare digit runs such as
    # dates or build numbers ("20261024") are not phone numbers
    "phone number": r"(?:\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b",
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


_HOST = re.compile(r"(?<![\w@.-])(?:[a-z0-9-]+\.)+[a-z]{2,}(?![\w-])")


def _site(link: str) -> str:
    """Registrable domain of a link or bare domain: https://www.npr.org/player/x -> npr.org."""
    host = re.split(r"[/?#:]", re.sub(r"^[a-z][a-z0-9+.-]*://", "", link.lower()), 1)[0]
    host = re.sub(r"(?<=[a-z])\d+$", "", host)   # "salon.com2020": share text that lost its "/" -> salon.com
    return _base(host)


def _full_link(link: str) -> bool:
    return link.startswith(("http://", "https://", "www."))


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


FAST_MODELS = {"parallax-ml"}   # quick word-based models: on web pages they only raise a caution alone


def _judge(spans, visible: str, detectors, long_passage_caution: bool = True, web: bool = False) -> list[Finding]:
    """web=True (live pages): stricter about what counts as a threat, because real sites hide a lot of
    harmless UI text. Threat needs an instruction pattern, a stronger model (Gemma), invisible-Unicode
    smuggling, or a hidden email/link/phone outside menus, tabs and dialogs. The fast model alone raises a
    caution; amounts alone (prices, upsell boxes) and facts inside collapsible UI are info.
    Markup text (alt/title/aria/data-* attributes, hidden fields, meta tags, JSON-LD) is red only when a
    detector other than the fast model flags it; links/phones/prices there alone are info, and on live
    pages so is a fast-model-only flag. A link whose visible text is one site's address but goes to another
    is a caution in emails and files (red only with another strong signal) and info alone on live pages.
    HTML comments: only facts -> info; only the fast model -> caution in emails/files, info on live pages;
    patterns or Gemma -> threat.
    Second pass (Gemma) runs only on spans the first pass reacted to; it flagging always upgrades. It saying
    harmless clears a fast-model-only reaction: any such reaction on live pages, but in emails and files
    (web=False) only a "maybe", never a fast-model flag."""
    seen_facts = facts(visible)
    # web: sites the page already shows (its own hostname, its links, visible text); a hidden link to one isn't new
    seen_sites = {_base(h) for h in _HOST.findall(visible.lower())} if web else set()
    first =[d for d in detectors if not getattr(d, "second_pass", False)]
    second = [d for d in detectors if getattr(d, "second_pass", False)]
    out = []
    for s in spans:
        why = []
        votes = {d.name: d(s.text) for d in first} if s.text.strip() else {}
        reacted = [n for n, v in votes.items() if v.flagged or getattr(v, "unsure", False)]
        if reacted:   # slow models (Gemma) only look at what the first pass reacted to
            votes.update({d.name: d(s.text) for d in second})
        new = {k: v - seen_facts[k] for k, v in facts(s.text).items()}
        if web:   # only full links count, and only to sites the page doesn't already show ("openai.com" alone is a logo name)
            new["link"] = {u for u in new["link"] if _full_link(u) and _site(u) not in seen_sites}
            new.pop("amount", None)   # hidden prices and headline numbers are normal on web pages
        new = {k: v for k, v in new.items() if v}
        unicode = any("Unicode tag payload" in r for r in s.reasons)
        checks = [votes[d.name] for d in second if d.name in votes]
        cleared = set()
        # live pages hide lots of harmless text, so there Gemma can cancel the fast model's flags; in emails and
        # files it only clears the fast model's "maybe" (it's weak on subtle steering the fast model catches)
        if checks and all(not v.flagged and not getattr(v, "unsure", False) and not str(v.detail).startswith("error")
                          for v in checks) and all(n in FAST_MODELS for n in reacted) and not new and not unicode \
                and (web or not any(votes[n].flagged for n in reacted)):
            cleared = set(reacted)   # the second pass says the fast model's hit was a false alarm
        flagged = [n for n, v in votes.items() if v.flagged and n not in cleared]
        if flagged:
            why.append("talks to an AI (" + ", ".join(flagged) + ")")
        for k, v in new.items():
            why.append(f"adds a hidden {k}: {', '.join(sorted(v))}")
        if unicode:
            why.append("text smuggled in invisible Unicode")
        markup = any(r.startswith(MARKUP) for r in s.reasons)   # alt/aria/data-*/JSON-LD/meta/link text
        mismatch = markup and any("link text shows" in r for r in s.reasons)
        if mismatch:
            why.append("link text shows one site but goes to another")
        long_hidden = long_passage_caution and len(s.text.split()) >= 25 and not markup
        unsure = [n for n, v in votes.items() if getattr(v, "unsure", False) and n not in cleared]
        is_comment = any("comment" in r.lower() for r in s.reasons)
        if web and any("collapsed UI" in r for r in s.reasons) and not flagged and not new:
            unsure = []   # menus, tabs and dialogs: a "maybe" from a model isn't worth a warning
        if web and markup and not flagged:
            unsure = []   # pages are full of alt text and structured data; only a real flag counts
        strong = bool(why)
        if markup and not mismatch and not unicode and not [n for n in flagged if n not in FAST_MODELS]:
            strong = False   # links/phones/prices or a fast-model guess in alt text or JSON-LD: never red alone
        if mismatch and not (flagged or unicode):
            strong = False   # a lookalike link alone is a caution in emails and files
        markup_label = markup and not mismatch and not unicode and (web or len(s.text.split()) < 12) \
            and flagged and all(n in FAST_MODELS for n in flagged)   # "Learn more about the assistant", meta descriptions
        if web and why:
            ui = any("collapsed UI" in r for r in s.reasons)
            strong_votes = [n for n in flagged if n not in FAST_MODELS]
            strong_facts = {k: v for k, v in new.items() if k != "amount"} if not (ui or is_comment) else {}
            if markup and not mismatch:
                strong_facts = {}
            strong = bool(strong_votes or strong_facts or unicode)
            if mismatch and not (strong_votes or unicode):
                strong = False   # on live pages a lookalike link is a caution (redirect/tracking links are common)
        ui_facts_only = web and why and not flagged and any("collapsed UI" in r for r in s.reasons) \
            and not unicode
        ui_facts_only = ui_facts_only or (markup and not mismatch and why and not flagged and not unicode) \
            or (web and markup_label) or (web and mismatch and not flagged and not unicode)
        if why and strong:
            level = "threat"
        elif ui_facts_only:
            level = "info"      # a phone number or price inside a closed menu/tab is normal UI
        elif why:
            level = "caution"
        elif (unsure or long_hidden) and not is_comment:
            level = "caution"
            why.append(f"might be instructing an AI ({', '.join(unsure)})" if unsure
                       else "a long passage you can't see")
        else:
            level = "info"
        if is_comment and not unicode and not [n for n in flagged if n not in FAST_MODELS]:
            # comments listing script/CDN links or license notes are build leftovers, not a message
            level = "caution" if flagged and not web else "info"
        out.append(Finding(s.text, s.reasons, level, why,
                           {n: {"flagged": v.flagged, "detail": v.detail, "unsure": getattr(v, "unsure", False)}
                            for n, v in votes.items()}))
    return out


def _report(kind, result, detectors, extra_findings=(), web: bool = False) -> Report:
    findings = _judge(result["hidden"], result["visible_text"], detectors,
                      long_passage_caution=not web, web=web) + list(extra_findings)
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


def scan_url(url: str, client=None, detectors=None, safe: bool = False) -> Report:
    """safe=True (public mode): only public http(s) targets, checked before connecting and on every
    redirect, 5 MB per response (parallax/netsafe.py). Raises netsafe.UnsafeURL when refused."""
    import httpx
    from . import netsafe
    from .gap.cloak import HUMAN_UA
    detectors = detectors or default_detectors()
    own = client is None
    client = client or (netsafe.client() if safe else httpx.Client(follow_redirects=True, timeout=15))
    fetch = (lambda u, ua: netsafe.safe_get(client, u, {"User-Agent": ua})) if safe else None
    try:
        html = fetch(url, HUMAN_UA) if safe else client.get(url, headers={"User-Agent": HUMAN_UA}).text
        cloak = check_url(url, client, fetch=fetch)
    finally:
        if own:
            client.close()
    extra = []
    for agent, d in cloak["agents"].items():
        if d["only_agent"]:
            extra.append(Finding(" ".join(d["only_agent"]), [f"served only to {agent}"], "threat",
                                 [f"page shows {agent} content people don't see"]))
            break  # one finding is enough; the same text usually goes to every agent
    rep = _report("web page", analyze_html(html), detectors, extra, web=True)   # a live page: web rules
    if cloak["cloaked_for"]:
        rep.headline = "This page shows AI agents different content: " + ", ".join(cloak["cloaked_for"])
    return rep
