// Talks to the local Parallax server (scanning, Gemma), sets the toolbar
// badge, and adds "Scan this file with Parallax" for PDF and Word links.

importScripts("ml.js");   // our trained classifier, used when the server is off
importScripts("server.js");

let MODEL = null;
async function model() {
  if (!MODEL) MODEL = await (await fetch(chrome.runtime.getURL("models/injection_lr.json"))).json();
  return MODEL;
}

const post = (path, body) => ParallaxServer.post(path, body);
const CLASSIFY_TIMEOUT_MS = 10000;   // after this the page keeps its quick offline verdict

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg.type === "classify") {
    ParallaxServer.post("/classify", msg.payload, false, CLASSIFY_TIMEOUT_MS).then(reply).catch(async e => {
      // Server off or too slow: score each hidden passage with the built-in model instead.
      try {
        const m = await model();
        reply({ error: String(e), timeout: !!e.timeout, ml: msg.payload.spans.map(s => ParallaxML.judge(m, s.text)) });
      } catch (e2) { reply({ error: String(e) + "; " + e2, timeout: !!e.timeout }); }
    });
    return true; // async reply
  }
  if (msg.type === "serverUrl") {   // for the playground page's status banner
    ParallaxServer.url().then(reply).catch(() => reply(null));
    return true;
  }
  if (msg.type === "ml") {   // the built-in model only, for the quick verdict shown before the server answers
    model().then(m => reply(msg.spans.map(s => ParallaxML.judge(m, s.text)))).catch(() => reply(null));
    return true;
  }
  if (msg.type === "verdict" && sender.tab) {
    const colors = { threat: "#ff4d5e", caution: "#f5b84a", clean: "#3d7eff", paused: "#737373" };
    chrome.action.setBadgeBackgroundColor({ tabId: sender.tab.id, color: colors[msg.verdict] });
    chrome.action.setBadgeText({ tabId: sender.tab.id, text: msg.verdict === "threat" ? String(msg.count) : msg.verdict === "caution" ? "?" : msg.verdict === "paused" ? "off" : "" });
    chrome.storage.session.set({ ["tab" + sender.tab.id]: msg });
  }
  if (msg.type === "scanUrl") {
    post("/scan/url", { url: msg.url }).then(reply).catch(e => reply({ error: e.message }));
    return true;
  }
});

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: "px-scan-link", title: "Scan this file with Parallax", contexts: ["link"] });
});

chrome.contextMenus.onClicked.addListener(async info => {
  if (info.menuItemId !== "px-scan-link") return;
  await chrome.tabs.create({ url: chrome.runtime.getURL("scan.html") + "?url=" + encodeURIComponent(info.linkUrl) });
});
