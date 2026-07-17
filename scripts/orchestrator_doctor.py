from __future__ import annotations

import json
import os
import plistlib
import subprocess
from pathlib import Path
from typing import Any

from scripts.install_local import MCP_LABEL, WEBUI_LABEL


def _listener(port: int) -> list[int]:
    result = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
        text=True,
        capture_output=True,
    )
    return [int(line) for line in result.stdout.splitlines() if line.strip().isdigit()]


def _process(pid: int) -> dict[str, Any]:
    command = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="], text=True, capture_output=True
    ).stdout.strip()
    cwd_lines = subprocess.run(
        ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], text=True, capture_output=True
    ).stdout.splitlines()
    cwd = next((line[1:] for line in cwd_lines if line.startswith("n")), None)
    return {"pid": pid, "command": command, "cwd": cwd}


def inspect(root: Path) -> dict[str, Any]:
    root = root.resolve()
    config_path = Path.home() / ".codex/config.toml"
    config = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    checks: dict[str, Any] = {
        "canonical_root": root == Path("/Users/xiaomao11/project/orchestrator-mcp"),
        "venv_python": (root / ".venv/bin/python").is_file(),
        "wrapper": (root / "codex-stdio-wrapper.sh").is_file(),
        "codex_uses_canonical_wrapper": str(root / "codex-stdio-wrapper.sh") in config,
        "codex_stdio": 'ORCHESTRATOR_MCP_TRANSPORT = "stdio"' in config,
        "codex_has_legacy_path": "/Users/xiaomao11/orchestrator-mcp" in config,
    }
    plists: dict[str, Any] = {}
    for label in (MCP_LABEL, WEBUI_LABEL):
        path = Path.home() / "Library/LaunchAgents" / f"{label}.plist"
        try:
            data = plistlib.loads(path.read_bytes())
            plists[label] = {
                "exists": True,
                "working_directory": data.get("WorkingDirectory"),
                "canonical": data.get("WorkingDirectory") == str(root),
            }
        except (FileNotFoundError, plistlib.InvalidFileException):
            plists[label] = {"exists": False, "canonical": False}
    listeners = {str(port): [_process(pid) for pid in _listener(port)] for port in (18067, 18068)}
    healthy = (
        all(value for key, value in checks.items() if key != "codex_has_legacy_path")
        and not checks["codex_has_legacy_path"]
        and all(item["canonical"] for item in plists.values())
        and len(listeners["18067"]) == 1
        and len(listeners["18068"]) == 1
        and all(proc["cwd"] == str(root) for rows in listeners.values() for proc in rows)
    )
    return {"ok": healthy, "root": str(root), "checks": checks, "plists": plists, "listeners": listeners}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    result = inspect(root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
