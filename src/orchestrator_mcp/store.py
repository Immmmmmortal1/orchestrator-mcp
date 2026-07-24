from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import runs_db_path


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _ensure_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                goal TEXT NOT NULL,
                profile TEXT NOT NULL,
                role TEXT NOT NULL,
                status TEXT NOT NULL,
                role_overrides TEXT NOT NULL DEFAULT '{}',
                workspace TEXT,
                extra_context TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS role_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                role TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                status TEXT NOT NULL,
                input_json TEXT,
                output_json TEXT,
                error TEXT,
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                estimated_cost_usd REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES runs(id)
            );

            CREATE INDEX IF NOT EXISTS idx_role_run ON role_executions(run_id, role);
            """
        )

        # Existing installations may still have the former stage-named columns.
        # Copy only the single review role that can be used by the active runtime.
        cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
        legacy_current_role = "current_stage" if "current_stage" in cols else None
        legacy_role_overrides = "stage_overrides" if "stage_overrides" in cols else None
        legacy_roles_json = "roles_json" if "roles_json" in cols else None
        if "role" not in cols:
            conn.execute("ALTER TABLE runs ADD COLUMN role TEXT NOT NULL DEFAULT ''")
        if "role_overrides" not in cols:
            conn.execute("ALTER TABLE runs ADD COLUMN role_overrides TEXT NOT NULL DEFAULT '{}'")
        if "workspace" not in cols:
            conn.execute("ALTER TABLE runs ADD COLUMN workspace TEXT")
        if "extra_context" not in cols:
            conn.execute("ALTER TABLE runs ADD COLUMN extra_context TEXT")

        if legacy_current_role:
            conn.execute(
                """
                UPDATE runs SET role = current_stage
                WHERE role = '' AND current_stage IN ('ui_review', 'code_review', 'general_review')
                """
            )
        if legacy_roles_json:
            rows = conn.execute(
                "SELECT id, roles_json FROM runs WHERE role = '' AND roles_json IS NOT NULL"
            ).fetchall()
            for run_id, raw_roles in rows:
                try:
                    old_roles = json.loads(raw_roles or "[]")
                except (TypeError, json.JSONDecodeError):
                    continue
                if isinstance(old_roles, list) and len(old_roles) == 1 and old_roles[0] in (
                    "ui_review",
                    "code_review",
                    "general_review",
                ):
                    conn.execute(
                        "UPDATE runs SET role = ? WHERE id = ?",
                        (old_roles[0], run_id),
                    )
        if legacy_role_overrides:
            conn.execute(
                """
                UPDATE runs SET role_overrides = stage_overrides
                WHERE (role_overrides IS NULL OR role_overrides = '{}')
                  AND stage_overrides IS NOT NULL
                """
            )

        # Preserve historical execution records without making the former schema
        # part of the active review implementation.
        legacy_tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if "stage_executions" in legacy_tables:
            copied = conn.execute("SELECT COUNT(*) FROM role_executions").fetchone()[0]
            if copied == 0:
                conn.execute(
                    """
                    INSERT INTO role_executions
                    (id, run_id, role, provider, model, status, input_json, output_json, error,
                     prompt_tokens, completion_tokens, estimated_cost_usd, created_at)
                    SELECT id, run_id, stage, provider, model, status, input_json, output_json, error,
                           prompt_tokens, completion_tokens, estimated_cost_usd, created_at
                    FROM stage_executions
                    """
                )


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    path = runs_db_path()
    _ensure_db(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


class RunStore:
    def create_run(
        self,
        *,
        goal: str,
        profile: str,
        role: str,
        role_overrides: dict[str, dict[str, str]] | None = None,
        workspace: str | None = None,
        extra_context: str | None = None,
    ) -> str:
        run_id = str(uuid.uuid4())
        now = _utc_now()
        overrides = json.dumps(role_overrides or {}, ensure_ascii=False)
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO runs (id, goal, profile, role, status, role_overrides,
                                  workspace, extra_context, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    goal,
                    profile,
                    role,
                    overrides,
                    workspace,
                    extra_context,
                    now,
                    now,
                ),
            )
        return run_id

    def get_run(self, run_id: str) -> dict[str, Any]:
        with _connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"run not found: {run_id}")
        data = dict(row)
        data["role_overrides"] = json.loads(data.get("role_overrides") or "{}")
        return data

    def update_run(self, run_id: str, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = _utc_now()
        if "role_overrides" in fields and isinstance(fields["role_overrides"], dict):
            fields["role_overrides"] = json.dumps(fields["role_overrides"], ensure_ascii=False)
        cols = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values()) + [run_id]
        with _connect() as conn:
            conn.execute(f"UPDATE runs SET {cols} WHERE id = ?", values)

    def record_role(
        self,
        *,
        run_id: str,
        role: str,
        provider: str,
        model: str,
        status: str,
        input_payload: dict[str, Any] | None,
        output_payload: dict[str, Any] | None,
        error: str | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO role_executions
                (run_id, role, provider, model, status, input_json, output_json, error,
                 prompt_tokens, completion_tokens, estimated_cost_usd, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    role,
                    provider,
                    model,
                    status,
                    json.dumps(input_payload or {}, ensure_ascii=False),
                    json.dumps(output_payload or {}, ensure_ascii=False) if output_payload else None,
                    error,
                    prompt_tokens,
                    completion_tokens,
                    estimated_cost_usd,
                    _utc_now(),
                ),
            )

    def latest_handoff(self, run_id: str, role: str) -> dict[str, Any] | None:
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT output_json FROM role_executions
                WHERE run_id = ? AND role = ? AND status = 'completed' AND output_json IS NOT NULL
                ORDER BY id DESC LIMIT 1
                """,
                (run_id, role),
            ).fetchone()
        if row is None or not row["output_json"]:
            return None
        return json.loads(row["output_json"])

    def list_role_executions(self, run_id: str) -> list[dict[str, Any]]:
        with _connect() as conn:
            rows = conn.execute(
                """
                SELECT role, provider, model, status, error, prompt_tokens,
                       completion_tokens, estimated_cost_usd, created_at
                FROM role_executions WHERE run_id = ?
                ORDER BY id ASC
                """,
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def cost_summary(self, run_id: str) -> dict[str, Any]:
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                    COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd
                FROM role_executions WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        return dict(row) if row else {"prompt_tokens": 0, "completion_tokens": 0, "estimated_cost_usd": 0.0}
