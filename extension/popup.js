const $ = id => document.getElementById(id);
const show = (cls, text) => { $("verdict").className = "v " + cls; $("verdict").textContent = text; };
const fmt = r => r.error ? r.error
  : r.headline + "\n\n" + (r.findings || []).filter(f => f.level !== "info")
      .map(f => "• " + f.text.slice(0, 160) + "\n  " + (f.why || []).join("; ")).join("\n");

function pdfUrl(tab) {
  try {
    const url = new URL(tab.url);
    // Chrome's built-in PDF viewer can expose its wrapper URL or the original URL.
    const viewer = url.hostname === "mhjfbmdgcfjbbpaeojofohoefgiehjai";
    if (viewer) return url.searchParams.get("file") || url.searchParams.get("src") || url.searchParams.get("url") || tab.url;
    if (/\.pdf$/i.test(url.pathname) || /\.pdf(?:\s|$)/i.test(tab.title || "") || /pdf viewer/i.test(tab.title || "")) return tab.url;
  } catch { /* Internal tabs may not have an accessible URL. */ }
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
    $("server-status").textContent = "Enter a valid server address starting with http:// or https://.";
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
  if (!tab) { show("clean", "No active page."); $("cloak").disabled = true; return; }
  const pdf = pdfUrl(tab);
  $("scan-pdf").hidden = !pdf;
  $("scan-pdf").onclick = () => openScan(pdf);
  const v = (await chrome.storage.session.get("tab" + tab.id))["tab" + tab.id];
  if (!v) show("clean", "No scan yet for this page.");
  else if (v.verdict === "threat") show("threat", `${v.count} hidden instruction${v.count > 1 ? "s" : ""} aimed at AI`);
  else if (v.verdict === "caution") show("caution", "Text here is hidden from you");
  else show("clean", v.hidden ? `Safe (${v.hidden} harmless hidden bits)` : "Nothing hidden from you");

  $("cloak").onclick = async () => {
    $("out").textContent = "Fetching the page as you and as AI agents…";
    $("out").textContent = fmt(await chrome.runtime.sendMessage({ type: "scanUrl", url: tab.url }));
  };
})();
