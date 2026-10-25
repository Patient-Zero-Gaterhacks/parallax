// Scans the page you're looking at (including an open Gmail message) for
// text that AI assistants will read but you can't see. Quiet by default: a small
// corner pill appears only when hidden text is aimed at AI; anything less serious only sets the toolbar badge.

(() => {
  const D = window.ParallaxDetect;
  let styleCache = new WeakMap();   // rebuilt every scan so Gmail updates aren't missed
  const env = {
    style: el => { let s = styleCache.get(el); if (!s) { s = getComputedStyle(el); styleCache.set(el, s); } return s; },
    rect: el => el.getBoundingClientRect(),
    get viewport() { return { width: innerWidth, height: innerHeight }; },
    get page() { return { width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight }; },
    get scroll() { return { x: scrollX, y: scrollY }; },
    topAt: (x, y) => document.elementFromPoint(x, y),
  };

  // Offline fallback if the Parallax server isn't running.
  const LOCAL = /(ignore|disregard)\s+(all\s+|any\s+)?(previous|prior|above)\s+instructions|note\s+(to|for)\s+(the\s+)?(ai|assistant|screeners?|reviewers?|agents?)|\b(assistant|ai agent)\s*:|you are an ai|from now on/i;
  // emails, full links (http(s):// or www.) and phone numbers; amounts and bare domains ("openai.com") alone aren't strong evidence
  const FACT = /[\w.+-]+@[\w-]+(\.[\w-]+)+|https?:\/\/\S+|\bwww\.[^\s<>"')]+|(?:\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b/g;
  const HOST = /(?<![\w@.-])(?:[a-z0-9-]+\.)+[a-z]{2,}(?![\w-])/g;
  // "salon.com2020" (share text that lost its "/") counts as salon.com
  // Brands phishing pages most often pretend to be (same list as parallax/scan.py): a look-alike link alone is
  // info, but visible text claiming one of these while the link goes elsewhere is a caution.
  const BRANDS = new Set(["paypal", "apple", "icloud", "google", "gmail", "microsoft", "office", "outlook", "live", "amazon",
    "netflix", "facebook", "instagram", "whatsapp", "meta", "linkedin", "twitter", "x", "chase", "wellsfargo", "bankofamerica",
    "citi", "capitalone", "americanexpress", "amex", "coinbase", "binance", "venmo", "zelle", "cashapp", "stripe", "dropbox",
    "docusign", "adobe", "fedex", "ups", "usps", "dhl", "irs", "ebay", "walmart", "steam", "discord"]);
  const siteOf = link => D.baseDomain(link.toLowerCase().replace(/^[a-z][a-z0-9+.-]*:\/\//, "").split(/[/?#:]/)[0].replace(/(?<=[a-z])\d+$/, ""));
  // Same rules as the server's web mode (parallax/scan.py _judge web=True): red only on strong evidence.
  function localJudge(spans, visible, ml) {
    // sites the page already shows (its hostname, its links, visible text): a hidden link to one isn't new
    const knownSites = new Set((visible.toLowerCase().match(HOST) || []).map(h => D.baseDomain(h)));
    const sameSite = f => /^(https?:\/\/|www\.)/i.test(f) && knownSites.has(siteOf(f));
    return spans.map((s, i) => {
      const m = ml && ml[i];
      const ui = s.reasons.some(r => r.startsWith("collapsed UI"));
      const comment = s.reasons.includes("HTML comment");
      // markup = alt/title/aria/data-* text, hidden fields, meta tags, JSON-LD: facts there alone are normal
      const markup = s.reasons.some(r => r.startsWith("markup:"));
      const newFacts = (s.text.match(FACT) || []).filter(f => !visible.includes(f) && !sameSite(f));
      const strong = [], weak = [];
      if (LOCAL.test(s.text)) strong.push("talks to an AI (offline check)");
      if (s.reasons.includes("Unicode tag payload")) strong.push("text smuggled in invisible Unicode");
      // facts inside menus/carousels, comments (script/CDN links) or markup alone stay info
      if (newFacts.length && !ui && !comment && !markup) strong.push("adds hidden " + newFacts.slice(0, 3).join(", "));
      const shown = s.reasons.map(r => /link text shows (\S+) but goes to/.exec(r)).find(Boolean);
      if (shown && BRANDS.has(D.baseDomain(shown[1]).split(".")[0])) weak.push("link text shows one site but goes to another");
      // a lookalike link alone, or the built-in model alone on markup text or a comment, stays info on web pages
      if (m && m.level === "sure" && !markup && !comment) weak.push(`might be instructing an AI (parallax-ml ${m.score.toFixed(2)})`);
      else if (m && m.level === "maybe" && !ui && !markup && !comment) weak.push(`might be instructing an AI (parallax-ml ${m.score.toFixed(2)})`);
      if (strong.length) return { text: s.text, where: s.reasons, level: "threat", why: strong.concat(weak) };
      if (weak.length) return { text: s.text, where: s.reasons, level: "caution", why: weak };
      return { text: s.text, where: s.reasons, level: "info", why: [] };
    });
  }

  let lastSpans = [];
  let dismissedKey = null;   // findings the user dismissed; don't show them again
  // sorted, so the same findings in a different order count as the same
  const keyOf = (threats, cautions) => threats.concat(cautions).map(f => f.text).sort().join("\n");

  // Per-site pause, like an ad blocker's "off on this site" switch (set from the popup).
  const isPaused = async () => {
    try { return ((await chrome.storage.local.get("paused")).paused || []).includes(location.hostname); }
    catch (e) { return false; }
  };

  // Scanning never waits on the server: every scan shows the quick offline verdict at once, then the
  // server's answer replaces it. Pages that change by themselves (feeds, Gmail, news) rescan often and
  // a slow server (Gemma on a laptop) can take seconds, so server calls go one at a time per tab, extra
  // rescans collapse into one follow-up call, and unchanged hidden text never goes back to the server.
  let started = 0;                                     // version of the newest scan
  let applied = { ver: 0, key: null, quick: false };   // what's on screen now
  let serverJob = null, nextJob = null;                // the call in flight, and the one latest call after it
  let sentKey = null, sentFindings = null;             // last hidden spans the server judged, and its answer (by span)
  let failed = { key: null, at: 0 };                   // don't re-ask about spans the server just failed on
  let lastUrl = location.href, lastMessage = null;
  const RETRY_MS = 60000;

  // Same hidden spans, in any order -> same key (FNV-1a over texts + reasons).
  const spanId = x => JSON.stringify([x.text, x.reasons]);
  function spansKey(spans) {
    let h = 0x811c9dc5;
    const s = spans.map(spanId).sort().join("\n");
    for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193); }
    return (h >>> 0).toString(36) + ":" + spans.length;
  }

  // Show one answer, unless a newer one is already showing. A server answer about the same spans as the
  // quick verdict on screen is an upgrade, even if a newer scan of the same spans has started since.
  function apply(ver, key, findings, spans, quick) {
    const upgrade = key === applied.key && applied.quick && !quick;
    if (ver < applied.ver && !upgrade) return;
    applied = { ver: Math.max(ver, applied.ver), key, quick };
    findings.forEach((f, i) => { f.el = spans[i] && spans[i].el; });
    const threats = findings.filter(f => f.level === "threat");
    const cautions = findings.filter(f => f.level === "caution");
    lastGroups = merge(threats.concat(cautions));
    lastVerdict = { verdict: threats.length ? "threat" : cautions.length ? "caution" : "clean",
                    count: merge(threats).length, cautions: merge(cautions).length, hidden: findings.length,
                    top: lastGroups[0] ? lastGroups[0].text.slice(0, 280) : "", gemma: lastGroups.some(byGemma),
                    quick: quick || false,     // "pending" | "timeout" | "offline" while it's only the quick check
                    page: location.href };
    lastMessage = { type: "verdict", ...lastVerdict,
                    items: threats.concat(cautions).map(f => ({ text: f.text.slice(0, 300), why: f.why, where: f.where })) };
    chrome.runtime.sendMessage(lastMessage);
    playgroundFindings = threats.concat(cautions).map(f => ({ text: f.text, level: f.level, where: f.where, why: f.why }));
    tellPlayground();
    if (keyOf(threats, cautions) === dismissedKey) return;
    render(threats, cautions);
  }

  function askServer(job) {
    if (serverJob) {   // one call at a time: remember only the latest page state for afterwards
      if (serverJob.key !== job.key) nextJob = job;
      return;
    }
    serverJob = job;
    (async () => {
      let res = null;
      try { res = await chrome.runtime.sendMessage({ type: "classify", payload: job.payload }); } catch (e) { /* worker gone */ }
      serverJob = null;
      if (res && res.findings) {
        sentKey = job.key; sentFindings = new Map(job.payload.spans.map((s, i) => [spanId(s), res.findings[i]]));
        apply(job.ver, job.key, res.findings.map(f => ({ ...f })), job.spans, false);
      } else {
        failed = { key: job.key, at: Date.now() };
        apply(job.ver, job.key, localJudge(job.payload.spans, job.payload.visible, res && res.ml), job.spans,
              res && res.timeout ? "timeout" : "offline");
      }
      const next = nextJob; nextJob = null;
      if (next && next.key !== job.key) askServer(next);
    })();
  }

  async function scan() {
    const ver = ++started;
    if (location.href !== lastUrl) {   // SPA route change: drop the previous page's result
      lastUrl = location.href; lastVerdict = null; lastGroups = []; lastMessage = null;
      applied = { ver: applied.ver, key: null, quick: false };
    }
    const paused = await isPaused();
    if (ver !== started) return;
    document.documentElement.dataset.parallax = paused ? "paused" : "on";
    if (paused) {
      document.querySelectorAll(".parallax-reveal").forEach(el => el.classList.remove("parallax-reveal"));
      applied = { ver, key: null, quick: false };   // answers to earlier scans can't overwrite the pause
      lastVerdict = { verdict: "paused" }; lastGroups = []; lastKey = null;
      removePanel();
      chrome.runtime.sendMessage(lastMessage = { type: "verdict", verdict: "paused", count: 0, hidden: 0, items: [] });
      tellPlayground();
      return;
    }
    styleCache = new WeakMap();
    const { hidden, visible } = D.scanDocument(document, env);
    // Collapse duplicates and keep the request small.
    const seen = new Set();
    lastSpans = hidden.filter(h => { const k = h.text.slice(0, 200); if (seen.has(k)) return false; seen.add(k); return true; }).slice(0, 200);
    const spans = lastSpans;
    const links = [...document.querySelectorAll("a[href]")].map(a => a.getAttribute("href").replace(/^(mailto|tel):/i, "")).join(" ");
    // Labels the user sees too: the tab title, and aria-label/title of visible elements (Google's account
    // button shows your email this way while a hidden copy sits in the page). Only visible elements count,
    // so a hidden label still gets judged. Capped to stay fast, and placed before the long text so the
    // 40000-character cut below never drops them.
    const labels = new Set([document.title]);
    for (const el of [...document.querySelectorAll("[aria-label], [title]")].slice(0, 500)) {
      if (!el.checkVisibility || !el.checkVisibility({ visibilityProperty: true, opacityProperty: true })) continue;
      labels.add(el.getAttribute("aria-label") || ""); labels.add(el.getAttribute("title") || "");
    }
    const known = [location.hostname, [...labels].join(" ").slice(0, 10000), links, visible].join(" ");
    const payload = { spans: lastSpans.map(h => ({ text: h.text.slice(0, 2000), reasons: h.reasons })),
                      visible: known.slice(0, 40000), context: "web" };
    const key = spansKey(payload.spans);
    if (key === sentKey) {   // hidden text unchanged (only visible text moved): reuse the server's answer
      apply(ver, key, payload.spans.map(s => ({ ...sentFindings.get(spanId(s)) })), spans, false);   // matched by span: order may differ
      return;
    }
    if (key !== applied.key) {   // new hidden text: show the quick offline verdict right away
      let ml = null;
      try { ml = await chrome.runtime.sendMessage({ type: "ml", spans: payload.spans }); } catch (e) { /* worker gone */ }
      apply(ver, key, localJudge(payload.spans, payload.visible, Array.isArray(ml) ? ml : null), spans, "pending");
    }
    if (key === failed.key && Date.now() - failed.at < RETRY_MS) return;   // keep the quick verdict for now
    askServer({ ver, key, payload, spans });
  }

  // ---- Panel -------------------------------------------------------------
  // One calm card: a single plain-language message, the hidden text it found,
  // and a way to reveal it. Only real threats open it automatically.

  const LOGO = '<svg viewBox="0 0 28 28" width="18" height="18" aria-hidden="true"><circle cx="10.5" cy="14" r="8.5" fill="none" stroke="#fff" stroke-width="1.6"/><circle cx="17.5" cy="14" r="8.5" fill="none" stroke="#3d7eff" stroke-width="1.6"/></svg>';

  // How the text was hidden, in plain words.
  function how(where) {
    const w = (where || []).join(" ");
    if (/text color ~ background|transparent text/.test(w)) return "same color as the background";
    if (/font-size/.test(w)) return "tiny text";
    if (/off-screen/.test(w)) return "moved off the page";
    if (/opacity/.test(w)) return "see-through text";
    if (/clipped|zero-size/.test(w)) return "shrunk to nothing";
    if (/covered by another/.test(w)) return "covered by something else";
    if (/Unicode/.test(w)) return "invisible characters";
    if (/HTML comment|markup:/.test(w)) return "inside the page code";
    if (/display:none|visibility:hidden|hidden>/.test(w)) return "hidden on the page";
    return "hidden from you";
  }

  // Pieces of one hidden message often arrive as several text nodes (one per line).
  // Join neighbours that were hidden the same way so the panel shows one message.
  function merge(findings) {
    const out = [];
    for (const f of findings) {
      const last = out[out.length - 1];
      if (last && f.el && last.els.includes(f.el) && last.level === f.level && how(last.where) === how(f.where)) {
        last.text += " " + f.text; if (!last.els.includes(f.el)) last.els.push(f.el); last.why = [...new Set(last.why.concat(f.why || []))];
      } else out.push({ text: f.text, where: f.where, why: f.why || [], level: f.level, els: f.els || [f.el] });
    }
    return out;
  }

  let lastVerdict = null;   // what the popup shows, so the badge, popup and page always agree
  let lastGroups = [];
  let lastKey = null;       // don't redraw (or re-animate) when a rescan finds the same thing
  let cardOpen = false;     // an open card stays open (redrawn in place) when a new result arrives
  let hovering = false, pendingRender = null;   // while the mouse is on the panel, keep the latest result for later
  let shrunkKey = null;     // messages whose pill already shrank: redraws of them start small
  // our fine-tuned Gemma reports as "parallax-transformer"; the untrained one as "gemma-4"
  const byGemma = g => (g.why || []).some(w => /^talks to an AI \([^)]*(gemma|parallax-transformer)/i.test(w));

  function removePanel() {
    const root = document.getElementById("parallax-panel"); root && root.remove();
    lastKey = null; cardOpen = false; hovering = false; pendingRender = null;
  }

  // Quiet by default. A real threat shows a small pill in the corner that shrinks to a dot;
  // clicking it opens a short card. Anything less serious only changes the toolbar badge.
  function render(threats, cautions, opts = {}) {
    // Don't change the panel under the mouse (the card would close mid-click); apply the latest result on leave.
    if (hovering && !opts.force) { pendingRender = [threats, cautions, opts]; return; }
    pendingRender = null;
    let root = document.getElementById("parallax-panel");
    const show = threats.length || (opts.force && cautions.length);
    if (!show) { removePanel(); return; }
    // Include levels and reasons: when the server's answer replaces the quick offline verdict for the same
    // hidden text, the card must redraw (otherwise it keeps "offline check" and never shows "Confirmed by Gemma").
    // Sorted, so the same messages in a different order don't redraw.
    const key = threats.concat(cautions).map(f => JSON.stringify([f.text, f.level, f.why || []])).sort().join("\n") +
      (opts.title || "");
    if (root && key === lastKey && !opts.force) return;
    lastKey = key;
    const groups = merge(threats.concat(cautions));
    if (!root) {
      root = document.createElement("div"); root.id = "parallax-panel"; document.documentElement.appendChild(root);
      root.addEventListener("pointerenter", () => { hovering = true; });
      root.addEventListener("pointerleave", () => {
        hovering = false;
        const next = pendingRender; pendingRender = null;
        if (next) render(...next);
      });
    }
    root.className = threats.length ? "px-threat" : "px-caution";
    const data = { groups, isThreat: !!threats.length, title: opts.title, key: keyOf(threats, cautions) };
    opts.force || cardOpen ? openCard(root, data) : openPill(root, data);
  }

  function openPill(root, d) {
    cardOpen = false;
    const n = d.groups.filter(g => g.level === "threat").length || d.groups.length;
    root.innerHTML = "";
    const pill = document.createElement("button"); pill.className = "px-pill";
    pill.setAttribute("aria-label", `Parallax: ${n} hidden message${n > 1 ? "s" : ""} found. Open details.`);
    pill.innerHTML = '<span class="px-dot"></span><span class="px-pill-n"></span><span class="px-pill-text"></span>';
    pill.querySelector(".px-pill-n").textContent = String(n);
    pill.querySelector(".px-pill-text").textContent = n > 1 ? "hidden messages" : "hidden message";
    pill.onclick = () => openCard(root, d);
    root.append(pill);
    // shrink to just the dot and number; a redraw of the same messages starts small instead of animating again
    if (shrunkKey === d.key) pill.classList.add("px-small");
    else setTimeout(() => { pill.classList.add("px-small"); shrunkKey = d.key; }, 6000);
  }

  function openCard(root, d) {
    const n = d.groups.filter(g => g.level === "threat").length || d.groups.length;
    cardOpen = true;
    root.innerHTML = "";
    const card = document.createElement("div"); card.className = "px-card";

    const head = document.createElement("div"); head.className = "px-top";
    const brand = document.createElement("span"); brand.className = "px-brand"; brand.innerHTML = LOGO + "<span>parallax</span>";
    const min = document.createElement("button"); min.className = "px-x"; min.setAttribute("aria-label", "Minimize"); min.textContent = "–";
    min.onclick = () => openPill(root, d);
    head.append(brand, min);

    const status = document.createElement("div"); status.className = "px-status";
    status.textContent = d.title || (d.isThreat ? (n > 1 ? `${n} hidden messages found` : "Hidden message found") : "Hidden text found");
    const sub = document.createElement("div"); sub.className = "px-sub";
    sub.textContent = d.isThreat ? "Suspicious text hidden on this page could affect an AI assistant."
                                 : "This page has text you can't see. It's probably harmless.";
    card.append(head, status, sub);

    // Every hidden message, each with how it was hidden in plain words; long lists scroll inside the card.
    const list = document.createElement("div"); list.className = "px-list";
    for (const g of d.groups) {
      const item = document.createElement("div"); item.className = "px-item";
      const quote = document.createElement("div"); quote.className = "px-quote"; quote.textContent = g.text.slice(0, 280);
      const hiddenHow = how(g.where);
      const note = document.createElement("div"); note.className = "px-sub"; note.textContent = hiddenHow[0].toUpperCase() + hiddenHow.slice(1);
      item.append(quote, note); list.append(item);
    }
    card.append(list);

    if (d.groups.some(byGemma)) {
      const tags = document.createElement("div"); tags.className = "px-tags";
      const t = document.createElement("span"); t.className = "px-tag px-gemma"; t.textContent = "Confirmed by Gemma";
      tags.append(t); card.append(tags);
    }

    const btns = document.createElement("div"); btns.className = "px-btns";
    const els = d.groups.flatMap(g => g.els).filter(Boolean);
    if (els.length) {
      const reveal = document.createElement("button"); reveal.className = "px-btn";
      reveal.textContent = els[0].classList.contains("parallax-reveal") ? "Hide again" : "Show on page";   // survives redraws
      reveal.onclick = () => { const on = !els[0].classList.contains("parallax-reveal");
        els.forEach(el => el.classList.toggle("parallax-reveal", on)); reveal.textContent = on ? "Hide again" : "Show on page";
        if (on) {   // revealed text sits in place now (even if it was moved off the page): take the user there
          els[0].scrollIntoView({ behavior: "smooth", block: "center" });
          els[0].classList.remove("parallax-flash"); void els[0].offsetWidth;   // restart the flash if clicked again
          els[0].classList.add("parallax-flash");
          setTimeout(() => els[0].classList.remove("parallax-flash"), 1200);
        } };
      btns.append(reveal);
    }
    const ignore = document.createElement("button"); ignore.className = "px-btn px-ghost"; ignore.textContent = "Ignore";
    ignore.onclick = () => { dismissedKey = d.key; removePanel(); };
    btns.append(ignore);
    card.append(btns);
    root.append(card);
  }

  // Results from a right-click file scan are shown in the same panel.
  chrome.runtime.onMessage.addListener((msg, sender, reply) => {
    if (msg.type === "getState") { reply(lastVerdict); return; }
    if (msg.type === "details") {
      if (lastGroups.length) render(lastGroups.filter(g => g.level === "threat").map(g => ({ ...g, el: g.els[0] })),
        lastGroups.filter(g => g.level === "caution").map(g => ({ ...g, el: g.els[0] })), { force: true });
      reply({ shown: !!lastGroups.length }); return;
    }
    if (msg.type === "reveal") {
      const els = lastGroups.flatMap(g => g.els).filter(Boolean);
      const on = els.length && !els[0].classList.contains("parallax-reveal");
      els.forEach(el => el.classList.toggle("parallax-reveal", on));
      if (els[0] && on) els[0].scrollIntoView({ behavior: "smooth", block: "center" });
      reply({ on }); return;
    }
    if (msg.type === "fileResult") {
      const r = msg.report;
      const f = (r.findings || []).filter(x => x.level !== "info");
      if (!f.length) { alert(`Parallax: ${r.headline}`); return; }
      render(f.filter(x => x.level === "threat"), f.filter(x => x.level === "caution"), { force: true, title: r.headline });
    }
  });

  let timer = null;
  const later = ms => { clearTimeout(timer); timer = setTimeout(() => { timer = null; scan(); }, ms); };
  // At most one scan per 1.2 s. Not a resetting debounce: pages that never stop changing (animations,
  // feeds) would otherwise push the scan back forever.
  const rescan = () => { if (!timer) later(1200); };
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
  chrome.storage.onChanged.addListener(ch => { if (ch.paused) { lastKey = null; dismissedKey = null; scan(); } });
  // SPA route changes: rescan soon (scan() clears the old page's result first).
  const soon = () => later(200);
  addEventListener("hashchange", soon);
  addEventListener("popstate", soon);
  // ---- "Am I protected?" playground --------------------------------------
  // Every page can see Parallax is running (<html data-parallax="on|paused">), nothing more. Only a page with
  // <meta name="parallax-playground" content="1"> (our #try page) also gets the verdict and its findings.
  let playgroundFindings = [];
  const isPlayground = () => !!document.querySelector('meta[name="parallax-playground"][content="1"]');
  const toPage = msg => { try { window.postMessage({ source: "parallax-extension", ...msg }, location.origin); } catch (e) { /* opaque origin */ } };
  function tellPlayground() {
    if (!isPlayground() || !lastVerdict) return;
    toPage({ type: "verdict", verdict: lastVerdict.verdict, quick: lastVerdict.quick || false, gemma: !!lastVerdict.gemma,
             findings: lastVerdict.verdict === "paused" ? [] : playgroundFindings });
  }
  addEventListener("message", async e => {
    if (e.source !== window || !e.data || e.data.source !== "parallax-page" || e.data.type !== "ping" || !isPlayground()) return;
    let server = null;
    try { server = await chrome.runtime.sendMessage({ type: "serverUrl" }); } catch (err) { /* worker gone */ }
    toPage({ type: "pong", version: chrome.runtime.getManifest().version, server, paused: await isPaused() });
    tellPlayground();   // the page may have started listening after the last verdict
  });

  // Back/Forward can restore this page from cache: tell the badge again what this page has.
  addEventListener("pageshow", e => { if (e.persisted && lastMessage) chrome.runtime.sendMessage(lastMessage); });
  scan();
})();
