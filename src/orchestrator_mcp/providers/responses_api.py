from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from ..profiles import Profile, StageConfig
from .base import ProviderResult
from .openai_compat import OpenAICompatibleProvider, _extract_json, chat_completions
from .prompts import build_messages
from ..config_store import get_local_reasoning_effort, get_local_wire_api
from ..credentials import api_key_for_provider, base_url_for_provider


def _responses_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/responses"):
        return base
    return f"{base}/responses"


def _parse_sse_text(raw: bytes) -> tuple[str, dict[str, int]]:
    """Parse Codex/OpenAI Responses SSE stream into final text + token usage."""
    buf = raw.decode("utf-8", errors="replace")
    deltas: list[str] = []
    done_text = ""
    usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0}

    while "\n\n" in buf:
        block, buf = buf.split("\n\n", 1)
        data_line = ""
        for line in block.splitlines():
            if line.startswith("data:"):
                data_line = line[5:].strip()
        if not data_line or data_line == "[DONE]":
            continue
        try:
            event = json.loads(data_line)
        except json.JSONDecodeError:
            continue

        typ = str(event.get("type") or "")
        if typ == "response.output_text.delta":
            delta = event.get("delta")
            if isinstance(delta, str) and delta:
                deltas.append(delta)
        elif typ == "response.output_text.done":
            text = event.get("text")
            if isinstance(text, str):
                done_text = text
        elif typ in ("response.completed", "response.done"):
            resp = event.get("response") if isinstance(event.get("response"), dict) else event
            u = resp.get("usage") if isinstance(resp, dict) else {}
            if isinstance(u, dict):
                usage["prompt_tokens"] = int(u.get("input_tokens") or u.get("prompt_tokens") or 0)
                usage["completion_tokens"] = int(u.get("output_tokens") or u.get("completion_tokens") or 0)
        elif typ == "response.failed":
            resp = event.get("response") if isinstance(event.get("response"), dict) else {}
            err = resp.get("error") if isinstance(resp, dict) else event.get("error")
            if isinstance(err, dict):
                raise RuntimeError(err.get("message") or "responses API failed")
            raise RuntimeError("responses API failed")

    text = done_text or "".join(deltas)
    if not text.strip():
        raise ValueError("empty responses API output")
    return text, usage


def responses_create(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    reasoning_effort: str | None = None,
    json_mode: bool = True,
    timeout: int = 120,
) -> tuple[str, dict[str, int]]:
    """Call OpenAI/Codex Responses API (SSE) and return assistant text."""
    system_parts: list[str] = []
    user_parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = str(msg.get("content") or "")
        if role == "system":
            system_parts.append(content)
        else:
            user_parts.append(content)

    body: dict[str, Any] = {
        "model": model,
        "input": "\n\n".join(user_parts).strip() or (user_parts[-1] if user_parts else ""),
        "max_output_tokens": 4096,
    }
    if system_parts:
        body["instructions"] = "\n\n".join(system_parts)
    if reasoning_effort:
        body["reasoning"] = {"effort": reasoning_effort}
    if json_mode:
        body["text"] = {"format": {"type": "json_object"}}

    url = _responses_url(base_url)
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc

    return _parse_sse_text(raw)


class ResponsesAPIProvider(OpenAICompatibleProvider):
    """Codex / OpenAI Responses wire (`wire_api = responses`)."""

    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        default_model: str,
        env_base_url: str | None = None,
        default_reasoning_effort: str = "medium",
    ) -> None:
        super().__init__(
            name=name,
            base_url=base_url,
            default_model=default_model,
            env_base_url=env_base_url,
        )
        self.default_reasoning_effort = default_reasoning_effort

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
            raise RuntimeError(f"{self.name} API key not configured")

        model = stage_config.model or self.default_model
        effort = get_local_reasoning_effort(self.name) or self.default_reasoning_effort
        messages = build_messages(
            stage=stage,
            goal=goal,
            stage_config=stage_config,
            inputs=inputs,
        )
        raw_text, tokens = responses_create(
            base_url=self._resolve_base_url(),
            api_key=api_key,
            model=model,
            messages=messages,
            reasoning_effort=effort or None,
            json_mode=True,
        )
        handoff = _extract_json(raw_text)
        return ProviderResult(
            handoff=handoff,
            prompt_tokens=tokens["prompt_tokens"],
            completion_tokens=tokens["completion_tokens"],
            estimated_cost_usd=0.0,
            raw_text=raw_text,
        )


class HybridOpenAIProvider(OpenAICompatibleProvider):
    """Pick chat/completions or responses based on WebUI `wire_api` setting."""

    def run_stage(
        self,
        *,
        stage: str,
        goal: str,
        stage_config: StageConfig,
        inputs: dict[str, Any],
        profile: Profile,
    ) -> ProviderResult:
        wire = get_local_wire_api(self.name)
        if wire == "responses":
            delegate = ResponsesAPIProvider(
                name=self.name,
                base_url=self.base_url,
                default_model=self.default_model,
                env_base_url=self.env_base_url,
            )
            return delegate.run_stage(
                stage=stage,
                goal=goal,
                stage_config=stage_config,
                inputs=inputs,
                profile=profile,
            )
        return super().run_stage(
            stage=stage,
            goal=goal,
            stage_config=stage_config,
            inputs=inputs,
            profile=profile,
        )


def ping_responses_provider(
    *,
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
    reasoning_effort: str | None = None,
    timeout: int = 60,
) -> tuple[str, dict[str, int]]:
    messages = [{"role": "user", "content": "Reply with one word: ok"}]
    return responses_create(
        base_url=base_url,
        api_key=api_key,
        model=model,
        messages=messages,
        reasoning_effort=reasoning_effort,
        json_mode=False,
        timeout=timeout,
    )


def ping_chat_provider(
    *,
    base_url: str,
    api_key: str,
    model: str,
    timeout: int = 60,
) -> tuple[str, dict[str, int]]:
    text, tokens = chat_completions(
        base_url=base_url,
        api_key=api_key,
        model=model,
        messages=[{"role": "user", "content": "Reply with one word: ok"}],
        timeout=timeout,
    )
    return text, tokens
