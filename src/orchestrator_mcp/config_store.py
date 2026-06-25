from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import data_dir
from .labels import profile_label_zh, provider_label_zh, schema_label_zh, source_label_zh, stage_label_zh

PROVIDER_IDS = ("deepseek", "moonshot", "zhipu", "openai", "codex-lb")
STAGE_IDS = ("plan", "code", "review", "deliver")

_DEFAULT_PROVIDER_META: dict[str, dict[str, str]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-v4-flash",
        "env_var": "DEEPSEEK_API_KEY",
    },
    "moonshot": {
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-8k",
        "env_var": "MOONSHOT_API_KEY",
    },
    "zhipu": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4-flash",
        "env_var": "ZHIPU_API_KEY",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "env_var": "OPENAI_API_KEY",
        "wire_api": "chat",
    },
    "codex-lb": {
        "base_url": "https://codex-lb.vvicat.dev/backend-api/codex",
        "default_model": "gpt-5.4",
        "env_var": "CODEX_LB_API_KEY",
        "wire_api": "responses",
        "default_reasoning_effort": "medium",
    },
}

# Curated model IDs for WebUI dropdowns (not live-fetched from vendor APIs).
# Official docs (2026-06): IDs are mostly lowercase + hyphens; paste exact API model string.
_MODEL_SUGGESTIONS: dict[str, list[str]] = {
    "deepseek": [
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        "deepseek-chat",
        "deepseek-reasoner",
    ],
    "moonshot": [
        "kimi-k2.6",
        "kimi-k2.5",
        "kimi-k2.7-code",
        "moonshot-v1-8k",
        "moonshot-v1-32k",
        "moonshot-v1-128k",
    ],
    "zhipu": [
        "glm-5.2",
        "glm-5.1",
        "glm-5",
        "glm-5-turbo",
        "glm-4.7",
        "glm-4.7-flash",
        "glm-4-flash",
        "glm-4-plus",
        "glm-4-air",
    ],
    "openai": ["gpt-4o-mini", "gpt-4o", "gpt-5", "gpt-5.4", "o3-mini", "o4-mini"],
    "codex-lb": ["gpt-5.4", "gpt-5", "gpt-4o"],
    "stub": ["stub", "stub-planner", "stub-coder", "stub-reviewer", "stub-deliver"],
}

_MODEL_PREFIXES: dict[str, str] = {
    "deepseek": "deepseek",
    "moonshot": "moonshot",
    "zhipu": "glm",
    "openai": "gpt",
    "codex-lb": "gpt",
    "stub": "stub",
}

# Extra accepted prefixes per provider (e.g. Kimi K2 series on Moonshot API).
_MODEL_EXTRA_PREFIXES: dict[str, tuple[str, ...]] = {
    "moonshot": ("kimi-",),
}

MODEL_NAMING_GUIDE: dict[str, dict[str, str]] = {
    "deepseek": {
        "pattern": "deepseek-*（全小写、连字符）",
        "examples": "deepseek-v4-flash, deepseek-v4-pro",
        "note": "deepseek-chat / deepseek-reasoner 为旧别名，2026-07-24 后退役；thinking 用 extra_body，不是 model 名",
    },
    "moonshot": {
        "pattern": "kimi-* 或 moonshot-v1-*（全小写）",
        "examples": "kimi-k2.6, kimi-k2.5, moonshot-v1-8k",
        "note": "国内 endpoint 常用 api.moonshot.cn；国际为 api.moonshot.ai",
    },
    "zhipu": {
        "pattern": "glm-*（全小写；直连 open.bigmodel.cn 用 glm-5.2 而非 ZHIPU/GLM-5.2）",
        "examples": "glm-5.2, glm-5.1, glm-4-flash",
        "note": "百炼/DashScope 前缀 ZHIPU/ 仅阿里云路由，本编排直连智谱 API",
    },
    "openai": {
        "pattern": "gpt-* 或 o*（全小写）",
        "examples": "gpt-4o-mini, gpt-5.4, o3-mini",
        "note": "Codex 中转见 codex-lb provider",
    },
    "codex-lb": {
        "pattern": "gpt-*（与 OpenAI 命名一致）",
        "examples": "gpt-5.4, gpt-5",
        "note": "走 Responses API，非 Chat Completions",
    },
}


def normalize_model_id(model: str) -> str:
    return (model or "").strip()


def _model_id_format_ok(model: str) -> bool:
    text = normalize_model_id(model)
    if not text or len(text) > 128:
        return False
    return all(ch.isalnum() or ch in "-_./" for ch in text)


