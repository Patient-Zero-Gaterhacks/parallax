#!/usr/bin/env bash
# Overnight full run, in order, unattended:
#   1. full training (trial-fix pipeline, one pass over every train-side pair, checkpoints)
#   2. validation: full model vs trial-fix vs V2 on trial-fix's exact validation panel (inside step 1)
#   3. pick the winner by the rules fixed in ml/pick_winner.py
#   4. official test, once, on the winner only (plus V2): BrowseSafe++ 20% test, AgentDojo, BIPIA test, hand-written
#   5. /workspace/morning_report.md
# A training crash stops the chain (no retry, no official tests) and still writes the report with
# trial-fix as the shipping model. The pod is never stopped by this script.
#
#   nohup bash ml/overnight.sh > /dev/null 2>&1 &      # on the pod, from /workspace/parallax
#   QUICK=1 bash ml/overnight.sh                        # smoke test: tiny data, no reserved test data scored
set -u
cd /workspace/parallax
export HF_HOME=/workspace/.cache/huggingface/ PARALLAX_DATA=/workspace/data_src PYTHONUNBUFFERED=1
PY=/workspace/venv/bin/python

if [ "${QUICK:-0}" = 1 ]; then
  OUT=models/quick-run STATE=/workspace/overnight-quick LOG=/workspace/overnight-quick.log
  REPORT=/workspace/morning_report_quick.md EXTRA=--quick
else
  OUT=models/full-run STATE=/workspace/overnight LOG=/workspace/overnight.log
  REPORT=/workspace/morning_report.md EXTRA=
fi
mkdir -p "$STATE"
: > "$STATE/steps.txt"
rm -f "$STATE/winner.json" "$STATE/official.json" "$STATE/training_status" "$STATE"/eval_*.txt

ts() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

run() {   # run <name> <command...>: timestamps in the log, exit code and seconds in steps.txt
  local name=$1; shift
  local t0; t0=$(date +%s)
  ts "START $name: $*"
  "$@" >> "$LOG" 2>&1
  local rc=$?
  echo "$name $rc $(( $(date +%s) - t0 ))" >> "$STATE/steps.txt"
  ts "END $name (exit $rc, $(( ($(date +%s) - t0) / 60 )) min)"
  return $rc
}

ts "OVERNIGHT START (QUICK=${QUICK:-0})"
if run train $PY -u ml/train_trial2.py --full $EXTRA --n-pairs 5000 --ckpt-every 250 --minutes 230 \
     --out "$OUT" --compare models/trial-fix --compare-npairs 5000; then
  echo ok > "$STATE/training_status"
  run pick_winner $PY ml/pick_winner.py "$OUT/trial_report.json" "$STATE/winner.json" || ts "pick_winner failed: trial-fix ships"
  W=$($PY -c "import json; print(json.load(open('$STATE/winner.json'))['winner'])" 2>/dev/null || echo trial-fix)
  if [ "$W" = full-run ]; then WDIR=$OUT; else WDIR=models/trial-fix; fi
  ts "WINNER: $W ($WDIR)"
  if [ "${QUICK:-0}" = 1 ]; then
    run official $PY -I ml/official_test.py --model "$WDIR" --out "$STATE/official.json" --self-check
  else
    run official $PY -I ml/official_test.py --model "$WDIR" --out "$STATE/official.json"
    run eval_pipeline bash -c "set -o pipefail; PARALLAX_ML_TRANSFORMER=$WDIR $PY -I ml/eval_pipeline.py | tee $STATE/eval_pipeline.txt"
    run eval_external bash -c "set -o pipefail; PARALLAX_ML_TRANSFORMER=$WDIR $PY -I ml/eval_external.py | tee $STATE/eval_external.txt"
  fi
else
  echo "crashed" > "$STATE/training_status"
  ts "TRAINING FAILED: stopping here (no retry, no official tests). trial-fix is the shipping model."
fi
run morning_report $PY ml/morning_report.py "$STATE" "$OUT/trial_report.json" "$REPORT" "$LOG"
ts "OVERNIGHT DONE. Pod left running."
