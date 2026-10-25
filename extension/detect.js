// Visibility checks for text nodes, using the browser's computed styles and
// layout. The functions take an `env` object so they can be tested in Node
// (jsdom has styles but no layout, so the tests pass fake rectangles).
//
// A text node is hidden if any of these hold:
//   display:none / visibility:hidden / opacity ~0 on it or an ancestor
//   font-size < 4px, or text colour ~ the background actually behind it
//   clipped to nothing, zero-sized box with overflow hidden, off-screen
//   covered by another element (checked only when on screen)
// plus: invisible Unicode, HTML comments (agents reading raw HTML see them), and markup text
// (alt/title/aria/data-* attributes, hidden fields, meta tags, JSON-LD, lookalike links; see markupSpans).

(function (root) {
  // Same ranges as _INVISIBLE_RANGES in parallax/gap/text.py (the last part is the Unicode "tag" block)
  const INVISIBLE = /[\u200B-\u200F\u202A-\u202E\u2060-\u2064\u2066-\u2069\uFEFF]|\uDB40[\uDC00-\uDC7F]/g;

  function parseRGB(s) {
    const m = /rgba?\(([^)]+)\)/.exec(s || "");
    if (!m) return null;
    const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number);
    if (p.length === 4 && p[3] === 0) return null; // transparent
    return p.slice(0, 3);
  }
  // Any CSS color -> [r, g, b, a] (0-255, alpha 0-1), or null if it can't be read.
  // Modern sites (e.g. Tailwind v4) use oklch()/lab()/color() colors, which parseRGB can't read;
  // the browser converts them by painting one pixel on an offscreen canvas.
  let ctx = null;
  const colorCache = new Map();
  function toRGBA(s) {
    if (!s) return null;
    const m = /^rgba?\(([^)]+)\)$/.exec(s.trim());
    if (m) {
      const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(v => v.endsWith("%") ? parseFloat(v) / 100 : Number(v));
      return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
    }
    if (s === "transparent") return [0, 0, 0, 0];
    if (colorCache.has(s)) return colorCache.get(s);
    let out = null;
    try {
      if (!ctx && typeof OffscreenCanvas !== "undefined") ctx = new OffscreenCanvas(1, 1).getContext("2d", { willReadFrequently: true });
      if (ctx) {
        ctx.fillStyle = "#010203";
        ctx.fillStyle = s;                                   // ignored by the browser if s isn't a valid color
        if (ctx.fillStyle !== "#010203" || /^#010203$/i.test(s)) {
          ctx.clearRect(0, 0, 1, 1);
          ctx.fillRect(0, 0, 1, 1);
          const d = ctx.getImageData(0, 0, 1, 1).data;
          out = [d[0], d[1], d[2], d[3] / 255];
        }
      }
    } catch (e) { out = null; }
    colorCache.set(s, out);
    return out;
  }

  function lum(c) {
    const f = x => { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
  }
  function contrast(a, b) {
    const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
    return (x + 0.05) / (y + 0.05);
  }
  function tagPayload(text) {
    let out = "";
    for (const ch of text) {
      const cp = ch.codePointAt(0);
      if (cp >= 0xE0020 && cp <= 0xE007E) out += String.fromCharCode(cp - 0xE0000);
    }
    return out;
  }

  // A real cover is opaque and stays put. Transparent overlays (e.g. a link stretched over a
  // card to make it clickable) and sticky/fixed headers you can scroll past don't hide anything.
  function coversForReal(top, env) {
    for (let a = top; a && a.nodeType === 1; a = a.parentElement) {
      const p = env.style(a).position;
      if (p === "fixed" || p === "sticky") return false;
    }
    const bg = toRGBA(env.style(top).backgroundColor);
    const opaque = (bg && bg[3] > 0.5) || /^(IMG|VIDEO|CANVAS|SVG|PICTURE)$/i.test(top.tagName);
    return opaque;
  }

  // Hidden text inside menus, dialogs, tabs, accordions and tooltips is UI the user can open.
  const UI_HIDDEN = "nav, header, footer, details, dialog, [role=menu], [role=menubar], [role=dialog], [role=tabpanel], " +
    "[role=tooltip], [role=listbox], [aria-modal=true], .modal, .dropdown, .menu, .tooltip, .tab-pane, .accordion, .collapse";
  function isCollapsibleUI(el) {
    if (el.closest(UI_HIDDEN) || el.closest("[hidden]")) return true;
    for (let a = el; a && a.nodeType === 1; a = a.parentElement) {
      const prev = a.previousElementSibling;
      if (prev && prev.hasAttribute && prev.hasAttribute("aria-expanded")) return true;
      if (a.id && a.ownerDocument.querySelector(`[aria-controls~="${CSS.escape ? CSS.escape(a.id) : a.id}"]`)) return true;
    }
    return false;
  }

  // env: { style(el) -> CSSStyleDeclaration-like, rect(el) -> {left,top,width,height},
  //        viewport: {width,height}, page: {width,height}, topAt(x,y) -> element|null }
  function assess(textNode, env) {
    const reasons = [];
    const el = textNode.parentElement;
    if (!el) return reasons;
    let opacity = 1, animated = false;
    for (let a = el; a && a.nodeType === 1; a = a.parentElement) {
      const s = env.style(a);
      if (parseFloat(s.opacity || "1") < 1 &&
          ((s.transitionDuration && /[1-9]/.test(s.transitionDuration) && /opacity|all/.test(s.transitionProperty || "all")) ||
           (s.animationName && s.animationName !== "none"))) animated = true;
      if (s.display === "none") { reasons.push(`display:none on <${a.tagName.toLowerCase()}>`); break; }
      if (s.visibility === "hidden" || s.visibility === "collapse") { reasons.push("visibility:hidden"); break; }
      opacity *= parseFloat(s.opacity || "1");
      const clip = s.clipPath || s.clip || "";
      if (/inset\(\s*(50%|100%)/.test(clip) || /circle\(\s*0(px|%)?\s*[ )]/.test(clip) ||
          /rect\(\s*[01](px)?[ ,]+[01](px)?[ ,]+[01](px)?[ ,]+[01](px)?\s*\)/.test(clip)) reasons.push("clipped to nothing");
      const mx = /matrix\(([^)]+)\)/.exec(s.transform || "");
      if (mx) {
        const v = mx[1].split(",").map(Number);
        if ((Math.abs(v[0]) <= 0.05 && Math.abs(v[1]) <= 0.05) || (Math.abs(v[2]) <= 0.05 && Math.abs(v[3]) <= 0.05)) reasons.push("transform:scale(0)");
      }
      if (s.overflow === "hidden" && (parseFloat(s.height) <= 1 || parseFloat(s.width) <= 1) && s.display !== "inline") reasons.push("inside a zero-size box");
    }
    if (reasons.length) return reasons;
    // Faded-out text that the page animates in (scroll reveals, tooltips) is normal UI, not hiding.
    if (opacity <= 0.05 && !animated) reasons.push(`opacity ${opacity.toFixed(2)}`);
    const s = env.style(el);
    const size = parseFloat(s.fontSize);
    if (/px$/.test(s.fontSize) && size < 4) reasons.push(`font-size ${size}px`);  // Chrome always reports px
    // Compare text color with the first solid background behind it. If either color can't be
    // read, skip this check rather than guess (guessing "black" flagged normal text as hidden).
    const color = toRGBA(s.color);
    let bg = null;
    for (let a = el; a && a.nodeType === 1 && !bg; a = a.parentElement) {
      const b = toRGBA(env.style(a).backgroundColor);
      if (b && b[3] > 0.5) bg = b;
    }
    if (!bg) bg = [255, 255, 255, 1];                         // page default
    const fill = s.webkitTextFillColor ? toRGBA(s.webkitTextFillColor) : null;
    if ((color && color[3] <= 0.05) || (fill && fill[3] <= 0.05)) reasons.push("transparent text");
    else if (color) {
      const c = contrast(color, bg);
      if (c < 1.5) reasons.push(`text color ~ background (${c.toFixed(2)}:1)`);
    }
    const r = env.rect(el);
    if (r && (r.left + r.width < 0 || r.top + r.height < 0 || r.left > env.page.width + 50 ||
              r.left > env.viewport.width + 5000)) reasons.push("positioned off-screen");   // right:-9999px widens the page itself
    if (r && env.topAt && r.width > 0 && r.height > 0 &&
        r.left >= 0 && r.top >= 0 && r.left + r.width <= env.viewport.width && r.top + r.height <= env.viewport.height) {
      const top = env.topAt(r.left + r.width / 2, r.top + r.height / 2);
      if (top && top !== el && !el.contains(top) && !top.contains(el) && coversForReal(top, env)) reasons.push("covered by another element");
    }
    return reasons;
  }

  // Text in the markup that AI agents reading the HTML see but the page never shows: alt/title/aria/
  // placeholder/data-* attributes, hidden form fields, meta tags, JSON-LD, and links whose text shows one
  // site but go to another. Same rules as _markup_spans in parallax/gap/html_gap.py; keep them in sync.
  const MARKUP = "markup:";
  const ATTR_LABELS = { "alt": "alt text", "title": "title attribute", "aria-label": "aria-label",
    "aria-description": "aria-description", "aria-placeholder": "placeholder", "placeholder": "placeholder",
    "summary": "summary attribute" };
  const META_SKIP = new Set(["viewport", "robots", "googlebot", "theme-color", "generator", "referrer", "format-detection",
    "color-scheme", "msapplication-tilecolor", "apple-mobile-web-app-capable", "csrf-token", "csrf-param",
    "google-site-verification", "og:image", "og:url", "og:type", "twitter:card", "twitter:image", "og:locale"]);
  const JSONLD_SKIP = new Set(["@context", "@type", "@id", "url", "image", "logo", "sameas", "contenturl", "thumbnailurl",
    "embedurl", "telephone", "email", "pricecurrency", "datepublished", "datemodified"]);
  const CJK = /[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]/g;
  const DOMAIN = /\b((?:[a-z0-9-]+\.)+(?:com|net|org|io|co|gov|edu|info|biz|app|dev|xyz|us|uk|ca|de|fr|ai|me|tv))\b/;
  const norm = t => t.replace(/\s+/g, " ").trim().toLowerCase();

  function sentenceLike(t, minWords = 5) {
    t = (t || "").trim();
    if (!t || "{[<".includes(t[0]) || t.length > 8000 || (/^\S+$/.test(t) && t.includes("://"))) return false;
    const words = t.split(/\s+/);
    const n = Math.max(words.length, Math.floor((t.match(CJK) || []).length / 2));
    if (n < minWords) return false;
    const lettered = words.filter(w => /\p{L}/u.test(w)).length;
    return lettered / Math.max(1, words.length) >= 0.6;
  }
  function baseDomain(host) {
    let p = host.toLowerCase().replace(/\.$/, "").split(".");
    if (p[0] === "www") p = p.slice(1);
    if (p.length >= 3 && ["co", "com", "org", "net", "ac", "gov", "edu"].includes(p[p.length - 2]) && p[p.length - 1].length === 2)
      return p.slice(-3).join(".");
    return p.slice(-2).join(".");
  }
  function* jsonStrings(o, key = "") {
    if (typeof o === "string") { if (!JSONLD_SKIP.has(key.toLowerCase())) yield o; }
    else if (Array.isArray(o)) { for (const v of o) yield* jsonStrings(v, key); }
    else if (o && typeof o === "object") { for (const [k, v] of Object.entries(o)) yield* jsonStrings(v, k); }
  }

  function markupSpans(doc, visible, limit = 80) {
    const seenVisible = norm(visible), seen = new Set(), out = [];
    const add = (text, reason, el) => {
      text = text.trim();
      const k = norm(text);
      if (!k || seen.has(k) || (k.length >= 12 && seenVisible.includes(k))) return;
      seen.add(k);
      out.push({ text, reasons: [`${MARKUP} ${reason}`], el });
    };
    for (const el of doc.querySelectorAll("*")) {
      if (out.length >= limit) break;
      const tag = el.tagName.toLowerCase();
      if (tag === "style" || el.closest("#parallax-panel")) continue;
      if (tag === "script") {
        if (!/ld\+json/i.test(el.getAttribute("type") || "")) continue;
        const raw = el.textContent || "";
        let strings;
        try { strings = [...jsonStrings(JSON.parse(raw))]; }
        catch (e) { strings = [...raw.matchAll(/"((?:[^"\\]|\\.){20,})"/g)].map(m => m[1]); }
        for (const t of strings) if (sentenceLike(t)) add(t, "structured data (JSON-LD)", null);
        continue;
      }
      for (const [attr, label] of Object.entries(ATTR_LABELS)) {
        const v = el.getAttribute(attr);
        if (v && sentenceLike(v)) add(v, `${label} on <${tag}>`, el);
      }
      for (const a of el.attributes) {
        if (a.name.startsWith("data-") && sentenceLike(a.value)) add(a.value, `data attribute ${a.name} on <${tag}>`, el);
      }
      if (tag === "input" && (el.getAttribute("type") || "").toLowerCase() === "hidden") {
        const v = el.getAttribute("value");
        if (v && sentenceLike(v, 4)) add(v, "hidden form field" + (el.getAttribute("name") ? ` '${el.getAttribute("name")}'` : ""), el);
      }
      if (tag === "meta" && el.getAttribute("content")) {
        const name = (el.getAttribute("name") || el.getAttribute("property") || el.getAttribute("itemprop") ||
                      el.getAttribute("http-equiv") || "").toLowerCase();
        if (name && !META_SKIP.has(name) && sentenceLike(el.getAttribute("content"))) add(el.getAttribute("content"), `meta tag ${name}`, null);
      }
      if (tag === "a" && el.getAttribute("href")) {
        const href = el.getAttribute("href").trim();
        let host = null;
        if (/^https?:\/\//i.test(href)) { try { host = new URL(href).hostname; } catch (e) { host = null; } }
        const shown = DOMAIN.exec((el.textContent || "").toLowerCase());
        if (host && shown && baseDomain(shown[1]) !== baseDomain(host)) add(href, `link text shows ${shown[1]} but goes to ${host}`, el);
      }
    }
    return out;
  }

  function scanDocument(doc, env) {
    const hidden = [], visible = [];
    const walker = doc.createTreeWalker(doc.body, 4 /* SHOW_TEXT */);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const p = n.parentElement;
      if (!p || /^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE)$/.test(p.tagName) || p.closest("#parallax-panel")) continue;
      const text = n.nodeValue.trim();
      if (!text) continue;
      const reasons = assess(n, env);
      const invis = (text.match(INVISIBLE) || []).length;
      const tags = tagPayload(text);
      if (invis >= 3) reasons.push(`${invis} invisible Unicode characters`);
      if (tags) reasons.push("Unicode tag payload");
      if (reasons.length && !tags && invis < 3 && isCollapsibleUI(p)) reasons.push("collapsed UI (menu, tab, dialog or accordion)");
      if (reasons.length) hidden.push({ text: tags ? text + " " + tags : text, reasons, el: p });
      else visible.push(text);
    }
    const cw = doc.createTreeWalker(doc.body, 128 /* SHOW_COMMENT */);
    for (let n = cw.nextNode(); n; n = cw.nextNode()) {
      const t = n.nodeValue.trim();
      if (t.length > 20) hidden.push({ text: t, reasons: ["HTML comment"], el: null });
    }
    for (const t of doc.querySelectorAll("template")) {        // never rendered, but in the HTML agents read
      const txt = (t.content ? t.content.textContent : t.textContent || "").replace(/\s+/g, " ").trim();
      if (txt.length > 20) hidden.push({ text: txt, reasons: ["inside <template> (never shown)"], el: null });
    }
    const visibleText = visible.join(" ");
    for (const m of markupSpans(doc, visibleText)) hidden.push(m);
    return { hidden, visible: visibleText };
  }

  const api = { assess, scanDocument, markupSpans, sentenceLike, contrast, parseRGB, toRGBA, tagPayload, isCollapsibleUI };
  if (typeof module !== "undefined") module.exports = api; else root.ParallaxDetect = api;
})(this);
