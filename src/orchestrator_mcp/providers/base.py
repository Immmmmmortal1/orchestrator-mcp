from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..profiles import Profile, StageConfig


@dataclass
class ProviderResult:
    handoff: dict[str, Any]
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0.0
    raw_text: str = ""


class LLMProvider(Protocol):
    name: str

    def run_stage(
        self,
        *,
        stage: str,
        goal: str,
        stage_config: StageConfig,
        inputs: dict[str, Any],
        profile: Profile,
    ) -> ProviderResult: ...


class StubProvider:
    """Placeholder provider — no external LLM calls."""

    name = "stub"

    def run_stage(
        self,
        *,
        stage: str,
        goal: str,
        stage_config: StageConfig,
        inputs: dict[str, Any],
        profile: Profile,
    ) -> ProviderResult:
        _ = profile
        schema_id = stage_config.output_schema
        if stage == "plan":
            handoff = {
                "schema": "plan.v1",
                "summary": f"[stub plan] {goal[:200]}",
                "tasks": [
                    {
                        "id": "T1",
                        "desc": f"Implement goal: {goal[:120]}",
                        "files_hint": [],
                    }
                ],
                "acceptance": ["Self-test passes", "Handoff schemas validate"],
                "risks": ["Stub provider — replace with real LLM before production"],
                "out_of_scope": [],
            }
        elif stage == "code":
            plan = inputs.get("plan") or {}
            tasks = plan.get("tasks") or [{"id": "T1"}]
            handoff = {
                "schema": "code_handoff.v1",
                "tasks_done": [t.get("id", "T1") for t in tasks],
                "files_changed": [],
                "test_commands": ["cd orchestrator-mcp && ./verify.sh"],
                "notes_for_reviewer": "Stub code stage — no files were modified.",
            }
        elif stage == "review":
            handoff = {
                "schema": "review.v1",
                "verdict": "pass",
                "blocking": [],
                "suggestions": ["Replace stub providers with real model adapters."],
            }
        elif stage == "deliver":
            plan = inputs.get("plan") or {}
            review = inputs.get("review") or {}
            handoff = {
                "schema": "deliver.v1",
                "title": plan.get("summary") or goal[:80],
                "summary": f"Pipeline completed with review verdict={review.get('verdict', 'unknown')}.",
                "test_plan": (inputs.get("code") or {}).get("test_commands") or [],
                "artifacts": [],
                "pr_body_markdown": (
                    f"## Summary\n\n{plan.get('summary', goal)}\n\n"
                    f"## Review\n\nVerdict: **{review.get('verdict', 'n/a')}**\n"
                ),
            }
        else:
            raise ValueError(f"stub provider does not support stage {stage!r}")

        if handoff.get("schema") != schema_id and schema_id:
            handoff["schema"] = schema_id

        return ProviderResult(
            handoff=handoff,
            prompt_tokens=128,
            completion_tokens=256,
            estimated_cost_usd=0.0,
            raw_text=str(handoff),
        )
