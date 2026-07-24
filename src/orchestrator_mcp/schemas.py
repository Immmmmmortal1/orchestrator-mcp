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

    if schema_id == "review.v1":
        _require_keys(data, ["verdict", "blocking", "suggestions"], "review.v1")
        if data["verdict"] not in ("pass", "revise"):
            raise ValueError("review.v1 verdict must be pass or revise")
        _require_type(data["blocking"], list, "blocking")
        _require_type(data["suggestions"], list, "suggestions")
        return

    raise ValueError(f"unknown schema: {schema_id}")
