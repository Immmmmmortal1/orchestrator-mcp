from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

from .config_store import get_local_api_key, get_local_base_url

_SERVER_MD = Path.home() / "Desktop" / "服务器.md"

_PROVIDER_ENV: dict[str, tuple[str, ...]] = {
    "deepseek": ("DEEPSEEK_API_KEY", "deepseekApiKey", "deepseek_api_key"),
    "moonshot": ("MOONSHOT_API_KEY", "moonshotApiKey", "moonshot_api_key", "kimiApiKey"),
    "zhipu": ("ZHIPU_API_KEY", "zhipuApiKey", "glmApiKey", "GLM_API_KEY"),
    "openai": ("OPENAI_API_KEY", "openaiApiKey", "openai_api_key", "gptApiKey"),
    "codex-lb": ("CODEX_LB_API_KEY", "codexLbApiKey", "codex_lb_api_key"),
}

_PROVIDER_ALIASES: dict[str, str] = {
    "glm": "zhipu",
    "gpt": "openai",
    "codex": "codex-lb",
}


def normalize_provider(name: str) -> str:
    key = (name or "").strip().lower()
    return _PROVIDER_ALIASES.get(key, key)


def clear_credential_cache() -> None:
    _server_md_text.cache_clear()


@lru_cache(maxsize=1)
def _server_md_text() -> str:
    if not _SERVER_MD.is_file():
        return ""
    try:
        return _SERVER_MD.read_text(encoding="utf-8")
    except OSError:
        return ""


def _lookup_in_server_md(label: str) -> str:
    text = _server_md_text()
    if not text:
        return ""
    pattern = re.compile(
        rf"(?im)^\s*{re.escape(label)}\s*[:：]?\s*\n\s*(\S+)",
    )
    match = pattern.search(text)
    if match:
        return match.group(1).strip()
    inline = re.compile(rf"(?im)^\s*{re.escape(label)}\s*[:：]\s*(\S+)\s*$")
    match = inline.search(text)
    return match.group(1).strip() if match else ""


def api_key_source(provider: str) -> str:
    canonical = normalize_provider(provider)
    spec = _PROVIDER_ENV.get(canonical)
    if not spec:
        return "none"
    env_name, *labels = spec
    if os.environ.get(env_name, "").strip():
        return "env"
    if get_local_api_key(canonical):
        return "local"
    for label in labels:
        if _lookup_in_server_md(label):
            return "server_md"
    return "none"


def api_key_for_provider(provider: str) -> str:
    """Resolve API key: env → local webui config → ~/Desktop/服务器.md."""
    canonical = normalize_provider(provider)
    spec = _PROVIDER_ENV.get(canonical)
    if not spec:
        return ""
    env_name, *labels = spec
    value = os.environ.get(env_name, "").strip()
    if value:
        return value
    value = get_local_api_key(canonical)
    if value:
        return value
    for label in labels:
        value = _lookup_in_server_md(label)
        if value:
            return value
    return ""


def base_url_for_provider(provider: str, *, env_var: str, default: str) -> str:
    canonical = normalize_provider(provider)
    override = os.environ.get(env_var, "").strip()
    if override:
        return override.rstrip("/")
    local = get_local_base_url(canonical)
    if local:
        return local.rstrip("/")
    return default.rstrip("/")


def provider_configured(provider: str) -> bool:
    return bool(api_key_for_provider(provider))


def list_provider_status() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for name in ("deepseek", "moonshot", "zhipu", "openai", "codex-lb"):
        env_name = _PROVIDER_ENV[name][0]
        rows.append(
            {
                "provider": name,
                "aliases": [k for k, v in _PROVIDER_ALIASES.items() if v == name],
                "configured": provider_configured(name),
                "source": api_key_source(name),
                "env_var": env_name,
            }
        )
    return rows
