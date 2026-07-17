from __future__ import annotations

import atexit
import fcntl
import json
import os
import re
import signal
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import data_dir

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_registered_path: Path | None = None
_registered_instance_id: str | None = None
_shutdown_handlers_installed = False


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def current_session_id() -> str:
    return os.environ.get("ORCHESTRATOR_MCP_SESSION_ID", "").strip()


def _validated_session_id(session_id: str) -> str:
    if not _SESSION_ID_RE.fullmatch(session_id):
        raise ValueError("ORCHESTRATOR_MCP_SESSION_ID is missing or invalid")
    return session_id


def sessions_dir() -> Path:
    path = data_dir() / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def session_record_path(session_id: str) -> Path:
    return sessions_dir() / f"{_validated_session_id(session_id)}.json"


@contextmanager
def _session_lock(session_id: str):
    lock_path = sessions_dir() / f"{_validated_session_id(session_id)}.lock"
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _process_start_fingerprint(pid: int) -> str | None:
    try:
        value = subprocess.check_output(
            ["ps", "-p", str(pid), "-o", "lstart="],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return value or None


def read_session_record(session_id: str) -> dict[str, Any] | None:
    path = session_record_path(session_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def register_current_process() -> dict[str, Any] | None:
    global _registered_instance_id, _registered_path

    transport = os.environ.get("ORCHESTRATOR_MCP_TRANSPORT", "streamable-http")
    if transport != "stdio":
        return None
    session_id = _validated_session_id(current_session_id())
    instance_id = str(uuid.uuid4())
    record = {
        "session_id": session_id,
        "instance_id": instance_id,
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "process_started_at": _process_start_fingerprint(os.getpid()),
        "transport": transport,
        "started_at": _utc_now(),
    }
    path = session_record_path(session_id)
    with _session_lock(session_id):
        temp = path.with_name(f".{path.name}.{os.getpid()}.{instance_id}.tmp")
        temp.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)
    _registered_path = path
    _registered_instance_id = instance_id
    atexit.register(unregister_current_process)
    return record


def unregister_current_process() -> None:
    global _registered_instance_id, _registered_path

    path = _registered_path
    instance_id = _registered_instance_id
    if path is None or instance_id is None:
        return
    _unregister_session_record(path, instance_id)
    _registered_path = None
    _registered_instance_id = None


def _unregister_session_record(path: Path, instance_id: str) -> None:
    session_id = path.stem
    try:
        with _session_lock(session_id):
            current = json.loads(path.read_text(encoding="utf-8"))
            if current.get("instance_id") == instance_id:
                path.unlink(missing_ok=True)
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        pass


def install_shutdown_handlers() -> None:
    global _shutdown_handlers_installed
    if _shutdown_handlers_installed:
        return

    def _shutdown(signum: int, _frame: object) -> None:
        unregister_current_process()
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    _shutdown_handlers_installed = True


def start_replacement_watchdog(interval_seconds: float = 0.25) -> None:
    path = _registered_path
    instance_id = _registered_instance_id
    if path is None or instance_id is None:
        return

    def _watch() -> None:
        while True:
            time.sleep(interval_seconds)
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                continue
            if current.get("instance_id") != instance_id:
                os._exit(0)

    threading.Thread(target=_watch, name="orchestrator-session-owner", daemon=True).start()


def current_session_status() -> dict[str, Any]:
    session_id = current_session_id()
    transport = os.environ.get("ORCHESTRATOR_MCP_TRANSPORT", "streamable-http")
    result: dict[str, Any] = {
        "transport": transport,
        "session_id": session_id or None,
        "pid": os.getpid(),
        "ppid": os.getppid(),
    }
    if transport != "stdio":
        result["registered"] = False
        return result
    try:
        record = read_session_record(session_id)
    except ValueError:
        record = None
    result["registered"] = bool(
        record
        and record.get("session_id") == session_id
        and record.get("pid") == os.getpid()
        and record.get("instance_id") == _registered_instance_id
    )
    result["instance_id"] = record.get("instance_id") if record else None
    return result


def registered_session_health(session_id: str) -> dict[str, Any]:
    try:
        record = read_session_record(session_id)
    except ValueError as exc:
        return {"ok": False, "session_id": session_id or None, "error": str(exc)}
    if record is None:
        return {"ok": False, "session_id": session_id, "error": "session record not found"}
    if record.get("session_id") != session_id or record.get("transport") != "stdio":
        return {"ok": False, "session_id": session_id, "error": "session record mismatch"}
    pid = record.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return {"ok": False, "session_id": session_id, "error": "session pid is invalid"}
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return {"ok": False, "session_id": session_id, "pid": pid, "error": "session pid is not alive"}
    expected_start = record.get("process_started_at")
    actual_start = _process_start_fingerprint(pid)
    if not expected_start or actual_start != expected_start:
        return {
            "ok": False,
            "session_id": session_id,
            "pid": pid,
            "error": "session process identity does not match",
        }
    return {"ok": True, **record}
