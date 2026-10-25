"""Detect AI-targeted cloaking: a site serving AI agents a different page.

Fetch the same URL as a person's browser and as known AI agents, and
diff what each would read, sentence by sentence. Sentences only the AI
gets are content the person never sees.

Limitation: sites can also spot agents by IP address or browser
fingerprint. We only change the user-agent, so cloaking based on IP
ranges won't show up here.
"""

from __future__ import annotations

import difflib
import re

import httpx

from .html_gap import analyze_html
from .text import instruction_score

HUMAN_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
AGENT_UAS = {
    "ChatGPT-User": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; ChatGPT-User/1.0; +https://openai.com/bot",
    "PerplexityBot": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; PerplexityBot/1.0; +https://perplexity.ai/perplexitybot)",
    "GPTBot": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; GPTBot/1.1; +https://openai.com/gptbot",
    "Google-Extended": "Mozilla/5.0 (compatible; Google-Extended)",
}


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [re.sub(r"\s+", " ", p).strip() for p in parts if len(p.strip()) > 3]


def _readable(html: str) -> str:
    # Visible text only; hidden spans are checked separately by the scanner.
    return analyze_html(html)["visible_text"]


def diff_pages(human_html: str, agent_html: str) -> dict:
    a, b = _sentences(_readable(human_html)), _sentences(_readable(agent_html))
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    only_agent, only_human = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("replace", "insert"):
            only_agent += b[j1:j2]
        if tag in ("replace", "delete"):
            only_human += a[i1:i2]
    # Ignore near-identical rewordings (timestamps, rotating ads).
    def novel(s, pool):
        return all(difflib.SequenceMatcher(a=s, b=p).ratio() < 0.85 for p in pool)

    only_agent = [s for s in only_agent if novel(s, a)]
    only_human = [s for s in only_human if novel(s, b)]
    score = sum(instruction_score(s)[0] for s in only_agent)
    return {"only_agent": only_agent, "only_human": only_human,
            "cloaked": bool(only_agent or only_human), "instruction_score": score}


def check_url(url: str, client: httpx.Client | None = None) -> dict:
    own = client is None
    client = client or httpx.Client(follow_redirects=True, timeout=15)
    try:
        human = client.get(url, headers={"User-Agent": HUMAN_UA}).text
        out = {}
        for name, ua in AGENT_UAS.items():
            out[name] = diff_pages(human, client.get(url, headers={"User-Agent": ua}).text)
        return {"url": url, "agents": out,
                "cloaked_for": [n for n, r in out.items() if r["cloaked"]]}
    finally:
        if own:
            client.close()
