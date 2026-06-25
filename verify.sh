#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
PYTHON="$("$ROOT/ensure-venv.sh")"
chmod +x "$ROOT/start.sh" "$ROOT/ensure-venv.sh" 2>/dev/null || true
echo "== orchestrator-mcp self-test =="
"$PYTHON" -m orchestrator_mcp.self_test
echo "PASS"
