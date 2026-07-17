#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV="$ROOT/.venv"

pick_python() {
  for py in python3.12 python3.11 python3.10 python3; do
    if command -v "$py" >/dev/null 2>&1; then
      if "$py" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
        echo "$py"
        return 0
      fi
    fi
  done
  echo "需要 Python 3.10+（mcp 包）。请安装 python3.11 后重试。" >&2
  exit 1
}

PY="$(pick_python)"

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "创建 venv: $VENV ($PY)" >&2
  "$PY" -m venv "$VENV"
fi

"$VENV/bin/python" -m pip install -q -U pip
"$VENV/bin/python" -m pip install -q -r "$ROOT/requirements.txt"
printf '%s\n' "$VENV/bin/python"
