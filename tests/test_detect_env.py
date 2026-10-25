"""Which detectors turn on: the untrained 31B is opt-in, and the fine-tuned model loads from a folder or a Hugging Face repo id."""

import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from parallax import detect  # noqa: E402
from parallax.detect import TransformerDetector, default_detectors, resolve_model  # noqa: E402

ok = []


def check(n, c, d=""):
    ok.append(bool(c)); print(f"[{'PASS' if c else 'FAIL'}] {n} {d}")


def names(**env):
    keys = ["GEMINI_API_KEY", "GOOGLE_API_KEY", "PARALLAX_ZERO_SHOT_GEMMA", "PARALLAX_ML_TRANSFORMER"]
    saved = {k: os.environ.pop(k, None) for k in keys}
    os.environ.update(env)
    try:
        return [d.name for d in default_detectors()]
    finally:
        for k in keys:
            os.environ.pop(k, None)
            if saved[k] is not None:
                os.environ[k] = saved[k]


check("no env: gemma-4 is off", "gemma-4" not in names())
check("GEMINI_API_KEY alone does not turn gemma-4 on", "gemma-4" not in names(GEMINI_API_KEY="x"))
check("GOOGLE_API_KEY alone does not turn gemma-4 on", "gemma-4" not in names(GOOGLE_API_KEY="x"))
check("flag without a key does not turn gemma-4 on", "gemma-4" not in names(PARALLAX_ZERO_SHOT_GEMMA="1"))
check("flag other than 1 does not turn it on", "gemma-4" not in names(GEMINI_API_KEY="x", PARALLAX_ZERO_SHOT_GEMMA="true"))
check("key + PARALLAX_ZERO_SHOT_GEMMA=1 turns gemma-4 on", "gemma-4" in names(GEMINI_API_KEY="x", PARALLAX_ZERO_SHOT_GEMMA="1"))

# model location: a folder that exists is used as is
with tempfile.TemporaryDirectory() as d:
    check("existing folder is used as is", resolve_model(d) == d)

    # naming: a Gemma model is called gemma-finetuned, any other keeps its generic name
    for body, expect in [('{"base": "google/gemma-3-1b-pt"}', True), ('{"base": "microsoft/deberta-v3-small"}', False)]:
        (Path(d) / "parallax_report.json").write_text(body)
        check(f"report {body} -> gemma={expect}", TransformerDetector._is_gemma(Path(d)) is expect)
    (Path(d) / "parallax_report.json").unlink()
    (Path(d) / "config.json").write_text('{"model_type": "gemma3_text"}')
    check("no report: config.json says gemma -> gemma-finetuned", TransformerDetector._is_gemma(Path(d)))

try:
    resolve_model("/no/such/folder/at/all")
    check("a missing folder is a clear error", False)
except FileNotFoundError as e:
    check("a missing folder is a clear error", "not a folder or a Hugging Face repo id" in str(e), str(e)[:60])

# repo id: downloaded with HF_TOKEN, only the files the product needs
calls = []
fake = types.ModuleType("huggingface_hub")
fake.snapshot_download = lambda repo, **kw: calls.append((repo, kw)) or "/cache/snap"
saved_mod = sys.modules.get("huggingface_hub")
sys.modules["huggingface_hub"] = fake
os.environ["HF_TOKEN"] = "hf_test"
try:
    got = resolve_model("someone/parallax-gemma")
finally:
    os.environ.pop("HF_TOKEN")
    if saved_mod is not None:
        sys.modules["huggingface_hub"] = saved_mod
    else:
        del sys.modules["huggingface_hub"]
repo, kw = calls[0]
check("repo id is downloaded", got == "/cache/snap" and repo == "someone/parallax-gemma")
check("HF_TOKEN is passed to the download", kw["token"] == "hf_test")
check("download is limited to model files (no checkpoints or optimizer)",
      "model.safetensors" in kw["allow_patterns"] and not any("optimizer" in p or "checkpoint" in p for p in kw["allow_patterns"]))

print("\nALL PASS" if all(ok) else "\nSOME CHECKS FAILED")
sys.exit(0 if all(ok) else 1)
