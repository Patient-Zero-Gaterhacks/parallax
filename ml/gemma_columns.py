"""Extra columns for the test scripts when Gemma is available (the before/after-Gemma ladder).

  GEMINI_API_KEY=...                 -> "+ Gemma (zero-shot)"  : Gemma 4 with no training, via Google AI Studio
  PARALLAX_ML_TRANSFORMER=<folder>   -> "+ Gemma (fine-tuned)" : our model from ml/train_transformer.py
"""

import os

from parallax.detect import GemmaDetector, MLDetector, PatternDetector, TransformerDetector


def extra_setups() -> dict:
    out = {}
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        out["+ Gemma (zero-shot)"] = [PatternDetector(), MLDetector(), GemmaDetector()]
    if os.environ.get("PARALLAX_ML_TRANSFORMER"):
        out["+ Gemma (fine-tuned)"] = [PatternDetector(), MLDetector(), TransformerDetector(os.environ["PARALLAX_ML_TRANSFORMER"])]
    return out
