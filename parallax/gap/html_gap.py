"""Find text in an HTML email or page that a person can't see but an AI will read.

Works from the HTML and CSS alone (emails rarely run scripts and mostly use
inline styles). Live web pages are checked by the extension instead, which
can ask the browser for real computed styles and layout.

Two kinds of finds:
  * hidden text: text nodes styled so a person can't see them (display:none,
    same color as the background, transparent, 0px font, off-screen, clipped,
    scaled to 0, inside <template>, ...), HTML comments, invisible Unicode
  * markup text: text that lives in the page's markup rather than on screen
    but that AI agents reading the HTML still see: alt/title/aria-label/
    placeholder/data-* attributes, hidden form fields, meta tags, JSON-LD
    structured data, and links whose text shows one site but go to another.
    Their reasons start with "markup:" so the judge can treat them more
    gently (pages are full of harmless alt text and structured data).
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from .text import instruction_score, invisible_chars

MARKUP = "markup:"   # prefix of every markup reason (see scan._judge)

NAMED = {
    "white": (255, 255, 255), "black": (0, 0, 0), "red": (255, 0, 0), "green": (0, 128, 0),
    "blue": (0, 0, 255), "yellow": (255, 255, 0), "orange": (255, 165, 0), "purple": (128, 0, 128),
    "gray": (128, 128, 128), "grey": (128, 128, 128), "silver": (192, 192, 192), "navy": (0, 0, 128),
    "maroon": (128, 0, 0), "olive": (128, 128, 0), "teal": (0, 128, 128), "aqua": (0, 255, 255),
    "cyan": (0, 255, 255), "fuchsia": (255, 0, 255), "magenta": (255, 0, 255), "lime": (0, 255, 0),
    "snow": (255, 250, 250), "ivory": (255, 255, 240), "whitesmoke": (245, 245, 245),
    "ghostwhite": (248, 248, 255), "floralwhite": (255, 250, 240), "linen": (250, 240, 230),
    "seashell": (255, 245, 238), "mintcream": (245, 255, 250), "azure": (240, 255, 255),
    "aliceblue": (240, 248, 255), "honeydew": (240, 255, 240), "beige": (245, 245, 220),
    "lightgray": (211, 211, 211), "lightgrey": (211, 211, 211), "gainsboro": (220, 220, 220),
    "darkgray": (169, 169, 169), "darkgrey": (169, 169, 169), "dimgray": (105, 105, 105),
    "dimgrey": (105, 105, 105),
    "transparent": None, "#fff": (255, 255, 255), "#000": (0, 0, 0),
}


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


# Colors ------------------------------------------------------------------------------------

def _gamma(x: float) -> int:
    x = max(0.0, min(1.0, x))
    x = 12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055
    return int(round(x * 255))


def _hsl(h, s, l):
    s, l = s / 100, l / 100
    k = lambda n: (n + h / 30) % 12  # noqa: E731
    a = s * min(l, 1 - l)
    f = lambda n: l - a * max(-1, min(k(n) - 3, 9 - k(n), 1))  # noqa: E731
    return tuple(int(round(255 * f(n))) for n in (0, 8, 4))


def _oklab(L, a, b):
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    return (_gamma(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
            _gamma(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
            _gamma(-0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s))


def _lab(L, a, b):
    fy = (L + 16) / 116
    fx, fz = fy + a / 500, fy - b / 200
    inv = lambda t: t ** 3 if t ** 3 > 0.008856 else (116 * t - 16) / 903.3  # noqa: E731
    X, Y, Z = 0.96422 * inv(fx), inv(fy), 0.82521 * inv(fz)       # D50 white
    return (_gamma(3.1338561 * X - 1.6168667 * Y - 0.4906146 * Z),
            _gamma(-0.9787684 * X + 1.9161415 * Y + 0.0334540 * Z),
            _gamma(0.0719453 * X - 0.2289914 * Y + 1.4052427 * Z))


def _hue(p: str) -> float:
    for unit, mul in (("deg", 1), ("grad", 0.9), ("rad", 180 / math.pi), ("turn", 360)):
        if p.endswith(unit):
            return float(p[:-len(unit)]) * mul
    return float(p)


def _comp(p: str, pct_scale: float) -> float:
    """One color component; a percentage maps to pct_scale at 100%. 'none' = 0."""
    if p == "none":
        return 0.0
    if p.endswith("%"):
        return float(p[:-1]) / 100 * pct_scale
    return float(p)


def _alpha(parts: list[str], i: int) -> float:
    return max(0.0, min(1.0, _comp(parts[i], 1))) if len(parts) > i else 1.0


def parse_rgba(v: str | None):
    """Any CSS color -> ((r, g, b), alpha), or None if it can't be read.
    Handles names, #rgb/#rgba/#rrggbb/#rrggbbaa, rgb(), hsl(), oklch(), oklab(), lab(), lch(), color(srgb ...)."""
    if not v:
        return None
    v = v.strip().lower()
    if v == "transparent":
        return (0, 0, 0), 0.0
    if v in NAMED:
        return NAMED[v], 1.0
    m = re.fullmatch(r"#([0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})", v)
    if m:
        h = m.group(1)
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        rgb = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
        return rgb, (int(h[6:8], 16) / 255 if len(h) == 8 else 1.0)
    m = re.fullmatch(r"(rgba?|hsla?|oklch|oklab|lab|lch|color)\(([^)]*)\)", v)
    if not m:
        return None
    fn, parts = m.group(1), [p for p in re.split(r"[\s,/]+", m.group(2)) if p]
    try:
        if fn.startswith("rgb") and len(parts) >= 3:
            rgb = tuple(max(0, min(255, int(_comp(p, 255)))) for p in parts[:3])
            return rgb, _alpha(parts, 3)
        if fn.startswith("hsl") and len(parts) >= 3:
            return _hsl(_hue(parts[0]) % 360, _comp(parts[1], 100), _comp(parts[2], 100)), _alpha(parts, 3)
        if fn == "oklch" and len(parts) >= 3:
            L, C, h = _comp(parts[0], 1), _comp(parts[1], 0.4), math.radians(_hue(parts[2]))
            return _oklab(L, C * math.cos(h), C * math.sin(h)), _alpha(parts, 3)
        if fn == "oklab" and len(parts) >= 3:
            return _oklab(_comp(parts[0], 1), _comp(parts[1], 0.4), _comp(parts[2], 0.4)), _alpha(parts, 3)
        if fn == "lab" and len(parts) >= 3:
            return _lab(_comp(parts[0], 100), _comp(parts[1], 125), _comp(parts[2], 125)), _alpha(parts, 3)
        if fn == "lch" and len(parts) >= 3:
            L, C, h = _comp(parts[0], 100), _comp(parts[1], 150), math.radians(_hue(parts[2]))
            return _lab(L, C * math.cos(h), C * math.sin(h)), _alpha(parts, 3)
        if fn == "color" and len(parts) >= 4:          # color(srgb r g b [/ a]); other spaces ~ srgb
            rgb = tuple(max(0, min(255, int(round(_comp(p, 1) * 255)))) for p in parts[1:4])
            return rgb, _alpha(parts, 4)
    except ValueError:
        return None
    return None


