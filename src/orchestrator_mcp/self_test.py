from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from .context.workspace import format_workspace_context_for_prompt, load_workspace_context
from .review import Orchestrator
from .providers import get_provider, list_provider_status, normalize_provider
from .providers.openai_compat import _extract_json


def _test_json_extract() -> None:
    sample = '```json\n{"schema":"review.v1","verdict":"pass","blocking":[],"suggestions":[]}\n```'
    parsed = _extract_json(sample)
    assert parsed["schema"] == "review.v1"


def _test_provider_registry() -> None:
    for name in ("deepseek", "moonshot", "zhipu", "glm", "openai", "gpt", "codex-lb", "codex", "stub"):
        provider = get_provider(name)
        assert provider.name or name == "glm"


def _test_aliases() -> None:
    assert normalize_provider("GPT") == "openai"
    assert normalize_provider("glm") == "zhipu"
    assert normalize_provider("codex") == "codex-lb"


def _test_workspace_context() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "AGENTS.md").write_text("# Agents\nUse snake_case for Python.\n", encoding="utf-8")
        learnings = root / ".learnings"
        learnings.mkdir()
        (learnings / "LEARNINGS.md").write_text("- always run verify.sh\n", encoding="utf-8")
        rules = root / ".cursor" / "rules"
        rules.mkdir(parents=True)
        (rules / "style.mdc").write_text("Prefer minimal diffs.\n", encoding="utf-8")

        ctx = load_workspace_context(root)
        if "AGENTS.md" not in ctx["sources"]:
            raise AssertionError("expected AGENTS.md in sources")
        if not any("snake_case" in s["content"] for s in ctx["sections"]):
            raise AssertionError("AGENTS content missing")

        prompt = format_workspace_context_for_prompt(ctx)
        if "snake_case" not in prompt or "minimal diffs" not in prompt:
            raise AssertionError("prompt missing workspace file contents")

        from .profiles import load_profile
        from .providers.prompts import build_messages

        messages = build_messages(
            role="ui_review",
            goal="Add workspace reader",
            role_config=load_profile("daily-dev-stub").role("ui_review"),
            inputs={"workspace_context": ctx},
        )
        system = messages[0]["content"]
        if "snake_case" not in system:
            raise AssertionError("build_messages did not inject workspace into system prompt")

        os.environ["ORCHESTRATOR_MCP_DATA"] = str(root / "data")
        (root / "data").mkdir()
        engine = Orchestrator()
        started = engine.start_run(
            goal="Workspace review test",
            profile_name="daily-dev-stub",
            role="ui_review",
            workspace=str(root),
            extra_context="Mid-run note from client",
        )
        if not started.get("workspace"):
            raise AssertionError("start_run should record workspace")
        if started.get("role") != "ui_review":
            raise AssertionError("start_run should preserve selected review role")
        if "AGENTS.md" not in (started.get("context_sources") or []):
            raise AssertionError("start_run should list context sources")

        run_id = started["run_id"]
        result = engine.dispatch_role(run_id)
        if not result.get("ok"):
            raise AssertionError(result.get("error") or "ui_review dispatch failed")

        del os.environ["ORCHESTRATOR_MCP_DATA"]

def _test_stub_single_role() -> str:
    engine = Orchestrator()
    started = engine.start_run(
        goal="Self-test orchestrator MCP framework",
        profile_name="daily-dev-stub",
        role="code_review",
        role_overrides={"code_review": {"model": "stub/stub-code-reviewer"}},
    )
    result = engine.dispatch_role(started["run_id"])
    if result.get("status") != "completed":
        raise AssertionError(f"stub review run not completed: {result.get('status')}")
    if result.get("role") != "code_review" or not result.get("handoff"):
        raise AssertionError("missing handoff for code_review")
    executions = result.get("executions") or []
    if executions and executions[0].get("provider") != "stub":
        raise AssertionError("role shorthand did not normalize to stub provider")
    return str(started["run_id"])


