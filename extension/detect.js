// Visibility checks for text nodes, using the browser's computed styles and
// layout. The functions take an `env` object so they can be tested in Node
// (jsdom has styles but no layout, so the tests pass fake rectangles).
//
// A text node is hidden if any of these hold:
//   display:none / visibility:hidden / opacity ~0 on it or an ancestor
//   font-size < 4px, or text colour ~ the background actually behind it
//   clipped to nothing, zero-sized box with overflow hidden, off-screen
//   covered by another element (checked only when on screen)
// plus: invisible Unicode, and HTML comments (agents reading raw HTML see them).

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

  // env: { style(el) -> CSSStyleDeclaration-like, rect(el) -> {left,top,width,height},
  //        viewport: {width,height}, page: {width,height}, topAt(x,y) -> element|null }
  function assess(textNode, env) {
    const reasons = [];
    const el = textNode.parentElement;
    if (!el) return reasons;
    let opacity = 1;
    for (let a = el; a && a.nodeType === 1; a = a.parentElement) {
      const s = env.style(a);
      if (s.display === "none") { reasons.push(`display:none on <${a.tagName.toLowerCase()}>`); break; }
      if (s.visibility === "hidden" || s.visibility === "collapse") { reasons.push("visibility:hidden"); break; }
      opacity *= parseFloat(s.opacity || "1");
      const clip = s.clipPath || s.clip || "";
      if (/inset\(\s*(50%|100%)/.test(clip) || /rect\(\s*0(px)?[ ,]+0(px)?[ ,]+0(px)?[ ,]+0/.test(clip)) reasons.push("clipped to nothing");
      if (s.overflow === "hidden" && (parseFloat(s.height) <= 1 || parseFloat(s.width) <= 1) && s.display !== "inline") reasons.push("inside a zero-size box");
    }
    if (reasons.length) return reasons;
    if (opacity <= 0.05) reasons.push(`opacity ${opacity.toFixed(2)}`);
    const s = env.style(el);
    const size = parseFloat(s.fontSize);
    if (/px$/.test(s.fontSize) && size < 4) reasons.push(`font-size ${size}px`);  // Chrome always reports px
    const color = parseRGB(s.color) || [0, 0, 0];
    let bg = null;
    for (let a = el; a && a.nodeType === 1 && !bg; a = a.parentElement) bg = parseRGB(env.style(a).backgroundColor);
    bg = bg || [255, 255, 255];
    const c = contrast(color, bg);
    if (c < 1.5) reasons.push(`text color ~ background (${c.toFixed(2)}:1)`);
    const r = env.rect(el);
    if (r && (r.left + r.width < 0 || r.top + r.height < 0 || r.left > env.page.width + 50)) reasons.push("positioned off-screen");
    if (r && env.topAt && r.width > 0 && r.height > 0 &&
        r.left >= 0 && r.top >= 0 && r.left + r.width <= env.viewport.width && r.top + r.height <= env.viewport.height) {
      const top = env.topAt(r.left + r.width / 2, r.top + r.height / 2);
      if (top && top !== el && !el.contains(top) && !top.contains(el)) reasons.push("covered by another element");
    }
    return reasons;
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
      if (reasons.length) hidden.push({ text: tags ? text + " " + tags : text, reasons, el: p });
      else visible.push(text);
    }
    const cw = doc.createTreeWalker(doc.body, 128 /* SHOW_COMMENT */);
    for (let n = cw.nextNode(); n; n = cw.nextNode()) {
      const t = n.nodeValue.trim();
      if (t.length > 20) hidden.push({ text: t, reasons: ["HTML comment"], el: null });
    }
    return { hidden, visible: visible.join(" ") };
  }

  const api = { assess, scanDocument, contrast, parseRGB, tagPayload };
  if (typeof module !== "undefined") module.exports = api; else root.ParallaxDetect = api;
})(this);
