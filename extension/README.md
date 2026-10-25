# Parallax for Chrome

Parallax finds text hidden from you that an AI can read. Basic page scanning works offline. File scanning, AI-bot comparisons, and Gemma assessment need a reachable scanning server; Gemma assessment also needs a model configured on that server.

## Install and update

1. Download and extract the repository ZIP, or clone the repository.
2. Open `chrome://extensions` and enable **Developer mode**.
3. Click **Load unpacked** and select the repository's **`extension/`** folder, the one containing `manifest.json`. Do not select the ZIP or repository root.
4. Click Chrome's puzzle-piece icon and pin **Parallax**.
5. Refresh tabs that were open before installation, then open Parallax from the toolbar.

To update, replace the files in the same folder (or pull the latest repository), click **Reload** on Parallax's card in `chrome://extensions`, and refresh your existing tabs.

## Server settings

You do not need to run Python to try hosted features. With no saved address, Parallax checks the hosted server's `/health` for up to three seconds. If that check fails, it selects `http://localhost:8787`. It caches the selection for five minutes for hosted, or thirty seconds for local. Failed scan requests do not automatically switch servers.

Open the popup's **Server settings**, enter an `http://` or `https://` address, and click **Save server** to use a particular backend. A saved address overrides automatic selection. The current hosted address is listed in the [root README](../README.md#try-it).

Local setup is optional: follow the [root README](../README.md#getting-started) to install Python dependencies, then run from the repository root:

```sh
uvicorn parallax.server:app --port 8787
```

Set **Server address** to `http://localhost:8787`. An optional repository-root `.env` is loaded at startup; explicit environment variables take precedence. Restart the backend after changing it. Local Gemma setup is described in the root README.

## Scan pages and files

- Open a web page or Gmail message. Click a warning pill or open the popup to review findings. **Show on page** reveals hidden text; **Hide again** restores the page.
- Use the popup's **Scan this site** switch to pause or resume scanning for the current hostname. Pausing one site does not pause other sites or manual file scans.
- **Scan a file** opens a full tab where you can choose or drop a PDF, Word `.docx`, saved email `.eml`, or `.html`/`.htm` file (up to 20 MB). Results include hidden text, where it was hidden, why it matters, and email attachments. Use **Scan another file** to reset.
- On an open PDF tab, choose **Scan this PDF**. You can also right-click a file link and choose **Scan this file with Parallax**.
- AI-bot comparison checks whether a page serves AI agents different content. It needs the server even though basic page scanning works offline.

## Troubleshooting

- **No scan on an existing tab:** refresh it after installation or an extension reload. Check that scanning is enabled for that site. Chrome's internal pages are not scannable; use **Scan this PDF** for PDFs.
- **Server unavailable or slow:** check the saved address in **Server settings** and visit its `/health` endpoint. Hosted service availability is required for hosted features. If you chose localhost, start your local backend. Basic page scanning continues offline.
- **Local PDF cannot be fetched:** in `chrome://extensions` → Parallax → **Details**, enable **Allow access to file URLs**, or drag the file into the scan page.
- **Download fails for a signed-in document:** open and save it in your browser, then upload the saved file.
- **Unreadable document:** try another copy. Damaged or empty PDFs and malformed Word documents cannot be scanned; password-protected PDFs need an unlocked copy.
- **File too large:** choose a file no larger than 20 MB. The hosted server also enforces request-size and rate limits.