def parse_color(v: str | None):
    """(r, g, b) for a visible color; None if transparent or unreadable."""
    p = parse_rgba(v)
    if not p or p[1] <= 0.02:
        return None
    return p[0]


_COLOR_TOKEN = re.compile(r"#[0-9a-f]{3,8}\b|(?:rgba?|hsla?|oklch|oklab|lab|lch|color)\([^)]*\)|\b[a-z]+\b")


def _bg_color(s: dict):
    """Solid background color from background-color, or the color inside a background shorthand."""
    if s.get("background-color"):
        p = parse_rgba(s["background-color"])
        return p[0] if p and p[1] > 0.5 else None
    bg = re.sub(r"url\([^)]*\)", " ", s.get("background", ""))
    for tok in _COLOR_TOKEN.findall(bg):
        p = parse_rgba(tok)
        if p:
            return p[0] if p[1] > 0.5 else None
    return None


def _lum(c):
    def ch(x):
        x /= 255
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(x) for x in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# CSS ---------------------------------------------------------------------------------------

def _decls(style: str) -> dict:
    out = {}
    for part in (style or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip().lower()] = v.strip().lower().replace("!important", "").strip()
    return out


def _drop_conditional_blocks(css: str) -> str:
    """Remove @media blocks that only apply on small screens, in print or for user settings
    (responsive emails hide desktop parts on phones); unwrap other @-blocks and keep their rules."""
    out, i = [], 0
    for m in re.finditer(r"@(media|supports|layer|container)([^{]*)\{", css):
        if m.start() < i:
            continue
        depth, j = 1, m.end()
        while j < len(css) and depth:
            depth += {"{": 1, "}": -1}.get(css[j], 0)
            j += 1
        out.append(css[i:m.start()])
        cond = m.group(2).lower()
        if not re.search(r"max-width|max-device-width|print|prefers-|hover|pointer|orientation", cond):
            out.append(css[m.end():j - 1])
        i = j
    out.append(css[i:])
    return "".join(out)


