// Shared by extension pages and the service worker.
// Hosted server for everyone (public mode, scripts/serve_public.sh). Replace the placeholder once it's up.
const HOSTED_URL = "https://REPLACE-ME-8787.proxy.runpod.net";

const ParallaxServer = {
  defaultUrl: "http://localhost:8787",
  hostedUrl: HOSTED_URL,
  _pick: null,   // { url, until }: which default answered last, so we don't probe on every request
  // The default when no server is set in the popup: the hosted one if /health answers within 3 s, else local.
  async defaultServer() {
    if (this._pick && Date.now() < this._pick.until) return this._pick.url;
    let url = this.defaultUrl;
    if (!this.hostedUrl.includes("REPLACE-ME")) {
      const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), 3000);
      try {
        if ((await fetch(this.hostedUrl + "/health", { signal: ctl.signal })).ok) url = this.hostedUrl;
      } catch { /* hosted server down or slow: use the local one */ } finally { clearTimeout(timer); }
    }
    this._pick = { url, until: Date.now() + (url === this.hostedUrl ? 300000 : 30000) };
    return url;
  },
  offlineMessage: "File scanning needs the Parallax server. Start it with: uvicorn parallax.server:app --port 8787 (or set a server address in the popup).",
  async url() {   // the popup's Server setting wins over both defaults
    return ((await chrome.storage.local.get("server")).server || await this.defaultServer()).replace(/\/+$/, "");
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
    if (!response.ok) {   // public mode explains refusals (unsafe link, too big, rate limit) in the body
      let reason = "";
      try { const j = await response.json(); reason = j.error || (typeof j.detail === "string" ? j.detail : ""); } catch { /* not JSON */ }
      throw new Error(reason || `Parallax server returned HTTP ${response.status}. Please try again.`);
    }
    return response.json();
  }
};
