// Runs the extension detector on an HTML file and prints the /classify payload.
const { JSDOM } = require(process.env.JSDOM_PATH || "jsdom");
const D = require("../detect.js");
const html = require("fs").readFileSync(process.argv[2], "utf8");
const w = new JSDOM(html).window;
const env = { style: el => w.getComputedStyle(el),
  rect: el => { const s = w.getComputedStyle(el); const l = parseFloat(s.left); return { left: isNaN(l) ? 10 : l, top: 10, width: 100, height: 16 }; },
  viewport: { width: 1200, height: 800 }, page: { width: 1200, height: 3000 }, topAt: null };
const r = D.scanDocument(w.document, env);
console.log(JSON.stringify({ spans: r.hidden.map(h => ({ text: h.text, reasons: h.reasons })), visible: r.visible, context: "web" }));
