// Our trained classifier, running inside the extension (no server needed).
// Mirrors parallax/ml_features.py + MLDetector in detect.py; keep them in sync.
// The model files in models/ are written by ml/train_fast.py and ml/train_fast_v2.py.

(function (root) {
  const EMAIL = /[\p{L}\p{N}_.+-]+\s?@\s?[\p{L}\p{N}_-]+(\s?\.\s?[\p{L}\p{N}_-]+)+/gu;
  const URL_RE = /(https?\s?:\s?\/\s?\/\s?[\p{L}\p{N}_-]+(\s?[.\/]\s?[\p{L}\p{N}_-]+)*\S*|www(\s?\.\s?[\p{L}\p{N}_-]+)+\S*|(?<![\p{L}\p{N}_])[\p{L}\p{N}_-]+(\s?\.\s?[\p{L}\p{N}_-]+)*\s?\.\s?(com|net|org|io|dev|co|info|biz|app|xyz)(?![\p{L}\p{N}_])\S*)/gu;
  const EMAILWORD = /(?<![\p{L}\p{N}_])e\s?-\s?mail/gu;
  const NUM = /\p{Nd}+/gu;
  const NONWORD = /[^a-z|\[\]{}*_ ]+/g;
  const LINK_BITS = new Set(["com", "net", "org", "www", "http", "https", "html", "htm"]);

  function normalize(text) {
    let t = text.toLowerCase().replace(EMAILWORD, "email");
    t = t.replace(EMAIL, " zemail ").replace(URL_RE, " zlink ").replace(NUM, " znum ").replace(NONWORD, " ");
    return t.split(/\s+/).filter(w => w.length > 1 && /[a-z]/.test(w) && !LINK_BITS.has(w)).join(" ");
  }

  // v2 normalizer: mirrors normalize_v2 in parallax/ml_features.py.
  const SPACED_URL = /(?<![\p{L}\p{N}_])(?:https?\s*:\s*\/\s*\/\s*|www\s*\.\s*)[\p{L}\p{N}_-]+(?:\s*[./]\s*[\p{L}\p{N}_-]+)*/gu;
  const NONWORD_V2 = /[^a-z ]+/g;
  const LEFTOVER = /(?<![\p{L}\p{N}_])(?:https?|www)(?![\p{L}\p{N}_])/gu;

  function normalizeV2(text) {
    let t = text.toLowerCase();
    t = t.replace(SPACED_URL, " zlink ").replace(EMAIL, " zemail ").replace(URL_RE, " zlink ").replace(NUM, " znum ");
    t = t.replace(NONWORD_V2, " ").replace(LEFTOVER, " ");
    return t.replace(/\s+/g, " ").trim();
  }

  function normalizerFor(model) {
    return model && model.normalizer === "v2" ? normalizeV2 : normalize;
  }

  function analyzer(text, norm) {
    const words = (norm || normalize)(text).split(" ").slice(0, 400);
    const feats = words.filter(Boolean);
    for (let i = 0; i + 1 < words.length; i++) feats.push(words[i] + " " + words[i + 1]);
    for (const w of words) {
      if (w.length >= 4 && w.length <= 30) {
        const p = "_" + w + "_";
        for (let i = 0; i + 4 <= p.length; i++) feats.push("#" + p.slice(i, i + 4));
      }
    }
    return feats;
  }

  function score(model, text) {
    const F = model.features, counts = new Map();
    for (const f of analyzer(text, normalizerFor(model))) if (Object.prototype.hasOwnProperty.call(F, f)) counts.set(f, (counts.get(f) || 0) + 1);
    let norm = 0;
    const vals = [];
    for (const [f, n] of counts) { const v = (1 + Math.log(n)) * F[f][0]; vals.push([f, v]); norm += v * v; }
    norm = Math.sqrt(norm) || 1;
    let z = model.bias;
    for (const [f, v] of vals) z += (v / norm) * F[f][1];
    z = Math.max(-30, Math.min(30, z));
    return 1 / (1 + Math.exp(-z));
  }

  const SURE = 0.85, MAYBE = 0.5, MIN_WORDS = 5;
  function judge(model, text) {
    if (text.trim().split(/\s+/).length < MIN_WORDS) return { score: null, level: "none" };
    const s = score(model, text);
    return { score: s, level: s >= SURE ? "sure" : s >= MAYBE ? "maybe" : "none" };
  }

  const api = { normalize, normalizeV2, normalizerFor, analyzer, score, judge, SURE, MAYBE, MIN_WORDS };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.ParallaxML = api;
})(typeof self !== "undefined" ? self : globalThis);