def _stylesheet_rules(soup) -> "_Rules":
    """Rules from <style> blocks. Selectors: tag, .class, #id, [attr], [attr=value] and
    combinations of them, joined by spaces or '>'. Pseudo-classes and sibling selectors
    are skipped (they need a browser); @media blocks are read as if they always apply."""
    rules = []
    for st in soup.find_all("style"):
        css = re.sub(r"/\*.*?\*/", "", st.get_text(), flags=re.S)
        css = _drop_conditional_blocks(css)
        for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            for s in sel.split(","):
                s = s.strip()
                if s and not s.startswith("@"):
                    rules.append((s, _decls(body)))
    return _Rules(rules)


class _Rules(list):
    """Stylesheet rules indexed by the last compound of each selector (its #id, else a .class, else the
    tag), so an element only tries rules that could match it, plus a cache of computed styles per
    element. Big news pages have thousands of rules and text nodes; without this, every rule was matched
    against every ancestor of every text node (over a minute per page). Lives for one analyze_html call."""

    def __init__(self, rules):
        super().__init__(rules)
        self.by_id, self.by_class, self.by_tag, self.rest, self.styles = {}, {}, {}, [], {}
        self.needs, self.anc = {}, {}   # tokens a rule needs among an element's ancestors; tokens of those ancestors
        for i, (sel, _) in enumerate(self):
            if _browser_only(sel):
                continue   # _matches never matches these
            comps = [p for p in re.sub(r"\s*>\s*", " > ", sel).split() if p != ">"]
            self.needs[i] = set().union(*[_tokens_of(c) for c in comps[:-1]]) if len(comps) > 1 else set()
            m = _COMPOUND.match(comps[-1])
            if not m:
                continue
            simple = re.sub(r"\[[^\]]*\]", "", m.group(2) or "")
            ids, classes = re.findall(r"#([\w-]+)", simple), re.findall(r"\.([\w-]+)", simple)
            tag = (m.group(1) or "").lower()
            if ids:
                self.by_id.setdefault(ids[0], []).append(i)
            elif classes:
                self.by_class.setdefault(classes[0], []).append(i)
            elif tag and tag != "*":
                self.by_tag.setdefault(tag, []).append(i)
            else:
                self.rest.append(i)

    def candidates(self, el: Tag) -> list[int]:
        idx = self.rest + self.by_tag.get(el.name, []) + self.by_id.get(el.get("id"), [])
        for c in el.get("class") or []:
            idx = idx + self.by_class.get(c, [])
        idx = sorted(set(idx))   # keep source order: later rules win
        if any(self.needs.get(i) for i in idx):   # ".menu p": skip unless some ancestor has class "menu"
            have = self.ancestors(el)
            idx = [i for i in idx if self.needs.get(i, set()) <= have]
        return idx

    def ancestors(self, el: Tag) -> frozenset:
        """Tag names, .classes and #ids of all of el's ancestors (cached per element)."""
        chain = []
        node = el.parent
        while isinstance(node, Tag) and node.name != "[document]" and id(node) not in self.anc:
            chain.append(node)
            node = node.parent
        have = self.anc.get(id(node), frozenset()) if isinstance(node, Tag) else frozenset()
        for node in reversed(chain):
            have = have | _own_tokens(node)
            self.anc[id(node)] = have
        return have


