"""Find text in a PDF that a person can't see but an AI will read.

We render each page and check every text span against the pixels it
actually produced ("ink"). One test catches white-on-white, text covered
by a shape, transparent text and tiny fonts. It also lets us tell an
attack apart from a scanned PDF's invisible OCR layer, whose words sit on
top of an image that shows the same words.
"""

from __future__ import annotations

import numpy as np
import pymupdf

from .html_gap import HiddenSpan
from .text import instruction_score, invisible_chars

ZOOM = 2.0
INK_MIN = 0.01          # share of pixels in the box that must look like ink
MIN_FONT_PT = 3.0


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


def analyze_pdf(path: str) -> dict:
    doc = pymupdf.open(path)
    spans: list[HiddenSpan] = []
    visible_parts: list[str] = []
    ocr_layer_words = 0

    for page in doc:
        pix = page.get_pixmap(matrix=pymupdf.Matrix(ZOOM, ZOOM), alpha=False)
        img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3)
        rect = page.rect
        traces = page.get_texttrace()
        # A real scanned page is one big image with only invisible OCR text.
        # Invisible text on a page that also has normal text, or over a
        # small picture, is not a scan: treat it as hidden.
        img_area = sum(pymupdf.Rect(i["bbox"]).intersect(rect).get_area()
                       for i in page.get_image_info())
        has_real_text = any(t["type"] != 3 and "".join(chr(c[0]) for c in t["chars"]).strip()
                            for t in traces)
        looks_scanned = img_area >= 0.8 * rect.get_area() and not has_real_text
        for tr in traces:
            text = "".join(chr(c[0]) for c in tr["chars"]).strip()
            if not text:
                continue
            bbox = tr["bbox"]
            reasons = []
            off_page = (bbox[2] < rect.x0 or bbox[0] > rect.x1 or
                        bbox[3] < rect.y0 or bbox[1] > rect.y1)
            if off_page:
                reasons.append("placed outside the page")
            if tr["size"] < MIN_FONT_PT:
                reasons.append(f"font {tr['size']:.1f}pt")
            if tr.get("opacity", 1) <= 0.05:
                reasons.append(f"opacity {tr.get('opacity')}")
            ink, busy = (0.0, 0.0) if off_page else _ink_ratio(img, bbox, _rgb(tr["color"]))
            invisible_mode = tr["type"] == 3
            if invisible_mode and busy > 0.05 and looks_scanned:
                # Scanned page: invisible OCR words over an image. Benign.
                # TODO: check the words match the image (e.g. Gemma vision).
                ocr_layer_words += len(text.split())
                visible_parts.append(text)
                continue
            if invisible_mode:
                reasons.append("invisible text render mode")
            elif not off_page and ink < INK_MIN:
                reasons.append(f"no visible ink in its box (ink {ink:.3f})")
            inv = invisible_chars(text)
            if inv["tag_payload"]:
                reasons.append(f"Unicode tag payload: {inv['tag_payload']!r}")
            if reasons:
                payload = text + (" " + inv["tag_payload"] if inv["tag_payload"] else "")
                sc, hits = instruction_score(payload)
                spans.append(HiddenSpan(payload, reasons, sc, hits))
            else:
                visible_parts.append(text)
    doc.close()
    return {"visible_text": " ".join(visible_parts), "hidden": spans,
            "attack": any(s.is_attack for s in spans),
            "ocr_layer_words": ocr_layer_words}
