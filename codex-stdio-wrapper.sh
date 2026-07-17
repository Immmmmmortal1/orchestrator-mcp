#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$ROOT/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  PYTHON="$("$ROOT/ensure-venv.sh")"
fi

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export ORCHESTRATOR_MCP_TRANSPORT="stdio"
export ORCHESTRATOR_MCP_SESSION_ID="${CODEX_THREAD_ID:?CODEX_THREAD_ID is required for per-session MCP isolation}"

exec "$PYTHON" -m orchestrator_mcp
