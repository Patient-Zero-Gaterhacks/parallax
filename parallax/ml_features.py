"""Text normalization and features shared by training, the server and the extension.

extension/ml.js does the same steps in JavaScript; keep the two identical
(tests/test_ml.py checks this).

Why normalize so much: the training data comes from different places (old
Enron mail is lowercased with spaces around punctuation, attack emails are
modern), and a model will happily learn "looks like Enron = harmless".
Lowercasing, swapping addresses/links/numbers for placeholders and dropping
punctuation removes those shortcuts. It also stops the model from
memorizing the one attacker address a dataset uses.
"""

from __future__ import annotations

import re

EMAIL = re.compile(r"[\w.+-]+\s?@\s?[\w-]+(\s?\.\s?[\w-]+)+")
# Links, including the spaced-out form old email corpora use ("www . site . com", "http : / /").
URL = re.compile(r"(https?\s?:\s?/\s?/\s?[\w-]+(\s?[./]\s?[\w-]+)*\S*|www(\s?\.\s?[\w-]+)+\S*|\b[\w-]+(\s?\.\s?[\w-]+)*\s?\.\s?(com|net|org|io|dev|co|info|biz|app|xyz)\b\S*)")
EMAILWORD = re.compile(r"\be\s?-\s?mail")
LETTER = re.compile(r"[a-z]")
NUM = re.compile(r"\d+")
NONWORD = re.compile(r"[^a-z|\[\]{}*_ ]+")
# leftover pieces of broken links; they only mark which dataset a text came from
LINK_BITS = {"com", "net", "org", "www", "http", "https", "html", "htm"}
SPACES = re.compile(r"\s+")


def normalize(text: str) -> str:
    t = EMAILWORD.sub("email", text.lower())
    t = EMAIL.sub(" zemail ", t)
    t = URL.sub(" zlink ", t)
    t = NUM.sub(" znum ", t)
    t = NONWORD.sub(" ", t)
    # drop letterless tokens ("**", "> >"), single letters and link fragments:
    # formatting habits of one dataset, not meaning
    return " ".join(w for w in SPACES.split(t) if len(w) > 1 and LETTER.search(w) and w not in LINK_BITS)


def analyzer(text: str, _norm=None) -> list[str]:
    """Word unigrams + bigrams, and character 4-grams inside words (robust to typos)."""
    words = (_norm or normalize)(text).split(" ")[:400]
    feats = [w for w in words if w]
    feats += [a + " " + b for a, b in zip(words, words[1:])]
    for w in words:
        if 4 <= len(w) <= 30:
            p = "_" + w + "_"
            feats += ["#" + p[i:i + 4] for i in range(len(p) - 3)]
    return feats


# v2 normalizer, used when the model JSON says "normalizer": "v2".
# It fixes two shortcuts found by ml/probe_shortcuts.py:
#   1. Enron writes links with spaces ("http : / / www . enron . com"), so the
#      old URL regex missed them and "http", "www", "com" became "harmless" words.
#      Now spaced links also become " zlink ".
#   2. LLMail attackers use lots of < > [ ] { } * | _ to obfuscate, so those
#      symbols became "attack" signals and any HTML-ish text looked suspicious.
#      v2 drops all symbols; the words around them still carry the meaning.
# extension/ml.js has the same function (normalizeV2); keep them identical.
SPACED_URL = re.compile(r"\b(?:https?\s*:\s*/\s*/\s*|www\s*\.\s*)[\w-]+(?:\s*[./]\s*[\w-]+)*")
NONWORD_V2 = re.compile(r"[^a-z ]+")
LEFTOVER = re.compile(r"\b(?:https?|www)\b")


def normalize_v2(text: str) -> str:
    t = text.lower()
    t = SPACED_URL.sub(" zlink ", t)
    t = EMAIL.sub(" zemail ", t)
    t = URL.sub(" zlink ", t)
    t = NUM.sub(" znum ", t)
    t = NONWORD_V2.sub(" ", t)
    t = LEFTOVER.sub(" ", t)
    return SPACES.sub(" ", t).strip()


def analyzer_v2(text: str) -> list[str]:
    return analyzer(text, normalize_v2)
