"""Bounded trial: can Gemma 3 1B tell an attacked web page from its clean twin when the
training window actually contains the attack?

Uses only the training side of every dataset (BrowseSafe++ train side split 85/15 into
train/validation by ml/bspp.trainval_split; LLMail phase 1 and Enron train split 85/15 by hash).
Never touches the BrowseSafe++ 20% test, BIPIA, AgentDojo or the hand-written set.

    python ml/train_trial.py --out /workspace/parallax/models/trial-windows \
        --compare /workspace/parallax/models/test-run

Writes <out>/trial_report.json and <out>/gemma_val.json (validation sample for the zero-shot
Gemma baseline, run separately with ml/gemma_val.py).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def h01(text: str, salt: str) -> float:
    return int(hashlib.sha256((salt + re.sub(r"\s+", " ", text).strip().lower()).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def email_sets(rng, n_train, n_val):
    from ml.train_fast import enron, llmail
    p1, _, _, _ = llmail()                       # phase 2 is a test set; not used here
    en_tr, _ = enron()                           # enron()'s own 15% is a test set; not used here
    p1 = list(dict.fromkeys(t[:3000] for t in p1 if t.strip()))
    en_tr = [t[:3000] for t in en_tr if t.strip()]
    split = lambda xs, salt: ([t for t in xs if h01(t, salt) >= .15], [t for t in xs if h01(t, salt) < .15])  # noqa: E731
    atk_tr, atk_va = split(p1, "email-atk|")
    ok_tr, ok_va = split(en_tr, "email-ok|")
    pick = lambda xs, k: rng.sample(xs, min(k, len(xs)))  # noqa: E731
    return (pick(atk_tr, n_train), pick(ok_tr, n_train), pick(atk_va, n_val), pick(ok_va, n_val),
            {"llmail_p1_train_side": len(atk_tr), "llmail_p1_val_side": len(atk_va),
             "enron_train_side": len(ok_tr), "enron_val_side": len(ok_va)})


def product_chunks(text):
    """Same chunking as parallax.detect.TransformerDetector.score (the shipped product)."""
    return [text[k:k + 1500] for k in range(0, max(1, len(text)), 1500)][:8] or [""]


class Scorer:
    def __init__(self, model, tok, dev, max_len=512, bs=16):
        import torch
        self.torch, self.model, self.tok, self.dev, self.max_len, self.bs = torch, model, tok, dev, max_len, bs

    def __call__(self, texts):
        torch, out = self.torch, []
        self.model.eval()
        with torch.no_grad(), torch.autocast(device_type="cuda", dtype=torch.bfloat16):
            for i in range(0, len(texts), self.bs):
                e = self.tok(texts[i:i + self.bs], truncation=True, max_length=self.max_len, padding=True,
                             return_tensors="pt").to(self.dev)
                lg = self.model(input_ids=e["input_ids"], attention_mask=e["attention_mask"]).logits.float()
                out += torch.softmax(lg, -1)[:, 1].tolist()
        return np.array(out)

    def pages(self, texts):
        parts, owner = [], []
        for i, t in enumerate(texts):
            for c in product_chunks(t):
                parts.append(c); owner.append(i)
        s = self(parts)
        best = np.zeros(len(texts))
        for o, v in zip(owner, s):
            best[o] = max(best[o], v)
        return best


def rate(scores, th):
    return f"{int((scores >= th).sum())}/{len(scores)}", round(float((scores >= th).mean()), 3) if len(scores) else None


def report_block(score_fn, val, page_val, skip_pairs=frozenset()):
    """Validation metrics for one model. score_fn(list[str]) -> np.array; page_val may be None."""
    out = {}
    ea, eo = score_fn(val["email_attack"]), score_fn(val["email_ok"])
    web = [r for r in val["web"] if r["pair_id"] not in skip_pairs]
    ws = score_fn([r["text"] for r in web])
    kinds = np.array([r["kind"] for r in web])
    for th in (0.5, 0.85):
        out[f"th{th}"] = {
            "email attack recall": rate(ea, th), "email false alarms": rate(eo, th),
            "web attack recall (windows)": rate(ws[kinds == "attack"], th),
            "web false alarms: clean twins": rate(ws[kinds == "twin"], th),
            "web false alarms: random clean chunks": rate(ws[kinds == "clean_chunk"], th)}
    by_pair = {}
    for r, s in zip(web, ws):
        if r["kind"] in ("attack", "twin"):
            by_pair.setdefault(r["pair_id"], {})[r["kind"]] = s
    gaps = np.array([d["attack"] - d["twin"] for d in by_pair.values() if len(d) == 2])
    out["attack minus twin score"] = {"pairs": len(gaps), "mean": round(float(gaps.mean()), 3),
                                      "median": round(float(np.median(gaps)), 3),
                                      "attack scored higher": f"{int((gaps > 0).sum())}/{len(gaps)}"}
    if page_val is not None:
        pa, po = page_val
        out["full pages, product chunking (th 0.5)"] = {"attacked pages flagged": rate(pa, .5),
                                                        "clean pages flagged": rate(po, .5)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="google/gemma-3-1b-pt")
    ap.add_argument("--out", default=str(ROOT / "models" / "trial-windows"))
    ap.add_argument("--compare", default=None, help="first fine-tuned trial (models/test-run) to compare")
    ap.add_argument("--n-pairs", type=int, default=4000, help="BrowseSafe++ pairs to load")
    ap.add_argument("--per-class", type=int, default=750)
    ap.add_argument("--clean-chunks", type=int, default=150)
    ap.add_argument("--val-email", type=int, default=600)
    ap.add_argument("--val-pages", type=int, default=150)
    ap.add_argument("--minutes", type=float, default=15)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--grad-accum", type=int, default=2)
    ap.add_argument("--max-len", type=int, default=512)
    a = ap.parse_args()
    t_all = time.time()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(0)
    rep = {"args": vars(a)}

    import torch
    from ml import bspp
    from ml.train_transformer import LABELS, load_model
    from parallax.detect import MLDetector
    from ml.probe_business import LINES

    # ---- data (training sides only) ----
    t0 = time.time()
    tok, model, pooled = load_model(a.model, torch.bfloat16)
    assert not pooled
    tr_pairs, _test_pairs = bspp.load(view="markdown", n_pairs=a.n_pairs)
    del _test_pairs                               # BrowseSafe++ 20% test: never used here
    tr, va, biggest = bspp.trainval_split(tr_pairs)
    rep["bspp split"] = {"loaded train-side pairs": len(tr_pairs), "train": len(tr), "val": len(va),
                         "largest group": biggest}
    tr_rows, tr_stats = bspp.transformer_windows(tr, tok, seed=1, clean_chunks=a.clean_chunks)
    va_rows, va_stats = bspp.transformer_windows(va, tok, seed=2, clean_chunks=len(va))
    rep["preprocessing coverage (train pairs)"] = dict(tr_stats)
    rep["preprocessing coverage (val pairs)"] = dict(va_stats)
    ea_tr, eo_tr, ea_va, eo_va, esz = email_sets(rng, a.per_class, a.val_email)
    rep["email split"] = esz

    pairs_tr = {}
    for r in tr_rows:
        if r["kind"] != "clean_chunk":
            pairs_tr.setdefault(r["pair_id"], []).append(r)
    pair_ids = rng.sample(sorted(pairs_tr), min(a.per_class, len(pairs_tr)))
    units = [[(r["text"], r["label"]) for r in pairs_tr[i]] for i in pair_ids]          # pairs stay together
    units += [[(r["text"], 0)] for r in tr_rows if r["kind"] == "clean_chunk"]
    units += [[(t, 1)] for t in ea_tr] + [[(t, 0)] for t in eo_tr]
    n_chunks = sum(r["kind"] == "clean_chunk" for r in tr_rows)
    rep["final training counts"] = {"email attacks": len(ea_tr), "harmless email": len(eo_tr),
                                    "web attack windows": len(pair_ids), "web clean twins": len(pair_ids),
                                    "web random clean chunks": n_chunks,
                                    "total rows": sum(len(u) for u in units)}
    val = {"email_attack": ea_va, "email_ok": eo_va, "web": va_rows}
    page_pairs = rng.sample(va, min(a.val_pages, len(va)))
    pages = ([p.malicious.content for p in page_pairs], [p.benign.content for p in page_pairs])
    rep["time: data prep (min)"] = round((time.time() - t0) / 60, 1)
    print(json.dumps(rep, indent=1), flush=True)

    # validation sample for the zero-shot Gemma baseline (run elsewhere: needs GEMINI_API_KEY)
    vr = random.Random(5)
    web_pairs = sorted({r["pair_id"] for r in va_rows if r["kind"] == "attack"})
    gp = set(vr.sample(web_pairs, min(100, len(web_pairs))))
    json.dump({"email_attack": vr.sample(ea_va, min(100, len(ea_va))), "email_ok": vr.sample(eo_va, min(100, len(eo_va))),
               "web": [r for r in va_rows if r["pair_id"] in gp and r["kind"] != "clean_chunk"]},
              open(out / "gemma_val.json", "w"))

    # ---- train: original checkpoint + LoRA, no class weighting, time-capped ----
    from peft import LoraConfig, get_peft_model
    dev = "cuda"
    model = get_peft_model(model, LoraConfig(task_type="SEQ_CLS", r=16, lora_alpha=32,
                                             target_modules="all-linear", lora_dropout=0.05)).to(dev)
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=2e-4, weight_decay=0.01)
    total = [a.epochs * sum(len(u) for u in units) // (a.batch * a.grad_accum)]
    warm = 10
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: (s + 1) / warm if s < warm else max(0.0, (total[0] - s) / max(1, total[0] - warm)))
    lossf = torch.nn.CrossEntropyLoss()
    model.train()
    t0, step, micro, done, epoch = time.time(), 0, 0, False, 0
    while not done and epoch < a.epochs:
        epoch += 1
        rng.shuffle(units)
        flat = [x for u in units for x in u]
        for i in range(0, len(flat) - a.batch + 1, a.batch):
            b = flat[i:i + a.batch]
            e = tok([t for t, _ in b], truncation=True, max_length=a.max_len, padding=True, return_tensors="pt").to(dev)
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                lg = model(input_ids=e["input_ids"], attention_mask=e["attention_mask"]).logits
            loss = lossf(lg.float(), torch.tensor([l for _, l in b], device=dev)) / a.grad_accum
            loss.backward()
            micro += 1
            if micro % a.grad_accum:
                continue
            torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.0)
            opt.step(); sched.step(); opt.zero_grad(); step += 1
            el = time.time() - t0
            if step == 5:                         # fit the schedule to the time budget
                total[0] = min(total[0], int(a.minutes * 60 / (el / step)))
                print(f"~{el / step:.2f}s/step -> {total[0]} steps planned", flush=True)
            if step % 25 == 0:
                print(f"epoch {epoch} step {step}/{total[0]} loss {loss.item() * a.grad_accum:.3f} {el / 60:.1f} min", flush=True)
            if step >= total[0] or el > a.minutes * 60:
                done = True
                break
    train_min = (time.time() - t0) / 60
    rep["training"] = {"steps": step, "planned": total[0], "epochs started": epoch,
                       "examples seen": step * a.batch * a.grad_accum, "actual runtime (min)": round(train_min, 1)}
    print(json.dumps(rep["training"]), flush=True)

    # ---- validation ----
    t0 = time.time()
    merged = model.merge_and_unload().eval()
    sc = Scorer(merged, tok, dev)
    page_scores = (sc.pages(pages[0]), sc.pages(pages[1]))
    rep["VALIDATION: trial model"] = report_block(sc, val, page_scores)
    s = sc(LINES)
    rep["probe_business (trial model)"] = f"{int((s >= .85).sum())}/20 threat, {int(((s >= .5) & (s < .85)).sum())}/20 caution, avg {s.mean():.2f}"
    print(json.dumps(rep["VALIDATION: trial model"], indent=1), flush=True)

    # ---- save + reload parity on 20 validation examples ----
    sample = [r["text"] for r in rng.sample(va_rows, 10)] + rng.sample(ea_va, 5) + rng.sample(eo_va, 5)
    before = sc(sample)
    merged.save_pretrained(out)
    tok.save_pretrained(out)
    json.dump({"base": a.model, "trial": "bspp windows", "lora": True, "report": rep}, open(out / "parallax_report.json", "w"), indent=1)
    del merged, model, sc
    torch.cuda.empty_cache()
    from parallax.detect import TransformerDetector
    det = TransformerDetector(str(out))
    after = Scorer(det.model, det.tok, dev)(sample)
    prod = np.array([det.score(t) for t in sample])
    rep["save/reload parity (20 val examples)"] = {
        "max |before - reloaded|": round(float(np.abs(before - after).max()), 4),
        "same decision at 0.5": f"{int(((before >= .5) == (after >= .5)).sum())}/20",
        "max |before - product TransformerDetector.score|": round(float(np.abs(before - prod).max()), 4),
        "reloaded dtype": str(next(det.model.parameters()).dtype)}
    del det
    torch.cuda.empty_cache()

    # ---- comparisons on the same validation data ----
    if a.compare and Path(a.compare).exists():
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        ctok = AutoTokenizer.from_pretrained(a.compare)
        cm = AutoModelForSequenceClassification.from_pretrained(a.compare, torch_dtype=torch.bfloat16).to(dev)
        csc = Scorer(cm, ctok, dev)
        # pairs the first trial trained on (first 500 loaded pairs, train side) are excluded for it
        seen = {p.pair_id for p in bspp.load(view="markdown", n_pairs=500)[0]}
        rep["VALIDATION: first fine-tuned trial (test-run)"] = report_block(csc, val, (csc.pages(pages[0]), csc.pages(pages[1])), seen)
        rep["VALIDATION: first fine-tuned trial (test-run)"]["note"] = (
            f"excluded {len(seen & {r['pair_id'] for r in va_rows})} val pairs it trained on; it also trained on a random "
            "~2% of LLMail p1/Enron train, so its email numbers are slightly optimistic")
        s = csc(LINES)
        rep["probe_business (first trial)"] = f"{int((s >= .85).sum())}/20 threat, {int(((s >= .5) & (s < .85)).sum())}/20 caution, avg {s.mean():.2f}"
        del cm, csc
        torch.cuda.empty_cache()
    v2 = MLDetector(ROOT / "parallax/models/injection_lr_v2.json")
    v2s = lambda texts: np.array([v2.score(t) for t in texts])  # noqa: E731
    rep["VALIDATION: V2 fast model"] = report_block(v2s, val, None)
    rep["VALIDATION: V2 fast model"]["note"] = "V2 was trained on all of LLMail p1 and Enron train, so its email numbers here are on data it saw"
    s = v2s(LINES)
    rep["probe_business (V2)"] = f"{int((s >= .85).sum())}/20 threat, {int(((s >= .5) & (s < .85)).sum())}/20 caution, avg {s.mean():.2f}"
    rep["time: validation + comparisons (min)"] = round((time.time() - t0) / 60, 1)
    rep["time: total (min)"] = round((time.time() - t_all) / 60, 1)
    json.dump(rep, open(out / "trial_report.json", "w"), indent=1)
    print("TRIAL_DONE", flush=True)


if __name__ == "__main__":
    main()
