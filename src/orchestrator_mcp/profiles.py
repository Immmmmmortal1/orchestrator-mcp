from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .credentials import normalize_provider
from .config import profiles_dir
from .config_store import get_active_profile_name, get_role_overrides
from .labels import profile_label_zh


REVIEW_ROLES = ("ui_review", "code_review", "general_review")
REVIEW_ROLE_IDS = frozenset(REVIEW_ROLES)
ROLE_ALIASES = {
    "review": "general_review",
    "ui": "ui_review",
    "code": "code_review",
    "general": "general_review",
    "other": "general_review",
    "other_review": "general_review",
}


def normalize_role(name: str | None) -> str:
    key = (name or "").strip().lower().replace("-", "_")
    return ROLE_ALIASES.get(key, key)


@dataclass
class RoleConfig:
    provider: str
    model: str
    output_schema: str
    skills: list[str] = field(default_factory=list)


@dataclass
class Profile:
    name: str
    description: str
    roles: dict[str, RoleConfig]
    max_review_rounds: int = 2
    skip_review: bool = False

    def role(self, name: str) -> RoleConfig:
        name = normalize_role(name)
        if name not in self.roles:
            raise KeyError(f"unknown role {name!r} in profile {self.name!r}")
        return self.roles[name]


def load_profile(name: str) -> Profile:
    path = profiles_dir() / f"{name}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"profile not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    roles_raw: dict[str, Any] = raw.get("roles") or {}
    roles: dict[str, RoleConfig] = {}
    for role_name, cfg in roles_raw.items():
        if not isinstance(cfg, dict):
            raise ValueError(f"invalid role config for {role_name}")
        role_key = normalize_role(str(role_name))
        roles[role_key] = RoleConfig(
            provider=normalize_provider(str(cfg.get("provider", "stub"))),
            model=str(cfg.get("model", "stub")),
            output_schema=str(cfg.get("output_schema", "")),
            skills=list(cfg.get("skills") or []),
        )
    fallback_role = roles.get("general_review") or next(iter(roles.values()), None)
    if fallback_role:
        for role_name in REVIEW_ROLES:
            roles.setdefault(
                role_name,
                RoleConfig(
                    provider=fallback_role.provider,
                    model=fallback_role.model,
                    output_schema=fallback_role.output_schema,
                    skills=list(fallback_role.skills),
                ),
            )
    routing = raw.get("routing") or {}
    profile = Profile(
        name=str(raw.get("name") or name),
        description=str(raw.get("description") or ""),
        roles=roles,
        max_review_rounds=int(routing.get("max_review_rounds", 2)),
        skip_review=bool(routing.get("skip_review", False)),
    )
    overrides = get_role_overrides(profile.name)
    if overrides:
        merged = dict(profile.roles)
        for role_name, ov in overrides.items():
            if role_name not in merged:
                continue
            base = merged[role_name]
            merged[role_name] = RoleConfig(
                provider=normalize_provider(ov.get("provider") or base.provider),
                model=str(ov.get("model") or base.model),
                output_schema=base.output_schema,
                skills=list(base.skills),
            )
        profile.roles = merged
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
