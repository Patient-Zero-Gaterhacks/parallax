"""Find text in a Word (.docx) file that a person can't see but an AI will read.

Résumés and cover letters are usually Word files, and applicant-tracking
systems read the raw XML, hidden runs included. We read the same XML and
check each run of text for Word's ways of hiding it:

  * the "hidden" font effect (<w:vanish/>, <w:specVanish/>, <w:webHidden/>)
  * text color equal to its background (run / paragraph / cell shading)
  * tiny font size

Headers, footers, text boxes and footnotes are included, since parsers read them.

We also report document data Word doesn't show on the page but parsers
pass on: core properties (title, subject, keywords, comments), reviewer
comments, tracked deletions (w:delText) and image alt text. Their reasons
start with "markup:" so the judge treats them gently (see scan._judge).
"""

from __future__ import annotations

import zipfile

from lxml import etree

from .html_gap import MARKUP, HiddenSpan, contrast, parse_color
from .text import instruction_score, invisible_chars

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
CORE = {"dc": "http://purl.org/dc/elements/1.1/",
        "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"}
MIN_HALF_POINTS = 8  # w:sz is in half-points: 8 = 4pt
PROSE_WORDS = 5      # core properties shorter than this are labels, not messages


def _q(tag):
    return f"{{{W}}}{tag}"


def _hex(v):
    if not v or v.lower() in ("auto", "none"):
        return None
    return parse_color("#" + v)


def _style_rpr(styles_root, style_id):
    """rPr of a character or paragraph style, following basedOn links."""
    out, seen = [], set()
    while style_id and style_id not in seen and styles_root is not None:
        seen.add(style_id)
        st = styles_root.find(f".//w:style[@w:styleId='{style_id}']", NS)
        if st is None:
            break
        rpr = st.find("w:rPr", NS)
        if rpr is not None:
            out.append(rpr)
        b = st.find("w:basedOn", NS)
        style_id = b.get(_q("val")) if b is not None else None
    return out


def _parts(z: zipfile.ZipFile):
    names = z.namelist()
    main = ["word/document.xml"]
    extra = [n for n in names if n.startswith("word/header") or n.startswith("word/footer")
             or n in ("word/footnotes.xml", "word/endnotes.xml")]
    return main + sorted(extra)


def _span(text: str, reasons: list[str]) -> HiddenSpan:
    sc, hits = instruction_score(text)
    return HiddenSpan(text, reasons, sc, hits)


def _core_properties(z: zipfile.ZipFile) -> list[HiddenSpan]:
    if "docProps/core.xml" not in z.namelist():
        return []
    root = etree.fromstring(z.read("docProps/core.xml"))
    out = []
    # Word's "Comments" property is dc:description
    for tag, label in (("dc:title", "title"), ("dc:subject", "subject"), ("cp:keywords", "keywords"),
                       ("dc:description", "comments/description")):
        el = root.find(tag, CORE)
        v = (el.text or "").strip() if el is not None else ""
        if len(v.split()) >= PROSE_WORDS:
            out.append(_span(v, [f"{MARKUP} document properties ({label})"]))
    return out


def _comments(z: zipfile.ZipFile) -> list[HiddenSpan]:
    if "word/comments.xml" not in z.namelist():
        return []
    out = []
    for c in etree.fromstring(z.read("word/comments.xml")).iter(_q("comment")):
        text = " ".join("".join(t.text or "" for t in p.iter(_q("t"))) for p in c.iter(_q("p"))).strip()
        if text:
            out.append(_span(text, [f"{MARKUP} reviewer comment"]))
    return out


def _part_markup(root, where: str) -> list[HiddenSpan]:
    """Tracked deletions and image alt text in one part."""
    out = []
    loc = [f"in {where}"] if where != "document" else []
    for p in root.iter(_q("p")):
        text = "".join(t.text or "" for t in p.iter(_q("delText"))).strip()
        if text:
            out.append(_span(text, [f"{MARKUP} deleted text (tracked changes)"] + loc))
    for el in root.iter("{*}docPr"):
        for attr in ("descr", "title"):
            v = (el.get(attr) or "").strip()
            if v:
                out.append(_span(v, [f"{MARKUP} image alt text"] + loc))
    return out


def analyze_docx(path: str) -> dict:
    z = zipfile.ZipFile(path)
    styles = etree.fromstring(z.read("word/styles.xml")) if "word/styles.xml" in z.namelist() else None
    doc_root = etree.fromstring(z.read("word/document.xml"))
    bg_el = doc_root.find("w:background", NS)
    page_bg = _hex(bg_el.get(_q("color"))) if bg_el is not None else None
    page_bg = page_bg or (255, 255, 255)

    spans: list[HiddenSpan] = []
    visible_parts: list[str] = []
    for part in _parts(z):
        root = doc_root if part == "word/document.xml" else etree.fromstring(z.read(part))
        where = part.split("/")[-1].replace(".xml", "")
        spans += _part_markup(root, where)
        for r in root.iter(_q("r")):
            text = "".join(t.text or "" for t in r.iter(_q("t")))
            if not text.strip():
                continue
            # Collect formatting from paragraph style, character style, run.
            p = next(r.iterancestors(_q("p")), None)
            rprs = []
            if p is not None:
                ps = p.find("w:pPr/w:pStyle", NS)
                if ps is not None:
                    rprs += _style_rpr(styles, ps.get(_q("val")))
            rpr = r.find("w:rPr", NS)
            if rpr is not None:
                cs = rpr.find("w:rStyle", NS)
                if cs is not None:
                    rprs += _style_rpr(styles, cs.get(_q("val")))
                rprs.append(rpr)

            def last(tag, attr="val"):
                v = None
                for x in rprs:
                    e = x.find(f"w:{tag}", NS)
                    if e is not None:
                        v = e.get(_q(attr), "true")
                return v

            reasons = []
            for tag in ("vanish", "specVanish", "webHidden"):
                v = last(tag)
                if v is not None and v not in ("0", "false"):
                    reasons.append(f"Word 'hidden' effect (w:{tag})")
            sz = last("sz")
            if sz is not None and sz.isdigit() and int(sz) < MIN_HALF_POINTS:
                reasons.append(f"font {int(sz) / 2:.1f}pt")
            color = _hex(last("color")) or (0, 0, 0)
            bg = _hex(last("shd", "fill"))
            if bg is None and p is not None:
                pshd = p.find("w:pPr/w:shd", NS)
                bg = _hex(pshd.get(_q("fill"))) if pshd is not None else None
            if bg is None:
                tc = next(r.iterancestors(_q("tc")), None)
                if tc is not None:
                    cshd = tc.find("w:tcPr/w:shd", NS)
                    bg = _hex(cshd.get(_q("fill"))) if cshd is not None else None
            bg = bg or page_bg
            if contrast(color, bg) < 1.5:
                reasons.append(f"text color ~ background (contrast {contrast(color, bg):.2f}:1)")
            inv = invisible_chars(text)
            if inv["tag_payload"]:
                reasons.append(f"Unicode tag payload: {inv['tag_payload']!r}")
            if reasons:
                payload = text + (" " + inv["tag_payload"] if inv["tag_payload"] else "")
                sc, hits = instruction_score(payload)
                spans.append(HiddenSpan(payload, reasons + ([f"in {where}"] if where != "document" else []), sc, hits))
            else:
                visible_parts.append(text)
    spans += _comments(z) + _core_properties(z)
    z.close()
    return {"visible_text": " ".join(visible_parts), "hidden": spans,
            "attack": any(s.is_attack for s in spans)}
