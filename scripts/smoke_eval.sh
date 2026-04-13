#!/usr/bin/env bash
# Minimal smoke: requires local Ollama for classify/query if invoked with RUN_LLM=1
set -euo pipefail
cd "$(dirname "$0")/.."
. .venv/bin/activate
pytest tests/ -q
echo "pytest OK"
if [[ "${RUN_LLM:-0}" == "1" ]]; then
  investigate status
  investigate query "test hospital" --local-only --fetch-threshold 1 || true
fi
