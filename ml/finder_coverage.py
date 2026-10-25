"""How often does the hidden-text FINDER surface BrowseSafe++'s attack? (Before any judging.)

    python3 -I ml/finder_coverage.py                    # our training side (dev numbers, run freely)
    python3 -I ml/finder_coverage.py --split test       # our held-out 20%: report once, don't tune on it
    python3 -I ml/finder_coverage.py --source <dir> --n-pairs 2000

For every attacked page, the attack counts as "found" when one hidden or markup passage contains
most of the injection text (>= 60% of the words of an injection fragment). For the clean twin we
count passages and run the web judge with patterns + the fast model (no Gemma), to show the cost
of finding more. The finder has no trained parts, so the training side is fair dev data; still,
the test side is reported separately. Data: BrowseSafe++ (Perplexity, CC BY 4.0).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml import bspp  # noqa: E402
from parallax.detect import MLDetector, PatternDetector  # noqa: E402
from parallax.gap.html_gap import MARKUP, analyze_html  # noqa: E402
from parallax.scan import _judge  # noqa: E402

WORD = re.compile(r"[^\W_]+", re.U)


def words(t: str) -> list[str]:
    return [w.lower() for w in WORD.findall(t)]


def fragments(pair) -> list[str]:
    frags = json.loads(pair.metadata.get("injection_text_fragments_json") or "[]") or list(pair.malicious.evidence)
    return [f for f in frags if len(words(f)) >= 3]


def found(frag: str, spans) -> str | None:
    """Kind of passage that carries the fragment: 'markup', 'hidden', or None."""
    fw = words(frag)[:40]
    for s in spans:
        sw = set(words(s.text))
        if fw and sum(w in sw for w in fw) / len(fw) >= 0.6:
            return "markup" if any(r.startswith(MARKUP) for r in s.reasons) else "hidden"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["train", "test"], default="train")
    ap.add_argument("--source", default=None)
    ap.add_argument("--n-pairs", type=int, default=None)
    ap.add_argument("--no-judge", action="store_true", help="skip the clean-twin judge (faster)")
    a = ap.parse_args()

    train, test = bspp.load(view="html", source=a.source, n_pairs=a.n_pairs)
    pairs = test if a.split == "test" else train
    dets = [PatternDetector(), MLDetector()]
    by = defaultdict(lambda: {"n": 0, "found": 0, "markup": 0, "clean_spans": 0, "clean_red": 0, "clean_yellow": 0})
    t0 = time.time()
    for i, p in enumerate(pairs):
        frags = fragments(p)
        if not frags:
            continue
        mal = analyze_html(p.malicious.content)
        kinds = [found(f, mal["hidden"]) for f in frags]
        hit = next((k for k in kinds if k), None)
        ben = analyze_html(p.benign.content)
        red = yellow = 0
        if not a.no_judge:
            lv = [f.level for f in _judge(ben["hidden"], ben["visible_text"], dets, long_passage_caution=False, web=True)]
            red, yellow = "threat" in lv, ("caution" in lv and "threat" not in lv)
        for key in (bspp.placement(p), "HIDDEN placements" if bspp.is_hidden(p) else "VISIBLE placements", "ALL"):
            s = by[key]
            s["n"] += 1; s["found"] += bool(hit); s["markup"] += hit == "markup"
            s["clean_spans"] += len(ben["hidden"]); s["clean_red"] += red; s["clean_yellow"] += yellow
        if (i + 1) % 500 == 0:
            print(f"  ...{i + 1}/{len(pairs)} ({time.time() - t0:.0f}s)")

    print(f"\nBrowseSafe++ {a.split} side, {by['ALL']['n']} attacked pages with known injection text\n")
    print(f"{'placement':28s} {'attack found':>16s} {'via markup':>11s} {'passages/clean page':>20s}"
          + ("" if a.no_judge else f" {'clean red':>10s} {'clean yellow':>13s}"))
    order = ["ALL", "HIDDEN placements", "VISIBLE placements"] + sorted(
        k for k in by if k not in ("ALL", "HIDDEN placements", "VISIBLE placements"))
    for k in order:
        s = by[k]; n = max(1, s["n"])
        line = (f"{k[:28]:28s} {f'{s['found']}/{s['n']} {100 * s['found'] / n:.0f}%':>16s} {s['markup']:>11d}"
                f" {s['clean_spans'] / n:>20.1f}")
        if not a.no_judge:
            line += f" {f'{100 * s['clean_red'] / n:.1f}%':>10s} {f'{100 * s['clean_yellow'] / n:.1f}%':>13s}"
        print(line)
    print("\nVisible placements (rewritten paragraphs, list items...) are not hidden, so the finder isn't meant to "
          "find them; the models reading the whole page cover those.")


if __name__ == "__main__":
    main()