def _tokens_of(comp: str) -> set:   # what an element must have to match one compound selector
    m = _COMPOUND.match(comp)
    if not m:
        return set()
    simple = re.sub(r"\[[^\]]*\]", "", m.group(2) or "")
    tag = (m.group(1) or "").lower()
    return ({tag} if tag and tag != "*" else set()) | {k + n for k, n in re.findall(r"([.#])([\w-]+)", simple)}


def _own_tokens(el: Tag) -> frozenset:
    return frozenset([el.name] + ["." + c for c in el.get("class") or []] + (["#" + el["id"]] if el.get("id") else []))


_COMPOUND = re.compile(r"^(\*|[a-z][\w-]*)?((?:[.#][\w-]+|\[[^\]]+\])*)$", re.I)
_ATTR = re.compile(r"\[\s*([\w-]+)\s*(?:([~^$*|]?=)\s*['\"]?([^'\"\]]*)['\"]?\s*)?\]")


def _compound_matches(el: Tag, comp: str) -> bool:
    m = _COMPOUND.match(comp)
    if not m:
        return False
    tag, rest = m.group(1), m.group(2) or ""
    if tag and tag != "*" and el.name != tag.lower():
        return False
    classes = el.get("class") or []
    for kind, name in re.findall(r"([.#])([\w-]+)", re.sub(r"\[[^\]]*\]", "", rest)):
        if kind == "." and name not in classes:
            return False
        if kind == "#" and el.get("id") != name:
            return False
    for name, op, val in _ATTR.findall(rest):
        if not el.has_attr(name):
            return False
        have = el.get(name)
        have = " ".join(have) if isinstance(have, list) else str(have)
        if op == "=" and have != val:
            return False
        if op == "~=" and val not in have.split():
            return False
        if op == "^=" and not have.startswith(val):
            return False
        if op == "$=" and not have.endswith(val):
            return False
        if op == "*=" and val not in have:
            return False
        if op == "|=" and not (have == val or have.startswith(val + "-")):
            return False
    return True


def _browser_only(sel: str) -> bool:   # pseudo-classes and sibling combinators need a browser
    return ":" in sel.replace("::", ":") or "+" in sel or "~" in re.sub(r"\[[^\]]*\]", "", sel)


def _matches(el: Tag, sel: str) -> bool:
    if _browser_only(sel):
        return False
    parts = re.sub(r"\s*>\s*", " > ", sel).split()
    comps = [p for p in parts if p != ">"]
    if not comps or not _compound_matches(el, comps[-1]):
        return False
    # walk up for the rest ('>' is treated like a space: a little generous, never misses)
    node = el.parent
    for comp in reversed(comps[:-1]):
        while isinstance(node, Tag) and node.name != "[document]" and not _compound_matches(node, comp):
            node = node.parent
        if not isinstance(node, Tag) or node.name == "[document]":
            return False
        node = node.parent
    return True


def computed(el: Tag, rules) -> dict:
    indexed = isinstance(rules, _Rules)
    if indexed and id(el) in rules.styles:
        return rules.styles[id(el)]
    style = {}
    for sel, d in ([rules[i] for i in rules.candidates(el)] if indexed else rules):
        if _matches(el, sel):
            style.update(d)
    style.update(_decls(el.get("style", "")))
    if el.get("bgcolor"):
        style.setdefault("background-color", el["bgcolor"])
    if el.name == "font" and el.get("color"):
        style.setdefault("color", el["color"])
    if indexed:
        rules.styles[id(el)] = style
    return style


