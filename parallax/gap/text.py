"""Text-level checks shared by every input type.

Two separate questions:
  1. Can a person see this text?            (html_gap, pdf_gap, docx_gap, cloak)
  2. Is this text talking to an AI system?  (instruction_score, here)

Hidden text alone is common and harmless: email preheaders, scanned-PDF
OCR layers, accessibility labels. Only hidden text that also reads like
an instruction to an assistant is an attack signal.
"""

from __future__ import annotations

import re
import unicodedata

# Characters that render as nothing but reach a language model.
_INVISIBLE_RANGES = [
    (0x200B, 0x200F),   # zero-width space/joiners, LRM/RLM
    (0x202A, 0x202E),   # bidi embeddings/overrides
    (0x2060, 0x2064),   # word joiner, invisible operators
    (0x2066, 0x2069),   # bidi isolates
    (0xFEFF, 0xFEFF),   # zero-width no-break space / BOM
    (0xE0000, 0xE007F), # Unicode "tag" characters: invisible ASCII copies
]


def _is_invisible(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _INVISIBLE_RANGES)


def invisible_chars(text: str) -> dict:
    """Count invisible code points and decode any Unicode-tag payload."""
    count = sum(1 for c in text if _is_invisible(c))
    tag_payload = "".join(chr(ord(c) - 0xE0000) for c in text
                          if 0xE0020 <= ord(c) <= 0xE007E)
    return {"count": count, "tag_payload": tag_payload}


def strip_invisible(text: str) -> str:
    return "".join(c for c in text if not _is_invisible(c))


# Instruction-likeness: a cheap first pass. The other detectors in detect.py
# (our trained model, Gemma) give a second opinion. Patterns target text
# addressed to a model or demanding an action, not ordinary marketing copy.
_PATTERNS = [
    (3, r"\b(ignore|disregard|forget)\b.{0,40}\b(previous|prior|above|earlier|all)\b.{0,20}\b(instructions?|rules|prompts?)"),
    (3, r"\b(you are|as an?) (an? )?(ai|assistant|language model|llm|agent|reviewer|screener)\b"),
    (3, r"\b(system prompt|developer message|new instructions?)\b"),
    (3, r"\b(note|message|instructions?|memo)\s+(to|for)\s+(?:\w+\s+){0,3}(ai|assistants?|llms?|models?|screeners?|reviewers?|agents?|bots?|copilots?)\b"),
    # Addressing an AI directly by name or role ("Hey Gemini,", "Dear AI,", "Copilot, ...", "AI - send").
    # A dash only counts with a space on both sides: "AI-Infused Curriculum" and "Agent-based" aren't addresses.
    (3, r"(?:^|[.!?]\s+|\n)\s*(?:hey|hi|hello|dear|attention|attn|ok|okay)?[\s,]*(?:gemini|chatgpt|gpt|claude|copilot|siri|alexa|bard|ai|assistant|agent|bot|chatbot|(?:the\s+)?(?:language\s+)?model|llm)(?:\s+(?:agent|assistant|model|bot|system))?\b(?:\s*(?:reading this|processing this))?(?:\s*[,:!]|\s+[-–—](?=\s))"),
    # Attempts to replace the assistant's instructions.
    (3, r"\b(system|admin|developer|root)[\s-]+(override|mode|instructions?|prompt|command)\b|\byour\s+(new\s+)?(task|job|instructions?|goal|role)\s+(is|are|now)\b|\bstop following\b|\bdo what this (email|message|page|document|text) says\b|\bnew (objective|directive)\b"),
    # Text aimed at an automated evaluator (hiring, peer review, rankings).
    (3, r"\b(automated|ai|algorithmic|machine)[- ](screening|review|reviewers?|ranking|evaluation|assessment|grading|scoring)\b"),
    (3, r"\b(reviewers?|screeners?|evaluators?|graders?|recruiters?|ranking systems?)\b.{0,50}\b(consensus|should|must|recommend(ed)?|accept(ed)?|reject|advance|shortlist)\b"),
    (2, r"\b(prefer|choose|select|favor)\s+(it|this|them|us|our)\b.{0,40}\b(over|instead of|above)\b"),
    (2, r"\b(top\s+\d+%|best[- ]in[- ]class|only (safe|right|good) (choice|option)|strongest (candidate|applicant|submission))\b"),
    (2, r"\b(assistant|ai|agent|model|llm|chatbot|copilot)\b.{0,30}\b(must|should|need to|will|please)\b"),
    (2, r"\b(forward|send|email|transfer|wire|share|upload|export)\b.{0,60}\b(to|at)\b\s+\S+@\S+"),
    (2, r"\b(do not|don't|never)\s+(tell|mention|inform|alert|show)\b.{0,30}\b(user|owner|recipient|human)\b"),
    (2, r"\b(rank|rate|score|recommend|review)\b.{0,40}\b(highly|first|top|positive(ly)?|accept)\b"),
    (2, r"\b(remember|save|store)\b.{0,40}\b(from now on|permanently|for future|always)\b"),
    (3, r"\b(from now on|going forward|in (all )?future (chats|conversations|answers))\b.{0,60}\b(recommend|tell|say|use|send|direct|always|never|remember)\b"),
    (1, r"\b(click|visit|go to|open)\b.{0,30}https?://"),
    (1, r"\b(password|passcode|2fa|one-time code|bank|account number|routing)\b"),
    (1, r"\bfrom now on\b|\bimmediately\b|\burgent(ly)?\b"),
]
_COMPILED = [(w, re.compile(p, re.I | re.S)) for w, p in _PATTERNS]


def instruction_score(text: str) -> tuple[int, list[str]]:
    t = unicodedata.normalize("NFKC", strip_invisible(text))
    matched = [(w, p) for w, p in _COMPILED if p.search(t)]
    return sum(w for w, _ in matched), [p.pattern for _, p in matched]


ATTACK_THRESHOLD = 3  # pattern score that counts as "talks to an AI"
