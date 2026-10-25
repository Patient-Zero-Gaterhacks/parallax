#!/usr/bin/env bash
# Host the Parallax server for everyone (judges, the extension's hosted default) in public mode:
# URL scans only reach public addresses, /approve and /gateway are off, sizes are capped and each
# client IP is rate-limited (see parallax/server.py). Logs go to /workspace/server.log.
#
# On the RunPod pod, from the repo folder, so it keeps running after you log out:
#   nohup bash scripts/serve_public.sh > /dev/null 2>&1 &
#   tail -f /workspace/server.log
# Stop it:  pkill -f "uvicorn parallax.server:app"
#
# Override the model folder or the allowed website origins if needed:
#   PARALLAX_ML_TRANSFORMER=/path/to/model PARALLAX_ALLOWED_ORIGINS=https://our-site.example \
#     nohup bash scripts/serve_public.sh > /dev/null 2>&1 &
set -eu
cd "$(dirname "$0")/.."
export PARALLAX_PUBLIC=1
export PARALLAX_ML_TRANSFORMER="${PARALLAX_ML_TRANSFORMER:-/workspace/parallax/models/trial-fix}"
export HF_HOME="${HF_HOME:-/workspace/.cache/huggingface/}"
PY="${PY:-/workspace/venv/bin/python}"
command -v "$PY" > /dev/null || PY=python3
echo "[$(date '+%Y-%m-%d %H:%M:%S')] starting Parallax (public mode, model: $PARALLAX_ML_TRANSFORMER)" >> /workspace/server.log
exec "$PY" -m uvicorn parallax.server:app --host 0.0.0.0 --port 8787 --workers 1 >> /workspace/server.log 2>&1
