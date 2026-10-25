// Scans the page you're looking at (including an open Gmail message) for
// text that AI assistants will read but you can't see, and shows a panel
// when something is aimed at AI.

(() => {
  const D = window.ParallaxDetect;
  let styleCache = new WeakMap();   // rebuilt every scan so Gmail updates aren't missed
  const env = {
    style: el => { let s = styleCache.get(el); if (!s) { s = getComputedStyle(el); styleCache.set(el, s); } return s; },
    rect: el => el.getBoundingClientRect(),
    get viewport() { return { width: innerWidth, height: innerHeight }; },
    get page() { return { width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight }; },
    topAt: (x, y) => document.elementFromPoint(x, y),
  };

  // Offline fallback if the Parallax server isn't running.
  const LOCAL = /(ignore|disregard)\s+(all\s+|any\s+)?(previous|prior|above)\s+instructions|note\s+(to|for)\s+(the\s+)?(ai|assistant|screeners?|reviewers?|agents?)|\b(assistant|ai agent)\s*:|you are an ai|from now on/i;
  const FACT = /[\w.+-]+@[\w-]+(\.[\w-]+)+|https?:\/\/\S+|\$\s?[\d,]+(\.\d\d)?/g;
  function localJudge(spans, visible, ml) {
    return spans.map((s, i) => {
      const m = ml && ml[i];
      const newFacts = (s.text.match(FACT) || []).filter(f => !visible.includes(f));
      const why = [];
      if (LOCAL.test(s.text)) why.push("talks to an AI (offline check)");
      if (m && m.level === "sure") why.push(`talks to an AI (parallax-ml ${m.score.toFixed(2)})`);
      if (newFacts.length) why.push("adds hidden " + newFacts.slice(0, 3).join(", "));
      if (s.reasons.includes("Unicode tag payload")) why.push("text smuggled in invisible Unicode");
      if (!why.length && m && m.level === "maybe") {
        return { text: s.text, where: s.reasons, level: "caution", why: [`might be instructing an AI (parallax-ml ${m.score.toFixed(2)})`] };
      }
      return { text: s.text, where: s.reasons, level: why.length ? "threat" : "info", why };
    });
  }

  let lastSpans = [];
  let dismissedKey = null;   // findings the user dismissed; don't show them again
  const keyOf = (threats, cautions) => threats.concat(cautions).map(f => f.text).join("\n");

  async function scan() {
    styleCache = new WeakMap();
    const { hidden, visible } = D.scanDocument(document, env);
    // Collapse duplicates and keep the request small.
    const seen = new Set();
    lastSpans = hidden.filter(h => { const k = h.text.slice(0, 200); if (seen.has(k)) return false; seen.add(k); return true; }).slice(0, 200);
    const payload = { spans: lastSpans.map(h => ({ text: h.text.slice(0, 2000), reasons: h.reasons })),
                      visible: visible.slice(0, 20000), context: "web" };
    let findings;
    try {
      const res = await chrome.runtime.sendMessage({ type: "classify", payload });
      findings = res && res.findings ? res.findings : localJudge(payload.spans, payload.visible, res && res.ml);
    } catch (e) {
      findings = localJudge(payload.spans, payload.visible);
    }
    findings.forEach((f, i) => { f.el = lastSpans[i] && lastSpans[i].el; });
    const threats = findings.filter(f => f.level === "threat");
    const cautions = findings.filter(f => f.level === "caution");
    chrome.runtime.sendMessage({ type: "verdict", verdict: threats.length ? "threat" : cautions.length ? "caution" : "clean",
                                 count: threats.length, hidden: findings.length,
                                 items: threats.concat(cautions).map(f => ({ text: f.text.slice(0, 300), why: f.why, where: f.where })) });
    if (keyOf(threats, cautions) === dismissedKey) return;
    render(threats, cautions);
  }

  function render(threats, cautions) {
    let panel = document.getElementById("parallax-panel");
    if (!threats.length && !cautions.length) { panel && panel.remove(); return; }
    if (!panel) { panel = document.createElement("div"); panel.id = "parallax-panel"; document.documentElement.appendChild(panel); }
    const items = threats.concat(cautions).slice(0, 6);
    panel.innerHTML = "";
    const h = document.createElement("div");
    h.className = "px-head " + (threats.length ? "px-threat" : "px-caution");
    h.textContent = threats.length
      ? `Parallax: ${threats.length} hidden instruction${threats.length > 1 ? "s" : ""} aimed at AI`
      : "Parallax: text on this page is hidden from you";
    panel.appendChild(h);
    const sub = document.createElement("div");
    sub.className = "px-sub";
    sub.textContent = "An AI assistant reading this page would see this. You can't.";
    panel.appendChild(sub);
    for (const f of items) {
      const it = document.createElement("div"); it.className = "px-item";
      const t = document.createElement("div"); t.className = "px-text"; t.textContent = f.text.slice(0, 220);
      const w = document.createElement("div"); w.className = "px-why"; w.textContent = (f.why || []).join("; ") + " · " + (f.where || []).join(", ");
      it.append(t, w); panel.appendChild(it);
    }
    const btns = document.createElement("div"); btns.className = "px-btns";
    const reveal = document.createElement("button"); reveal.textContent = "Reveal on page";
    reveal.onclick = () => { for (const f of items) if (f.el) f.el.classList.toggle("parallax-reveal"); };
    const close = document.createElement("button"); close.textContent = "Dismiss";
    close.onclick = () => { dismissedKey = keyOf(threats, cautions); panel.remove(); };
    btns.append(reveal, close); panel.appendChild(btns);
  }

  // Results from a right-click file scan are shown in the same panel.
  chrome.runtime.onMessage.addListener(msg => {
    if (msg.type === "fileResult") {
      const r = msg.report;
      const f = (r.findings || []).filter(x => x.level !== "info");
      if (!f.length) { alert(`Parallax: ${r.headline}`); return; }
      render(f.filter(x => x.level === "threat"), f.filter(x => x.level === "caution"));
      document.querySelector("#parallax-panel .px-head").textContent = "Parallax: " + r.headline;
    }
  });

  let timer = null;
  const rescan = () => { clearTimeout(timer); timer = setTimeout(scan, 1200); };
  // Ignore changes we made ourselves (adding, editing or removing the panel).
  const inPanel = n => n.nodeType === 1 && !!n.closest("#parallax-panel");
  const isOurs = m => {
    const t = m.target.nodeType === 1 ? m.target : m.target.parentElement;
    if (t && inPanel(t)) return true;
    const nodes = [...m.addedNodes, ...m.removedNodes];
    return nodes.length > 0 && nodes.every(inPanel);
  };
  new MutationObserver(muts => {
    if (muts.some(m => !isOurs(m))) rescan();
  }).observe(document.documentElement, { childList: true, subtree: true, characterData: true });
  scan();
})();
