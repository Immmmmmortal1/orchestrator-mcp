from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

MCP_LABEL = "com.xiaomao11.orchestrator-mcp"
WEBUI_LABEL = "com.xiaomao11.orchestrator-webui"
LEGACY_ROOT = Path.home() / "orchestrator-mcp"


def build_codex_block(root: Path) -> str:
    return f'''[mcp_servers.orchestrator_mcp]
command = "{root / 'codex-stdio-wrapper.sh'}"
args = []
startup_timeout_sec = 120.0

[mcp_servers.orchestrator_mcp.env]
ORCHESTRATOR_MCP_TRANSPORT = "stdio"
PYTHONPATH = "{root / 'src'}"
'''


def replace_codex_block(text: str, block: str) -> str:
    pattern = re.compile(
        r"(?ms)^\[mcp_servers\.orchestrator_mcp\]\n.*?"
        r"(?=^\[mcp_servers\.(?!orchestrator_mcp(?:\.|\]))|\Z)"
    )
    replacement = block.rstrip() + "\n\n"
    if pattern.search(text):
        return pattern.sub(replacement, text, count=1)
    return text.rstrip() + "\n\n" + replacement


def build_launchd_plist(root: Path, label: str, *, webui: bool) -> dict[str, Any]:
    python = str(root / ".venv/bin/python")
    env = {"PYTHONPATH": str(root / "src")}
    module = "orchestrator_mcp"
    stdout = "/tmp/orchestrator-mcp.launchd.log"
    stderr = "/tmp/orchestrator-mcp.launchd.err"
    if webui:
        module = "orchestrator_mcp.webui.app"
        env.update(ORCHESTRATOR_WEBUI_HOST="127.0.0.1", ORCHESTRATOR_WEBUI_PORT="18068")
        stdout = "/tmp/orchestrator-webui.launchd.log"
        stderr = "/tmp/orchestrator-webui.launchd.err"
    else:
        env.update(
            ORCHESTRATOR_MCP_HOST="127.0.0.1",
            ORCHESTRATOR_MCP_PORT="18067",
            ORCHESTRATOR_MCP_TRANSPORT="streamable-http",
        )
    return {
        "Label": label,
        "ProgramArguments": [python, "-m", module],
        "WorkingDirectory": str(root),
        "EnvironmentVariables": env,
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": stdout,
        "StandardErrorPath": stderr,
    }


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=check)


def _bootstrap_after_unload(
    uid: str,
    label: str,
    plist_path: Path,
    *,
    timeout: float = 10.0,
) -> None:
    deadline = time.monotonic() + timeout
    while True:
        state = _run("launchctl", "print", f"gui/{uid}/{label}", check=False)
        if state.returncode != 0:
            started = _run(
                "launchctl", "bootstrap", f"gui/{uid}", str(plist_path), check=False
            )
            if started.returncode == 0:
                return
        if time.monotonic() >= deadline:
            detail = (state.stderr or state.stdout or "launchd state did not converge").strip()
            raise RuntimeError(f"timed out reloading {label}: {detail}")
        time.sleep(0.05)


def _port_listener_pids(port: int) -> list[int]:
    result = _run(
        "lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t", check=False
    )
    return [int(line) for line in result.stdout.splitlines() if line.strip().isdigit()]


def _wait_for_listener(port: int, *, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while True:
        if _port_listener_pids(port):
            return
        if time.monotonic() >= deadline:
            raise RuntimeError(f"timed out waiting for port {port} to listen")
        time.sleep(0.05)


def _backup(path: Path, stamp: str) -> Path | None:
    if not path.exists():
        return None
    backup = path.with_name(f"{path.name}.bak.{stamp}")
    shutil.copy2(path, backup)
    return backup


def _migrate_legacy_data(root: Path, stamp: str) -> list[str]:
    marker = root / "data/.legacy-migration-complete"
    if marker.exists() or not LEGACY_ROOT.is_dir():
        return []
    migrated: list[str] = []
    for name in ("providers.local.json", "stages.local.json"):
        source = LEGACY_ROOT / "data" / name
        target = root / "data" / name
        if source.is_file() and not target.exists():
            shutil.copy2(source, target)
            migrated.append(name)
    source_db = LEGACY_ROOT / "data/runs/orchestrator.db"
    target_db = root / "data/runs/orchestrator.db"
    if source_db.is_file() and not target_db.exists():
        target_db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(source_db) as source, sqlite3.connect(target_db) as target:
            source.backup(target)
        migrated.append("runs/orchestrator.db")
    marker.write_text(datetime.now().astimezone().isoformat() + "\n", encoding="utf-8")
    return migrated


def install(root: Path) -> dict[str, Any]:
    root = root.resolve()
    if root != Path("/Users/xiaomao11/project/orchestrator-mcp"):
        raise ValueError(f"refusing non-canonical root: {root}")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    _run(str(root / "ensure-venv.sh"))
    os.chmod(root / "codex-stdio-wrapper.sh", 0o755)

    uid = str(os.getuid())
    for label in (MCP_LABEL, WEBUI_LABEL):
        _run("launchctl", "bootout", f"gui/{uid}/{label}", check=False)

    config = Path.home() / ".codex/config.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    original = config.read_text(encoding="utf-8") if config.exists() else ""
    config_backup = _backup(config, stamp)
    config.write_text(replace_codex_block(original, build_codex_block(root)), encoding="utf-8")

    launch_agents = Path.home() / "Library/LaunchAgents"
    launch_agents.mkdir(parents=True, exist_ok=True)
    plist_paths: list[Path] = []
    for label, webui in ((MCP_LABEL, False), (WEBUI_LABEL, True)):
        path = launch_agents / f"{label}.plist"
        _backup(path, stamp)
        with path.open("wb") as handle:
            plistlib.dump(build_launchd_plist(root, label, webui=webui), handle, sort_keys=False)
        plist_paths.append(path)

    migrated = _migrate_legacy_data(root, stamp)
    for path, label in zip(plist_paths, (MCP_LABEL, WEBUI_LABEL), strict=True):
        _bootstrap_after_unload(uid, label, path)
    _wait_for_listener(18067)
    _wait_for_listener(18068)

    return {
        "ok": True,
        "root": str(root),
        "config_backup": str(config_backup) if config_backup else None,
        "plists": [str(path) for path in plist_paths],
        "migrated": migrated,
        "restart_codex_required": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        result = install(args.root)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
