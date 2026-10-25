"""Data-fix trial (and, with bigger numbers, the full run): attack windows with better twin
matching, html_gap hidden passages, harmless business email, one pass over more data, and
whole-page scoring with the product's own chunking.

Training sides only. BrowseSafe++ train side is split 85/15 into train/validation by
ml/bspp.trainval_split; LLMail phase 1 and Enron train are split 85/15 by hash. Never touches the
BrowseSafe++ 20% test, BIPIA, AgentDojo or the hand-written set.

    python ml/train_trial2.py --out /workspace/parallax/models/trial-fix \
        --compare /workspace/parallax/models/trial-windows
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ml.train_trial import Scorer, email_sets, rate  # noqa: E402

EN = lambda lang: bool(__import__("re").search(r"\b(en|english)\b", str(lang).lower()))  # noqa: E731  values look like "['en']"


def page_scores(score_fn, texts):
    from parallax.detect import page_chunks
    parts, owner = [], []
    for i, t in enumerate(texts):
        for c in page_chunks(t):
            parts.append(c); owner.append(i)
    s = score_fn(parts)
    best = np.zeros(len(texts))
    for o, v in zip(owner, s):
        best[o] = max(best[o], v)
    return best


def evaluate(score_fn, val, skip=frozenset()):
    out = {}
    ea, eo = score_fn(val["email_attack"]), score_fn(val["email_ok"])
    web = [r for r in val["web"] if r["pair_id"] not in skip]
    hid = [r for r in val["hidden"] if r["pair_id"] not in skip]
    ws, hs = score_fn([r["text"] for r in web]), score_fn([r["text"] for r in hid]) if hid else np.array([])
    kind = np.array([r["kind"] for r in web]); hk = np.array([r["kind"] for r in hid])
    pages = [p for p in val["pages"] if p["pair_id"] not in skip]
    pa, po = page_scores(score_fn, [p["mal"] for p in pages]), page_scores(score_fn, [p["ben"] for p in pages])
    lang_web = np.array([EN(r["language"]) for r in web]); lang_page = np.array([EN(p["language"]) for p in pages])
    for th in (0.5, 0.85):
        att = (kind == "attack")
        out[f"threshold {th}"] = {
            "email attack recall": rate(ea, th), "email false alarms": rate(eo, th),
            "web window recall": rate(ws[att], th),
            "web twin false alarms": rate(ws[kind == "twin"], th),
            "web random-chunk false alarms": rate(ws[kind == "clean_chunk"], th),
            "hidden passage recall": rate(hs[hk == "hidden_attack"], th) if len(hs) else None,
            "hidden passage false alarms": rate(hs[hk == "hidden_clean"], th) if len(hs) else None,
            "whole page attacked caught (any chunk >= th)": rate(pa, th),
            "whole page clean flagged (any chunk >= th)": rate(po, th),
            "web window recall, English": rate(ws[att & lang_web], th),
            "web window recall, other languages": rate(ws[att & ~lang_web], th),
            "whole page caught, English": rate(pa[lang_page], th),
            "whole page caught, other languages": rate(pa[~lang_page], th)}
    by = defaultdict(dict)
    for r, s in zip(web, ws):
        if r["kind"] in ("attack", "twin"):
            by[r["pair_id"]][r["kind"]] = s
    gaps = np.array([d["attack"] - d["twin"] for d in by.values() if len(d) == 2])
    out["attack minus twin score"] = {"pairs": len(gaps), "mean": round(float(gaps.mean()), 3),
                                      "median": round(float(np.median(gaps)), 3),
                                      "attack scored higher": f"{int((gaps > 0).sum())}/{len(gaps)}"}
    pg = pa - po
    out["attacked page minus clean page score"] = {"pages": len(pg), "mean": round(float(pg.mean()), 3),
                                                   "attacked scored higher": f"{int((pg > 0).sum())}/{len(pg)}"}
    return out


def probe(score_fn):
    from ml.probe_business import LINES
    s = score_fn(LINES)
    return f"{int((s >= .85).sum())}/20 threat, {int(((s >= .5) & (s < .85)).sum())}/20 caution, avg {s.mean():.2f}"


def coverage(per_pair, pairs):
    place = {p.pair_id: __import__("ml.bspp", fromlist=["placement"]).placement(p) for p in pairs}
    tot = Counter(v if not v.startswith("unrepresented") else "unrepresented" for v in per_pair.values())
    reasons = Counter(v for v in per_pair.values() if v.startswith("unrepresented"))
    by = defaultdict(Counter)
    for pid, v in per_pair.items():
        by[place[pid]]["unrepresented" if v.startswith("unrepresented") else v] += 1
    n = sum(tot.values())
    return {"pairs": n, **{k: f"{v} ({100 * v / n:.1f}%)" for k, v in tot.items()}, "unrepresented reasons": dict(reasons),
            "by placement": {k: dict(c) for k, c in sorted(by.items(), key=lambda x: -sum(x[1].values()))}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="google/gemma-3-1b-pt")
    ap.add_argument("--out", required=True)
    ap.add_argument("--compare", default=None, help="trial-windows model dir")
    ap.add_argument("--compare-npairs", type=int, default=4000, help="pairs trial-windows loaded (to exclude its train side)")
    ap.add_argument("--n-pairs", type=int, default=5000, help="BrowseSafe++ pairs to load (0 = all)")
    ap.add_argument("--web-pairs", type=int, default=2000)
    ap.add_argument("--email", type=int, default=2000, help="email attacks and harmless emails each")
    ap.add_argument("--business", type=int, default=300)
    ap.add_argument("--clean-chunks", type=int, default=1000)
    ap.add_argument("--val-email", type=int, default=600)
    ap.add_argument("--minutes", type=float, default=25)
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
    from ml.business_harmless import generate
    from ml.train_transformer import load_model
    from parallax.detect import MLDetector, TransformerDetector

    # ---- data (training sides only) ----
    t0 = time.time()
    tok, model, pooled = load_model(a.model, torch.bfloat16)
    assert not pooled
    n = a.n_pairs or None
    tr_pairs, test_pairs = bspp.load(view="markdown", n_pairs=n)
    del test_pairs                                # BrowseSafe++ 20% test: never used here
    html_tr, html_test = bspp.load(view="html", n_pairs=n)
    del html_test
    html_by_id = {p.pair_id: p for p in html_tr}
    tr, va, biggest = bspp.trainval_split(tr_pairs)
    rep["bspp split"] = {"train-side pairs loaded": len(tr_pairs), "train": len(tr), "val": len(va),
                         "largest group": biggest, "html view matched": sum(p.pair_id in html_by_id for p in tr_pairs)}
    tr_rows, tr_stats, tr_per = bspp.transformer_windows(tr, tok, seed=1, clean_chunks=a.clean_chunks)
    va_rows, va_stats, va_per = bspp.transformer_windows(va, tok, seed=2, clean_chunks=len(va))
    rep["represented pairs (train)"] = coverage(tr_per, tr)
    rep["represented pairs (val)"] = coverage(va_per, va)
    tr_hid, tr_hstats = bspp.hidden_passages(tr, html_by_id)
    va_hid, va_hstats = bspp.hidden_passages(va, html_by_id)
    rep["hidden passages + finder hit rate (train)"] = dict(tr_hstats)
    rep["hidden passages + finder hit rate (val)"] = dict(va_hstats)
    rep["languages (val pairs)"] = dict(Counter(str(p.metadata.get("language_payload")) for p in va).most_common(8))
    ea_tr, eo_tr, ea_va, eo_va, esz = email_sets(rng, a.email, a.val_email)
    biz = generate(a.business)
    rep["email split"] = esz

    pairs_tr = defaultdict(list)
    for r in tr_rows:
        if r["kind"] != "clean_chunk":
            pairs_tr[r["pair_id"]].append(r)
    pick = rng.sample(sorted(pairs_tr), min(a.web_pairs, len(pairs_tr)))
    units = [[(r["text"], r["label"]) for r in pairs_tr[i]] for i in pick]       # pairs stay together
    units += [[(r["text"], 0)] for r in tr_rows if r["kind"] == "clean_chunk"]
    units += [[(r["text"], r["label"])] for r in tr_hid]
    units += [[(t, 1)] for t in ea_tr] + [[(t, 0)] for t in eo_tr] + [[(t, 0)] for t in biz]
    rep["final training counts"] = {
        "email attacks": len(ea_tr), "harmless email (Enron)": len(eo_tr), "harmless business email (new)": len(biz),
        "web attack windows": len(pick), "web clean twins": len(pick),
        "web random clean chunks": sum(r["kind"] == "clean_chunk" for r in tr_rows),
        "hidden attack passages": sum(r["label"] for r in tr_hid), "hidden clean passages": sum(1 - r["label"] for r in tr_hid),
        "total rows": sum(len(u) for u in units)}
    val = {"email_attack": ea_va, "email_ok": eo_va, "web": va_rows, "hidden": va_hid,
           "pages": [{"pair_id": p.pair_id, "mal": p.malicious.content, "ben": p.benign.content,
                      "language": str(p.metadata.get("language_payload"))} for p in va]}
    rep["time: data prep (min)"] = round((time.time() - t0) / 60, 1)
    print(json.dumps(rep, indent=1), flush=True)

    # ---- train: original checkpoint + LoRA, no class weighting, one pass, time-capped ----
    from peft import LoraConfig, get_peft_model
    dev = "cuda"
    model = get_peft_model(model, LoraConfig(task_type="SEQ_CLS", r=16, lora_alpha=32,
                                             target_modules="all-linear", lora_dropout=0.05)).to(dev)
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=2e-4, weight_decay=0.01)
    rng.shuffle(units)
    flat = [x for u in units for x in u]
    total = [len(flat) // (a.batch * a.grad_accum)]
    warm = 10
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: (s + 1) / warm if s < warm else max(0.0, (total[0] - s) / max(1, total[0] - warm)))
    lossf = torch.nn.CrossEntropyLoss()
    model.train()
    t0, step, micro = time.time(), 0, 0
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
        if step == 10:                            # fit the schedule to the time budget
            total[0] = min(total[0], int(a.minutes * 60 / (el / step)))
            print(f"~{el / step:.2f}s/step -> {total[0]} steps planned (one pass = {len(flat) // (a.batch * a.grad_accum)})", flush=True)
        if step % 50 == 0:
            print(f"step {step}/{total[0]} loss {loss.item() * a.grad_accum:.3f} {el / 60:.1f} min", flush=True)
        if step >= total[0] or el > a.minutes * 60:
            break
    rep["training"] = {"steps": step, "planned": total[0], "one full pass": len(flat) // (a.batch * a.grad_accum),
                       "rows seen": step * a.batch * a.grad_accum, "rows available": len(flat),
                       "actual runtime (min)": round((time.time() - t0) / 60, 1)}
    print(json.dumps(rep["training"]), flush=True)

    # ---- validation: new model ----
    t0 = time.time()
    merged = model.merge_and_unload().eval()
    sc = Scorer(merged, tok, dev)
    rep["VALIDATION: new trial"] = evaluate(sc, val)
    rep["probe_business: new trial"] = probe(sc)
    print(json.dumps(rep["VALIDATION: new trial"], indent=1), flush=True)

    # ---- save, reload parity, CPU timing ----
    sample = [r["text"] for r in rng.sample(va_rows, 10)] + rng.sample(ea_va, 5) + rng.sample(eo_va, 5)
    before = sc(sample)
    merged.save_pretrained(out)
    tok.save_pretrained(out)
    json.dump({"base": a.model, "trial": "bspp windows + fixes", "lora": True}, open(out / "parallax_report.json", "w"))
    del merged, model, sc
    torch.cuda.empty_cache()
    det = TransformerDetector(str(out))
    after = Scorer(det.model, det.tok, dev)(sample)
    prod = np.array([det.score(t) for t in sample])
    rep["save/reload parity (20 val examples)"] = {
        "max |before - reloaded|": round(float(np.abs(before - after).max()), 4),
        "same decision at 0.5": f"{int(((before >= .5) == (after >= .5)).sum())}/20",
        "max |before - product TransformerDetector.score|": round(float(np.abs(before - prod).max()), 4)}
    torch.set_num_threads(8)
    det.dev = "cpu"; det.model = det.model.to("cpu")
    passages = [r["text"] for r in rng.sample(va_hid or va_rows, min(20, len(va_hid or va_rows)))]
    t1 = time.time(); [det.score(t) for t in passages]; per_passage = (time.time() - t1) / len(passages)
    pgs = [p["mal"] for p in rng.sample(val["pages"], 5)]
    t1 = time.time(); [det.score(t) for t in pgs]; per_page = (time.time() - t1) / len(pgs)
    rep["CPU time (pod CPU, 8 threads, product TransformerDetector, saved dtype)"] = {
        "per hidden passage (s)": round(per_passage, 2), "per whole page, up to 8 chunks (s)": round(per_page, 2),
        "dtype": str(next(det.model.parameters()).dtype)}
    del det
    torch.cuda.empty_cache()

    # ---- comparisons on the same validation data ----
    if a.compare and Path(a.compare).exists():
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        seen = {p.pair_id for p in bspp.trainval_split(bspp.load(view="markdown", n_pairs=a.compare_npairs)[0])[0]}
        ctok = AutoTokenizer.from_pretrained(a.compare)
        cm = AutoModelForSequenceClassification.from_pretrained(a.compare, dtype=torch.bfloat16).to(dev)
        csc = Scorer(cm, ctok, dev)
        rep["VALIDATION: trial-windows"] = evaluate(csc, val, skip=seen)
        rep["VALIDATION: trial-windows"]["note"] = f"excluded {len(seen & {p.pair_id for p in va})} val pairs on its train side"
        rep["probe_business: trial-windows"] = probe(csc)
        del cm, csc
        torch.cuda.empty_cache()
    v2 = MLDetector(ROOT / "parallax/models/injection_lr_v2.json")
    v2s = lambda texts: np.array([v2.score(t) for t in texts])  # noqa: E731
    rep["VALIDATION: V2"] = evaluate(v2s, val)
    rep["VALIDATION: V2"]["note"] = "V2 trained on all of LLMail p1 + Enron train: its email numbers are on data it saw"
    rep["probe_business: V2"] = probe(v2s)

    # ---- gate ----
    new, old = rep["VALIDATION: new trial"]["threshold 0.5"], rep.get("VALIDATION: trial-windows", {}).get("threshold 0.5")
    best_rule = min((0.5, 0.85), key=lambda th: rep["VALIDATION: new trial"][f"threshold {th}"]["whole page clean flagged (any chunk >= th)"][1])
    g = {"whole-page clean flagged < 5% (best page rule on val)":
         rep["VALIDATION: new trial"][f"threshold {best_rule}"]["whole page clean flagged (any chunk >= th)"],
         "page rule": f"any chunk >= {best_rule}",
         "probe_business threats <= 2": rep["probe_business: new trial"]}
    if old:
        for k in ("web twin false alarms", "email attack recall", "email false alarms"):
            g[f"{k}: new vs trial-windows"] = [new[k], old[k]]
    rep["GATE inputs"] = g
    rep["time: validation + comparisons (min)"] = round((time.time() - t0) / 60, 1)
    rep["time: total (min)"] = round((time.time() - t_all) / 60, 1)
    json.dump(rep, open(out / "trial_report.json", "w"), indent=1)
    print("TRIAL_DONE", flush=True)


if __name__ == "__main__":
    main()
