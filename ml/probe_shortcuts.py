"""Shortcut probe: does the model react to formatting instead of meaning?

Each probe takes the same text twice, once plain and once with a harmless
change (a URL, "**" bold markers, an Enron-style reply quote, a "Body:" label).
The meaning doesn't change, so a model that learned the security concept
should give about the same score both times. Big moves = shortcut learning.

Usage:
  python3 ml/probe_shortcuts.py                               # shipped model
  python3 ml/probe_shortcuts.py --model path/to/injection_lr.json
  python3 ml/probe_shortcuts.py --model a.json --model b.json  # compare two
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ml.eval_sets import ATTACKS, BENIGN  # noqa: E402

DEFAULT = ROOT / "parallax" / "models" / "injection_lr.json"


def load(path):
    """Load a model JSON and return a score(text) function (same math as extension/ml.js)."""
    m = json.load(open(path))
    F, bias = m["features"], m["bias"]
    # A model file can say which normalizer it was trained with.
    if m.get("normalizer") == "v2":
        from parallax.ml_features import analyzer_v2 as analyzer
    else:
        from parallax.ml_features import analyzer

    def score(text):
        counts = {}
        for f in analyzer(text):
            if f in F:
                counts[f] = counts.get(f, 0) + 1
        vals = [((1 + math.log(n)) * F[f][0], F[f][1]) for f, n in counts.items()]
        norm = math.sqrt(sum(v * v for v, _ in vals)) or 1
        z = bias + sum(v / norm * w for v, w in vals)
        return 1 / (1 + math.exp(-max(-30, min(30, z))))

    return score


ATK = [t for v in ATTACKS.values() for t in v]
BEN = [t for v in BENIGN.values() for t in v]

# Each probe: (name, which texts, transform). Meaning stays the same.
PROBES = [
    ("attack + a normal URL sentence", ATK, lambda t: t + " More info at https://www.example.com/help"),
    ("attack + Enron-style spaced URL", ATK, lambda t: t + " see http : / / www . example . com"),
    ("attack + Enron-style quote marks", ATK, lambda t: "> > " + t),
    ("attack + an Enron name (Vince)", ATK, lambda t: "Vince, " + t),
    ("benign + 'Body:' label", BEN, lambda t: "Body: " + t),
    ("benign + **bold** markers", BEN, lambda t: "**" + t + "**"),
    ("benign + angle-bracket tag", BEN, lambda t: "<div> " + t + " </div>"),
    ("benign + a URL", BEN, lambda t: t + " https://www.example.com"),
]


def run(path):
    score = load(path)
    print(f"\n=== {path}")
    print(f"{'probe':40s} {'avg score before':>16s} {'after':>8s} {'flips':>14s}")
    total_shift = 0.0
    for name, texts, tf in PROBES:
        before = [score(t) for t in texts]
        after = [score(tf(t)) for t in texts]
        # a "flip" = crosses the extension's 0.85 threat line or 0.5 caution line
        flips = sum((b >= 0.5) != (a >= 0.5) or (b >= 0.85) != (a >= 0.85) for b, a in zip(before, after))
        shift = sum(abs(a - b) for a, b in zip(after, before)) / len(texts)
        total_shift += shift
        print(f"{name:40s} {sum(before)/len(before):16.3f} {sum(after)/len(after):8.3f} {flips:>6d}/{len(texts):<7d}")
    print(f"{'average |score change| per probe':40s} {total_shift/len(PROBES):16.3f}   (lower = less shortcut-y)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", action="append")
    args = ap.parse_args()
    for p in args.model or [DEFAULT]:
        run(p)