def get_custom_models(provider: str) -> list[str]:
    entry = load_providers_local().get(provider) or {}
    if not isinstance(entry, dict):
        return []
    raw = entry.get("custom_models")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = normalize_model_id(str(item))
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _model_matches_provider_prefix(provider: str, model: str) -> bool:
    pid = provider
    text = normalize_model_id(model)
    prefix = _MODEL_PREFIXES.get(pid)
    if prefix and text.startswith(prefix):
        return True
    for extra in _MODEL_EXTRA_PREFIXES.get(pid, ()):
        if text.startswith(extra):
            return True
    if pid == "openai" and text.startswith("o"):
        return True
    return False


def provider_model_meta(provider: str) -> dict[str, Any]:
    from .credentials import normalize_provider

    pid = normalize_provider(provider)
    if pid == "stub":
        return {
            "default_model": "stub",
            "model_suggestions": list(_MODEL_SUGGESTIONS["stub"]),
            "custom_models": [],
        }
    local_default = get_local_default_model(pid)
    meta = _DEFAULT_PROVIDER_META.get(pid, {})
    default = local_default or str(meta.get("default_model") or "")
    suggestions = list(_MODEL_SUGGESTIONS.get(pid, []))
    custom = get_custom_models(pid)
    for item in custom:
        if item not in suggestions:
            suggestions.append(item)
    if default and default not in suggestions:
        suggestions.insert(0, default)
    guide = MODEL_NAMING_GUIDE.get(pid, {})
    return {
        "default_model": default,
        "model_suggestions": suggestions,
        "custom_models": custom,
        "naming_pattern": guide.get("pattern", ""),
        "naming_examples": guide.get("examples", ""),
        "naming_note": guide.get("note", ""),
    }


def model_valid_for_provider(provider: str, model: str) -> bool:
    from .credentials import normalize_provider

    pid = normalize_provider(provider)
    text = normalize_model_id(model)
    if not text:
        return False
    meta = provider_model_meta(pid)
    if text == meta["default_model"]:
        return True
    if text in meta["model_suggestions"]:
        return True
    if text in get_custom_models(pid):
        return True
    return _model_matches_provider_prefix(pid, text)


def add_custom_model(provider: str, model: str) -> dict[str, Any]:
    from .credentials import api_key_for_provider, api_key_source, normalize_provider

    pid = normalize_provider(provider)
    if pid not in PROVIDER_IDS:
        raise ValueError(f"unknown provider: {provider}")
    text = normalize_model_id(model)
    if not text:
        raise ValueError("model id required")
    if not _model_id_format_ok(text):
        raise ValueError("model id contains invalid characters (use letters, digits, - _ . /)")
    if not model_valid_for_provider(pid, text) and not _model_matches_provider_prefix(pid, text):
        guide = MODEL_NAMING_GUIDE.get(pid, {})
        hint = guide.get("pattern") or "provider-specific prefix"
        raise ValueError(f"model id does not match {pid} naming ({hint})")

    all_providers = load_providers_local()
    entry = dict(all_providers.get(pid) or {})
    custom = get_custom_models(pid)
    if text not in custom:
        custom.append(text)
    entry["custom_models"] = custom
    all_providers[pid] = entry
    save_providers_local(all_providers)

    key = api_key_for_provider(pid)
    view = provider_public_view(
        pid,
        source=api_key_source(pid),
        configured=bool(key),
        api_key=key,
    )
    view["added_model"] = text
    return view


def resolve_model_for_provider(provider: str, model: str) -> str:
    text = (model or "").strip()
    if model_valid_for_provider(provider, text):
        return text
    return str(provider_model_meta(provider).get("default_model") or text)


def provider_models_for_ui() -> dict[str, dict[str, Any]]:
    from .credentials import normalize_provider

    out: dict[str, dict[str, Any]] = {}
    for pid in (*PROVIDER_IDS, "stub"):
        out[normalize_provider(pid)] = provider_model_meta(pid)
    return out


def _providers_path() -> Path:
    return data_dir() / "providers.local.json"


