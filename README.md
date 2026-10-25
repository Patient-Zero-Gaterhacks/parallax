# Parallax

**Antivirus for AI assistants.** Built at Gator Hack V.

AI assistants read our emails, PDFs, Word files and web pages. Attackers can
hide instructions in them (white text, tiny fonts, hidden layers) that a
person can't see but the AI still reads and follows. Parallax finds that
hidden text and stops the assistant from acting on it.

## Features

- **Hidden-text scanner**: checks HTML emails, `.eml` files with attachments, PDFs, Word files and web pages, and gives one verdict: threat, caution or clean.
- **Trained model**: a fast classifier that decides whether hidden text is "talking to an AI". It runs on the server and inside the Chrome extension, with Gemma 4 as an optional second check.
- **Chrome extension**: scans the page you're on and open Gmail messages, highlights hidden text, and lets you right-click a PDF or Word link to scan it.
- **Action guard**: blocks an assistant from sending, paying, sharing or remembering anything that came from hidden text.
- **MCP gateway**: sits between Claude Desktop or Cursor and your tools, removes hidden text from results, and pauses risky actions until you approve them.
- **Demo + attack lab**: a demo inbox that shows the same request with and without Parallax.

## Project structure

```
parallax/
├── parallax/            # Backend (Python)
│   ├── gap/             # Finds hidden text in HTML, PDF, Word and web pages
│   ├── guard/           # Stops the assistant from acting on hidden text
│   ├── mcp_gateway/     # Protects Claude Desktop / Cursor tools
│   ├── models/          # Trained model files
│   ├── static/          # Demo page
│   ├── scan.py          # One scanner for every file type
│   ├── detect.py        # Decides if hidden text is talking to an AI
│   └── server.py        # API, demo and attack lab
├── frontend/            # Web app (React + Vite), empty for now
├── extension/           # Chrome extension
├── ml/                  # Training and testing the model
├── eval/                # Evaluation scripts
├── tests/               # Tests
├── scripts/get_data.sh  # Downloads the public datasets
├── .env.example         # Settings and API keys (copy to .env)
├── requirements.txt     # What you need to run Parallax
└── requirements-ml.txt  # Extra packages, only for retraining the model
```

## What you need

- Python 3.10 or newer
- Git
- Google Chrome (for the extension)
- Node.js 18 or newer (for the frontend and the extension tests)

## Setup

1. Clone the repo:

   ```bash
   git clone https://github.com/Patient-Zero-Gaterhacks/parallax.git
   cd parallax
   ```

2. Make a virtual environment and turn it on:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
   ```

3. Install the packages:

   ```bash
   pip install -r requirements.txt
   ```

4. Make your `.env` file and add any keys you have (all optional, e.g. a Gemini API key turns on the Gemma 4 check):

   ```bash
   cp .env.example .env
   ```

   Load it into your terminal before running the server:

   ```bash
   set -a; source .env; set +a      # Windows: set each variable with $env:NAME="value"
   ```

## Run it

Start the server:

```bash
uvicorn parallax.server:app --port 8787
```

- Demo: http://localhost:8787/demo
- Attack lab: http://localhost:8787/lab

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Then open http://localhost:5173.

### Chrome extension

1. Go to `chrome://extensions` and turn on **Developer mode**.
2. Click **Load unpacked** and pick the `extension/` folder.
3. Visit a lab page or open an email in Gmail. Right-click a PDF or Word link and choose **Scan this file with Parallax**.

### MCP gateway (Claude Desktop / Cursor)

1. Copy `gateway.example.json` to `gateway.json` and list the MCP servers you want to protect.
2. In your Claude Desktop or Cursor config, point to Parallax instead of those servers:

   ```json
   {"mcpServers": {"parallax": {"command": "python",
     "args": ["-m", "parallax.mcp_gateway", "--config", "/full/path/gateway.json"],
     "env": {"PYTHONPATH": "/full/path/parallax"}}}}
   ```

3. Keep the server running so you can approve paused actions at `http://localhost:8787/approve/<id>`.

## Tests

```bash
for t in tests/test_*.py; do python3 $t; done
cd extension && npm i jsdom && node test/detect.test.js
```

## Retraining the model (optional)

```bash
pip install -r requirements-ml.txt
bash scripts/get_data.sh                      # about 900 MB, saved to ../data_src
PARALLAX_DATA=../data_src python3 ml/train_fast_v2.py
```

More details are in `ml/README.md`.

## License

MIT