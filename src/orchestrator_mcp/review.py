from __future__ import annotations

from typing import Any

from .config_store import normalize_role_overrides
from .context.workspace import load_workspace_context, resolve_workspace
from .credentials import normalize_provider
from .profiles import REVIEW_ROLE_IDS, Profile, RoleConfig, load_profile, normalize_role
from .providers import get_provider
from .schemas import validate_handoff
from .store import RunStore


class ReviewError(Exception):
    pass


class Orchestrator:
    """Run exactly one independent review role per persisted review task."""

    def __init__(self, store: RunStore | None = None) -> None:
        self.store = store or RunStore()

    @staticmethod
    def _normalize_role(role: str) -> str:
        target = normalize_role(role)
        if target not in REVIEW_ROLE_IDS:
            raise ReviewError(f"invalid review role: {role}")
        return target

    def start_run(
        self,
        *,
        goal: str,
        role: str,
        profile_name: str = "daily-dev",
        role_overrides: dict[str, dict[str, str]] | None = None,
        workspace: str | None = None,
        extra_context: str | None = None,
    ) -> dict[str, Any]:
        profile = load_profile(profile_name)
        target_role = self._normalize_role(role)
        profile.role(target_role)
        resolved_workspace = None
        ws = resolve_workspace(workspace)
        if ws is not None:
            resolved_workspace = str(ws)
        normalized_overrides = normalize_role_overrides(
            role_overrides,
            default_role=target_role,
        )
        run_id = self.store.create_run(
            goal=goal,
            profile=profile.name,
            role=target_role,
            role_overrides=normalized_overrides,
            workspace=resolved_workspace,
            extra_context=(extra_context or "").strip() or None,
        )
        context_meta: dict[str, Any] | None = None
        if resolved_workspace:
            context_meta = load_workspace_context(
                resolved_workspace,
                skill_names=[],
                extra_context=(extra_context or "").strip() or None,
            )
        return {
            "ok": True,
            "run_id": run_id,
            "profile": profile.name,
            "role": target_role,
            "workspace": resolved_workspace,
            "context_sources": (context_meta or {}).get("sources") or [],
        }

    def resolve_role_config(self, run: dict[str, Any]) -> RoleConfig:
        role = self._normalize_role(run["role"])
        profile = load_profile(run["profile"])
        cfg = profile.role(role)
        overrides = normalize_role_overrides(
            run.get("role_overrides") or {},
            default_role=role,
        )
        role_override = overrides.get(role) or {}
        if role_override.get("provider"):
            cfg.provider = normalize_provider(role_override["provider"])
        if role_override.get("model"):
            cfg.model = role_override["model"]
        cfg.provider = normalize_provider(cfg.provider)
        return cfg

    def _inputs_for_role(
        self,
        run_id: str,
        role: str,
        role_config: RoleConfig,
    ) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        inputs: dict[str, Any] = {"goal": run["goal"], "role": role}
        workspace = run.get("workspace")
        if workspace:
            inputs["workspace_context"] = load_workspace_context(
                workspace,
                skill_names=role_config.skills,
                extra_context=run.get("extra_context"),
            )
        return inputs

    def _status_after_role(self, run_id: str) -> str:
        executions = self.store.list_role_executions(run_id)
        if not executions:
            return "pending"
        latest = executions[-1]["status"]
        if latest == "completed":
            return "completed"
        if latest == "failed":
            return "failed"
        return "running"

    def dispatch_role(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        target = self._normalize_role(run["role"])
        profile = load_profile(run["profile"])
        role_config = self.resolve_role_config(run)
        provider = get_provider(role_config.provider)
        inputs = self._inputs_for_role(run_id, target, role_config)
        self.store.update_run(run_id, status="running")
        try:
            result = provider.run_role(
                role=target,
                goal=run["goal"],
                role_config=role_config,
                inputs=inputs,
                profile=profile,
            )
            validate_handoff(role_config.output_schema, result.handoff)
            self.store.record_role(
                run_id=run_id,
                role=target,
                provider=role_config.provider,
                model=role_config.model,
                status="completed",
                input_payload={
                    "role": target,
                    "inputs_keys": list(inputs.keys()),
                    "context_sources": (inputs.get("workspace_context") or {}).get("sources"),
                },
                output_payload=result.handoff,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                estimated_cost_usd=result.estimated_cost_usd,
            )
        except Exception as exc:
            self.store.record_role(
                run_id=run_id,
                role=target,
                provider=role_config.provider,
                model=role_config.model,
                status="failed",
                input_payload={"role": target},
                output_payload=None,
                error=str(exc),
            )
            self.store.update_run(run_id, status=self._status_after_role(run_id))
            raise ReviewError(str(exc)) from exc

        status = self._status_after_role(run_id)
        self.store.update_run(run_id, status=status)
        return {
            "ok": True,
            "run_id": run_id,
            "role": target,
            "provider": role_config.provider,
            "model": role_config.model,
            "handoff": result.handoff,
            "status": status,
            "cost": self.store.cost_summary(run_id),
        }

    def set_role_override(
        self,
        run_id: str,
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        role = self._normalize_role(run["role"])
        overrides = dict(run.get("role_overrides") or {})
        entry = dict(overrides.get(role) or {})
        if provider:
            entry["provider"] = provider
        if model:
            entry["model"] = model
        normalized = normalize_role_overrides({role: entry}, default_role=role)
        overrides[role] = normalized.get(role, entry)
        self.store.update_run(run_id, role_overrides=overrides)
        return {"ok": True, "run_id": run_id, "role": role, "override": overrides[role]}

    def status(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        role = self._normalize_role(run["role"])
        return {
            "ok": True,
            "run": {
                "id": run["id"],
                "goal": run["goal"],
                "profile": run["profile"],
                "role": role,
                "workspace": run.get("workspace"),
                "status": run["status"],
                "role_overrides": run.get("role_overrides") or {},
            },
            "handoff": self.store.latest_handoff(run_id, role),
            "executions": self.store.list_role_executions(run_id),
            "cost": self.store.cost_summary(run_id),
        }

    def handoff(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        role = self._normalize_role(run["role"])
        payload = self.store.latest_handoff(run_id, role)
        if payload is None:
            raise ReviewError(f"no completed handoff for role {role!r}")
        return {"ok": True, "run_id": run_id, "role": role, "handoff": payload}
