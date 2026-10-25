"""Find text in a PDF that a person can't see but an AI will read.

We render each page and check every text span against the pixels it
actually produced ("ink"). One test catches white-on-white, text covered
by a shape, transparent text and tiny fonts. It also lets us tell an
attack apart from a scanned PDF's invisible OCR layer, whose words sit on
top of an image that shows the same words.

On top of that:
  * text in an optional-content layer that is turned off (viewers don't
    draw it and most extractors skip it, but an AI fed the raw file can
    read it): we switch every layer on to extract it
  * text an image or filled shape is drawn over (from the page's drawing
    order, since the image itself may contain ink-like pixels)
  * hidden pieces on a page that share a reason are joined, in reading
    order, so an attack split one word per line is judged as a sentence
  * document data a viewer doesn't show on the page: annotation comments,
    form field values, metadata, embedded files. Their reasons start with
    "markup:" so the judge treats them gently (see scan._judge).
"""

from __future__ import annotations

import re

import numpy as np
import pymupdf

from .html_gap import MARKUP, HiddenSpan
from .text import instruction_score, invisible_chars

ZOOM = 2.0
INK_MIN = 0.01          # share of pixels in the box that must look like ink
MIN_FONT_PT = 3.0
COVER_MIN = 0.6         # share of a span's box an image/shape drawn later must cover
MERGE_MAX_WORDS = 400   # longest passage built from joined pieces
PROSE_WORDS = 5         # metadata shorter than this is a label, not a message
EMBED_MAX_BYTES = 2_000_000


def _rgb(c):
    if isinstance(c, (list, tuple)):
        if len(c) == 1:
            return (int(c[0] * 255),) * 3
        if len(c) >= 3:
            return tuple(int(x * 255) for x in c[:3])
    if isinstance(c, int):
        return ((c >> 16) & 255, (c >> 8) & 255, c & 255)
    return (0, 0, 0)


def _ink_ratio(img: np.ndarray, bbox, color) -> tuple[float, float]:
    """Return (ink share, non-background share) inside bbox."""
    h, w, _ = img.shape
    x0, y0, x1, y1 = [int(round(v * ZOOM)) for v in bbox]
    x0, x1 = max(0, x0), min(w, max(x1, x0 + 1))
    y0, y1 = max(0, y0), min(h, max(y1, y0 + 1))
    region = img[y0:y1, x0:x1].reshape(-1, 3).astype(int)
    if region.size == 0:
        return 0.0, 0.0
    # Background = the most common colour around the box edge.
    pad = 3
    ring = np.concatenate([
        img[max(0, y0 - pad):y0, x0:x1].reshape(-1, 3),
        img[y1:min(h, y1 + pad), x0:x1].reshape(-1, 3),
    ]).astype(int)
    if len(ring) == 0:
        ring = region
    vals, counts = np.unique(ring, axis=0, return_counts=True)
    bg = vals[counts.argmax()]
    far_from_bg = np.abs(region - bg).sum(axis=1) > 60
    near_color = np.abs(region - np.array(color)).sum(axis=1) < 200
    return float((far_from_bg & near_color).mean()), float(far_from_bg.mean())


def _all_layers_on(path: str, doc) -> tuple[object, set]:
    """A second copy of the document with every optional-content layer on, and the names of the
    layers that are off by default. No layers off: the document itself."""
    off = {v["name"] for v in doc.get_ocgs().values() if not v["on"]}
    if not off:
        return doc, off
    full = pymupdf.open(path)
    for c in full.layer_ui_configs():
        if not c["on"]:
            full.set_layer_ui_config(c["number"], 0)
    try:   # layers missing from the viewer's layer list: clear the default OFF list too
        cat = full.pdf_catalog()
        full.xref_set_key(cat, "OCProperties/D/OFF", "[]")
        full.xref_set_key(cat, "OCProperties/D/BaseState", "/ON")
    except Exception:
        pass
    return full, off


def _covers(page, log, off_layers) -> dict[int, list]:
    """Opaque images and filled shapes by drawing position: {seqno: bbox}."""
    images = {tuple(round(v, 1) for v in i["bbox"]): i.get("has-mask", False)
              for i in page.get_image_info()}
    paths = None
    out = {}
    for n, entry in enumerate(log):
        kind, bbox = entry[0], entry[1]
        if len(entry) > 2 and entry[2] in off_layers:
            continue
        if kind == "fill-image":
            if images.get(tuple(round(v, 1) for v in bbox)):
                continue   # image with a transparency mask: may not hide what's under it
            out[n] = bbox
        elif kind in ("fill-path", "fill-shade"):
            if kind == "fill-path":
                if paths is None:
                    paths = {d["seqno"]: d for d in page.get_drawings()}
                d = paths.get(n)
                if d is not None and (d.get("fill_opacity") or 1) < 0.5:
                    continue
            out[n] = bbox
    return out