def _px(v: str | None):
    if not v:
        return None
    m = re.match(r"(-?\d*\.?\d+)\s*(px|pt|em|rem|%|vw|vh)?", v)
    if not m:
        return None
    n, unit = float(m.group(1)), m.group(2) or "px"
    return {"px": n, "pt": n * 1.333, "em": n * 16, "rem": n * 16, "%": n * 0.16, "vw": n * 12, "vh": n * 8}[unit]


# Analysis: hidden text ---------------------------------------------------------------------

_SCALE = re.compile(r"scale[xy3d]*\(\s*(-?\d*\.?\d+)")


def _scaled_away(tr: str) -> bool:
    return any(abs(float(n)) <= 0.05 for n in _SCALE.findall(tr))


def _opacity(v: str | None):
    m = re.match(r"\s*(\d*\.?\d+)\s*(%)?", v or "")
    if not m:
        return None
    return float(m.group(1)) / (100 if m.group(2) else 1)
_TRANSLATE_FAR = re.compile(r"translate[xy3d]*\(\s*(-\d{3,}(?:\.\d+)?)px")


def _visibility_reasons(node: NavigableString, rules) -> list[str]:
    reasons = []
    color_raw, bg, size = None, None, None
    for el in [p for p in node.parents if isinstance(p, Tag)]:
        if el.name == "[document]":
            continue
        s = computed(el, rules)
        if el.name == "template":
            reasons.append("inside <template> (never shown)")
        if el.has_attr("hidden"):
            reasons.append(f"<{el.name} hidden>")
        if s.get("display") == "none":
            reasons.append(f"display:none on <{el.name}>")
        if s.get("visibility") in ("hidden", "collapse"):
            reasons.append(f"visibility:hidden on <{el.name}>")
        if s.get("mso-hide") == "all":
            reasons.append("mso-hide:all")
        op = _opacity(s.get("opacity"))
        if op is not None and op <= 0.05:
            reasons.append(f"opacity:{s['opacity']}")
        clipped = s.get("overflow") in ("hidden", "clip") or s.get("overflow-x") in ("hidden", "clip") \
            or s.get("overflow-y") in ("hidden", "clip")
        for k in ("max-height", "height", "width", "max-width"):
            v = _px(s.get(k))
            if v is not None and v <= 1 and clipped:
                reasons.append(f"{k}:0 + overflow:hidden")
        for k in ("left", "top", "right", "bottom", "text-indent", "margin-left", "margin-top"):
            v = _px(s.get(k))
            if v is not None and v <= -500:
                reasons.append(f"{k}:{s.get(k)} (off-screen)")
        tr = s.get("transform", "")
        if tr and _scaled_away(tr):
            reasons.append("transform:scale(0)")
        mt = _TRANSLATE_FAR.search(tr)
        if mt and float(mt.group(1)) <= -500:
            reasons.append("moved off-screen with transform")
        clip = s.get("clip", "")
        if clip and re.search(r"rect\(\s*[01](?:px)?[\s,]+[01](?:px)?[\s,]+[01](?:px)?[\s,]+[01](?:px)?\s*\)", clip):
            reasons.append("clip:rect(0...)")
        cp = s.get("clip-path", "")
        if cp and (re.search(r"inset\(\s*(50|100)%", cp) or re.search(r"circle\(\s*0", cp)):
            reasons.append("clip-path hides it")
        if s.get("-webkit-text-fill-color") == "transparent":
            reasons.append("transparent text")
        if color_raw is None and s.get("color") and parse_rgba(s.get("color")):
            color_raw = s.get("color")
        if bg is None:
            bg = _bg_color(s)
        if size is None and _px(s.get("font-size")) is not None:
            size = _px(s.get("font-size"))
    p = parse_rgba(color_raw) if color_raw else None
    if p and p[1] <= 0.05:
        reasons.append("transparent text")
    else:
        color = p[0] if p else (0, 0, 0)
        bg = bg or (255, 255, 255)
        if contrast(color, bg) < 1.5:
            reasons.append(f"text color ~ background (contrast {contrast(color, bg):.2f}:1)")
    if size is not None and size < 4:
        reasons.append(f"font-size {size:.1f}px")
    return list(dict.fromkeys(reasons))