def _stages_path() -> Path:
    return data_dir() / "stages.local.json"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _mask_secret(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if len(text) <= 8:
        return "*" * len(text)
    return f"{text[:4]}…{text[-4:]}"


def clear_config_cache() -> None:
    """Call after writes so credentials pick up new values."""
    from . import credentials

    credentials.clear_credential_cache()


def load_providers_local() -> dict[str, Any]:
    raw = _read_json(_providers_path())
    return raw.get("providers") if isinstance(raw.get("providers"), dict) else {}


def save_providers_local(providers: dict[str, Any]) -> None:
    _write_json(_providers_path(), {"version": 1, "providers": providers})
    clear_config_cache()


def get_local_provider_entry(provider: str) -> dict[str, str]:
    entry = load_providers_local().get(provider) or {}
    if not isinstance(entry, dict):
        return {}
    return {
        "api_key": str(entry.get("api_key") or "").strip(),
        "base_url": str(entry.get("base_url") or "").strip(),
        "default_model": str(entry.get("default_model") or "").strip(),
        "wire_api": str(entry.get("wire_api") or "").strip(),
        "reasoning_effort": str(entry.get("reasoning_effort") or "").strip(),
    }


def get_local_api_key(provider: str) -> str:
    return get_local_provider_entry(provider).get("api_key", "")


def get_local_base_url(provider: str) -> str:
    return get_local_provider_entry(provider).get("base_url", "")


def get_local_default_model(provider: str) -> str:
    return get_local_provider_entry(provider).get("default_model", "")


def get_local_wire_api(provider: str) -> str:
    local = get_local_provider_entry(provider).get("wire_api", "")
    if local in ("chat", "responses"):
        return local
    default = _DEFAULT_PROVIDER_META.get(provider, {}).get("wire_api", "chat")
    return str(default or "chat")


def get_local_reasoning_effort(provider: str) -> str:
    local = get_local_provider_entry(provider).get("reasoning_effort", "")
    if local in ("low", "medium", "high"):
        return local
    default = _DEFAULT_PROVIDER_META.get(provider, {}).get("default_reasoning_effort", "")
    return str(default or "")


def provider_public_view(provider: str, *, source: str, configured: bool, api_key: str) -> dict[str, Any]:
    meta = _DEFAULT_PROVIDER_META[provider]
    local = get_local_provider_entry(provider)
    base_url = local.get("base_url") or meta["base_url"]
    default_model = local.get("default_model") or meta["default_model"]
    wire_api = get_local_wire_api(provider)
    reasoning_effort = get_local_reasoning_effort(provider)
    labels = provider_label_zh(provider)
    return {
        "provider": provider,
        "aliases": {"zhipu": ["glm"], "openai": ["gpt"], "codex-lb": ["codex"]}.get(provider, []),
        "label_zh": labels["label_zh"],
        "vendor_zh": labels["vendor_zh"],
        "description_zh": labels["description_zh"],
        "configured": configured,
        "source": source,
        "source_label_zh": source_label_zh(source),
        "env_var": meta["env_var"],
        "base_url": base_url,
        "default_model": default_model,
        "wire_api": wire_api,
        "wire_api_label_zh": "Responses API（Codex 中转）" if wire_api == "responses" else "Chat Completions",
        "reasoning_effort": reasoning_effort,
        "api_key_hint": _mask_secret(api_key) if configured else "",
        "model_suggestions": provider_model_meta(provider)["model_suggestions"],
        "custom_models": get_custom_models(provider),
        "naming_pattern": MODEL_NAMING_GUIDE.get(provider, {}).get("pattern", ""),
        "naming_examples": MODEL_NAMING_GUIDE.get(provider, {}).get("examples", ""),
        "naming_note": MODEL_NAMING_GUIDE.get(provider, {}).get("note", ""),
    }


def list_providers_for_ui() -> list[dict[str, Any]]:
    from .credentials import api_key_for_provider, api_key_source

    rows: list[dict[str, Any]] = []
    for provider in PROVIDER_IDS:
        key = api_key_for_provider(provider)
        rows.append(
            provider_public_view(
                provider,
                source=api_key_source(provider),
                configured=bool(key),
                api_key=key,
            )
        )
    return rows


def update_provider_from_ui(
    provider: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    default_model: str | None = None,
    wire_api: str | None = None,
    reasoning_effort: str | None = None,
    clear_api_key: bool = False,
) -> dict[str, Any]:
    if provider not in PROVIDER_IDS:
        raise ValueError(f"unknown provider: {provider}")

    all_providers = load_providers_local()
    entry = dict(all_providers.get(provider) or {})
    if not isinstance(entry, dict):
        entry = {}

    if clear_api_key:
        entry.pop("api_key", None)
    elif api_key is not None and api_key.strip():
        entry["api_key"] = api_key.strip()

    if base_url is not None:
        entry["base_url"] = base_url.strip()
    if default_model is not None:
        entry["default_model"] = default_model.strip()
    if wire_api is not None:
        value = wire_api.strip().lower()
        if value and value not in ("chat", "responses"):
            raise ValueError("wire_api must be chat or responses")
        if value:
            entry["wire_api"] = value
    if reasoning_effort is not None:
        value = reasoning_effort.strip().lower()
        if value and value not in ("", "low", "medium", "high"):
            raise ValueError("reasoning_effort must be low, medium, or high")
        if value:
            entry["reasoning_effort"] = value
        else:
            entry.pop("reasoning_effort", None)

    all_providers[provider] = entry
    save_providers_local(all_providers)

    from .credentials import api_key_for_provider, api_key_source

    key = api_key_for_provider(provider)
    return provider_public_view(
        provider,
        source=api_key_source(provider),
        configured=bool(key),
        api_key=key,
    )


def load_stages_local() -> dict[str, Any]:
    raw = _read_json(_stages_path())
    profiles = raw.get("profiles")
    return profiles if isinstance(profiles, dict) else {}


def get_active_profile_name() -> str:
    raw = _read_json(_stages_path())
    name = str(raw.get("active_profile") or "daily-dev").strip()
    return name or "daily-dev"


def resolve_profile_name(name: str | None = None) -> str:
    """MCP / CLI default: explicit profile name, else WebUI active_profile."""
    cleaned = (name or "").strip()
    if cleaned:
        return cleaned
    return get_active_profile_name()


def set_active_profile_name(name: str) -> None:
    raw = _read_json(_stages_path())
    raw["version"] = 1
    raw["active_profile"] = name.strip()
    if "profiles" not in raw or not isinstance(raw.get("profiles"), dict):
        raw["profiles"] = load_stages_local()
    _write_json(_stages_path(), raw)


def get_stage_overrides(profile_name: str) -> dict[str, dict[str, str]]:
    profiles = load_stages_local()
    raw = profiles.get(profile_name) or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for stage in STAGE_IDS:
        cfg = raw.get(stage)
        if isinstance(cfg, dict):
            out[stage] = {
                k: str(v)
                for k, v in cfg.items()
                if k in ("provider", "model") and str(v).strip()
            }
    return out


def save_stage_overrides(profile_name: str, stages: dict[str, dict[str, str]]) -> None:
    raw = _read_json(_stages_path())
    raw["version"] = 1
    profiles = raw.get("profiles")
    if not isinstance(profiles, dict):
        profiles = {}
    cleaned: dict[str, dict[str, str]] = {}
    for stage in STAGE_IDS:
        cfg = stages.get(stage) or {}
        if not isinstance(cfg, dict):
            continue
        item: dict[str, str] = {}
        if cfg.get("provider"):
            item["provider"] = str(cfg["provider"]).strip()
        if cfg.get("model"):
            item["model"] = str(cfg["model"]).strip()
        if item.get("provider") and item.get("model"):
            item["model"] = resolve_model_for_provider(item["provider"], item["model"])
        if item:
            cleaned[stage] = item
    profiles[profile_name] = cleaned
    raw["profiles"] = profiles
    _write_json(_stages_path(), raw)
    clear_config_cache()


def get_profile_stages_for_ui(profile_name: str) -> dict[str, Any]:
    from .profiles import STAGE_ORDER, load_profile

    profile = load_profile(profile_name)
    overrides = get_stage_overrides(profile_name)
    stages: list[dict[str, Any]] = []
    for stage in STAGE_ORDER:
        base = profile.stages[stage]
        ov = overrides.get(stage) or {}
        provider = ov.get("provider") or base.provider
        model = ov.get("model") or base.model
        model_mismatch = bool(model) and not model_valid_for_provider(provider, model)
        suggested_model = resolve_model_for_provider(provider, model)
        stage_labels = stage_label_zh(stage)
        prov_labels = provider_label_zh(provider)
        stages.append(
            {
                "stage": stage,
                "label_zh": stage_labels["label_zh"],
                "description_zh": stage_labels["description_zh"],
                "provider": provider,
                "provider_label_zh": prov_labels["label_zh"],
                "model": model,
                "suggested_model": suggested_model,
                "model_mismatch": model_mismatch,
                "output_schema": base.output_schema,
                "schema_label_zh": schema_label_zh(base.output_schema),
                "skills": base.skills,
                "overridden": bool(ov),
            }
        )

    def _provider_option(pid: str) -> dict[str, object]:
        labels = provider_label_zh(pid)
        aliases: list[str] = []
        if pid == "zhipu":
            aliases = ["glm"]
        elif pid == "openai":
            aliases = ["gpt"]
        elif pid == "codex-lb":
            aliases = ["codex"]
        return {
            "id": pid,
            "aliases": aliases,
            "label_zh": labels["label_zh"],
            "vendor_zh": labels["vendor_zh"],
        }

    profile_labels = profile_label_zh(profile_name, profile.description)
    return {
        "profile": profile_name,
        "label_zh": profile_labels["label_zh"],
        "description": profile.description,
        "description_zh": profile_labels["description_zh"],
        "active_profile": get_active_profile_name(),
        "stages": stages,
        "provider_options": [_provider_option(p) for p in PROVIDER_IDS]
        + [_provider_option("stub")],
        "provider_models": provider_models_for_ui(),
        "model_list_source": "curated",
        "model_list_source_zh": "仓库内置常见 model ID + Provider 自定义模型 + default_model；不实时拉厂商 API",
        "model_naming_guide": MODEL_NAMING_GUIDE,
    }
