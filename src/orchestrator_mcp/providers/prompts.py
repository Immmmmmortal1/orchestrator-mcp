from __future__ import annotations

import json
from typing import Any

from ..profiles import RoleConfig

_ROLE_RULES: dict[str, str] = {
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
}


def build_messages(
    *,
    role: str,
    goal: str,
    role_config: RoleConfig,
    inputs: dict[str, Any],
) -> list[dict[str, str]]:
    from ..context.workspace import format_workspace_context_for_prompt

    rules = _ROLE_RULES.get(role)
    if not rules:
        raise ValueError(f"unsupported role for LLM prompt: {role}")

    system_parts = [
        "You are an independent review-role worker in a review hub, not a software delivery pipeline. "
        "Review only the caller-provided goal and evidence. Do not plan implementation, modify files, commit, push, or deliver code. "
        "Output MUST be a single valid JSON object. No markdown fences, no commentary.",
        rules,
    ]

    workspace_block = format_workspace_context_for_prompt(inputs.get("workspace_context"))
    if workspace_block:
        system_parts.append(workspace_block)

    system = "\n\n".join(system_parts)

    user_payload: dict[str, Any] = {"goal": goal, "role": role}
    ctx = inputs.get("workspace_context")
    if isinstance(ctx, dict):
        user_payload["workspace"] = ctx.get("workspace")
        user_payload["context_sources"] = ctx.get("sources") or []

    user = "Input context (JSON):\n" + json.dumps(user_payload, ensure_ascii=False, indent=2)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