# Analysis: markup text ---------------------------------------------------------------------

ATTR_LABELS = {"alt": "alt text", "title": "title attribute", "aria-label": "aria-label",
               "aria-description": "aria-description", "aria-placeholder": "placeholder",
               "placeholder": "placeholder", "summary": "summary attribute"}
META_SKIP = {"viewport", "robots", "googlebot", "theme-color", "generator", "referrer", "format-detection",
             "color-scheme", "msapplication-tilecolor", "apple-mobile-web-app-capable", "csrf-token",
             "csrf-param", "google-site-verification", "og:image", "og:url", "og:type", "twitter:card",
             "twitter:image", "og:locale"}
JSONLD_SKIP_KEYS = {"@context", "@type", "@id", "url", "image", "logo", "sameas", "contenturl", "thumbnailurl",
                    "embedurl", "telephone", "email", "pricecurrency", "datepublished", "datemodified"}
_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")
_DOMAIN = re.compile(r"\b((?:[a-z0-9-]+\.)+(?:com|net|org|io|co|gov|edu|info|biz|app|dev|xyz|us|uk|ca|de|fr|ai|me|tv))\b")


def _sentence_like(t: str, min_words: int = 5) -> bool:
    """Prose, not an ID, class list, URL or JSON blob."""
    t = (t or "").strip()
    if not t or t[0] in "{[<" or len(t) > 8000 or re.fullmatch(r"\S+", t) and "://" in t:
        return False
    words = t.split()
    n = max(len(words), len(_CJK.findall(t)) // 2)
    if n < min_words:
        return False
    lettered = sum(bool(re.search(r"[^\W\d_]", w)) for w in words)
    return lettered / max(1, len(words)) >= 0.6


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip().lower()


def _base(host: str) -> str:
    parts = host.lower().strip(".").split(".")
    if parts and parts[0] == "www":
        parts = parts[1:]
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "ac", "gov", "edu") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _jsonld_strings(obj, key=""):
    if isinstance(obj, str):
        if key.lower() not in JSONLD_SKIP_KEYS:
            yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _jsonld_strings(v, str(k))
    elif isinstance(obj, list):
        for v in obj:
            yield from _jsonld_strings(v, key)


# Lookalike links: only when the visible link text is itself an address ("paypal.com", "https://x.com/y").
REDIRECTORS = {"t.co", "l.facebook.com", "lm.facebook.com", "lnkd.in", "out.reddit.com", "web.archive.org",
               "archive.org", "googleads.g.doubleclick.net", "paid.outbrain.com"}
_IMAGE_EXT = re.compile(r"\.(jpe?g|png|gif|webp|svg|avif)$", re.I)


def _redirector(host: str, path: str) -> bool:   # short links and redirect services show one site, go via another
    h = host.lower().removeprefix("www.")
    return h in REDIRECTORS or (_base(h) == "google.com" and path.startswith("/url"))


def _image_host(host: str, path: str) -> bool:
    h = host.lower()
    return bool(_IMAGE_EXT.search(path)) or h.split(".")[0] in ("img", "images", "image", "i", "pbs", "media", "cdn", "static") \
        or h.endswith((".cloudfront.net", ".akamaized.net", ".twimg.com", ".fbcdn.net", ".googleusercontent.com",
                       ".wp.com", "imgur.com", ".cdninstagram.com"))