def _covered_by(bbox, seqno, covers) -> list:
    """Covers drawn after the span that hide most of its box."""
    r = pymupdf.Rect(bbox)
    area = r.get_area()
    if area <= 0:
        return []
    return [c for n, c in covers.items()
            if n > seqno and pymupdf.Rect(c).intersect(r).get_area() >= COVER_MIN * area]


def _kind(reason: str) -> str:
    """A reason without its measurements, for grouping: "font 1.0pt" -> "font"."""
    reason = re.sub(r"\s*\([^)]*\)$", "", reason)
    return re.sub(r"^(font|opacity) .*", r"\1", reason)


def _span(text: str, reasons: list[str]) -> HiddenSpan:
    sc, hits = instruction_score(text)
    return HiddenSpan(text, reasons, sc, hits)


def _merge(pieces: list[tuple]) -> list[HiddenSpan]:
    """Join hidden pieces of one page that share their reasons, in reading order, into passages of up to
    MERGE_MAX_WORDS words. pieces: (sort key, text, reasons). Unicode-tag pieces stay on their own."""
    groups: dict[tuple, list] = {}
    alone = []
    for key, text, reasons in sorted(pieces, key=lambda p: p[0]):
        if any("Unicode tag payload" in r for r in reasons):
            alone.append(_span(text, reasons))
            continue
        groups.setdefault(tuple(sorted({_kind(r) for r in reasons})), []).append((text, reasons))
    out = []
    for items in groups.values():
        texts, first, words = [], None, 0
        for text, reasons in items:
            n = len(text.split())
            if texts and words + n > MERGE_MAX_WORDS:
                out.append(_joined(texts, first))
                texts, words = [], 0
            if not texts:
                first = reasons
            texts.append(text)
            words += n
        if texts:
            out.append(_joined(texts, first))
    return out + alone


def _joined(texts: list[str], reasons: list[str]) -> HiddenSpan:
    extra = [f"{len(texts)} pieces joined"] if len(texts) > 1 else []
    return _span(" ".join(texts), reasons + extra)


def _passages(text: str):
    words = text.split()
    for k in range(0, len(words), MERGE_MAX_WORDS):
        yield " ".join(words[k:k + MERGE_MAX_WORDS])


def _as_text(data: bytes) -> str | None:
    """The file's text if it is a text file, else None."""
    for enc in (("utf-16",) if data[:2] in (b"\xff\xfe", b"\xfe\xff") else ("utf-8",)):
        try:
            s = data.decode(enc)
        except UnicodeDecodeError:
            return None
        bad = sum(1 for c in s if ord(c) < 32 and c not in "\t\n\r\f")
        return s if s.strip() and bad <= 0.01 * len(s) else None
    return None


def _embedded(name: str, data: bytes, where: str) -> list[HiddenSpan]:
    text = _as_text(data[:EMBED_MAX_BYTES])
    if text is None:   # can't read it as text: say it's there
        return [_span(name, [f"{MARKUP} embedded file not scanned ({name})"])]
    return [_span(p, [f"{MARKUP} {where} ({name})"]) for p in _passages(text)]


def _document_data(doc) -> list[HiddenSpan]:
    """Text a viewer doesn't show on the page: comments, form values, metadata, embedded files."""
    out = []
    meta = doc.metadata or {}
    for key in ("title", "subject", "keywords", "author"):
        v = (meta.get(key) or "").strip()
        if len(v.split()) >= PROSE_WORDS:
            out.append(_span(v, [f"{MARKUP} document metadata ({key})"]))
    for n, page in enumerate(doc):
        for a in page.annots() or []:
            kind = a.type[1]
            if a.type[0] == pymupdf.PDF_ANNOT_POPUP:
                continue   # a popup repeats its parent's text
            if a.type[0] == pymupdf.PDF_ANNOT_FILE_ATTACHMENT:
                try:
                    out += _embedded(a.file_info.get("filename") or "attachment", a.get_file(),
                                     f"file attached on page {n + 1}")
                except Exception:
                    pass
            content = (a.info.get("content") or "").strip()
            if content:
                out.append(_span(content, [f"{MARKUP} annotation comment ({kind}, page {n + 1})"]))
        for w in page.widgets() or []:
            v = w.field_value
            if isinstance(v, str) and v.strip() and v not in ("Off", "Yes"):
                out.append(_span(v.strip(), [f"{MARKUP} form field value ({w.field_name or 'unnamed'})"]))
    for name in doc.embfile_names():
        try:
            out += _embedded(name, doc.embfile_get(name), "embedded file")
        except Exception:
            out.append(_span(name, [f"{MARKUP} embedded file not scanned ({name})"]))
    return out


