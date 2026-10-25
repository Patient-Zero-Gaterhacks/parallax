# Parallax extension redesign integration

Adapted to upstream main at 47912f1535e36204bdf316c53c447e2bbfb12bfd.

## Install

Merge the included extension folder into the repository's extension folder.
Keep the current backend and frontend folders. This package contains the complete
extension, including the scan page, server helper, detector and model files.

In Chrome, open chrome://extensions, enable Developer mode, and choose Load
unpacked, then select the extension folder. If already installed, click Reload.
Reload web pages that were open before the extension update.

The built-in classifier works without the server. For file scans, bot-view
comparisons and optional Gemma classification, start the existing backend from
the repository root:

```sh
uvicorn parallax.server:app --port 8787
```

The popup's Server settings can point to a different HTTP or HTTPS backend.
Files open in the dedicated scan tab so results persist after the popup closes.
The existing 20 MB limit, document attachment results, open-PDF button and
right-click file scanning remain available.

## Integration choices

- Imported the supplied dark popup, branded icons, compact threat pill and card.
- Added per-site pause/resume, synchronized toolbar state and popup findings.
- Preserved upstream carousel, same-site link and modern-color handling, the
  offline classifier, current models and backend routes.
- Preserved scan.html, scan.js and server.js; did not import the ZIP's older
  detector or replace the backend or website frontend.
- Grouped only fragments from the same element. The card lists every hidden
  message with how it was hidden, including cautions alongside threats.
- Discarded stale asynchronous scan responses after pause/resume or newer scans.
- Gemma confirmation is shown only for a positive Gemma instruction vote.

## Validation

Passed:
- extension/test/detect.test.js (15 detector cases)
- extension/test/ui.test.js (DOM integration: popup, alerts, all findings,
  reveal, pause/resume, stale responses, false-alarm rules, file/PDF routing,
  server settings, unsupported tabs and no active tab)
- tests/test_extension_pipeline.py (extension detector to actual scanner API)
- tests/test_server.py (including PDF and Word scans)
- tests/test_second_pass.py (including mocked Gemma behavior)
- tests/test_detect_env.py (with host proxy variables unset)
- JavaScript syntax checks and git diff --check

Run JS checks with jsdom installed in the test environment, for example:

```sh
cd extension
npm install --no-save jsdom
node test/detect.test.js
node test/ui.test.js
```

Browser-based color and real-site fixture suites were not run: Chromium could
not be downloaded in the build environment. The new interface has DOM-level
coverage, but needs a manual Chrome smoke test for visual appearance and actual
extension permissions. No live Gemma model was downloaded or evaluated.

The package also includes extension-redesign.patch for applying this change
against the upstream commit above. Apply that patch OR copy the extension
folder; do not do both. No GitHub commits or pushes were made.
