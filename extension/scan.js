const $ = id => document.getElementById(id);
const MAX_SIZE = 20 * 1024 * 1024;
const SIZE_MESSAGE = "This file is over 20 MB. Choose a file that is 20 MB or smaller.";
const LOCAL_MESSAGE = "To scan local files, turn on 'Allow access to file URLs' for Parallax in chrome://extensions, or drag the file onto this page.";
let busy = false;

function reset() {
  $("file").value = "";
  $("status").textContent = "";
  $("results").hidden = true;
  $("headline").textContent = "";
  $("verdict").textContent = "";
  $("verdict").className = "v";
  $("findings").replaceChildren();
  $("attachments").replaceChildren();
  $("reset").hidden = true;
}

function element(tag, text, className) {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
}

function banner(node, verdict) {
  const level = ["threat", "caution", "clean"].includes(verdict) ? verdict : "caution";
  node.className = "v " + level;
  node.textContent = { threat: "Threat · Hidden instructions found", caution: "Caution · Review hidden text", clean: "Clean · No suspicious hidden text" }[level];
}

const describe = value => Array.isArray(value) ? value.join("; ") : (value || "");
function findings(parent, report) {
  for (const f of report.findings || []) {
    if (f.level === "info") continue;
    const item = element("div", "", "finding");
    item.append(element("mark", f.text || ""), element("p", "Where: " + describe(f.where)),
      element("p", "Why: " + describe(f.why)));
    parent.append(item);
  }
}

function attachments(parent, report) {
  for (const [index, child] of (report.children || []).entries()) {
    const section = element("section", "", "attachment");
    section.append(element("h3", `Attachment ${index + 1}: ${child.headline}`));
    const verdict = element("div", "");
    banner(verdict, child.verdict);
    section.append(verdict);
    findings(section, child);
    attachments(section, child);
    parent.append(section);
  }
}

async function scan(file) {
  if (file.size > MAX_SIZE) throw new Error(SIZE_MESSAGE);
  if (!/\.(pdf|docx|eml|html|htm)$/i.test(file.name)) {
    throw new Error("Choose a PDF, Word (.docx), saved email (.eml), or HTML (.html, .htm) file.");
  }
  $("status").textContent = "Scanning " + file.name + "…";
  const body = new FormData();
  body.append("file", file, file.name);
  const report = await ParallaxServer.post("/scan/file", body, true);
  banner($("verdict"), report.verdict);
  $("headline").textContent = report.headline;
  findings($("findings"), report);
  attachments($("attachments"), report);
  $("results").hidden = false;
  $("status").textContent = "";
}

async function run(getFile) {
  if (busy) return;
  reset();
  busy = true;
  $("choose").disabled = true;
  $("file").disabled = true;
  $("reset").hidden = true;
  try {
    await scan(await getFile());
  } catch (error) {
    $("status").textContent = error.message;
  } finally {
    busy = false;
    $("choose").disabled = false;
    $("file").disabled = false;
    $("reset").hidden = false;
  }
}

async function download(rawUrl) {
  const url = new URL(rawUrl);
  if (!["http:", "https:", "file:"].includes(url.protocol)) {
    throw new Error("This file URL cannot be downloaded. Save the file and drag it onto this page.");
  }
  $("status").textContent = "Downloading file…";
  let response;
  let blob;
  try {
    response = await fetch(url.href, { credentials: "include" });
    if (!response.ok) throw new Error(`Download returned HTTP ${response.status}. Save the file and drag it onto this page.`);
    if (Number(response.headers.get("content-length")) > MAX_SIZE) {
      if (response.body) await response.body.cancel();
      throw new Error(SIZE_MESSAGE);
    }
    blob = await response.blob();
  } catch (error) {
    if (url.protocol === "file:") throw new Error(LOCAL_MESSAGE);
    if (error instanceof TypeError) throw new Error("Couldn't download this file. Open it in your browser, then save it and drag it onto this page.");
    throw error;
  }
  let name = url.pathname.split("/").pop() || "file";
  try { name = decodeURIComponent(name); } catch { /* Keep malformed URL escapes literal. */ }
  if (!/\.(pdf|docx|eml|html|htm)$/i.test(name) && blob.type.split(";")[0] === "application/pdf") name += ".pdf";
  return new File([blob], name, { type: blob.type });
}

$("choose").onclick = () => $("file").click();
$("file").onchange = event => {
  const file = event.target.files[0];
  if (file) run(() => file);
};
$("reset").onclick = () => { reset(); $("choose").focus(); };
// Prevent dropped files from navigating away from the extension page.
document.addEventListener("dragover", event => event.preventDefault());
document.addEventListener("drop", event => event.preventDefault());
$("drop").addEventListener("dragover", event => {
  event.preventDefault();
  if (!busy) $("drop").classList.add("dragging");
});
$("drop").addEventListener("dragleave", () => $("drop").classList.remove("dragging"));
$("drop").addEventListener("drop", event => {
  event.preventDefault();
  $("drop").classList.remove("dragging");
  if (busy) return;
  const files = event.dataTransfer.files;
  if (files.length !== 1) {
    reset();
    $("status").textContent = "Please drop one file at a time.";
    return;
  }
  const file = files[0];
  run(() => file);
});

const source = new URLSearchParams(location.search).get("url");
if (source) run(() => download(source));
