"""Look inside the trained model.

  python3 ml/inspect_model.py                 # the words the model learned matter most
  python3 ml/inspect_model.py "some text"     # score a passage and show WHY

The model is just a list of ~60,000 features (words, word pairs, 4-letter
pieces), each with a weight. Positive = looks like an attack, negative =
looks harmless. A passage's score adds up the weights of the features in it.
"""

import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from parallax.ml_features import analyzer, normalize  # noqa: E402

M = json.load(open(ROOT / "parallax/models/injection_lr.json"))
F = M["features"]


def explain(text):
    counts = Counter(f for f in analyzer(text) if f in F)
    vals = {f: (1 + math.log(n)) * F[f][0] for f, n in counts.items()}
    norm = math.sqrt(sum(v * v for v in vals.values())) or 1
    contrib = {f: v / norm * F[f][1] for f, v in vals.items()}
    z = M["bias"] + sum(contrib.values())
    p = 1 / (1 + math.exp(-max(-30, min(30, z))))
    print(f"\ntext:       {text}\nnormalized: {normalize(text)}")
    verdict = "ATTACK (threat)" if p >= 0.85 else "maybe (caution)" if p >= 0.5 else "harmless"
    if len(text.split()) < 5:
        verdict += "  [note: Parallax ignores the model for passages under 5 words]"
    print(f"score:      {p:.3f}  -> {verdict}")
    print("pushed toward ATTACK by:  ", ", ".join(f"{f!r} {c:+.2f}" for f, c in sorted(contrib.items(), key=lambda x: -x[1])[:8]))
    print("pushed toward HARMLESS by:", ", ".join(f"{f!r} {c:+.2f}" for f, c in sorted(contrib.items(), key=lambda x: x[1])[:8]))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        for t in sys.argv[1:]:
            explain(t)
    else:
        w = sorted(F.items(), key=lambda kv: kv[1][1])
        print(f"{len(F)} features, trained on: {M.get('trained_on')}\n")
        print("Most ATTACK-like:  ", ", ".join(repr(k) for k, _ in w[::-1][:30]))
        print("\nMost HARMLESS-like:", ", ".join(repr(k) for k, _ in w[:30]))
        print("\n(a '#' feature is a 4-letter piece of a word; '_' marks a word's start or end)")
