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
                status TEXT NOT NULL,
                current_stage TEXT,
                review_round INTEGER NOT NULL DEFAULT 0,
                stage_overrides TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS stage_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                stage TEXT NOT NULL,
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

            CREATE INDEX IF NOT EXISTS idx_stage_run ON stage_executions(run_id, stage);
            """
        )
        cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
        if "workspace" not in cols:
            conn.execute("ALTER TABLE runs ADD COLUMN workspace TEXT")
        if "extra_context" not in cols:
            conn.execute("ALTER TABLE runs ADD COLUMN extra_context TEXT")


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
        stage_overrides: dict[str, dict[str, str]] | None = None,
        workspace: str | None = None,
        extra_context: str | None = None,
    ) -> str:
        run_id = str(uuid.uuid4())
        now = _utc_now()
        overrides = json.dumps(stage_overrides or {}, ensure_ascii=False)
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO runs (id, goal, profile, status, current_stage, review_round,
                                  stage_overrides, workspace, extra_context, created_at, updated_at)
                VALUES (?, ?, ?, 'pending', 'plan', 0, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    goal,
                    profile,
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
        data["stage_overrides"] = json.loads(data.get("stage_overrides") or "{}")
        return data

    def update_run(self, run_id: str, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = _utc_now()
        if "stage_overrides" in fields and isinstance(fields["stage_overrides"], dict):
            fields["stage_overrides"] = json.dumps(fields["stage_overrides"], ensure_ascii=False)
        cols = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [run_id]
        with _connect() as conn:
            conn.execute(f"UPDATE runs SET {cols} WHERE id = ?", values)

    def record_stage(
        self,
        *,
        run_id: str,
        stage: str,
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
                INSERT INTO stage_executions
                (run_id, stage, provider, model, status, input_json, output_json, error,
                 prompt_tokens, completion_tokens, estimated_cost_usd, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    stage,
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

    def latest_handoff(self, run_id: str, stage: str) -> dict[str, Any] | None:
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT output_json FROM stage_executions
                WHERE run_id = ? AND stage = ? AND status = 'completed' AND output_json IS NOT NULL
                ORDER BY id DESC LIMIT 1
                """,
                (run_id, stage),
            ).fetchone()
        if row is None or not row["output_json"]:
            return None
        return json.loads(row["output_json"])

    def list_stage_executions(self, run_id: str) -> list[dict[str, Any]]:
        with _connect() as conn:
            rows = conn.execute(
                """
                SELECT stage, provider, model, status, error, prompt_tokens,
                       completion_tokens, estimated_cost_usd, created_at
                FROM stage_executions WHERE run_id = ?
                ORDER BY id ASC
                """,
                (run_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def cost_summary(self, run_id: str) -> dict[str, Any]:
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                    COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd
                FROM stage_executions WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        return dict(row) if row else {"prompt_tokens": 0, "completion_tokens": 0, "estimated_cost_usd": 0.0}
