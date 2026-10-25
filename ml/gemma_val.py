"""Zero-shot baseline: the shipped GemmaDetector (Gemma 4, prompted, no training) on the trial's
validation sample (gemma_val.json written by ml/train_trial.py). Needs GEMINI_API_KEY.

    python ml/gemma_val.py path/to/gemma_val.json

Calls that still fail after retries are excluded and counted, not scored as "safe".
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from parallax.detect import GemmaDetector  # noqa: E402


def ask(det, text, tries=4):
    for k in range(tries):
        v = det(text)
        if not v.detail.startswith("error:"):
            return v.flagged
        time.sleep(5 * 2 ** k)
    return None


def main():
    data = json.load(open(sys.argv[1]))
    det = GemmaDetector()
    print("model:", det.model)
    res, errors = {}, {}
    sets = {"email attack": data["email_attack"], "harmless email": data["email_ok"],
            "web attack window": [r["text"] for r in data["web"] if r["kind"] == "attack"],
            "web clean twin": [r["text"] for r in data["web"] if r["kind"] == "twin"]}
    for name, texts in sets.items():
        out = [ask(det, t) for t in texts]
        res[name] = [x for x in out if x is not None]
        errors[name] = sum(x is None for x in out)
        print(f"  {name:18s} flagged {sum(res[name])}/{len(res[name])}   failed calls excluded: {errors[name]}", flush=True)
    print("note: the prompt says the text was hidden; validation windows are whole visible page passages")
    json.dump({"model": det.model, "flagged": {k: f"{sum(v)}/{len(v)}" for k, v in res.items()}, "failed_calls": errors},
              open(Path(sys.argv[1]).with_name("gemma_val_result.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