def analyze_pdf(path: str) -> dict:
    doc = pymupdf.open(path)
    full, off_layers = _all_layers_on(path, doc)
    spans: list[HiddenSpan] = []
    visible_parts: list[str] = []
    ocr_layer_words = 0

    for page, fpage in zip(doc, full):
        pix = page.get_pixmap(matrix=pymupdf.Matrix(ZOOM, ZOOM), alpha=False)
        img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3)
        rect = page.rect
        traces = fpage.get_texttrace()    # every layer on: includes text in hidden layers
        covers = _covers(fpage, fpage.get_bboxlog(layers=True), off_layers)
        # A real scanned page is one big image with only invisible OCR text.
        # Invisible text on a page that also has normal text, or over a
        # small picture, is not a scan: treat it as hidden.
        img_area = sum(pymupdf.Rect(i["bbox"]).intersect(rect).get_area()
                       for i in page.get_image_info())
        has_real_text = any(t["type"] != 3 and "".join(chr(c[0]) for c in t["chars"]).strip()
                            for t in traces)
        looks_scanned = img_area >= 0.8 * rect.get_area() and not has_real_text
        page_area = rect.get_area()
        texts = [(tr, "".join(chr(c[0]) for c in tr["chars"]).strip()) for tr in traces]
        texts = [(tr, t) for tr, t in texts if t]
        covered = {id(tr): _covered_by(tr["bbox"], tr["seqno"], covers) for tr, _ in texts}
        # Some scanners put the OCR text under the page image instead of on top: every word on the
        # page sits under one page-sized image. That's a scan, not an attack.
        under_scan = bool(texts) and all(
            any(pymupdf.Rect(c).intersect(rect).get_area() >= 0.8 * page_area for c in covered[id(tr)])
            for tr, _ in texts)
        pieces = []
        for tr, text in texts:
            bbox = tr["bbox"]
            reasons = []
            in_hidden_layer = tr.get("layer") in off_layers
            if in_hidden_layer:
                reasons.append("in a hidden layer (turned off)")
            off_page = (bbox[2] < rect.x0 or bbox[0] > rect.x1 or
                        bbox[3] < rect.y0 or bbox[1] > rect.y1)
            if off_page:
                reasons.append("placed outside the page")
            if tr["size"] < MIN_FONT_PT:
                reasons.append(f"font {tr['size']:.1f}pt")
            if tr.get("opacity", 1) <= 0.05:
                reasons.append(f"opacity {tr.get('opacity')}")
            ink, busy = (0.0, 0.0) if off_page or in_hidden_layer else _ink_ratio(img, bbox, _rgb(tr["color"]))
            invisible_mode = tr["type"] == 3
            if (invisible_mode and busy > 0.05 and looks_scanned) or under_scan:
                # Scanned page: invisible OCR words over an image. Benign.
                # TODO: check the words match the image (e.g. Gemma vision).
                ocr_layer_words += len(text.split())
                visible_parts.append(text)
                continue
            if invisible_mode:
                reasons.append("invisible text render mode")
            elif covered[id(tr)] and not in_hidden_layer:
                reasons.append("covered by an image or shape drawn on top")
            elif not off_page and not in_hidden_layer and ink < INK_MIN:
                reasons.append(f"no visible ink in its box (ink {ink:.3f})")
            inv = invisible_chars(text)
            if inv["tag_payload"]:
                reasons.append(f"Unicode tag payload: {inv['tag_payload']!r}")
            if reasons:
                payload = text + (" " + inv["tag_payload"] if inv["tag_payload"] else "")
                origin_y = tr["chars"][0][2][1] if tr["chars"] else bbox[3]
                pieces.append(((round(origin_y / 2), bbox[0], tr["seqno"]), payload, reasons))
            else:
                visible_parts.append(text)
        spans += _merge(pieces)
    spans += _document_data(doc)
    if full is not doc:
        full.close()
    doc.close()
    return {"visible_text": " ".join(visible_parts), "hidden": spans,
            "attack": any(s.is_attack for s in spans),
            "ocr_layer_words": ocr_layer_words}
