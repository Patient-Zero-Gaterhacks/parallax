"""Find text in a Word (.docx) file that a person can't see but an AI will read.

Résumés and cover letters are usually Word files, and applicant-tracking
systems read the raw XML, hidden runs included. We read the same XML and
check each run of text for Word's ways of hiding it:

  * the "hidden" font effect (<w:vanish/>, <w:specVanish/>, <w:webHidden/>)
  * text color equal to its background (run / paragraph / cell shading)
  * tiny font size

Headers, footers, text boxes, footnotes and comments are included, since parsers read them.
"""

from __future__ import annotations

import zipfile

from lxml import etree

from .html_gap import HiddenSpan, contrast, parse_color
from .text import instruction_score, invisible_chars

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
MIN_HALF_POINTS = 8  # w:sz is in half-points: 8 = 4pt


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
             or n in ("word/footnotes.xml", "word/endnotes.xml", "word/comments.xml")]
    return main + sorted(extra)


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
    z.close()
    return {"visible_text": " ".join(visible_parts), "hidden": spans,
            "attack": any(s.is_attack for s in spans)}
