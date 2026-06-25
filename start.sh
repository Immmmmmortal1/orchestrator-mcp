#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export ORCHESTRATOR_MCP_TRANSPORT="${ORCHESTRATOR_MCP_TRANSPORT:-streamable-http}"
export ORCHESTRATOR_MCP_HOST="${ORCHESTRATOR_MCP_HOST:-127.0.0.1}"
export ORCHESTRATOR_MCP_PORT="${ORCHESTRATOR_MCP_PORT:-18067}"

PYTHON="$("$ROOT/ensure-venv.sh")"
echo "orchestrator-mcp → http://${ORCHESTRATOR_MCP_HOST}:${ORCHESTRATOR_MCP_PORT}/mcp"
exec "$PYTHON" -m orchestrator_mcp
