const $ = id => document.getElementById(id);
const fmt = r => !r ? "No response from Parallax. Please try again." : r.error ? r.error
  : r.headline + "\n\n" + (r.findings || []).filter(f => f.level !== "info")
      .map(f => "• " + f.text.slice(0, 160) + "\n  " + (f.why || []).join("; ")).join("\n");

function show(state, title, sub) {
  $("status").className = "status " + state;
  $("title").textContent = title;
  $("sub").textContent = sub;
}

// The page shows a quick offline verdict first; these say so until the server's answer replaces it.
const QUICK = { pending: "Quick check · the full check is on the way.",
                timeout: "Quick check (server didn't answer in time).",
                offline: "Quick check (the Parallax server isn't running)." };

function render(v, available, waiting = "scanning") {
  $("found").hidden = true;
  if (!v && waiting === "unreachable") return show("paused", "Refresh this page to scan it",
    "This tab was open before Parallax started.");
  if (!v) return show("paused", !available ? "Can't scan this page" : waiting === "slow" ? "Still checking…" : "Scanning…",
    !available ? "Use file scanning for documents and PDFs."
      : waiting === "slow" ? "The server is slow. The result will show here when it's ready." : "Waiting for this page's scan.");
  if (v.verdict === "paused") return show("paused", "Paused on this site", "Turn scanning back on below.");
  const quick = QUICK[v.quick];
  if (v.verdict === "threat") show("threat", v.count > 1 ? `${v.count} hidden messages` : "Hidden message found",
    quick || "Suspicious hidden text an AI assistant could read.");
  else if (v.verdict === "caution") show("caution", "Hidden text found", quick || "Its purpose isn't clear. Review the findings.");
  else show("", "No suspicious hidden text found", quick || "This scan found no hidden text that needs review.");
  if ((v.verdict === "threat" || v.verdict === "caution") && v.top) {
    $("found").hidden = false; $("quote").textContent = v.top; $("gemma").hidden = !v.gemma;
  }
}

function pdfUrl(tab) {
  try {
    const url = new URL(tab.url);
    if (url.hostname === "mhjfbmdgcfjbbpaeojofohoefgiehjai")
      return url.searchParams.get("file") || url.searchParams.get("src") || url.searchParams.get("url") || tab.url;
    if (/\.pdf$/i.test(url.pathname) || /\.pdf(?:\s|$)/i.test(tab.title || "") || /pdf viewer/i.test(tab.title || "")) return tab.url;
  } catch { /* Browser tabs may not expose a URL. */ }
  return null;
}

async function openScan(url) {
  await chrome.tabs.create({ url: chrome.runtime.getURL("scan.html") + (url ? "?url=" + encodeURIComponent(url) : "") });
  window.close();
}

$("scan-file").onclick = () => openScan();
$("server-form").onsubmit = async event => {
  event.preventDefault();
  const value = $("server").value.trim();
  try {
    if (!/^https?:\/\//i.test(value)) throw new Error();
    new URL(value);
  } catch {
    $("server-status").textContent = "Enter a valid address starting with http:// or https://.";
    return;
  }
  const server = value.replace(/\/+$/, "");
  await chrome.storage.local.set({ server });
  $("server").value = server;
  $("server-status").textContent = "Server saved.";
};

(async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  $("server").value = await ParallaxServer.url();
  let host = "", available = false;
  try {
    const url = new URL(tab?.url);
    available = ["https:", "http:"].includes(url.protocol);
    if (available) host = url.hostname;
  } catch { /* No active web tab. */ }
  const pdf = tab && pdfUrl(tab);
  if (pdf) available = false;
  $("scan-pdf").hidden = !pdf;
  $("scan-pdf").onclick = () => openScan(pdf);
  $("cloak").disabled = !available;
  $("toggle").disabled = !available;
  const paused = (await chrome.storage.local.get("paused")).paused || [];
  $("toggle").checked = available && !paused.includes(host);

  // Ask the page itself (it knows its own verdict; the stored one may belong to the previous page in this tab).
  let v = null, reachable = true;
  const ask = async () => {
    try { v = await chrome.tabs.sendMessage(tab.id, { type: "getState" }); reachable = true; }
    catch { reachable = false; }   // tab opened before the extension was (re)loaded
    if (paused.includes(host)) v = { verdict: "paused" };
  };
  if (available) await ask();
  render(v, available, reachable ? "scanning" : "unreachable");

  // No verdict yet: keep asking, and after 15 s say the server is slow instead of "Scanning…" forever.
  const opened = Date.now();
  const poll = setInterval(async () => {
    if (!available || v) return clearInterval(poll);
    await ask();
    render(v, true, !reachable ? "unreachable" : Date.now() - opened > 15000 ? "slow" : "scanning");
  }, 1000);

  // Update while open after an asynchronous scan or pause/resume.
  chrome.storage.onChanged.addListener((changes, area) => {
    if (available && area === "session" && changes["tab" + tab.id]) { v = changes["tab" + tab.id].newValue; render(v, true); }
  });
  $("details").onclick = async () => {
    try {
      const result = await chrome.tabs.sendMessage(tab.id, { type: "details" });
      if (result?.shown) window.close();
      else $("out").textContent = "The page changed. Reopen Parallax to check it again.";
    } catch { $("out").textContent = "Reload the page to enable Parallax."; }
  };
  $("show").onclick = async () => {
    try {
      const r = await chrome.tabs.sendMessage(tab.id, { type: "reveal" });
      $("show").textContent = r?.on ? "Hide again" : "Show hidden text on page";
    } catch { $("out").textContent = "Reload the page to enable Parallax."; }
  };
  $("toggle").onchange = async e => {
    const list = new Set((await chrome.storage.local.get("paused")).paused || []);
    e.target.checked ? list.delete(host) : list.add(host);
    await chrome.storage.local.set({ paused: [...list] });
    render(e.target.checked ? null : { verdict: "paused" }, true);
  };
  $("cloak").onclick = async () => {
    $("cloak").disabled = true;
    $("out").textContent = "Fetching the page as you and as AI agents…";
    try { $("out").textContent = fmt(await chrome.runtime.sendMessage({ type: "scanUrl", url: tab.url })); }
    catch (e) { $("out").textContent = e.message; }
    finally { $("cloak").disabled = !available; }
  };
})();
