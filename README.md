# Parallax: antivirus for AI

Your AI assistant should never act on something you can't see.

AI assistants read email, PDFs, Word files and web pages, and attackers now
hide instructions in them that only the AI can see. Parallax finds that
hidden content and stops an assistant from acting on it.

## What's here

| Piece | Path | What it does |
| --- | --- | --- |
| Scan engine | `parallax/scan.py`, `parallax/gap/` | One verdict (threat / caution / clean) for HTML email, `.eml` with attachments, PDF, Word, web pages |
| Detectors | `parallax/detect.py` | "Is this hidden text talking to an AI?" Patterns + **our trained model** always; Gemma 4, our fine-tuned transformer, Prompt Guard 2, Azure Prompt Shields when configured |
| Trained models | `ml/`, `parallax/models/` | Classifier trained on Microsoft LLMail-Inject + other public sets; runs in the server and inside the extension. GPU script adds Perplexity BrowseSafe. See `ml/README.md` |
| Action guard | `parallax/guard/` | Planner/reader split, labels, dual extraction, policy on send/pay/remember/open |
| API + attack lab | `parallax/server.py` | `/scan/*`, `/classify`, `/assistant`, `/demo`, `/lab` |
| Demo UI | `parallax/static/demo.html` | María's inbox; same request with and without Parallax |
| Chrome extension | `extension/` | Scans the live page and open Gmail messages; badge + panel; right-click "Scan this file with Parallax"; cloaking check |
| MCP gateway | `parallax/mcp_gateway/` | Sits between Claude Desktop/Cursor and your MCP servers: pins tool definitions, quarantines poisoned tools, strips hidden text from results, blocks or pauses risky actions |

## Run it

New here? `docs` walkthrough: "Parallax — Run It Yourself". Get the data with `bash scripts/get_data.sh`.

```bash
pip install -r requirements.txt
export GEMINI_API_KEY=...            # optional: turns on Gemma 4 detector + reader
uvicorn parallax.server:app --port 8787
```

* Demo: http://localhost:8787/demo
* Attack lab: http://localhost:8787/lab
* Extension: Chrome -> `chrome://extensions` -> Developer mode -> Load unpacked -> `extension/`.
  Visit the lab pages or open an email in Gmail; right-click a PDF/Word link -> "Scan this file with Parallax".

Optional detectors: `PARALLAX_PROMPT_GUARD=1` (accept Meta's license on
Hugging Face first, needs `transformers` + `torch`), or
`CONTENT_SAFETY_ENDPOINT` / `CONTENT_SAFETY_KEY` for Azure Prompt Shields.
`PARALLAX_GEMMA_PLANNER=1` lets Gemma write plans instead of the fixed demo plans.

## MCP gateway (Claude Desktop, Cursor)

1. Copy `gateway.example.json` to `gateway.json` and list the MCP servers you
   want protected (any stdio server: `command`, `args`, `env`).
2. Point your client at Parallax instead of those servers. Claude Desktop
   (`claude_desktop_config.json`) or Cursor (`.cursor/mcp.json`):

```json
{"mcpServers": {"parallax": {"command": "python",
  "args": ["-m", "parallax.mcp_gateway", "--config", "/full/path/gateway.json"],
  "env": {"PYTHONPATH": "/full/path/parallax"}}}}
```

3. Keep `uvicorn parallax.server:app --port 8787` running for the approval page.

What it does: tools appear as `server__tool`. Poisoned descriptions are never
shown to the model; a tool whose definition changes is hidden until you run
`python -m parallax.mcp_gateway approve-tool server/tool`. Email/HTML results
have hidden text removed. Sending to an address that only appeared in hidden
text is blocked; using an address/link/amount read from a tool result pauses
until you click Approve at `http://localhost:8787/approve/<id>` (single use).
`python -m parallax.mcp_gateway status` shows what happened.

The demo server `parallax.mcp_gateway.demo_mail_server` has poisoned emails;
`DEMO_POISON=1` poisons a tool description, `DEMO_RUG_PULL=1` changes one.

## Tests

```bash
for t in tests/test_*.py; do python3 $t; done        # 99 checks
cd extension && npm i jsdom && node test/detect.test.js   # 15 checks
python3 eval/run_eval.py                              # guard: 56 attacks + 7 benign
python3 ml/eval_pipeline.py                           # patterns vs patterns + trained model
JSDOM_PATH=extension/node_modules/jsdom python3 eval/run_full_eval.py   # all containers
```

## Honest accuracy (offline, without Gemma)

* Hidden text found: every hiding technique we built, across email, PDF, Word and web.
* Hidden text that adds an address, amount, link or phone you can't see:
  caught on held-out examples too (6/6), because the check is structural.
* Hidden instructions with no facts: pattern rules alone caught 0/210 of AgentDojo's
  attacks (written by ETH Zurich researchers, never trained on). With the hidden-facts
  check and our trained model: 158/210 threats + 24 cautions. Details: `ml/README.md`.
* Harmful actions (pay/send/remember from hidden text): blocked 56/56 by
  the guard even with a reader that obeys the attacker.
* Benign hidden content (preheaders, screen-reader labels, collapsed FAQs,
  scanned-PDF text layers): 0 false threats in our set.

## Known limits

* Gemma not yet measured live (build sandbox had no API access).
* The gateway uses the MCP Python SDK 2.x; confirm it connects to your
  Claude Desktop/Cursor version on day one.
* The gateway can't see your chat, so an address you typed that ALSO
  appeared in a tool result still pauses for approval (add it to `allow`).
* Cloaking keyed on IP address can't be seen by changing the user agent.
* A scanned PDF whose invisible text differs from its image needs a vision check.
* The extension shows the danger but can't stop another company's assistant;
  the guard protects assistants built on Parallax.

Layer 2 follows Google DeepMind's CaMeL design (2025); dual extraction is ours.

MIT license.
