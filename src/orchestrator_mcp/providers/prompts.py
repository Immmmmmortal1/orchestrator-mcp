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
    rules = _STAGE_RULES.get(stage)
    if not rules:
        raise ValueError(f"unsupported stage for LLM prompt: {stage}")

    skill_note = ""
    if stage_config.skills:
        skill_note = f"Follow skills: {', '.join(stage_config.skills)}.\n"

    system = (
        "You are a stage worker in a software delivery pipeline. "
        "Output MUST be a single valid JSON object. No markdown fences, no commentary.\n"
        f"{skill_note}{rules}"
    )

    user_payload: dict[str, Any] = {"goal": goal, "stage": stage}
    if inputs.get("plan"):
        user_payload["plan"] = inputs["plan"]
    if inputs.get("code"):
        user_payload["code_handoff"] = inputs["code"]
    if inputs.get("review"):
        user_payload["review"] = inputs["review"]

    user = "Input context (JSON):\n" + json.dumps(user_payload, ensure_ascii=False, indent=2)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
