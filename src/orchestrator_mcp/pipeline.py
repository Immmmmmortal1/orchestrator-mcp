from __future__ import annotations

from typing import Any

from .context.workspace import load_workspace_context, resolve_workspace
from .credentials import normalize_provider
from .profiles import Profile, STAGE_ORDER, StageConfig, load_profile
from .providers import get_provider
from .schemas import validate_handoff
from .store import RunStore


class PipelineError(Exception):
    pass


class Orchestrator:
    def __init__(self, store: RunStore | None = None) -> None:
        self.store = store or RunStore()

    def start_run(
        self,
        *,
        goal: str,
        profile_name: str = "daily-dev",
        stage_overrides: dict[str, dict[str, str]] | None = None,
        workspace: str | None = None,
        extra_context: str | None = None,
    ) -> dict[str, Any]:
        profile = load_profile(profile_name)
        resolved_workspace = None
        ws = resolve_workspace(workspace)
        if ws is not None:
            resolved_workspace = str(ws)
        run_id = self.store.create_run(
            goal=goal,
            profile=profile.name,
            stage_overrides=stage_overrides,
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
            "workspace": resolved_workspace,
            "context_sources": (context_meta or {}).get("sources") or [],
            "next_stage": "plan",
            "stages": list(STAGE_ORDER),
        }

    def resolve_stage_config(self, run: dict[str, Any], stage: str) -> StageConfig:
        profile = load_profile(run["profile"])
        cfg = profile.stage(stage)
        overrides = run.get("stage_overrides") or {}
        stage_override = overrides.get(stage) or {}
        if stage_override.get("provider"):
            cfg.provider = normalize_provider(stage_override["provider"])
        if stage_override.get("model"):
            cfg.model = stage_override["model"]
        cfg.provider = normalize_provider(cfg.provider)
        return cfg

    def _inputs_for_stage(
        self,
        run_id: str,
        stage: str,
        stage_cfg: StageConfig,
    ) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        inputs: dict[str, Any] = {"goal": run["goal"]}
        workspace = run.get("workspace")
        if workspace:
            inputs["workspace_context"] = load_workspace_context(
                workspace,
                skill_names=stage_cfg.skills,
                extra_context=run.get("extra_context"),
            )
        if stage in ("code", "review", "deliver"):
            plan = self.store.latest_handoff(run_id, "plan")
            if plan is None:
                raise PipelineError("plan handoff missing — run plan stage first")
            inputs["plan"] = plan
        if stage in ("review", "deliver"):
            code = self.store.latest_handoff(run_id, "code")
            if code is None:
                raise PipelineError("code handoff missing — run code stage first")
            inputs["code"] = code
        if stage == "deliver":
            review = self.store.latest_handoff(run_id, "review")
            if review is None and not load_profile(self.store.get_run(run_id)["profile"]).skip_review:
                raise PipelineError("review handoff missing — run review stage first")
            inputs["review"] = review or {"verdict": "skipped"}
        return inputs

    def dispatch_stage(self, run_id: str, stage: str | None = None) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        profile = load_profile(run["profile"])
        target = stage or run.get("current_stage") or "plan"
        if target not in STAGE_ORDER:
            raise PipelineError(f"invalid stage: {target}")

        if run["status"] == "completed":
            return {"ok": True, "run_id": run_id, "status": "completed", "message": "run already completed"}

        if target == "review" and profile.skip_review:
            self.store.update_run(run_id, current_stage="deliver", status="running")
            return self.dispatch_stage(run_id, "deliver")

        stage_cfg = self.resolve_stage_config(run, target)
        provider = get_provider(stage_cfg.provider)
        inputs = self._inputs_for_stage(run_id, target, stage_cfg)

        self.store.update_run(run_id, status="running", current_stage=target)
        try:
            result = provider.run_stage(
                stage=target,
                goal=run["goal"],
                stage_config=stage_cfg,
                inputs=inputs,
                profile=profile,
            )
            validate_handoff(stage_cfg.output_schema, result.handoff)
            self.store.record_stage(
                run_id=run_id,
                stage=target,
                provider=stage_cfg.provider,
                model=stage_cfg.model,
                status="completed",
                input_payload={
                    "stage": target,
                    "inputs_keys": list(inputs.keys()),
                    "context_sources": (inputs.get("workspace_context") or {}).get("sources"),
                },
                output_payload=result.handoff,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                estimated_cost_usd=result.estimated_cost_usd,
            )
        except Exception as exc:
            self.store.record_stage(
                run_id=run_id,
                stage=target,
                provider=stage_cfg.provider,
                model=stage_cfg.model,
                status="failed",
                input_payload={"stage": target},
                output_payload=None,
                error=str(exc),
            )
            self.store.update_run(run_id, status="failed")
            raise PipelineError(str(exc)) from exc

        next_stage, status = self._next_state(run_id, target, result.handoff, profile)
        self.store.update_run(run_id, current_stage=next_stage, status=status)
        return {
            "ok": True,
            "run_id": run_id,
            "stage": target,
            "provider": stage_cfg.provider,
            "model": stage_cfg.model,
            "handoff": result.handoff,
            "next_stage": next_stage,
            "status": status,
            "cost": self.store.cost_summary(run_id),
        }

    def _next_state(
        self,
        run_id: str,
        stage: str,
        handoff: dict[str, Any],
        profile: Profile,
    ) -> tuple[str | None, str]:
        if stage == "review" and handoff.get("verdict") == "revise":
            run = self.store.get_run(run_id)
            rounds = int(run.get("review_round") or 0) + 1
            self.store.update_run(run_id, review_round=rounds)
            if rounds < profile.max_review_rounds:
                return "code", "running"
            return None, "failed"

        idx = STAGE_ORDER.index(stage)
        if idx + 1 < len(STAGE_ORDER):
            return STAGE_ORDER[idx + 1], "running"
        return None, "completed"

    def run_pipeline(
        self,
        *,
        goal: str,
        profile_name: str = "daily-dev",
        stage_overrides: dict[str, dict[str, str]] | None = None,
        workspace: str | None = None,
        extra_context: str | None = None,
    ) -> dict[str, Any]:
        started = self.start_run(
            goal=goal,
            profile_name=profile_name,
            stage_overrides=stage_overrides,
            workspace=workspace,
            extra_context=extra_context,
        )
        run_id = started["run_id"]
        stages_run: list[str] = []

        while True:
            run = self.store.get_run(run_id)
            if run["status"] in ("completed", "failed"):
                break
            stage = run.get("current_stage")
            if not stage:
                break
            self.dispatch_stage(run_id, stage)
            stages_run.append(stage)

        final = self.status(run_id)
        final["stages_executed"] = stages_run
        return final

    def set_stage_override(
        self,
        run_id: str,
        stage: str,
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        if stage not in STAGE_ORDER:
            raise PipelineError(f"invalid stage: {stage}")
        run = self.store.get_run(run_id)
        overrides = dict(run.get("stage_overrides") or {})
        entry = dict(overrides.get(stage) or {})
        if provider:
            entry["provider"] = provider
        if model:
            entry["model"] = model
        overrides[stage] = entry
        self.store.update_run(run_id, stage_overrides=overrides)
        return {"ok": True, "run_id": run_id, "stage": stage, "override": entry}

    def status(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        handoffs = {
            stage: self.store.latest_handoff(run_id, stage)
            for stage in STAGE_ORDER
        }
        return {
            "ok": True,
            "run": {
                "id": run["id"],
                "goal": run["goal"],
                "profile": run["profile"],
                "workspace": run.get("workspace"),
                "status": run["status"],
                "current_stage": run["current_stage"],
                "review_round": run["review_round"],
                "stage_overrides": run.get("stage_overrides") or {},
            },
            "handoffs": {k: v for k, v in handoffs.items() if v is not None},
            "executions": self.store.list_stage_executions(run_id),
            "cost": self.store.cost_summary(run_id),
        }

    def handoff(self, run_id: str, stage: str) -> dict[str, Any]:
        payload = self.store.latest_handoff(run_id, stage)
        if payload is None:
            raise PipelineError(f"no completed handoff for stage {stage!r}")
        return {"ok": True, "run_id": run_id, "stage": stage, "handoff": payload}
