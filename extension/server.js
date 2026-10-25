// Shared by extension pages and the service worker.
const ParallaxServer = {
  defaultUrl: "http://localhost:8787",
  offlineMessage: "File scanning needs the Parallax server. Start it with: uvicorn parallax.server:app --port 8787 (or set a server address in the popup).",
  async url() {
    return ((await chrome.storage.local.get("server")).server || this.defaultUrl).replace(/\/+$/, "");
  },
  async post(path, body, isForm = false) {
    const url = await this.url();
    let response;
    try {
      response = await fetch(url + path, isForm ? { method: "POST", body }
        : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    } catch {
      throw new Error(this.offlineMessage);
    }
    if (!response.ok) throw new Error(`Parallax server returned HTTP ${response.status}. Please try again.`);
    return response.json();
  }
};
