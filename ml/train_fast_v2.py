"""Retrain the fast classifier without the shortcuts the v1 model learned.

What v1 got wrong (see ml/probe_shortcuts.py):
  * Harmless examples were 2000s Enron mail, attacks were modern LLMail emails,
    so the model learned "looks like Enron" (names like Vince, 'gas', '> >',
    spaced-out links) = harmless, and "<", "**", "body", links = attack.
  * ~21% of the Enron test rows were duplicates of training rows.

What v2 changes (same model type: TF-IDF + logistic regression, same JSON format):
  1. normalize_v2: spaced links become zlink, all symbols dropped.
  2. De-duplicate every source after normalizing, before splitting.
  3. Enron split 70/15/15 (train / validation / sealed test).
  4. Paired carrier examples: take a harmless document and hide an attack
     sentence inside it -> label 1; the same document without it -> label 0.
     Writing style is now in both classes, so only the hidden instruction decides.
  5. Decorations (links, signatures, greetings, quote marks) are added to both
     classes at the same rate, so they stop carrying label information.
  6. Pick C on the validation split; the sealed test sets are scored once.

Run:  PARALLAX_DATA=../data_src python3 ml/train_fast_v2.py
      PARALLAX_DATA=../data_src python3 ml/train_fast_v2.py --compare parallax/models/injection_lr.json
Writes parallax/models/injection_lr_v2.json (+ the extension copy). Doesn't touch v1.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ml import train_fast as v1  # noqa: E402  (reuse the dataset loaders)
from ml.eval_sets import ATTACKS, BENIGN  # noqa: E402
from ml.probe_shortcuts import PROBES, load as load_model  # noqa: E402
from parallax.ml_features import analyzer_v2, normalize_v2  # noqa: E402

OUT = ROOT / "parallax" / "models" / "injection_lr_v2.json"
rng = random.Random(11)
v1.rng.seed(11)

# Decorations for training. The probe uses different strings (example.com, "Vince", "Body:",
# "<div>") so it still measures generalization, not memorization.
DECOR = [
    lambda t: t + " " + rng.choice(["https://", "http://", "www."]) + rng.choice(["news", "shop", "acme", "mail", "docs", "cdn"]) + rng.choice([".com", ".org", ".net", ".io"]) + "/" + rng.choice(["a", "p/123", "help", "faq"]),
    lambda t: t + " http : / / www . " + rng.choice(["acme", "ferc", "yahoo", "cnn"]) + " . com",
    lambda t: rng.choice(["Hi ", "Dear ", "Thanks ", "", "Hey "]) + rng.choice(["Sally", "Mark", "Priya", "Jeff", "Ana", "Kay", "Louise", "Chris", "team"]) + ", " + t,
    lambda t: t + "\n" + rng.choice(["Sent from my iPhone", "-- Regards, J.", "Best, Tom", "Thanks!", "Cheers", "> > original message"]),
    lambda t: rng.choice(["> ", "> > ", "* ", "- ", "# ", "[1] "]) + t,
    lambda t: rng.choice(["<p>", "<span>", "[", "{"]) + t + rng.choice(["</p>", "</span>", "]", "}"]),
]


# Everyday email/web lines that sound like commands but are written for people.
# Keep these different from the hand-written test set (never paste test sentences here).
HARD_BENIGN = [
    "If you didn't request this code, you can safely ignore this message.",
    "Please disregard this notice if you have already made your payment.",
    "If you did not sign up for this account, ignore this email and no changes will be made.",
    "You can ignore this reminder if you've already registered for the event.",
    "If this wasn't you, please reset your password and contact support.",
    "Do not reply to this automated message; this inbox is not monitored.",
    "Ignore the previous version of this document; the updated schedule is attached.",
    "Please forward this email to anyone on your team who should attend.",
    "Disregard my last email, the meeting is still on Thursday.",
    "Your verification code expires in 10 minutes. Do not share it with anyone.",
    "If you received this message in error, please delete it and notify the sender.",
    "To stop receiving these emails, click unsubscribe at the bottom of this message.",
    "Send your completed form to the front desk before your appointment.",
    "Remember to bring a photo ID and your insurance card to your visit.",
    "Summarize your experience in the survey below; it takes two minutes.",
    "Our AI assistant can help you track orders and process returns.",
    "Reply STOP to opt out of text messages.",
    "Confirm your email address to finish setting up your account.",
]


def decorate(texts, p=0.3):
    return [rng.choice(DECOR)(t) if rng.random() < p else t for t in texts]


def dedupe(texts):
    seen, out = set(), []
    for t in texts:
        k = normalize_v2(t)
        if k and k not in seen:
            seen.add(k)
            out.append(t)
    return out


def split3(texts, a=0.70, b=0.15):
    texts = dedupe(texts)
    rng.shuffle(texts)
    i, j = int(len(texts) * a), int(len(texts) * (a + b))
    return texts[:i], texts[i:j], texts[j:]


def embed(carrier, payload, max_len=1500):
    """Hide `payload` at a random sentence boundary inside `carrier`. Returns (attacked, clean) crops of the same text."""
    sents = [s for s in v1.SENT.split(carrier) if s.strip()]
    if not sents:
        return payload, ""
    i = rng.randint(0, len(sents))
    before, after = " ".join(sents[:i]), " ".join(sents[i:])
    budget = max(0, max_len - len(payload)) // 2
    before, after = before[-budget:], after[:budget]
    return (before + " " + payload + " " + after).strip(), (before + " " + after).strip()


def build():
    p1, p2, fp, lv = v1.llmail()
    en = v1.pd.read_csv(v1.DATA / "enron_spam_data/enron_spam_data.csv").fillna("")
    en_tr, en_va, en_te = split3((en["Subject"] + ". " + en["Message"]).tolist())
    b_ctx_tr, b_ctx_te = bipia_split()
    p1 = dedupe(p1)
    rng.shuffle(p1)
    cut = int(len(p1) * 0.9)
    p1_tr, p1_va = p1[:cut], p1[cut:]
    p1_keys = {normalize_v2(t) for t in p1}
    p2 = [t for t in dedupe(p2) if normalize_v2(t) not in p1_keys]  # no phase-1 copies in the test
    fp = dedupe(fp)
    fp_tr, fp_te = fp[: len(fp) // 2], fp[len(fp) // 2:]

    pos, neg = [], []
    # --- attacks
    pos += [t[:3000] for t in p1_tr]
    pos += [w for t in p1_tr for w in v1.windows(t, cue_only=True)]
    extra = dedupe(v1.extra_attacks())
    pos += extra * 2
    from ml.synth import generate
    sp, sn = generate()
    pos += sp
    # --- harmless
    neg += [t[:3000] for t in en_tr]
    neg += [w for t in en_tr for w in v1.windows(t, cue_only=False)]
    neg += [w for t in en_tr for w in v1.windows(t, cue_only=True)]
    neg += fp_tr + lv + [w for t in fp_tr + lv for w in v1.windows(t, cue_only=False, n=3)]
    neg += v1.TRAIN_UI * 10 + sn + HARD_BENIGN * 30
    neg += b_ctx_tr * 3  # harmless documents/tables/code (not email)
    # --- paired carriers: same document with and without a hidden payload
    payloads = [w for t in p1_tr for w in v1.windows(t, cue_only=True)] + extra + sp
    carriers = en_tr + fp_tr + lv + b_ctx_tr * 10
    for _ in range(3000):  # hard-benign lines hidden inside documents too
        neg.append(embed(rng.choice(carriers), rng.choice(HARD_BENIGN))[0])
    for _ in range(30000):
        a, c = embed(rng.choice(carriers), rng.choice(payloads))
        pos.append(a)
        if c:
            neg.append(c)

    # BrowseSafe, if downloaded from Hugging Face (uses the dataset's own split)
    bs = v1.browsesafe()
    if bs:
        for t, l in zip(*bs[0]):
            (pos if l else neg).append(t[:3000])

    # decorations on BOTH classes at the same rate
    pos, neg = decorate(pos), decorate(neg)
    # drop exact texts that ended up in both classes
    pk, nk = {normalize_v2(t) for t in pos}, {normalize_v2(t) for t in neg}
    both = pk & nk
    pos = [t for t in pos if normalize_v2(t) not in both]
    neg = [t for t in neg if normalize_v2(t) not in both]

    val = {"LLMail p1 held-out 10% vs Enron val": (p1_va, en_va)}

    hand_atk = [t for v in ATTACKS.values() for t in v]
    hand_ben = [t for v in BENIGN.values() for t in v]
    b_ctx_te_s = rng.sample(b_ctx_te, 150)
    b_atk = v1.bipia()[1]
    held = {
        "LLMail phase 2 vs Enron test (both de-duplicated)": (p2, en_te),
        "LLMail phase 2 sentences vs Enron sentences":
            ([w for t in p2 for w in v1.windows(t, True)], [w for t in en_te for w in v1.windows(t, False)]),
        "harmless LLM-written emails": ([], fp_te),
        "NEW hand-written attacks hidden in unseen BIPIA docs": (
            [embed(c, rng.choice(hand_atk))[0] for c in b_ctx_te_s], b_ctx_te_s),
        "NEW hand-written HARMLESS passages in unseen BIPIA docs": (
            [], [embed(c, rng.choice(hand_ben))[0] for c in b_ctx_te_s]),
        "BIPIA off-task 'attacks' in docs (needs user task)": (
            [embed(c, rng.choice(b_atk))[0] for c in b_ctx_te_s], []),
    }
    if bs:
        held["BrowseSafe test"] = ([t for t, l in zip(*bs[1]) if l], [t for t, l in zip(*bs[1]) if not l])
    for k, v in ATTACKS.items():
        held[f"hand-written attacks: {k}"] = (v, [])
    held["hand-written harmless (all)"] = ([], hand_ben)
    return pos, neg, val, held, bool(bs)


def bipia_split():
    b = v1.DATA / "BIPIA/benchmark"
    tr, te = [], []
    for name in ("email", "table", "code"):
        for f, dest in (("train.jsonl", tr), ("test.jsonl", te)):
            for line in open(b / name / f):
                c = json.loads(line)["context"]
                dest.append(c if isinstance(c, str) else json.dumps(c))
    return dedupe(tr), dedupe(te)


def report(scorers, held, ths=(0.5, 0.85)):
    names = list(scorers)
    print(f"{'':58s}" + "".join(f"{n + ' @' + str(th):>22s}" for n in names for th in ths))
    for set_name, (p, n) in held.items():
        cells = []
        for nm in names:
            sp = np.asarray(scorers[nm](p)) if p else np.array([])
            sn = np.asarray(scorers[nm](n)) if n else np.array([])
            for th in ths:
                c = []
                if p:
                    c.append(f"{int((sp >= th).sum())}/{len(p)}")
                if n:
                    c.append(f"FA {int((sn >= th).sum())}/{len(n)}")
                cells.append(" ".join(c))
        print(f"{set_name[:57]:58s}" + "".join(f"{c:>22s}" for c in cells))


def probe(scorers):
    print("\nShortcut probe: avg |score change| when only formatting changes (lower is better)")
    for nm, s in scorers.items():
        tot, flips = 0.0, 0
        for _, texts, tf in PROBES:
            b, a = np.asarray(s(texts)), np.asarray(s([tf(t) for t in texts]))
            tot += np.abs(a - b).mean()
            flips += int((((b >= .5) != (a >= .5)) | ((b >= .85) != (a >= .85))).sum())
        print(f"  {nm:12s} avg change {tot / len(PROBES):.3f}   decisions flipped {flips}/{sum(len(t) for _, t, _ in PROBES)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--compare", help="old model JSON to score on the same test sets")
    args = ap.parse_args()
    t0 = time.time()
    pos, neg, val, held, bs = build()
    X, y = pos + neg, [1] * len(pos) + [0] * len(neg)
    print(f"training rows: {len(X)} (attacks {len(pos)}, harmless {len(neg)}){' + BrowseSafe' if bs else ''}")
    vec = TfidfVectorizer(analyzer=analyzer_v2, min_df=3, max_features=60000, sublinear_tf=True, dtype=np.float32)
    Xm = vec.fit_transform(X)

    # choose C on validation only
    best = None
    (vp, vn), = val.values()
    for C in (1.0, 4.0):
        clf = LogisticRegression(C=C, max_iter=3000, class_weight="balanced").fit(Xm, y)
        sp, sn = clf.predict_proba(vec.transform(vp))[:, 1], clf.predict_proba(vec.transform(vn))[:, 1]
        rec, fa = (sp >= .85).mean(), (sn >= .85).mean()
        print(f"  C={C}: validation recall@0.85 {rec:.3f}, false alarms@0.85 {fa:.4f}")
        if best is None or rec - 5 * fa > best[0]:
            best = (rec - 5 * fa, C, clf)
    _, C, clf = best
    print(f"picked C={C}; trained in {time.time() - t0:.0f}s, {len(vec.vocabulary_)} features\n")

    scorers = {"v2": lambda texts: clf.predict_proba(vec.transform(texts))[:, 1] if texts else []}
    if args.compare:
        old = load_model(args.compare)
        scorers = {"v1": lambda texts: [old(t) for t in texts], **scorers}
    print("Sealed test sets (never trained on, never used to pick settings). 'FA' = false alarms.")
    report(scorers, held)
    probe(scorers)

    feats = {f: [round(float(vec.idf_[i]), 4), round(float(clf.coef_[0][i]), 4)] for f, i in vec.vocabulary_.items()}
    json.dump({"version": 2, "normalizer": "v2", "threshold": 0.5, "bias": round(float(clf.intercept_[0]), 4),
               "sublinear_tf": True, "features": feats,
               "trained_on": "LLMail p1 + Enron + LLMail harmless + BIPIA train docs + paired carriers" + (" + BrowseSafe" if bs else "")},
              open(OUT, "w"), separators=(",", ":"))
    ext = ROOT / "extension" / "models" / OUT.name
    ext.write_bytes(OUT.read_bytes())
    top = sorted(feats.items(), key=lambda kv: kv[1][1])
    print("\nstrongest 'harmless' features:", [k for k, _ in top[:25]])
    print("strongest 'attack' features:  ", [k for k, _ in top[-25:]])
    print(f"\nexported -> {OUT} and {ext}")


if __name__ == "__main__":
    main()
