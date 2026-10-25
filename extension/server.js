// Shared by extension pages and the service worker.
const ParallaxServer = {
  defaultUrl: "http://localhost:8787",
  offlineMessage: "File scanning needs the Parallax server. Start it with: uvicorn parallax.server:app --port 8787 (or set a server address in the popup).",
  async url() {
    return ((await chrome.storage.local.get("server")).server || this.defaultUrl).replace(/\/+$/, "");
  },
  timeoutMessage: "The Parallax server didn't answer in time.",
  // timeoutMs: give up after this long (error.timeout = true); 0 waits as long as the server takes.
  async post(path, body, isForm = false, timeoutMs = 0) {
    const url = await this.url();
    const ctl = new AbortController();
    const timer = timeoutMs ? setTimeout(() => ctl.abort(), timeoutMs) : null;
    let response;
    try {
      response = await fetch(url + path, isForm ? { method: "POST", body, signal: ctl.signal }
        : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: ctl.signal });
    } catch {
      if (ctl.signal.aborted) throw Object.assign(new Error(this.timeoutMessage), { timeout: true });
      throw new Error(this.offlineMessage);
    } finally {
      clearTimeout(timer);
    }
    if (!response.ok) throw new Error(`Parallax server returned HTTP ${response.status}. Please try again.`);
    return response.json();
  }
};
