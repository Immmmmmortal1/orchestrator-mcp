from __future__ import annotations

import json
from typing import Any

from ..profiles import StageConfig

_STAGE_RULES: dict[str, str] = {
    "plan": (
        "Produce plan.v1 JSON only. Fields: schema=plan.v1, summary, tasks[{id,desc,files_hint?}], "
        "acceptance[], risks[], out_of_scope[]. Break work into concrete engineering tasks."
    ),
    "code": (
        "Produce code_handoff.v1 JSON only. Fields: schema=code_handoff.v1, tasks_done[], "
        "files_changed[], test_commands[], notes_for_reviewer. "
        "Base decisions on the provided plan; describe intended code changes (paths + rationale)."
    ),
    "review": (
        "Produce review.v1 JSON only. Fields: schema=review.v1, verdict=pass|revise, "
        "blocking[], suggestions[]. Judge whether code handoff satisfies the plan acceptance criteria."
    ),
    "ui_review": (
        "Produce review.v1 JSON only. Fields: schema=review.v1, verdict=pass|revise, "
        "blocking[], suggestions[]. You are a UI implementation reviewer. Focus on Figma/design parity, "
        "runtime view hierarchy evidence, missing/extra elements, typography, color, spacing, size, alignment, "
        "interaction states, accessibility identifiers, and screenshot/DebugBridge discrepancies. "
        "Do not block on unrelated code-style issues unless they directly affect UI correctness."
    ),
    "code_review": (
        "Produce review.v1 JSON only. Fields: schema=review.v1, verdict=pass|revise, "
        "blocking[], suggestions[]. You are a code reviewer. Focus on correctness, regressions, state flow, "
        "error handling, architecture fit, performance, security/privacy, maintainability, and missing tests. "
        "Do not block on visual pixel differences unless the implementation code clearly causes them."
    ),
    "general_review": (
        "Produce review.v1 JSON only. Fields: schema=review.v1, verdict=pass|revise, "
        "blocking[], suggestions[]. You are a general product/implementation reviewer. Focus on requirements, "
        "user flow completeness, edge cases, consistency, release risk, and anything not covered by dedicated "
        "UI or code review roles."
    ),
    "deliver": (
        "Produce deliver.v1 JSON only. Fields: schema=deliver.v1, title, summary, test_plan[], "
        "artifacts[], pr_body_markdown. Summarize for human handoff / PR description."
    ),
}


def build_messages(
    *,
    stage: str,
    goal: str,
    stage_config: StageConfig,
    inputs: dict[str, Any],
) -> list[dict[str, str]]:
    from ..context.workspace import format_workspace_context_for_prompt

    rules = _STAGE_RULES.get(stage)
    if not rules:
        raise ValueError(f"unsupported stage for LLM prompt: {stage}")

    system_parts = [
        "You are a stage worker in a software delivery pipeline. "
        "Output MUST be a single valid JSON object. No markdown fences, no commentary.",
        rules,
    ]

    workspace_block = format_workspace_context_for_prompt(inputs.get("workspace_context"))
    if workspace_block:
        system_parts.append(workspace_block)

    system = "\n\n".join(system_parts)

    user_payload: dict[str, Any] = {"goal": goal, "stage": stage}
    if inputs.get("plan"):
        user_payload["plan"] = inputs["plan"]
    if inputs.get("code"):
        user_payload["code_handoff"] = inputs["code"]
    if inputs.get("review"):
        user_payload["review"] = inputs["review"]

    ctx = inputs.get("workspace_context")
    if isinstance(ctx, dict):
        user_payload["workspace"] = ctx.get("workspace")
        user_payload["context_sources"] = ctx.get("sources") or []

    user = "Input context (JSON):\n" + json.dumps(user_payload, ensure_ascii=False, indent=2)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
