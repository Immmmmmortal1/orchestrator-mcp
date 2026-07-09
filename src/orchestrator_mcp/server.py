from __future__ import annotations

import json
import os

from mcp.server.fastmcp import FastMCP

from .config_store import (
    get_active_profile_name,
    get_stage_overrides,
    normalize_stage_overrides,
    resolve_profile_name,
)
from .context.workspace import load_workspace_context, resolve_workspace
from .pipeline import Orchestrator, PipelineError
from .profiles import STAGE_ORDER, list_profiles, load_profile, normalize_stage
from .providers import get_provider, list_provider_status, normalize_provider, provider_configured

mcp = FastMCP(
    "orchestrator-mcp",
    instructions=(
        "Role-based review hub for a primary coding agent. "
        "The caller provides the evidence and implementation context; this MCP routes it to a reviewer model. "
        "Stages are ui_review, code_review, and general_review. "
        "Typical flow: orchestrate_effective_config, then orchestrate_run_pipeline with an optional stage."
    ),
    host=os.environ.get("ORCHESTRATOR_MCP_HOST", "127.0.0.1"),
    port=int(os.environ.get("ORCHESTRATOR_MCP_PORT", "18067")),
)

_engine = Orchestrator()


def _json(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _parse_overrides(raw: str, *, default_stage: str = "general_review") -> dict[str, dict[str, str]] | None:
    text = (raw or "").strip()
    if not text:
        return None
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("stage_overrides must be a JSON object")
    return normalize_stage_overrides(data, default_stage=default_stage)


def _effective_config(profile: str = "", stage_overrides_json: str = "", stage: str = "") -> dict[str, object]:
    target_stage = normalize_stage(stage) if stage else ""
    if target_stage and target_stage not in STAGE_ORDER:
        raise ValueError(f"invalid stage: {stage}")
    overrides = _parse_overrides(stage_overrides_json, default_stage=target_stage or "general_review") or {}
    resolved = resolve_profile_name(profile)
    profile_cfg = load_profile(resolved)
    webui_overrides = get_stage_overrides(profile_cfg.name)
    stages: list[dict[str, object]] = []
    warnings: list[str] = []
    selected_stages = (target_stage,) if target_stage else STAGE_ORDER
    for stage_name in selected_stages:
        cfg = profile_cfg.stage(stage_name)
        runtime = overrides.get(stage_name) or {}
        provider = normalize_provider(runtime.get("provider") or cfg.provider)
        model = runtime.get("model") or cfg.model
        configured = provider == "stub" or provider_configured(provider)
        source = (
            "runtime_override"
            if runtime
            else ("webui_stage_override" if stage_name in webui_overrides else "profile_yaml")
        )
        if not configured:
            warnings.append(
                f"{stage_name} provider {provider!r} is not configured; save a WebUI Stage override or configure its API key."
            )
        stages.append(
            {
                "stage": stage_name,
                "provider": provider,
                "model": model,
                "configured": configured,
                "source": source,
                "webui_overridden": stage_name in webui_overrides,
                "runtime_overridden": bool(runtime),
            }
        )
    return {
        "ok": True,
        "active_profile": get_active_profile_name(),
        "profile": profile_cfg.name,
        "stages": stages,
        "warnings": warnings,
    }


@mcp.tool()
def orchestrate_list_profiles() -> str:
    """List orchestration profiles; active_profile is the WebUI default used when profile is omitted."""
    active = get_active_profile_name()
    return _json(
        {
            "ok": True,
            "active_profile": active,
            "profiles": list_profiles(active_name=active),
        }
    )


@mcp.tool()
def orchestrate_effective_config(
    profile: str = "",
    stage_overrides_json: str = "",
    stage: str = "",
) -> str:
    """Show the effective profile/stage provider/model MCP will use, without calling any LLM."""
    try:
        return _json(_effective_config(profile, stage_overrides_json, stage))
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})


@mcp.tool()
def orchestrate_list_providers() -> str:
    """List LLM providers and whether API keys are configured (no secrets returned)."""
    return _json({"ok": True, "providers": list_provider_status()})


