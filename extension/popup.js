const $ = id => document.getElementById(id);
const fmt = r => !r ? "No response from Parallax. Please try again." : r.error ? r.error
  : r.headline + "\n\n" + (r.findings || []).filter(f => f.level !== "info")
      .map(f => "• " + f.text.slice(0, 160) + "\n  " + (f.why || []).join("; ")).join("\n");

function show(state, title, sub) {
  $("status").className = "status " + state;
  $("title").textContent = title;
  $("sub").textContent = sub;
}

function render(v, available) {
  $("found").hidden = true;
  if (!v) return show("paused", available ? "Scanning…" : "Can't scan this page",
    available ? "Waiting for this page's scan. Reload the page if needed." : "Use file scanning for documents and PDFs.");
  if (v.verdict === "paused") return show("paused", "Paused on this site", "Turn scanning back on below.");
  if (v.verdict === "threat") show("threat", v.count > 1 ? `${v.count} hidden messages` : "Hidden message found",
    "Suspicious hidden text an AI assistant could read.");
  else if (v.verdict === "caution") show("caution", "Hidden text found", "Its purpose isn't clear. Review the findings.");
  else show("", "No suspicious hidden text found", "This scan found no hidden text that needs review.");
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

  let v = null;
  if (available) {
    try { v = await chrome.tabs.sendMessage(tab.id, { type: "getState" }); } catch { /* Reload after installing. */ }
    if (!v) v = (await chrome.storage.session.get("tab" + tab.id))["tab" + tab.id];
    if (paused.includes(host)) v = { verdict: "paused" };
  }
  render(v, available);

  // Update while open after an asynchronous scan or pause/resume.
  chrome.storage.onChanged.addListener((changes, area) => {
    if (available && area === "session" && changes["tab" + tab.id]) render(changes["tab" + tab.id].newValue, true);
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
