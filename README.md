<div align="center">

# Parallax

**Antivirus for AI assistants.** Your AI reads what you can't see. Parallax finds it and stops your assistant from acting on it.

[![Gator Hack V](https://img.shields.io/badge/Gator%20Hack%20V-UF%202026-orange)](#)
[![Model](https://img.shields.io/badge/model-fine--tuned%20Gemma%203%201B-4285F4)](https://huggingface.co/brandenxo/parallax-gemma)
[![Data](https://img.shields.io/badge/trained%20on-BrowseSafe%2B%2B-6f42c1)](https://huggingface.co/datasets/perplexity-ai/browsesafe-plus-plus)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Chrome](https://img.shields.io/badge/Chrome-extension%20(MV3)-34A853)
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

<img src="docs/img/website.png" alt="Parallax website: Your AI reads what you can't see." width="100%">

</div>

## Overview

AI assistants now read our inboxes, browse for us and open our files. Attackers hide instructions in them (white text, 0px fonts, HTML comments, alt text, hidden PDF layers, pages that show AI agents different content) that a person never sees but the AI reads and may follow: forward these statements, pay this account, recommend this site.

Parallax compares what a person sees with what the AI reads, judges whether the difference is aimed at the AI, and blocks the assistant from acting on it. It works on live web pages and Gmail (Chrome extension), on emails, PDFs and Word files (scanner), and on the tools an assistant uses (MCP gateway).

<div align="center">
  <img src="docs/img/website_problem.png" alt="Same email, two readings: what you see vs what your AI reads" width="100%">
  <br>
  <sub><b>Same email, two readings.</b> Left: the email a person sees. Right: what an AI assistant receives, including a white-on-white instruction to pay a new account. Parallax flags it (talks to an AI, adds a hidden email address) and holds it back from the assistant.</sub>
</div>

## Try it

- **Demo inbox:** https://z6tfp4t9fcdojg-8787.proxy.runpod.net/demo — the same requests to an assistant, with and without Parallax
- **Attack lab:** https://z6tfp4t9fcdojg-8787.proxy.runpod.net/lab — pages and files with hidden attacks
- **Chrome extension:** load `extension/` unpacked ([steps](#2-chrome-extension)). It uses the hosted server, so our fine-tuned Gemma works with nothing running on your laptop.
- **Model:** [brandenxo/parallax-gemma](https://huggingface.co/brandenxo/parallax-gemma)

The hosted server runs on a rented GPU during judging and may be off afterwards; everything also runs locally ([Getting started](#getting-started)).

## How it works

1. **Find** text a person can't see but an AI reads. Web pages: the extension asks Chrome for real computed styles and layout (same color as the background, transparent, tiny, off-screen, clipped, covered, scaled to zero). Emails and HTML: inline and stylesheet CSS. PDFs: each text span is compared with the ink it actually renders. Word: hidden-text effects, colors, sizes. Everywhere: HTML comments, alt/title/aria/data-* text, hidden form fields, structured data, invisible Unicode, and look-alike links.
2. **Judge** each hidden passage. Instruction patterns and a fast word model check every passage (both also run offline inside the extension). Passages they react to go to **our fine-tuned Gemma 3 1B**, which confirms real attacks and clears false alarms. A hidden email, link or phone number the reader never saw is evidence on its own.
3. **Decide:** threat, caution or clean, with plain-language reasons ("written for an AI assistant", "same color as the background").
4. **Show** it: a red pill and card on the page, **Show on page** to reveal the hidden text, and a scan page for files.
5. **Stop** the action: the action guard and MCP gateway block sends, payments and memories that came from hidden text, and pause anything that uses details from untrusted content until you approve it.

```mermaid
flowchart LR
    A["(a) Email, web page,<br/>PDF, Word file,<br/>MCP tool result"] --> B["(b) Find hidden text<br/>styles · ink · comments<br/>markup · invisible Unicode"]
    B --> C["(c) Patterns +<br/>fast model<br/>every passage"]
    C -- reacted --> D["(d) Fine-tuned<br/>Gemma 3 1B<br/>second pass"]
    C -- silent --> E
    D --> E["(e) Verdict<br/>threat · caution · clean"]
    E --> F["(f) Extension card<br/>Show on page<br/>file scan report"]
    E --> G["(g) Action guard +<br/>MCP gateway<br/>block or pause"]
```

<sub><b>System overview.</b> (a) Content an assistant is about to read. (b) Finders for each format compare what a person sees with what the AI reads. (c) Fast checks judge every hidden passage. (d) Gemma reads only the passages the fast checks reacted to, so a page with 100 hidden passages costs a couple of Gemma calls. (e) One verdict format for every input. (f) What the person sees. (g) What the assistant is allowed to do.</sub>

<table>
  <tr>
    <td width="50%"><img src="docs/img/extension_threat.png" alt="Extension card on a page with hidden instructions"><br><sub><b>Chrome extension.</b> A recipe page hides two instructions for AI. The card explains each one; Show on page reveals them in red.</sub></td>
    <td width="50%"><img src="docs/img/demo.png" alt="Demo inbox, with and without Parallax"><br><sub><b>Demo inbox.</b> "Summarize my email from the clinic": without Parallax the assistant sends María's bank statements to the attacker and saves a fake support number. With Parallax it just summarizes.</sub></td>
  </tr>
  <tr>
    <td width="50%"><img src="docs/img/scan_file.png" alt="File scan page finding a hidden instruction in a PDF"><br><sub><b>File scan.</b> A résumé PDF with an invisible "rank them first" note for AI screeners.</sub></td>
    <td width="50%"><b>What's in the repo</b><br><br>

| Part | Path |
| --- | --- |
| Finders (HTML, PDF, Word, cloaking) | `parallax/gap/` |
| Judge and one scanner for every input | `parallax/scan.py`, `parallax/detect.py` |
| Server, demo, attack lab, public mode | `parallax/server.py` |
| Action guard | `parallax/guard/` |
| MCP gateway | `parallax/mcp_gateway/` |
| Chrome extension | `extension/` |
| Website | `frontend/` |
| Training and evaluation | `ml/` |
| Tests | `tests/` |

</td>
  </tr>
</table>

## Results

Every test set below was held out: never trained on, and settings weren't chosen on it. More detail in [`ml/README.md`](ml/README.md).

**Our fine-tuned Gemma 3 1B on BrowseSafe++** (Perplexity, October 2026). Official test, run once, on the 20% of pairs we held out: 5,843 attacked/clean page pairs, with the same injection text never on both sides of the split. The page is read in up to 8 chunks and flagged if any chunk scores at least 0.85.

| | Fine-tuned Gemma 3 1B | Our fast model (V2) |
| :--- | :---: | :---: |
| Attacks caught (attack within the 8 chunks read) | **4,515 / 4,781 (94.4%)** | 3,241 (67.8%) |
| Clean pages flagged | **227 / 4,781 (4.7%)** | 1,774 (37.1%) |
| Both right: attack caught, clean twin not flagged | **89.7%** | 32.1% |
| Hidden placements: caught / clean flagged (of 495) | **398 / 12** | 279 / 128 |
| Other languages: caught (of 652) | **510** | 227 |

**The whole Parallax pipeline**, from finding the hidden text to the verdict:

| | Patterns + fast model | + fine-tuned Gemma |
| :--- | :---: | :---: |
| AgentDojo attacks (ETH Zurich, 210) → threat | 109 (51%) | **148 (70%)** |
| AgentDojo harmless content (231) → threat | 25 | 27 |
| Hand-written hidden attacks (44) → threat | 30 (68%) | **32 (72%)** |
| Hand-written harmless hidden text (36) → threat | 0 | 1 |

Notes:

- Counting every BrowseSafe++ page, including long ones whose attack sits past the 8 chunks Gemma reads: 4,590 / 5,843 caught (78.6%).
- The first version of the second pass let Gemma cancel the fast model's catches everywhere, which **lowered** the hand-written result to 24/44 (Gemma alone is weak on subtle "steering" text). We changed the rule so that in emails and files Gemma can upgrade a warning but not cancel a confident catch; the table shows that version. On live web pages Gemma can still cancel fast-model alarms, because that is what removed false alarms on real sites. This change was made after seeing these test results.
- Gemma turns vague warnings into firm answers: with it there are fewer "caution" results, and a few attacks that used to get a caution now get none (hand-written: 30 threat + 9 caution without Gemma, 32 + 0 with).
- A second, longer Gemma training run caught slightly more but was "unsure" on far more clean text. It didn't pass the bar we set before training, so we ship the first.
- Weak spot: BIPIA (mostly off-topic questions rather than instructions; 6 / 75 caught).
- **Real websites:** in a 30-site manual test (Wikipedia, GitHub, BBC, CNN, NYT, Apple, Etsy...), every remaining warning came from rules, not the models, and Gemma cleared the one model-made false alarm. We also use 243 saved real pages from the Mozilla Readability and Trafilatura test sets to find and fix the rules behind false alarms (`tests/test_real_site_false_alarms.py`).

## Limitations

- Gemma reads up to 8 chunks of a page; attacks deeper in very long pages are only seen by the faster checks.
- In the live page scan, Gemma only sees hidden passages the fast checks reacted to.
- The extension judges what Chrome renders. A site that shows AI agents different content (cloaking) is checked separately by the server.
- Instructions written in plain **visible** text aren't flagged by the page scan (they aren't hidden). Gemma is good at these (1,250 / 1,611 rewritten paragraphs in BrowseSafe++), and it's what we'd add next.

## Getting started

### Prerequisites

- Python 3.10+, Git, Google Chrome
- Node.js 18+ (website and extension tests)
- For our Gemma model locally: `pip install -r requirements-ml.txt` (PyTorch + Transformers); a GPU helps but isn't required

### 1. Server

```bash
git clone https://github.com/Patient-Zero-Gaterhacks/parallax.git
cd parallax
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn parallax.server:app --port 8787
```

Demo at http://localhost:8787/demo, attack lab at http://localhost:8787/lab. To add our fine-tuned Gemma as the second pass:

```bash
pip install -r requirements-ml.txt
PARALLAX_ML_TRANSFORMER=brandenxo/parallax-gemma uvicorn parallax.server:app --port 8787
```

`GET /health` lists the detectors that are on.

### 2. Chrome extension

1. Open `chrome://extensions` and turn on **Developer mode**.
2. **Load unpacked** → pick the `extension/` folder. After pulling new code, click reload ↻ and refresh open tabs.
3. Visit a lab page or open an email in Gmail. A red pill appears when hidden text is aimed at AI; click it for details and **Show on page**.
4. **Scan a file** in the popup opens a scan page for PDFs, Word files and saved emails. On an open PDF, use **Scan this PDF**; right-click a file link for **Scan this file with Parallax**.
5. The extension uses the hosted server by default and falls back to `http://localhost:8787`; set another one in the popup's **Settings**. Without any server, the page scan still works offline with the built-in model.

### 3. Website

```bash
cd frontend && npm install && npm run dev      # http://localhost:5173
```

### 4. MCP gateway (Claude Desktop, Cursor, Claude Code)

1. Copy `gateway.example.json` to `gateway.json` and list the MCP servers you want to protect.
2. Point your client at Parallax instead of those servers:

   ```json
   {"mcpServers": {"parallax": {"command": "python",
     "args": ["-m", "parallax.mcp_gateway", "--config", "/full/path/gateway.json"],
     "env": {"PYTHONPATH": "/full/path/parallax"}}}}
   ```

3. Keep the server running to approve paused actions at `http://localhost:8787/approve/<id>`, or run `python -m parallax.mcp_gateway approve <id>`.

### Optional detectors

| Variable | Turns on |
| --- | --- |
| `PARALLAX_ML_TRANSFORMER` | `parallax-transformer`, our fine-tuned Gemma 3 1B (a folder or `brandenxo/parallax-gemma`) |
| `PARALLAX_ZERO_SHOT_GEMMA=1` + `GEMINI_API_KEY` | `gemma-4`, untrained Gemma 4 31B via the Gemini API (both needed) |
| `PARALLAX_PROMPT_GUARD=1` | `prompt-guard-2` (accept Meta's license on Hugging Face first) |
| `CONTENT_SAFETY_ENDPOINT` + `CONTENT_SAFETY_KEY` | `azure-prompt-shields` |

Keys go in your environment or a `.env` file (`cp .env.example .env`); never commit them.

### Hosting it for others

`scripts/serve_public.sh` runs the server in **public mode** (`PARALLAX_PUBLIC=1`): URL scans only reach public addresses (checked again on every redirect), the approval and gateway pages are off, uploads and requests are size-capped and each client IP is rate-limited. We host it on a RunPod GPU pod with HTTP port 8787 exposed:

```bash
nohup bash scripts/serve_public.sh > /dev/null 2>&1 &      # logs: /workspace/server.log
```

## Tests

```bash
for t in tests/test_*.py; do python3 $t | tail -1; done
cd extension && npm i --no-save jsdom && node test/detect.test.js && node test/ui.test.js
```

Browser tests (`test_extension_*`, `test_web_false_alarms.py`, `test_finder_gaps.py`) load the real extension in Chromium through Playwright and skip if it isn't installed.

## Training and evaluation

```bash
pip install -r requirements-ml.txt
bash scripts/get_data.sh                                   # public datasets, about 900 MB, into ../data_src
PARALLAX_DATA=../data_src python3 ml/train_fast_v2.py      # fast model
python3 -I ml/eval_pipeline.py                             # hand-written hidden attacks
PARALLAX_DATA=../data_src python3 -I ml/eval_external.py   # AgentDojo
```

Fine-tuning Gemma (`ml/train_transformer.py`) and the BrowseSafe++ split (`ml/bspp.py`) are described in [`ml/README.md`](ml/README.md).

## Credits and licenses

- **BrowseSafe++** by Perplexity (October 2026), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/): training data for our fine-tuned Gemma (our 80% split) and its held-out test (our 20% split, `ml/bspp.py`).
- **Gemma 3 1B** by Google: our model is a fine-tune of `google/gemma-3-1b-pt`, distributed under the [Gemma Terms of Use](https://ai.google.dev/gemma/terms) and [Prohibited Use Policy](https://ai.google.dev/gemma/prohibited_use_policy).
- Fast-model training data: [LLMail-Inject](https://github.com/microsoft/llmail-inject-challenge-analysis) (Microsoft), [Enron spam](https://github.com/MWiechmann/enron_spam_data), [InjecAgent](https://github.com/uiuc-kang-lab/InjecAgent) (UIUC), [Tensor Trust](https://github.com/HumanCompatibleAI/tensor-trust-data).
- Test only: [AgentDojo](https://github.com/ethz-spylab/agentdojo) (ETH Zurich), [BIPIA](https://github.com/microsoft/BIPIA) (Microsoft).
- Real-page false-alarm checks: saved pages from [Mozilla Readability](https://github.com/mozilla/readability) and [Trafilatura](https://github.com/adbar/trafilatura) test sets.

Each dataset keeps its own license; see the links.

## License

MIT for our code ([LICENSE](LICENSE)). The fine-tuned model follows the Gemma Terms of Use.

Built at Gator Hack V (University of Florida) by Branden Rivera and Jesica Bermudes.
