"""Test Parallax on BrowseSafe++ pages it has never seen (our 20% held-out share).

    python3 -I ml/eval_browsesafe.py                     # full Parallax scanner on the HTML pages
    python3 -I ml/eval_browsesafe.py --source ./folder   # use a local copy instead of downloading
    python3 -I ml/eval_browsesafe.py --n-pairs 2000      # quicker run on part of the data
    PARALLAX_ML_TRANSFORMER=models/parallax-gemma python3 -I ml/eval_browsesafe.py   # with fine-tuned Gemma
    GEMINI_API_KEY=...  python3 -I ml/eval_browsesafe.py --n-pairs 300               # with zero-shot Gemma

Each pair = an attacked page + the same page with the attack removed. A good
detector flags the first and not the second. Results are split by where the
attack sits, because Parallax is built to catch hidden text: attacks rewritten
into visible paragraphs are a different problem (we report them anyway).
"""

import argparse
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml import bspp  # noqa: E402
from parallax.detect import default_detectors, page_chunks  # noqa: E402
from parallax.scan import scan_html  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=None)
    ap.add_argument("--n-pairs", type=int, default=None)
    ap.add_argument("--all-pairs", action="store_true", help="test on every pair (only for a model that was not trained on BrowseSafe++)")
    ap.add_argument("--mode", choices=["scanner", "page"], default="scanner",
                    help="scanner = Parallax as shipped (judges hidden text only); "
                         "page = run the detectors on the whole page text (what a page classifier like fine-tuned Gemma does)")
    ap.add_argument("--caution-counts", action="store_true", help="count 'caution' as flagged too")
    a = ap.parse_args()

    train, test = bspp.load(view="html" if a.mode == "scanner" else "markdown", source=a.source, n_pairs=a.n_pairs)
    if a.all_pairs:
        test = train + test
    dets = default_detectors()
    print(f"BrowseSafe++ held-out pairs: {len(test)}   detectors: {[d.name for d in dets]}\n")
    flagged = ("threat", "caution") if a.caution_counts else ("threat",)
    by = defaultdict(lambda: [0, 0, 0, 0])   # caught, n, false alarms, pair-correct
    t0 = time.time()
    def judge(content):
        if a.mode == "scanner":
            return scan_html(content, dets).verdict in flagged
        for c in page_chunks(content):
            for d in dets:
                v = d(c)
                if v.flagged or (a.caution_counts and getattr(v, "unsure", False)):
                    return True
        return False

    for i, p in enumerate(test):
        hit = judge(p.malicious.content)
        fa = judge(p.benign.content)
        for key in (bspp.placement(p), "HIDDEN placements" if bspp.is_hidden(p) else "VISIBLE placements", "ALL"):
            s = by[key]
            s[0] += hit; s[1] += 1; s[2] += fa; s[3] += hit and not fa
        if (i + 1) % 200 == 0:
            print(f"  ...{i + 1}/{len(test)} ({time.time() - t0:.0f}s)")
    print(f"\n{'placement':30s} {'attacks caught':>16s} {'clean twins flagged':>21s} {'pair right':>12s}")
    order = ["ALL", "HIDDEN placements", "VISIBLE placements"] + sorted(k for k in by if k not in
                                                                       ("ALL", "HIDDEN placements", "VISIBLE placements"))
    for k in order:
        c, n, fa, pc = by[k]
        print(f"{k:30s} {f'{c}/{n} ({100 * c // max(n, 1)}%)':>16s} {f'{fa}/{n} ({100 * fa // max(n, 1)}%)':>21s} "
              f"{f'{100 * pc // max(n, 1)}%':>12s}")
    print("\n'pair right' = flagged the attacked page AND left its clean twin alone.")


if __name__ == "__main__":
    main()
