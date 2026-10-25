// Talks to the local Parallax server (scanning, Gemma), sets the toolbar
// badge, and adds "Scan this file with Parallax" for PDF and Word links.

importScripts("ml.js");   // our trained classifier, used when the server is off

let MODEL = null;
async function model() {
  if (!MODEL) MODEL = await (await fetch(chrome.runtime.getURL("models/injection_lr.json"))).json();
  return MODEL;
}

const DEFAULT_SERVER = "http://localhost:8787";
const server = async () => (await chrome.storage.local.get("server")).server || DEFAULT_SERVER;

async function post(path, body, isForm = false) {
  const res = await fetch((await server()) + path, isForm ? { method: "POST", body }
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error(`server ${res.status}`);
  return res.json();
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg.type === "classify") {
    post("/classify", msg.payload).then(reply).catch(async e => {
      // Server off: score each hidden passage with the built-in model instead.
      try {
        const m = await model();
        reply({ error: String(e), ml: msg.payload.spans.map(s => ParallaxML.judge(m, s.text)) });
      } catch (e2) { reply({ error: String(e) + "; " + e2 }); }
    });
    return true; // async reply
  }
  if (msg.type === "verdict" && sender.tab) {
    const colors = { threat: "#b42318", caution: "#9a6100", clean: "#1f7a4d" };
    chrome.action.setBadgeBackgroundColor({ tabId: sender.tab.id, color: colors[msg.verdict] });
    chrome.action.setBadgeText({ tabId: sender.tab.id, text: msg.verdict === "threat" ? String(msg.count) : msg.verdict === "caution" ? "?" : "" });
    chrome.storage.session.set({ ["tab" + sender.tab.id]: msg });
  }
  if (msg.type === "scanUrl") {
    post("/scan/url", { url: msg.url }).then(reply).catch(e => reply({ error: String(e) }));
    return true;
  }
  if (msg.type === "scanUpload") {
    const fd = new FormData();
    fd.append("file", new Blob([new Uint8Array(msg.bytes)]), msg.name);
    post("/scan/file", fd, true).then(reply).catch(e => reply({ error: String(e) }));
    return true;
  }
});

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: "px-scan-link", title: "Scan this file with Parallax", contexts: ["link"] });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== "px-scan-link") return;
  try {
    const blob = await (await fetch(info.linkUrl)).blob();
    const name = decodeURIComponent(new URL(info.linkUrl).pathname.split("/").pop() || "file");
    const fd = new FormData();
    fd.append("file", blob, name);
    const report = await post("/scan/file", fd, true);
    chrome.tabs.sendMessage(tab.id, { type: "fileResult", report });
  } catch (e) {
    chrome.tabs.sendMessage(tab.id, { type: "fileResult", report: { headline: "Couldn't scan that file: " + e, findings: [] } });
  }
});
