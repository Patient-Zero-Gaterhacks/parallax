"""Fair head-to-head of two fast models on data NEITHER of them trained on.

    PARALLAX_DATA=../data_src python3 -I ml/compare_models.py parallax/models/injection_lr.json parallax/models/injection_lr_v2.json

Why a separate script: each training script has its own Enron and LLMail
splits, so each model's "own test set" partly overlaps the other model's
training data. Here every harmless email is one that both models held out,
and near-copies of training sentences are removed from the test sets.
"""

import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml import train_fast as v1  # noqa: E402
from ml.eval_sets import ATTACKS, BENIGN  # noqa: E402
from parallax.detect import MLDetector, PatternDetector  # noqa: E402
from parallax.gap.html_gap import HiddenSpan  # noqa: E402
from parallax.ml_features import normalize_v2  # noqa: E402
from parallax.scan import _judge  # noqa: E402

TH_SURE, TH_MAYBE = 0.85, 0.5


def key(t):
    return normalize_v2(t)


def v2_enron_split():
    """Re-create train_fast_v2's 70/15/15 Enron split (same seed, same order of random calls)."""
    from ml import train_fast_v2 as v2
    v2.rng.seed(11)
    en = v1.pd.read_csv(v1.DATA / "enron_spam_data/enron_spam_data.csv").fillna("")
    return v2.split3((en["Subject"] + ". " + en["Message"]).tolist())


def similar(a, b):
    wa, wb = set(key(a).split()), set(key(b).split())
    return len(wa & wb) / max(1, min(len(wa), len(wb)))


def main():
    paths = sys.argv[1:] or ["parallax/models/injection_lr.json", "parallax/models/injection_lr_v2.json"]
    models = {Path(p).stem.replace("injection_lr", "model") or p: MLDetector(Path(p)) for p in paths}

    # Build the shared, clean test sets
    p1, p2, fp, lv = v1.llmail()
    p1k = {key(t) for t in p1}
    p2 = [t for t in dict.fromkeys(p2) if key(t) not in p1k]
    en1_tr, en1_te = v1.enron()                       # v1's 85/15
    en2_tr, en2_va, en2_te = v2_enron_split()         # v2's 70/15/15
    seen = {key(t) for t in en1_tr} | {key(t) for t in en2_tr} | {key(t) for t in en2_va}
    k1 = {key(t) for t in en1_te}
    enron_fair = [t for t in dict.fromkeys(en2_te) if key(t) in k1 and key(t) not in seen]
    _, b_atk = v1.bipia()
    from ml.train_fast_v2 import HARD_BENIGN, bipia_split
    _, b_te = bipia_split()                           # v2 trained on BIPIA *train* docs, so test docs only
    from ml.eval_external import TEMPLATES, goals, harmless
    G, H = goals(), harmless()
    ad_atk = [t.format(goal=g) for t in TEMPLATES.values() for g in G]
    leaked = [h for h in H if any(similar(h, hb) >= 0.7 for hb in HARD_BENIGN)]
    H_clean = [h for h in H if h not in leaked]
    hand_atk = [t for v in ATTACKS.values() for t in v]
    hand_ben = [t for v in BENIGN.values() for t in v]
    rng = random.Random(5)
    sent = lambda texts, n: [w for t in rng.sample(texts, min(n, len(texts))) for w in v1.windows(t, False)]  # noqa: E731

    sets = [  # (name, attacks, harmless)
        ("LLMail phase 2, whole emails (attacks)", p2, []),
        ("Enron emails both models held out (harmless)", [], enron_fair),
        ("  ...same, single sentences (harmless)", [], sent(enron_fair, 3000)),
        ("AgentDojo attacks, 5 styles x 42 goals", ad_atk, []),
        ("AgentDojo harmless content", [], H),
        ("  ...minus near-copies of v2's training lines", [], H_clean),
        ("Hand-written hidden attacks / harmless", hand_atk, hand_ben),
        ("BIPIA attack lines alone", b_atk, []),
        ("BIPIA test documents (harmless)", [], b_te),
    ]
    print(f"clean Enron rows held out by both models: {len(enron_fair)}; "
          f"AgentDojo harmless lines that resemble v2 training lines: {len(leaked)} {[l[:60] for l in leaked]}\n")
    names = list(models)
    hdr = "".join(f"{n + ' threat':>18s}{n + ' warn':>16s}" for n in names)
    print(f"{'test set':48s}{hdr}")
    for name, atk, ben in sets:
        for label, texts in (("caught", atk), ("false alarm", ben)):
            if not texts:
                continue
            cells = []
            for n in names:
                s = [models[n].score(t) if len(t.split()) >= 5 else 0.0 for t in texts]
                sure = sum(x >= TH_SURE for x in s); warn = sum(x >= TH_MAYBE for x in s)
                cells.append(f"{f'{sure}/{len(texts)} {100 * sure / len(texts):.1f}%':>18s}{f'{100 * warn / len(texts):.1f}%':>16s}")
            print(f"{(name + ' ' + label)[:47]:48s}" + "".join(cells))

    # Full Parallax judge (patterns + hidden facts + model), the way the product uses it
    print("\nFull Parallax judge on AgentDojo (patterns + hidden-facts check + model), threat / caution:")
    for n in names:
        dets = [PatternDetector(), models[n]]
        lv_a = [_judge([HiddenSpan(t, ["display:none"])], "Here is the document.", dets, False)[0].level for t in ad_atk]
        lv_h = [_judge([HiddenSpan(t, ["display:none"])], "Here is the document.", dets, False)[0].level for t in H_clean]
        print(f"  {n:14s} attacks {lv_a.count('threat')}/{len(ad_atk)} threat +{lv_a.count('caution')} caution | "
              f"harmless {lv_h.count('threat')}/{len(H_clean)} threat +{lv_h.count('caution')} caution")

    print("\nSpeed and size:")
    sample = (hand_atk + hand_ben) * 20
    for n in names:
        t0 = time.time()
        for t in sample:
            models[n].score(t)
        print(f"  {n:14s} {1000 * (time.time() - t0) / len(sample):.3f} ms per passage, "
              f"{Path(paths[names.index(n)]).stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
