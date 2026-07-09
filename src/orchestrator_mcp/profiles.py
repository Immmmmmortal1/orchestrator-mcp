from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .credentials import normalize_provider
from .config import profiles_dir
from .config_store import get_active_profile_name, get_stage_overrides
from .labels import profile_label_zh


STAGE_ORDER = ("ui_review", "code_review", "general_review")
STAGE_ALIASES = {
    "review": "general_review",
    "ui": "ui_review",
    "code": "code_review",
    "general": "general_review",
    "other": "general_review",
    "other_review": "general_review",
}


def normalize_stage(name: str | None) -> str:
    key = (name or "").strip().lower().replace("-", "_")
    return STAGE_ALIASES.get(key, key)


@dataclass
class StageConfig:
    provider: str
    model: str
    output_schema: str
    skills: list[str] = field(default_factory=list)


@dataclass
class Profile:
    name: str
    description: str
    stages: dict[str, StageConfig]
    max_review_rounds: int = 2
    skip_review: bool = False

    def stage(self, name: str) -> StageConfig:
        name = normalize_stage(name)
        if name not in self.stages:
            raise KeyError(f"unknown stage {name!r} in profile {self.name!r}")
        return self.stages[name]


def load_profile(name: str) -> Profile:
    path = profiles_dir() / f"{name}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"profile not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    stages_raw: dict[str, Any] = raw.get("stages") or {}
    stages: dict[str, StageConfig] = {}
    for stage_name, cfg in stages_raw.items():
        if not isinstance(cfg, dict):
            raise ValueError(f"invalid stage config for {stage_name}")
        stage_key = normalize_stage(str(stage_name))
        stages[stage_key] = StageConfig(
            provider=normalize_provider(str(cfg.get("provider", "stub"))),
            model=str(cfg.get("model", "stub")),
            output_schema=str(cfg.get("output_schema", "")),
            skills=list(cfg.get("skills") or []),
        )
    fallback_stage = stages.get("general_review") or next(iter(stages.values()), None)
    if fallback_stage:
        for stage_name in STAGE_ORDER:
            stages.setdefault(
                stage_name,
                StageConfig(
                    provider=fallback_stage.provider,
                    model=fallback_stage.model,
                    output_schema=fallback_stage.output_schema,
                    skills=list(fallback_stage.skills),
                ),
            )
    routing = raw.get("routing") or {}
    profile = Profile(
        name=str(raw.get("name") or name),
        description=str(raw.get("description") or ""),
        stages=stages,
        max_review_rounds=int(routing.get("max_review_rounds", 2)),
        skip_review=bool(routing.get("skip_review", False)),
    )
    overrides = get_stage_overrides(profile.name)
    if overrides:
        merged = dict(profile.stages)
        for stage_name, ov in overrides.items():
            if stage_name not in merged:
                continue
            base = merged[stage_name]
            merged[stage_name] = StageConfig(
                provider=normalize_provider(ov.get("provider") or base.provider),
                model=str(ov.get("model") or base.model),
                output_schema=base.output_schema,
                skills=list(base.skills),
            )
        profile.stages = merged
    return profile


def list_profiles(*, active_name: str | None = None) -> list[dict[str, str | bool]]:
    root = profiles_dir()
    if not root.is_dir():
        return []
    active = (active_name or get_active_profile_name()).strip() or "daily-dev"
    out: list[dict[str, str | bool]] = []
    for path in sorted(root.glob("*.yaml")):
        try:
            profile = load_profile(path.stem)
            labels = profile_label_zh(profile.name, profile.description)
            out.append(
                {
                    "name": profile.name,
                    "label_zh": labels["label_zh"],
                    "description": profile.description,
                    "description_zh": labels["description_zh"],
                    "is_active": profile.name == active,
                }
            )
        except Exception:
            out.append(
                {
                    "name": path.stem,
                    "label_zh": path.stem,
                    "description": "(load error)",
                    "description_zh": "配置加载失败",
                    "is_active": path.stem == active,
                }
            )
    out.sort(key=lambda item: (0 if item.get("is_active") else 1, str(item.get("name"))))
    return out