def _test_config_store_roundtrip() -> None:
    saved_deepseek = os.environ.pop("DEEPSEEK_API_KEY", None)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["ORCHESTRATOR_MCP_DATA"] = tmp
            from . import config_store

            config_store.clear_config_cache()
            config_store.update_provider_from_ui(
                "deepseek",
                api_key="sk-test-key-12345678",
                base_url="https://api.deepseek.com/v1",
                default_model="deepseek-chat",
            )
            if config_store.get_local_api_key("deepseek") != "sk-test-key-12345678":
                raise AssertionError("local api key not persisted")

            rows = config_store.list_providers_for_ui()
            deepseek = next(r for r in rows if r["provider"] == "deepseek")
            if not deepseek["configured"] or deepseek["source"] != "local":
                raise AssertionError("expected deepseek configured from local store")

            config_store.set_active_profile_name("daily-dev")
            config_store.save_role_overrides(
                "daily-dev-stub",
                {
                    "review": {"model": "stub/stub-general-reviewer"},
                    "ui_review": {"model": "stub/stub-ui-reviewer"},
                },
            )
            if config_store.get_active_profile_name() != "daily-dev":
                raise AssertionError("save_role_overrides must not change active_profile")
            if config_store.resolve_profile_name("") != "daily-dev":
                raise AssertionError("resolve_profile_name should use active_profile")
            if config_store.resolve_profile_name("daily-dev-stub") != "daily-dev-stub":
                raise AssertionError("resolve_profile_name should honor explicit profile")

            if config_store.model_valid_for_provider("zhipu", "gpt-4o-mini"):
                raise AssertionError("gpt-4o-mini should not be valid for zhipu")
            if not config_store.model_valid_for_provider("zhipu", "glm-5.2"):
                raise AssertionError("glm-5.2 should be valid for zhipu")
            if not config_store.model_valid_for_provider("moonshot", "kimi-k2.6"):
                raise AssertionError("kimi-k2.6 should be valid for moonshot")
            if config_store.resolve_model_for_provider("zhipu", "gpt-4o-mini") != "glm-4-flash":
                raise AssertionError("mismatched model should resolve to provider default")

            config_store.add_custom_model("deepseek", "deepseek-v4-pro")
            if "deepseek-v4-pro" not in config_store.get_custom_models("deepseek"):
                raise AssertionError("custom model not persisted")

            ui = config_store.get_profile_roles_for_ui("daily-dev-stub")
            ui_review = next(s for s in ui["roles"] if s["role"] == "ui_review")
            general_review = next(s for s in ui["roles"] if s["role"] == "general_review")
            if ui_review["provider"] != "stub" or ui_review["model"] != "stub-ui-reviewer":
                raise AssertionError("ui_review override not applied")
            if general_review["provider"] != "stub" or general_review["model"] != "stub-general-reviewer":
                raise AssertionError("role override not applied")

            providers_path = Path(tmp) / "providers.local.json"
            roles_path = Path(tmp) / "roles.local.json"
            if not providers_path.is_file() or not roles_path.is_file():
                raise AssertionError("local config files not written")

            from fastapi.testclient import TestClient
            from .webui.app import app

            client = TestClient(app)
            health = client.get("/api/health")
            if health.status_code != 200:
                raise AssertionError("webui health failed")
            api_providers = client.get("/api/providers")
            if api_providers.status_code != 200 or not api_providers.json().get("providers"):
                raise AssertionError("webui providers api failed")
            add_model = client.post(
                "/api/providers/zhipu/models",
                json={"model": "glm-5.2"},
            )
            if add_model.status_code != 200:
                raise AssertionError("add custom model api failed")

            del os.environ["ORCHESTRATOR_MCP_DATA"]
            config_store.clear_config_cache()
    finally:
        if saved_deepseek is not None:
            os.environ["DEEPSEEK_API_KEY"] = saved_deepseek


def _test_live_review_optional() -> None:
    if os.environ.get("ORCHESTRATOR_LIVE_TEST", "").strip().lower() not in ("1", "true", "yes"):
        return
    engine = Orchestrator()
    started = engine.start_run(goal="Review this smoke-test goal", profile_name="daily-dev", role="general_review")
    run_id = started["run_id"]
    result = engine.dispatch_role(run_id)
    if not result.get("ok"):
        raise AssertionError(result.get("error") or "general_review dispatch failed")
    handoff = result.get("handoff") or {}
    if handoff.get("schema") != "review.v1":
        raise AssertionError("live review handoff invalid")


def run_self_test() -> int:
    try:
        _test_json_extract()
        _test_provider_registry()
        _test_aliases()
        _test_workspace_context()
        run_id = _test_stub_single_role()
        _test_config_store_roundtrip()
        _test_live_review_optional()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    providers = list_provider_status()
    print(
        json.dumps(
            {
                "ok": True,
                "run_id": run_id,
                "providers": providers,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run_self_test())
