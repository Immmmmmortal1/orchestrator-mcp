from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..profiles import Profile, RoleConfig


@dataclass
class ProviderResult:
    handoff: dict[str, Any]
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0.0
    raw_text: str = ""


class LLMProvider(Protocol):
    name: str

    def run_role(
        self,
        *,
        role: str,
        goal: str,
        role_config: RoleConfig,
        inputs: dict[str, Any],
        profile: Profile,
    ) -> ProviderResult: ...


class StubProvider:
    """Placeholder provider — no external LLM calls."""

    name = "stub"

    def run_role(
        self,
        *,
        role: str,
        goal: str,
        role_config: RoleConfig,
        inputs: dict[str, Any],
        profile: Profile,
    ) -> ProviderResult:
        _ = profile
        schema_id = role_config.output_schema
        if role in ("ui_review", "code_review", "general_review"):
            handoff = {
                "schema": "review.v1",
                "verdict": "pass",
                "blocking": [],
                "suggestions": [f"Replace stub provider with a real model for {role}."],
            }
        else:
            raise ValueError(f"stub provider does not support review role {role!r}")

        if handoff.get("schema") != schema_id and schema_id:
            handoff["schema"] = schema_id

        return ProviderResult(
            handoff=handoff,
            prompt_tokens=128,
            completion_tokens=256,
            estimated_cost_usd=0.0,
            raw_text=str(handoff),
        )
