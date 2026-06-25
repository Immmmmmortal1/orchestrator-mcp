from __future__ import annotations

import json
import os
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA = _PKG_ROOT / "data"


def package_root() -> Path:
    return _PKG_ROOT


def data_dir() -> Path:
    d = Path(os.environ.get("ORCHESTRATOR_MCP_DATA", str(_DEFAULT_DATA)))
    d.mkdir(parents=True, exist_ok=True)
    return d


def profiles_dir() -> Path:
    override = os.environ.get("ORCHESTRATOR_MCP_PROFILES")
    if override:
        return Path(override)
    return package_root() / "profiles"


def schemas_dir() -> Path:
    override = os.environ.get("ORCHESTRATOR_MCP_SCHEMAS")
    if override:
        return Path(override)
    return package_root() / "schemas"


def runs_db_path() -> Path:
    return data_dir() / "runs" / "orchestrator.db"


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)
