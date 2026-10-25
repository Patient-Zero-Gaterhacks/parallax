"""Fine-tune Gemma (or another transformer) as Parallax's strong injection classifier.

Run on a rented GPU. Typical runs:

    # Gemma 3 1B on BrowseSafe++ + everything ml/train_fast.py uses (L4 GPU, ~1-2 h)
    python ml/train_transformer.py --model google/gemma-3-1b-pt --bspp --lora --batch 8 --max-len 512

    # Gemma 4 (needs a custom classifier head; handled automatically)
    python ml/train_transformer.py --model <a Gemma 4 model id> --bspp --lora --batch 4 --max-len 512

    # Backup: small non-Gemma model, fastest (~30 min)
    python ml/train_transformer.py --model microsoft/deberta-v3-small --bspp

Flags:
  --bspp        add BrowseSafe++ (Perplexity, Oct 2026): 80% of its public pairs for training,
                the other 20% held out for testing (see ml/bspp.py for how it's split)
  --hf          also add BrowseSafe-Bench (Nov 2025) and the full LLMail set from Hugging Face
  --lora        train small add-on weights instead of the whole model (much less GPU memory);
                they are merged back in when saving
  --smoke gemma3|gemma4|bert   run the whole pipeline on CPU with a tiny model built from
                scratch (no downloads) to check the code works; its scores mean nothing

Use the result:  PARALLAX_ML_TRANSFORMER=models/parallax-transformer uvicorn parallax.server:app
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ml.train_fast import build, evaluate  # noqa: E402

LABELS = {"id2label": {0: "benign", 1: "injection"}, "label2id": {"benign": 0, "injection": 1}}


def html_to_text(html: str) -> str:
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    except Exception:
        return html


def hf_extra(max_llmail=60000, seed=3):
    """BrowseSafe-Bench + full LLMail from Hugging Face (needs access to huggingface.co)."""
    from datasets import load_dataset
    out, held = [], {}
    rng = random.Random(seed)
    try:
        bs = load_dataset("perplexity-ai/browsesafe-bench")
        lab = lambda r: 1 if str(r["label"]).lower() in ("yes", "1", "true") else 0  # noqa: E731
        tr, te = bs["train"], bs["test"]
        out.append(([html_to_text(r["content"])[:6000] for r in tr], [lab(r) for r in tr]))
        texts, labels = [html_to_text(r["content"]) for r in te], [lab(r) for r in te]
        held["BrowseSafe-Bench test (Nov 2025)"] = ([t for t, l in zip(texts, labels) if l],
                                                    [t for t, l in zip(texts, labels) if not l])
        print(f"BrowseSafe-Bench: {len(tr)} train, {len(te)} test")
    except Exception as e:
        print("BrowseSafe-Bench not loaded:", e)
    try:
        ll = load_dataset("microsoft/llmail-inject-challenge")
        rows = []
        for split in ll:
            cols = ll[split].column_names
            body = next((c for c in ("body", "email_body", "text", "content") if c in cols), None)
            subj = next((c for c in ("subject", "email_subject") if c in cols), None)
            if not body:
                print(f"LLMail split {split}: no body column in {cols}"); continue
            for r in ll[split]:
                rows.append(((r[subj] + ". ") if subj and r[subj] else "") + (r[body] or ""))
        rows = list(dict.fromkeys(t for t in rows if t.strip()))
        rng.shuffle(rows)
        out.append((rows[:max_llmail], [1] * min(len(rows), max_llmail)))
        print(f"LLMail full: {len(rows)} unique attacks, using {min(len(rows), max_llmail)}")
    except Exception as e:
        print("LLMail (HF) not loaded:", e)
    return out, held


def bspp_extra(source=None, n_pairs=None):
    from ml import bspp
    tr, te = bspp.load(view="markdown", source=source, n_pairs=n_pairs)
    X, y = bspp.rows(tr)
    print(f"BrowseSafe++: {len(tr)} pairs to train, {len(te)} pairs held out")
    held = {"BrowseSafe++ held-out 20% (Oct 2026)": ([p.malicious.content for p in te], [p.benign.content for p in te])}
    return [([t[:6000] for t in X], y)], held


class PooledClassifier:
    """Any transformer backbone + a yes/no head on its last real token (for models with no
    ready-made classifier class in transformers, e.g. Gemma 4)."""

    def __new__(cls, backbone, hidden):
        import torch.nn as nn

        class _M(nn.Module):
            def __init__(self):
                super().__init__()
                self.backbone, self.head = backbone, nn.Linear(hidden, 2)
                self.config = backbone.config

            def forward(self, input_ids, attention_mask, **_):
                from types import SimpleNamespace
                h = self.backbone(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
                last = attention_mask.sum(1) - 1        # right padding: last real token
                pooled = h[range(h.shape[0]), last]
                return SimpleNamespace(logits=self.head(pooled.to(self.head.weight.dtype)))
        return _M()


def save_pooled(model, out: Path):
    import torch
    bb = model.backbone
    if hasattr(bb, "merge_and_unload"):
        bb = bb.merge_and_unload()
    bb.save_pretrained(out / "backbone")
    torch.save(model.head.state_dict(), out / "parallax_head.pt")
    json.dump({"hidden": model.head.in_features, **LABELS}, open(out / "parallax_head.json", "w"))


def load_pooled(path: str, device="cpu"):
    """Used by parallax.detect.TransformerDetector for Gemma 4 style models."""
    import torch
    from transformers import AutoModel
    meta = json.load(open(Path(path) / "parallax_head.json"))
    m = PooledClassifier(AutoModel.from_pretrained(Path(path) / "backbone"), meta["hidden"])
    m.head.load_state_dict(torch.load(Path(path) / "parallax_head.pt", map_location=device))
    return m.to(device).eval()


def tiny(arch, texts):
    """From-scratch tokenizer + tiny model, so --smoke needs no downloads."""
    from tokenizers import Tokenizer, models, normalizers, pre_tokenizers, trainers
    from tokenizers.processors import TemplateProcessing
    import transformers as T
    tok = Tokenizer(models.WordPiece(unk_token="[UNK]"))
    tok.normalizer = normalizers.BertNormalizer(lowercase=True)
    tok.pre_tokenizer = pre_tokenizers.BertPreTokenizer()
    tok.train_from_iterator(texts, trainers.WordPieceTrainer(vocab_size=4000, special_tokens=["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]"]))
    tok.post_processor = TemplateProcessing(single="[CLS] $A [SEP]", special_tokens=[
        ("[CLS]", tok.token_to_id("[CLS]")), ("[SEP]", tok.token_to_id("[SEP]"))])
    hf_tok = T.PreTrainedTokenizerFast(tokenizer_object=tok, unk_token="[UNK]", pad_token="[PAD]",
                                       cls_token="[CLS]", sep_token="[SEP]", mask_token="[MASK]")
    kw = dict(vocab_size=4000, hidden_size=64, intermediate_size=128, num_hidden_layers=2, num_attention_heads=2)
    if arch == "bert":
        return hf_tok, T.BertForSequenceClassification(T.BertConfig(**kw, num_labels=2, **LABELS)), False
    if arch == "gemma3":
        cfg = T.Gemma3TextConfig(**kw, num_key_value_heads=1, head_dim=32, num_labels=2, pad_token_id=0, **LABELS)
        return hf_tok, T.Gemma3TextForSequenceClassification(cfg), False
    cfg = T.Gemma4TextConfig(**kw, num_key_value_heads=1, head_dim=32, pad_token_id=0)
    return hf_tok, PooledClassifier(T.AutoModel.from_config(cfg), 64), True


def load_model(name, dtype):
    import transformers as T
    tok = T.AutoTokenizer.from_pretrained(name)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    tok.padding_side = "right"
    try:
        model = T.AutoModelForSequenceClassification.from_pretrained(name, num_labels=2, torch_dtype=dtype, **LABELS)
        model.config.pad_token_id = tok.pad_token_id
        return tok, model, False
    except ValueError as e:
        print(f"No ready-made classifier for {name} ({str(e)[:80]}...); using a custom head.")
        bb = T.AutoModel.from_pretrained(name, torch_dtype=dtype)
        hidden = getattr(bb.config, "hidden_size", None) or bb.config.text_config.hidden_size
        return tok, PooledClassifier(bb, hidden), True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="google/gemma-3-1b-pt")
    ap.add_argument("--out", default=str(ROOT / "models" / "parallax-transformer"))
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--max-len", type=int, default=512)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--grad-accum", type=int, default=4, help="steps to add up before each update (bigger effective batch)")
    ap.add_argument("--lr", type=float, default=None, help="default 2e-4 with --lora, 2e-5 without")
    ap.add_argument("--lora", action="store_true")
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--bspp", action="store_true")
    ap.add_argument("--bspp-source", default=None, help="local BrowseSafe++ folder instead of downloading")
    ap.add_argument("--bspp-pairs", type=int, default=None, help="use only this many pairs (quick test)")
    ap.add_argument("--hf", action="store_true")
    ap.add_argument("--max-rows", type=int, default=None, help="cap training rows (quick test)")
    ap.add_argument("--smoke", choices=["bert", "gemma3", "gemma4"], default=None)
    a = ap.parse_args()

    import torch
    from transformers import get_linear_schedule_with_warmup

    extra, extra_held = [], {}
    if a.bspp:
        e, h = bspp_extra(a.bspp_source, a.bspp_pairs); extra += e; extra_held.update(h)
    if a.hf:
        e, h = hf_extra(); extra += e; extra_held.update(h)
    X, y, held, _ = build(extra)
    held.update(extra_held)

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    bf16 = dev == "cuda" and torch.cuda.is_bf16_supported()
    dtype = torch.bfloat16 if bf16 else torch.float32
    rng = random.Random(0)
    if a.smoke:
        idx = rng.sample(range(len(X)), min(3000, len(X)))
        X, y = [X[i] for i in idx], [y[i] for i in idx]
        held = {k: (p[:30], n[:30]) for k, (p, n) in held.items()}
        a.max_len, a.batch, a.grad_accum, a.epochs = 128, 16, 1, 1
        tok, model, pooled = tiny(a.smoke, X)
    else:
        if a.max_rows and len(X) > a.max_rows:
            idx = rng.sample(range(len(X)), a.max_rows)
            X, y = [X[i] for i in idx], [y[i] for i in idx]
        tok, model, pooled = load_model(a.model, dtype)
    print(f"training rows: {len(X)} (attacks {sum(y)}, harmless {len(y) - sum(y)}) on {dev}{' bf16' if bf16 else ''}")

    if a.lora:
        from peft import LoraConfig, get_peft_model
        if pooled:
            model.backbone = get_peft_model(model.backbone, LoraConfig(r=a.lora_r, lora_alpha=2 * a.lora_r,
                                                                       target_modules="all-linear", lora_dropout=0.05))
        else:
            model = get_peft_model(model, LoraConfig(task_type="SEQ_CLS", r=a.lora_r, lora_alpha=2 * a.lora_r,
                                                     target_modules="all-linear", lora_dropout=0.05))
        trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
        print(f"LoRA: training {trainable / 1e6:.1f}M parameters")
    lr = a.lr or (2e-4 if a.lora else 2e-5)
    if a.smoke:
        lr = 1e-3
    model.to(dev)

    order = list(range(len(X)))
    a.batch = min(a.batch, len(order))   # otherwise the loop below never takes a step
    steps = max(1, int(len(order) / (a.batch * a.grad_accum) * a.epochs))
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=lr, weight_decay=0.01)
    sched = get_linear_schedule_with_warmup(opt, max(1, int(0.05 * steps)), steps)
    w_pos = (len(y) - sum(y)) / max(1, sum(y))
    lossf = torch.nn.CrossEntropyLoss(weight=torch.tensor([1.0, w_pos], device=dev))
    autocast = torch.autocast(device_type="cuda", dtype=torch.bfloat16 if bf16 else torch.float16) if dev == "cuda" \
        else torch.autocast("cpu", enabled=False)

    def enc(texts):
        e = tok(texts, truncation=True, max_length=a.max_len, padding=True, return_tensors="pt").to(dev)
        return {"input_ids": e["input_ids"], "attention_mask": e["attention_mask"]}

    model.train()
    t0, step, micro = time.time(), 0, 0
    ckpt_every = max(50, steps // 5)
    while step < steps:
        rng.shuffle(order)
        for i in range(0, len(order) - a.batch + 1, a.batch):
            b = order[i:i + a.batch]
            with autocast:
                logits = model(**enc([X[j] for j in b])).logits
            loss = lossf(logits.float(), torch.tensor([y[j] for j in b], device=dev)) / a.grad_accum
            loss.backward()
            micro += 1
            if micro % a.grad_accum:
                continue
            torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.0)
            opt.step(); sched.step(); opt.zero_grad()
            step += 1
            if step % 20 == 0 or step == steps:
                el = time.time() - t0
                print(f"step {step}/{steps} loss {loss.item() * a.grad_accum:.3f}  {el / 60:.1f} min, ~{el / step * (steps - step) / 60:.0f} min left")
            if step % ckpt_every == 0 and not a.smoke:
                Path(a.out).mkdir(parents=True, exist_ok=True)
                torch.save({k: v for k, v in model.state_dict().items() if "lora" in k or "head" in k or "score" in k},
                           Path(a.out) / "checkpoint_trainable.pt")
            if step >= steps:
                break

    model.eval()

    @torch.no_grad()
    def score(texts):
        from parallax.detect import page_chunks
        out = []
        for t in texts:
            parts = page_chunks(t)
            with autocast:
                p = torch.softmax(model(**enc(parts)).logits.float(), -1)[:, 1].max().item()
            out.append(p)
        return np.array(out)

    print("\nHeld-out results (threshold 0.5):")
    report = evaluate(score, held)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if pooled:
        save_pooled(model, out)
    else:
        m = model.merge_and_unload() if hasattr(model, "merge_and_unload") else model
        m.save_pretrained(out)
    tok.save_pretrained(out)
    json.dump({"base": f"tiny {a.smoke} (smoke test)" if a.smoke else a.model, "bspp": a.bspp, "hf": a.hf,
               "lora": a.lora, "report": report}, open(out / "parallax_report.json", "w"), indent=1)
    print(f"\nsaved -> {out}\nuse it: PARALLAX_ML_TRANSFORMER={out} uvicorn parallax.server:app --port 8787")


if __name__ == "__main__":
    main()
