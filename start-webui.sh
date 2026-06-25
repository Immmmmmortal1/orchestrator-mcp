#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
PYTHON="$("$ROOT/ensure-venv.sh")"
HOST="${ORCHESTRATOR_WEBUI_HOST:-127.0.0.1}"
PORT="${ORCHESTRATOR_WEBUI_PORT:-18068}"
echo "Orchestrator Web UI → http://${HOST}:${PORT}"
exec "$PYTHON" -m orchestrator_mcp.webui.app
