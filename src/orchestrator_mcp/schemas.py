from __future__ import annotations

from typing import Any


def _require_keys(data: dict[str, Any], keys: list[str], label: str) -> None:
    missing = [k for k in keys if k not in data]
    if missing:
        raise ValueError(f"{label} missing keys: {', '.join(missing)}")


def _require_type(value: Any, expected: type, field: str) -> None:
    if not isinstance(value, expected):
        raise ValueError(f"{field} must be {expected.__name__}")


def validate_handoff(schema_id: str, data: dict[str, Any]) -> None:
    if data.get("schema") != schema_id:
        raise ValueError(f"schema mismatch: expected {schema_id!r}, got {data.get('schema')!r}")

    if schema_id == "plan.v1":
        _require_keys(data, ["summary", "tasks", "acceptance", "risks"], "plan.v1")
        _require_type(data["summary"], str, "summary")
        _require_type(data["tasks"], list, "tasks")
        if not data["tasks"]:
            raise ValueError("plan.v1 tasks must not be empty")
        for task in data["tasks"]:
            _require_type(task, dict, "task")
            _require_keys(task, ["id", "desc"], "task")
        return

    if schema_id == "code_handoff.v1":
        _require_keys(
            data,
            ["tasks_done", "files_changed", "test_commands", "notes_for_reviewer"],
            "code_handoff.v1",
        )
        for key in ("tasks_done", "files_changed", "test_commands"):
            _require_type(data[key], list, key)
        _require_type(data["notes_for_reviewer"], str, "notes_for_reviewer")
        return

    if schema_id == "review.v1":
        _require_keys(data, ["verdict", "blocking", "suggestions"], "review.v1")
        if data["verdict"] not in ("pass", "revise"):
            raise ValueError("review.v1 verdict must be pass or revise")
        _require_type(data["blocking"], list, "blocking")
        _require_type(data["suggestions"], list, "suggestions")
        return

    if schema_id == "deliver.v1":
        _require_keys(data, ["title", "summary", "test_plan", "artifacts"], "deliver.v1")
        for key in ("title", "summary"):
            _require_type(data[key], str, key)
        for key in ("test_plan", "artifacts"):
            _require_type(data[key], list, key)
        return

    raise ValueError(f"unknown schema: {schema_id}")