def _shown_domain(a: Tag) -> str | None:
    """The domain a link visibly claims, if its text is just an address: at most 4 words and mostly the domain.
    Text inside <noscript>/<script>/<style> doesn't count (images carry no text, so they never claim one)."""
    text = " ".join(s.strip() for s in a.find_all(string=True)
                    if not isinstance(s, Comment) and not s.find_parent(("noscript", "script", "style"))).strip()
    if not text or len(text.split()) > 4:
        return None
    m = _DOMAIN.search(text.lower())
    if not m:
        return None
    core = re.sub(r"^https?://|/.*$", "", text.lower().strip(" <>()[]\"'"))
    return m.group(1) if len(m.group(1)) >= 0.6 * max(1, len(core)) and m.group(1) in core else None


def _markup_spans(soup, visible: str, limit: int = 80) -> list[HiddenSpan]:
    seen_visible = _norm(visible)
    out, seen = [], set()

    def add(text, reason):
        text = text.strip()
        k = _norm(text)
        if not k or k in seen or (len(k) >= 12 and k in seen_visible):
            return     # repeats what's already on screen (e.g. title = link text)
        seen.add(k)
        sc, hits = instruction_score(text)
        out.append(HiddenSpan(text, [f"{MARKUP} {reason}"], sc, hits))

    for el in soup.find_all(True):
        if el.name in ("style", "head") or (el.name == "script" and "ld+json" not in (el.get("type") or "")):
            continue
        if el.name == "script":
            raw = el.string or el.get_text() or ""
            try:
                strings = list(_jsonld_strings(json.loads(raw)))
            except (ValueError, RecursionError):
                strings = re.findall(r'"((?:[^"\\]|\\.){20,})"', raw)
            for s in strings:
                if _sentence_like(s):
                    add(s, "structured data (JSON-LD)")
            continue
        for attr, label in ATTR_LABELS.items():
            v = el.get(attr)
            if isinstance(v, str) and _sentence_like(v):
                add(v, f"{label} on <{el.name}>")
        for k, v in el.attrs.items():
            if k.startswith("data-") and isinstance(v, str) and _sentence_like(v):
                add(v, f"data attribute {k} on <{el.name}>")
        if el.name == "input" and (el.get("type") or "").lower() == "hidden":
            v = el.get("value")
            if isinstance(v, str) and _sentence_like(v, 4):
                add(v, "hidden form field" + (f" '{el.get('name')}'" if el.get("name") else ""))
        if el.name == "meta" and el.get("content"):
            name = (el.get("name") or el.get("property") or el.get("itemprop") or el.get("http-equiv") or "").lower()
            if name and name not in META_SKIP and _sentence_like(el["content"]):
                add(el["content"], f"meta tag {name}")
        if el.name == "a" and el.get("href"):
            href = el["href"].strip()
            shown = _shown_domain(el)
            u = urlparse(href) if href.lower().startswith(("http://", "https://")) else None
            host = u.hostname if u else None
            if host and shown and _base(shown) != _base(host) and not _redirector(host, u.path) \
                    and not _image_host(host, u.path) and not _image_host(shown, ""):
                add(href, f"link text shows {shown} but goes to {host}")
        if len(out) >= limit:
            break
    return out


def _skip_comment(c: str) -> bool:
    """Not a message: conditional comments (IE's and Outlook's <!--[if mso]> in nearly every newsletter)
    and commented-out code (tags, or under 40% letters)."""
    t = c.strip()
    if t.startswith("[if ") or "<![endif]" in t:
        return True
    if re.search(r"<(script|link|meta|style|div)\b", t, re.I):
        return True
    chars = re.sub(r"\s", "", t)
    return bool(chars) and sum(ch.isalpha() for ch in chars) / len(chars) < 0.4


def analyze_html(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    rules = _stylesheet_rules(soup)
    spans: list[HiddenSpan] = []
    visible_parts: list[str] = []

    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        if c.strip() and not _skip_comment(c):
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
    visible = " ".join(visible_parts)
    spans += _markup_spans(soup, visible)
    return {"visible_text": visible, "hidden": spans,
            "attack": any(s.is_attack for s in spans)}
