"""Find text in an HTML email that a person can't see but an AI will read.

Works from the email's own HTML and CSS (emails rarely run scripts and
mostly use inline styles). Live web pages are checked by the extension
instead, which can ask the browser for real computed styles and layout.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from .text import instruction_score, invisible_chars

NAMED = {"white": (255, 255, 255), "black": (0, 0, 0), "red": (255, 0, 0),
         "transparent": None, "#fff": (255, 255, 255), "#000": (0, 0, 0)}


@dataclass
class HiddenSpan:
    text: str
    reasons: list[str]
    score: int = 0
    hits: list[str] = field(default_factory=list)

    @property
    def is_attack(self) -> bool:
        from .text import ATTACK_THRESHOLD
        return self.score >= ATTACK_THRESHOLD


# Colors

def parse_color(v: str | None):
    if not v:
        return None
    v = v.strip().lower()
    if v in NAMED:
        return NAMED[v]
    m = re.fullmatch(r"#([0-9a-f]{3}|[0-9a-f]{6})", v)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    m = re.fullmatch(r"rgba?\(([^)]+)\)", v)
    if m:
        # handles both "rgb(1, 2, 3)" and the newer "rgb(1 2 3 / 0.5)"
        parts = [p for p in re.split(r"[\s,/]+", m.group(1)) if p]
        try:
            nums = [_color_num(p, i) for i, p in enumerate(parts)]
        except ValueError:
            return None
        if len(nums) < 3:
            return None
        if len(nums) >= 4 and nums[3] == 0:   # fully transparent
            return None
        return tuple(max(0, min(255, int(n))) for n in nums[:3])
    return None


def _color_num(p: str, i: int) -> float:
    """One number from rgb()/rgba(). Percentages: 0-255 for r/g/b, 0-1 for alpha."""
    if p.endswith("%"):
        return float(p[:-1]) * (2.55 if i < 3 else 0.01)
    return float(p)


def _lum(c):
    def ch(x):
        x /= 255
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(x) for x in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# CSS

def _decls(style: str) -> dict:
    out = {}
    for part in (style or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip().lower()] = v.strip().lower().replace("!important", "").strip()
    return out


def _stylesheet_rules(soup) -> list[tuple[str, dict]]:
    """Simple selectors only (tag, .class, #id, comma lists) - enough for
    the hiding tricks seen in practice; complex selectors need a browser."""
    rules = []
    for st in soup.find_all("style"):
        css = re.sub(r"/\*.*?\*/", "", st.get_text(), flags=re.S)
        for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            for s in sel.split(","):
                rules.append((s.strip(), _decls(body)))
    return rules


def _matches(el: Tag, sel: str) -> bool:
    if sel.startswith("."):
        return sel[1:] in (el.get("class") or [])
    if sel.startswith("#"):
        return el.get("id") == sel[1:]
    return el.name == sel.lower()


def computed(el: Tag, rules) -> dict:
    style = {}
    for sel, d in rules:
        if _matches(el, sel):
            style.update(d)
    style.update(_decls(el.get("style", "")))
    if el.get("bgcolor"):
        style.setdefault("background-color", el["bgcolor"])
    if el.name == "font" and el.get("color"):
        style.setdefault("color", el["color"])
    return style


def _px(v: str | None):
    if not v:
        return None
    m = re.match(r"(-?\d*\.?\d+)\s*(px|pt|em|rem|%)?", v)
    if not m:
        return None
    n, unit = float(m.group(1)), m.group(2) or "px"
    return {"px": n, "pt": n * 1.333, "em": n * 16, "rem": n * 16, "%": n * 0.16}[unit]


# Analysis

def _visibility_reasons(node: NavigableString, rules) -> list[str]:
    reasons = []
    color, bg, size = None, None, None
    for el in [p for p in node.parents if isinstance(p, Tag)]:
        if el.name == "[document]":
            continue
        s = computed(el, rules)
        if el.has_attr("hidden"):
            reasons.append(f"<{el.name} hidden>")
        if s.get("display") == "none":
            reasons.append(f"display:none on <{el.name}>")
        if s.get("visibility") in ("hidden", "collapse"):
            reasons.append(f"visibility:hidden on <{el.name}>")
        if s.get("mso-hide") == "all":
            reasons.append("mso-hide:all")
        op = _px(s.get("opacity"))
        if op is not None and op <= 0.05:
            reasons.append(f"opacity:{s['opacity']}")
        for k in ("max-height", "height", "width", "max-width"):
            v = _px(s.get(k))
            if v is not None and v <= 1 and s.get("overflow") == "hidden":
                reasons.append(f"{k}:0 + overflow:hidden")
        for k in ("left", "top", "text-indent", "margin-left"):
            v = _px(s.get(k))
            if v is not None and v <= -500:
                reasons.append(f"{k}:{s.get(k)} (off-screen)")
        if "clip" in s and re.search(r"rect\(\s*0", s["clip"]):
            reasons.append("clip:rect(0...)")
        if color is None and parse_color(s.get("color")):
            color = parse_color(s.get("color"))
        if bg is None and parse_color(s.get("background-color") or s.get("background")):
            bg = parse_color(s.get("background-color") or s.get("background"))
        if size is None and _px(s.get("font-size")) is not None:
            size = _px(s.get("font-size"))
    color = color or (0, 0, 0)
    bg = bg or (255, 255, 255)
    if contrast(color, bg) < 1.5:
        reasons.append(f"text color ~ background (contrast {contrast(color, bg):.2f}:1)")
    if size is not None and size < 4:
        reasons.append(f"font-size {size:.1f}px")
    return reasons


def analyze_html(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    rules = _stylesheet_rules(soup)
    spans: list[HiddenSpan] = []
    visible_parts: list[str] = []

    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        if c.strip():
            sc, hits = instruction_score(c)
            spans.append(HiddenSpan(c.strip(), ["HTML comment"], sc, hits))
    for node in soup.find_all(string=True):
        if isinstance(node, Comment) or node.parent.name in ("style", "script", "head", "title"):
            continue
        txt = str(node).strip()
        if not txt:
            continue
        inv = invisible_chars(txt)
        reasons = _visibility_reasons(node, rules)
        if inv["count"] >= 3:
            reasons.append(f"{inv['count']} invisible Unicode characters")
        if inv["tag_payload"]:
            reasons.append(f"Unicode tag payload: {inv['tag_payload']!r}")
        if reasons:
            payload = txt + (" " + inv["tag_payload"] if inv["tag_payload"] else "")
            sc, hits = instruction_score(payload)
            spans.append(HiddenSpan(payload, reasons, sc, hits))
        else:
            visible_parts.append(txt)
    return {"visible_text": " ".join(visible_parts), "hidden": spans,
            "attack": any(s.is_attack for s in spans)}
