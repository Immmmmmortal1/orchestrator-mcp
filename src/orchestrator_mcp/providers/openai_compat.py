from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from ..profiles import Profile, StageConfig
from .base import ProviderResult
from ..credentials import api_key_for_provider, base_url_for_provider, normalize_provider
from .prompts import build_messages


def _extract_json(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("empty model response")
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fenced:
        parsed = json.loads(fenced.group(1))
        if isinstance(parsed, dict):
            return parsed
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        parsed = json.loads(raw[start : end + 1])
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("model response is not valid JSON object")


def chat_completions(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    timeout: int = 120,
) -> tuple[str, dict[str, int]]:
    url = f"{base_url.rstrip('/')}/chat/completions"
    body = {
        "model": model,
        "messages": messages,
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc

    content = payload["choices"][0]["message"]["content"]
    usage = payload.get("usage") or {}
    tokens = {
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
    }
    return str(content), tokens


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        default_model: str,
        env_base_url: str | None = None,
    ) -> None:
        self.name = name
        self.base_url = base_url
        self.default_model = default_model
        self.env_base_url = env_base_url

    def _resolve_base_url(self) -> str:
        return base_url_for_provider(
            self.name,
            env_var=self.env_base_url or "",
            default=self.base_url,
        )

    def run_stage(
        self,
        *,
        stage: str,
        goal: str,
        stage_config: StageConfig,
        inputs: dict[str, Any],
        profile: Profile,
    ) -> ProviderResult:
        _ = profile
        api_key = api_key_for_provider(self.name)
        if not api_key:
            raise RuntimeError(
                f"{self.name} API key not configured "
                f"(set env or add label in ~/Desktop/服务器.md)"
            )
        model = stage_config.model or self.default_model
        messages = build_messages(
            stage=stage,
            goal=goal,
            stage_config=stage_config,
            inputs=inputs,
        )
        raw_text, tokens = chat_completions(
            base_url=self._resolve_base_url(),
            api_key=api_key,
            model=model,
            messages=messages,
        )
        handoff = _extract_json(raw_text)
        return ProviderResult(
            handoff=handoff,
            prompt_tokens=tokens["prompt_tokens"],
            completion_tokens=tokens["completion_tokens"],
            estimated_cost_usd=0.0,
            raw_text=raw_text,
        )


def make_openai_compatible_providers() -> dict[str, OpenAICompatibleProvider]:
    from .responses_api import HybridOpenAIProvider, ResponsesAPIProvider

    return {
        "deepseek": OpenAICompatibleProvider(
            name="deepseek",
            base_url="https://api.deepseek.com/v1",
            default_model="deepseek-chat",
            env_base_url="DEEPSEEK_BASE_URL",
        ),
        "moonshot": OpenAICompatibleProvider(
            name="moonshot",
            base_url="https://api.moonshot.cn/v1",
            default_model="moonshot-v1-8k",
            env_base_url="MOONSHOT_BASE_URL",
        ),
        "zhipu": OpenAICompatibleProvider(
            name="zhipu",
            base_url="https://open.bigmodel.cn/api/paas/v4",
            default_model="glm-4-flash",
            env_base_url="ZHIPU_BASE_URL",
        ),
        "openai": HybridOpenAIProvider(
            name="openai",
            base_url="https://api.openai.com/v1",
            default_model="gpt-4o-mini",
            env_base_url="OPENAI_BASE_URL",
        ),
        "codex-lb": ResponsesAPIProvider(
            name="codex-lb",
            base_url="https://codex-lb.vvicat.dev/backend-api/codex",
            default_model="gpt-5.4",
            env_base_url="CODEX_LB_BASE_URL",
            default_reasoning_effort="medium",
        ),
    }
