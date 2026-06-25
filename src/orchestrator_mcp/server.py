from __future__ import annotations

import json
import os

from mcp.server.fastmcp import FastMCP

from .config_store import get_active_profile_name, resolve_profile_name
from .context.workspace import load_workspace_context, resolve_workspace
from .pipeline import Orchestrator, PipelineError
from .profiles import list_profiles
from .providers import get_provider, list_provider_status, normalize_provider, provider_configured

mcp = FastMCP(
    "orchestrator-mcp",
    instructions=(
        "Multi-model agent orchestration: plan → code → review → deliver. "
        "Stages and handoff schemas are fixed; providers/models are swappable via profiles "
        "or per-run overrides. Pass workspace (or set ORCHESTRATOR_WORKSPACE) to load the same "
        "AGENTS.md / .cursor/rules / .learnings files the IDE client uses — no separate MCP memory file. "
        "Typical flow: orchestrate_run_start → orchestrate_dispatch (repeat) or orchestrate_run_pipeline."
    ),
    host=os.environ.get("ORCHESTRATOR_MCP_HOST", "127.0.0.1"),
    port=int(os.environ.get("ORCHESTRATOR_MCP_PORT", "18067")),
)

_engine = Orchestrator()


def _json(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _parse_overrides(raw: str) -> dict[str, dict[str, str]] | None:
    text = (raw or "").strip()
    if not text:
        return None
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("stage_overrides must be a JSON object")
    return data


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
    workspace: str = "",
    extra_context: str = "",
) -> str:
    """Create a pipeline run. Returns run_id and next_stage=plan. Empty profile uses WebUI active_profile."""
    try:
        overrides = _parse_overrides(stage_overrides_json)
        resolved = resolve_profile_name(profile)
        ws = (workspace or "").strip() or None
        extra = (extra_context or "").strip() or None
        return _json(
            _engine.start_run(
                goal=goal,
                profile_name=resolved,
                stage_overrides=overrides,
                workspace=ws,
                extra_context=extra,
            )
        )
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})


@mcp.tool()
def orchestrate_dispatch(run_id: str, stage: str = "") -> str:
    """Run one pipeline stage (default: run.current_stage). Validates handoff schema."""
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
    workspace: str = "",
    extra_context: str = "",
) -> str:
    """Run plan→code→review→deliver sequentially. Empty profile uses WebUI active_profile."""
    try:
        overrides = _parse_overrides(stage_overrides_json)
        resolved = resolve_profile_name(profile)
        ws = (workspace or "").strip() or None
        extra = (extra_context or "").strip() or None
        return _json(
            _engine.run_pipeline(
                goal=goal,
                profile_name=resolved,
                stage_overrides=overrides,
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
    """Fetch latest completed handoff for a stage (plan|code|review|deliver)."""
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