@mcp.tool()
def orchestrate_provider_check(provider: str) -> str:
    """Check if a provider (deepseek|moonshot|zhipu|glm|openai|gpt) has credentials."""
    name = normalize_provider(provider)
    try:
        get_provider(name)
    except KeyError as exc:
        return _json({"ok": False, "error": str(exc)})
    return _json({"ok": True, "provider": name, "configured": provider_configured(name)})


@mcp.tool()
def orchestrate_workspace_context(
    workspace: str = "",
    skill: str = "",
) -> str:
    """Preview project context loaded from workspace (same files as IDE client). Read-only."""
    try:
        root = resolve_workspace(workspace or None)
        if root is None:
            return _json(
                {
                    "ok": False,
                    "error": "workspace required (argument or ORCHESTRATOR_WORKSPACE env)",
                }
            )
        skill_names = [s.strip() for s in skill.split(",") if s.strip()] if skill.strip() else []
        ctx = load_workspace_context(root, skill_names=skill_names or None)
        return _json({"ok": True, "context": ctx})
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})


@mcp.tool()
def orchestrate_run_start(
    goal: str,
    profile: str = "",
    stage_overrides_json: str = "",
    stage: str = "",
    workspace: str = "",
    extra_context: str = "",
) -> str:
    """Create a review run. Optional stage: ui_review|code_review|general_review. Empty profile uses WebUI active_profile."""
    try:
        target_stage = normalize_stage(stage) if stage else ""
        overrides = _parse_overrides(stage_overrides_json, default_stage=target_stage or "general_review")
        resolved = resolve_profile_name(profile)
        ws = (workspace or "").strip() or None
        extra = (extra_context or "").strip() or None
        return _json(
            _engine.start_run(
                goal=goal,
                profile_name=resolved,
                stage_overrides=overrides,
                stage=target_stage or None,
                workspace=ws,
                extra_context=extra,
            )
        )
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})


@mcp.tool()
def orchestrate_dispatch(run_id: str, stage: str = "") -> str:
    """Run one review role stage (default: run.current_stage). Valid stages: ui_review, code_review, general_review."""
    try:
        target = stage.strip() or None
        return _json(_engine.dispatch_stage(run_id, target))
    except PipelineError as exc:
        return _json({"ok": False, "error": str(exc)})
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})


@mcp.tool()
def orchestrate_run_pipeline(
    goal: str,
    profile: str = "",
    stage_overrides_json: str = "",
    stage: str = "",
    workspace: str = "",
    extra_context: str = "",
) -> str:
    """Run all review roles, or one role when stage is set. Empty profile uses WebUI active_profile."""
    try:
        target_stage = normalize_stage(stage) if stage else ""
        overrides = _parse_overrides(stage_overrides_json, default_stage=target_stage or "general_review")
        resolved = resolve_profile_name(profile)
        ws = (workspace or "").strip() or None
        extra = (extra_context or "").strip() or None
        return _json(
            _engine.run_pipeline(
                goal=goal,
                profile_name=resolved,
                stage_overrides=overrides,
                stage=target_stage or None,
                workspace=ws,
                extra_context=extra,
            )
        )
    except PipelineError as exc:
        return _json({"ok": False, "error": str(exc)})
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})


@mcp.tool()
def orchestrate_status(run_id: str) -> str:
    """Get run status, handoffs, stage executions, and cost summary."""
    try:
        return _json(_engine.status(run_id))
    except KeyError as exc:
        return _json({"ok": False, "error": str(exc)})


@mcp.tool()
def orchestrate_handoff(run_id: str, stage: str) -> str:
    """Fetch latest completed handoff for a review role stage."""
    try:
        return _json(_engine.handoff(run_id, stage))
    except PipelineError as exc:
        return _json({"ok": False, "error": str(exc)})


@mcp.tool()
def orchestrate_stage_override(
    run_id: str,
    stage: str,
    provider: str = "",
    model: str = "",
) -> str:
    """Override provider/model for a stage before dispatch (e.g. swap plan to kimi)."""
    try:
        return _json(
            _engine.set_stage_override(
                run_id,
                stage,
                provider=provider.strip() or None,
                model=model.strip() or None,
            )
        )
    except PipelineError as exc:
        return _json({"ok": False, "error": str(exc)})


def main() -> None:
    transport = os.environ.get("ORCHESTRATOR_MCP_TRANSPORT", "streamable-http")
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
