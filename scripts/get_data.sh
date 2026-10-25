#!/usr/bin/env bash
# Downloads every public dataset Parallax trains or tests on (about 900 MB).
# Usage: bash scripts/get_data.sh [folder]   (default: ../data_src next to the repo)
set -e
DEST="${1:-$(cd "$(dirname "$0")/../.." && pwd)/data_src}"
mkdir -p "$DEST" && cd "$DEST"
clone() { [ -d "$2" ] && echo "have $2" || git clone --depth 1 "https://github.com/$1" "$2"; }

# Training
clone microsoft/llmail-inject-challenge-analysis llmail-inject-challenge-analysis   # ~29k real attack emails (Microsoft)
clone MWiechmann/enron_spam_data enron_spam_data                                     # 33.7k normal + spam emails
clone uiuc-kang-lab/InjecAgent InjecAgent                                            # attacks hidden in tool results
clone HumanCompatibleAI/tensor-trust-data tensor-trust-data                          # "take over the AI" attempts
# Testing only (never trained on)
clone microsoft/BIPIA BIPIA
clone ethz-spylab/agentdojo agentdojo
(cd enron_spam_data && [ -f enron_spam_data.csv ] || unzip -o -q enron_spam_data.zip)

echo
echo "Done: $DEST"
echo "Hugging Face sets (BrowseSafe, BrowseSafe++, full LLMail) are fetched by ml/train_transformer.py --hf,"
echo "or by hand:  pip install huggingface_hub && huggingface-cli download perplexity-ai/browsesafe-plus-plus --repo-type dataset --local-dir $DEST/browsesafe-plus-plus"
