"""Does the trained model help Parallax? Patterns alone vs patterns + model.

Every example is treated as a passage hidden from the reader (as Parallax
sees it) and judged by the real scan logic. None of these examples were
trained on. Run: python3 ml/eval_pipeline.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml.eval_sets import ATTACKS, BENIGN  # noqa: E402
from parallax.detect import MLDetector, PatternDetector  # noqa: E402
from ml.gemma_columns import extra_setups  # noqa: E402
from parallax.gap.html_gap import HiddenSpan  # noqa: E402
from parallax.scan import _judge  # noqa: E402

VISIBLE = "Hi, here is the information you asked for. Thanks, Jordan"
SETUPS = {"patterns only": [PatternDetector()], "model only": [MLDetector()],
          "patterns + model": [PatternDetector(), MLDetector()]}
SETUPS.update(extra_setups())


def levels(texts, dets):
    return [_judge([HiddenSpan(t, ["display:none"])], VISIBLE, dets, long_passage_caution=False)[0].level
            for t in texts]


def main():
    rows = []
    print(f"{'':34s}" + "".join(f"{k:>22s}" for k in SETUPS))
    for group, sets in (("ATTACK", ATTACKS), ("HARMLESS", BENIGN)):
        tot = {k: [0, 0, 0] for k in SETUPS}
        for name, texts in sets.items():
            cells = []
            for k, dets in SETUPS.items():
                lv = levels(texts, dets)
                th, ca = lv.count("threat"), lv.count("caution")
                tot[k][0] += th; tot[k][1] += ca; tot[k][2] += len(texts)
                cells.append(f"{th}/{len(texts)} (+{ca}?)")
            print(f"{group[0]} {name:32s}" + "".join(f"{c:>22s}" for c in cells))
        label = "attacks -> threat" if group == "ATTACK" else "harmless -> threat"
        print(f"  {label:32s}" + "".join(
            f"{f'{a}/{n} ({100 * a // n}%) +{c}?':>22s}" for a, c, n in tot.values()))
        rows.append(tot)
        print()
    print("(+N?) = also raised as 'caution' (a softer warning), not counted as caught.")
    return rows


if __name__ == "__main__":
    main()
