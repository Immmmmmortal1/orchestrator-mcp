from __future__ import annotations

import json
import os

from mcp.server.fastmcp import FastMCP

from .config_store import (
    get_active_profile_name,
    get_role_overrides,
    normalize_role_overrides,
    resolve_profile_name,
)
from .context.workspace import load_workspace_context, resolve_workspace
from .review import Orchestrator, ReviewError
from .profiles import REVIEW_ROLES, REVIEW_ROLE_IDS, list_profiles, load_profile, normalize_role
from .providers import get_provider, list_provider_status, normalize_provider, provider_configured
from .session_runtime import (
    current_session_status,
    install_shutdown_handlers,
    register_current_process,
    start_replacement_watchdog,
)

mcp = FastMCP(
    "orchestrator-mcp",
    instructions=(
        "Review Hub for a primary coding agent. "
        "This MCP provides independent UI, code, and general review capabilities; it is not a software-delivery pipeline. "
        "The primary agent must provide the review goal and authoritative evidence/context. "
        "The MCP routes that request to configured reviewer roles and returns structured review findings and handoffs. "
        "Review roles do not implement fixes, modify the workspace, commit, push, create pull requests, or own plan/code/deliver roles. "
        "Use orchestrate_effective_config to inspect role configuration, orchestrate_run_start to create one review run, "
        "orchestrate_dispatch to run the role bound to that run, "
        "and orchestrate_handoff or orchestrate_status to retrieve results."
    ),
    host=os.environ.get("ORCHESTRATOR_MCP_HOST", "127.0.0.1"),
    port=int(os.environ.get("ORCHESTRATOR_MCP_PORT", "18067")),
)

_engine = Orchestrator()


def _json(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _parse_overrides(raw: str, *, default_role: str = "general_review") -> dict[str, dict[str, str]] | None:
    text = (raw or "").strip()
    if not text:
        return None
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("role_overrides must be a JSON object")
    return normalize_role_overrides(data, default_role=default_role)


def _effective_config(profile: str = "", role_overrides_json: str = "", role: str = "") -> dict[str, object]:
    target_role = normalize_role(role) if role else ""
    if target_role and target_role not in REVIEW_ROLE_IDS:
        raise ValueError(f"invalid role: {role}")
    overrides = _parse_overrides(role_overrides_json, default_role=target_role or "general_review") or {}
    resolved = resolve_profile_name(profile)
    profile_cfg = load_profile(resolved)
    webui_overrides = get_role_overrides(profile_cfg.name)
    roles: list[dict[str, object]] = []
    warnings: list[str] = []
    role_names = (target_role,) if target_role else REVIEW_ROLES
    for role_name in role_names:
        cfg = profile_cfg.role(role_name)
        runtime = overrides.get(role_name) or {}
        provider = normalize_provider(runtime.get("provider") or cfg.provider)
        model = runtime.get("model") or cfg.model
        configured = provider == "stub" or provider_configured(provider)
        source = (
            "runtime_override"
            if runtime
            else ("webui_role_override" if role_name in webui_overrides else "profile_yaml")
        )
        if not configured:
            warnings.append(
                f"{role_name} provider {provider!r} is not configured; save a WebUI Role override or configure its API key."
            )
        roles.append(
            {
                "role": role_name,
                "provider": provider,
                "model": model,
                "configured": configured,
                "source": source,
                "webui_overridden": role_name in webui_overrides,
                "runtime_overridden": bool(runtime),
            }
        )
    return {
        "ok": True,
        "active_profile": get_active_profile_name(),
        "profile": profile_cfg.name,
        "roles": roles,
        "warnings": warnings,
        "mcp_session": current_session_status(),
    }


@mcp.tool()
def orchestrate_list_profiles() -> str:
    """List review-role profiles; active_profile is the WebUI default used when profile is omitted."""
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
    role_overrides_json: str = "",
    role: str = "",
) -> str:
    """Show the effective provider/model for each configured review role, without calling any LLM."""
    try:
        return _json(_effective_config(profile, role_overrides_json, role))
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
    role: str,
    profile: str = "",
    role_overrides_json: str = "",
    workspace: str = "",
    extra_context: str = "",
) -> str:
    """Create a persisted review run for exactly one explicitly selected review role.

    This creates review state only; it does not plan work, implement changes, or deliver code.
    role is required and must be ui_review, code_review, or general_review.
    """
    try:
        target_role = role.strip()
        if not target_role:
            raise ValueError("role is required; choose one review role")
        overrides = _parse_overrides(role_overrides_json, default_role=target_role)
        resolved = resolve_profile_name(profile)
        ws = (workspace or "").strip() or None
        extra = (extra_context or "").strip() or None
        return _json(
            _engine.start_run(
                goal=goal,
                profile_name=resolved,
                role=target_role,
                role_overrides=overrides,
                workspace=ws,
                extra_context=extra,
            )
        )
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})


@mcp.tool()
def orchestrate_dispatch(run_id: str) -> str:
    """Run one configured review role and return its structured review handoff.

    The role is bound when the run is created. It does not modify the workspace or implement fixes.
    """
    try:
        return _json(_engine.dispatch_role(run_id))
    except ReviewError as exc:
        return _json({"ok": False, "error": str(exc)})
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})


@mcp.tool()
def orchestrate_status(run_id: str) -> str:
    """Get one review-run status, its role handoff, executions, and cost summary."""
    try:
        return _json(_engine.status(run_id))
    except KeyError as exc:
        return _json({"ok": False, "error": str(exc)})


@mcp.tool()
def orchestrate_handoff(run_id: str) -> str:
    """Fetch the latest completed structured handoff for the run's review role."""
    try:
        return _json(_engine.handoff(run_id))
    except ReviewError as exc:
        return _json({"ok": False, "error": str(exc)})


@mcp.tool()
def orchestrate_role_override(
    run_id: str,
    provider: str = "",
    model: str = "",
) -> str:
    """Override the provider/model for the run's review role before dispatch."""
    try:
        return _json(
            _engine.set_role_override(
                run_id,
                provider=provider.strip() or None,
                model=model.strip() or None,
            )
        )
    except ReviewError as exc:
        return _json({"ok": False, "error": str(exc)})


def main() -> None:
    transport = os.environ.get("ORCHESTRATOR_MCP_TRANSPORT", "streamable-http")
    if transport == "stdio":
        install_shutdown_handlers()
        register_current_process()
        start_replacement_watchdog()
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
