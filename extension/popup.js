const $ = id => document.getElementById(id);
const show = (cls, text) => { $("verdict").className = "v " + cls; $("verdict").textContent = text; };
const fmt = r => r.error ? "Error: " + r.error + "\nIs the Parallax server running?"
  : r.headline + "\n\n" + (r.findings || []).filter(f => f.level !== "info")
      .map(f => "• " + f.text.slice(0, 160) + "\n  " + (f.why || []).join("; ")).join("\n");

(async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  $("srv").textContent = (await chrome.storage.local.get("server")).server || "http://localhost:8787";
  const v = (await chrome.storage.session.get("tab" + tab.id))["tab" + tab.id];
  if (!v) show("clean", "No scan yet for this page.");
  else if (v.verdict === "threat") show("threat", `${v.count} hidden instruction${v.count > 1 ? "s" : ""} aimed at AI`);
  else if (v.verdict === "caution") show("caution", "Text here is hidden from you");
  else show("clean", v.hidden ? `Safe (${v.hidden} harmless hidden bits)` : "Nothing hidden from you");

  $("cloak").onclick = async () => {
    $("out").textContent = "Fetching the page as you and as AI agents…";
    $("out").textContent = fmt(await chrome.runtime.sendMessage({ type: "scanUrl", url: tab.url }));
  };
  $("file").onchange = async e => {
    const f = e.target.files[0]; if (!f) return;
    $("out").textContent = "Scanning " + f.name + "…";
    const bytes = Array.from(new Uint8Array(await f.arrayBuffer()));
    $("out").textContent = fmt(await chrome.runtime.sendMessage({ type: "scanUpload", name: f.name, bytes }));
  };
})();
