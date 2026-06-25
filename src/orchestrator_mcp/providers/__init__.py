from __future__ import annotations

from .base import LLMProvider, ProviderResult, StubProvider
from ..credentials import list_provider_status, normalize_provider, provider_configured
from .openai_compat import make_openai_compatible_providers

PROVIDERS: dict[str, LLMProvider] = {"stub": StubProvider()}
PROVIDERS.update(make_openai_compatible_providers())

# Aliases: glm -> zhipu, gpt -> openai
PROVIDERS["glm"] = PROVIDERS["zhipu"]
PROVIDERS["gpt"] = PROVIDERS["openai"]
PROVIDERS["codex"] = PROVIDERS["codex-lb"]


def get_provider(name: str) -> LLMProvider:
    key = normalize_provider(name)
    provider = PROVIDERS.get(key)
    if provider is None:
        registered = sorted({k for k in PROVIDERS if k not in ("glm", "gpt")})
        raise KeyError(f"unknown provider {name!r}; registered: {', '.join(registered)}")
    return provider


__all__ = [
    "LLMProvider",
    "ProviderResult",
    "StubProvider",
    "PROVIDERS",
    "get_provider",
    "list_provider_status",
    "normalize_provider",
    "provider_configured",
]
