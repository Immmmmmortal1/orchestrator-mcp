from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

AGENT_DOC_NAMES = ("AGENTS.md", "CLAUDE.md", "agent.md", "Agent.md")
LEARNING_REL_PATHS = (
    ".learnings/LEARNINGS.md",
    ".learnings/ERRORS.md",
    ".learnings/FEATURE_REQUESTS.md",
)
SKIP_NAME_PARTS = (
    ".env",
    "credentials",
    "secret",
    "private_key",
    "id_rsa",
)


def resolve_workspace(workspace: str | None = None) -> Path | None:
    raw = (workspace or "").strip() or os.environ.get("ORCHESTRATOR_WORKSPACE", "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"workspace is not a directory: {path}")
    return path


def _should_skip(path: Path) -> bool:
    lowered = path.name.lower()
    return any(part in lowered for part in SKIP_NAME_PARTS)


def _read_text_file(path: Path) -> str | None:
    if not path.is_file() or _should_skip(path):
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _collect_agent_docs(root: Path) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    for name in AGENT_DOC_NAMES:
        content = _read_text_file(root / name)
        if content:
            sections.append({"path": name, "content": content})
    return sections


def _collect_rules(root: Path) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    rules_dir = root / ".cursor" / "rules"
    if not rules_dir.is_dir():
        return sections
    for path in sorted(rules_dir.glob("*")):
        if path.suffix.lower() not in (".mdc", ".md", ".markdown"):
            continue
        content = _read_text_file(path)
        if content:
            sections.append({"path": _rel(path, root), "content": content})
    return sections


def _collect_learnings(root: Path) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    for rel in LEARNING_REL_PATHS:
        path = root / rel
        content = _read_text_file(path)
        if content:
            sections.append({"path": rel, "content": content})
    return sections


def _skill_search_roots(root: Path) -> list[Path]:
    return [
        root / ".cursor" / "skills",
        root / ".agents" / "skills",
        root / "skills",
    ]


def _resolve_skill_path(root: Path, skill_name: str) -> Path | None:
    name = skill_name.strip()
    if not name:
        return None
    candidates: list[Path] = []
    for base in _skill_search_roots(root):
        candidates.extend(
            [
                base / name / "SKILL.md",
                base / f"{name}.md",
                base / name,
            ]
        )
    home_skills = Path.home() / ".cursor" / "skills" / name / "SKILL.md"
    candidates.append(home_skills)
    for path in candidates:
        if path.is_file() and not _should_skip(path):
            return path
    return None


def _load_skills(root: Path, skill_names: list[str] | None) -> list[dict[str, str]]:
    skills: list[dict[str, str]] = []
    seen: set[str] = set()
    for name in skill_names or []:
        key = name.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        path = _resolve_skill_path(root, key)
        if path is None:
            skills.append(
                {
                    "name": key,
                    "path": "",
                    "content": f"(skill file not found for {key!r})",
                }
            )
            continue
        content = _read_text_file(path)
        if content:
            try:
                skill_path = _rel(path, root)
            except ValueError:
                skill_path = str(path)
            skills.append({"name": key, "path": skill_path, "content": content})
    return skills


def _git_snapshot(root: Path) -> dict[str, Any] | None:
    git_dir = root / ".git"
    if not git_dir.exists():
        return None
    try:
        branch = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(root), "diff", "--name-only", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
        diff_stat = subprocess.run(
            ["git", "-C", str(root), "diff", "--stat", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None
    dirty_files = [line for line in dirty.splitlines() if line.strip()]
    return {
        "branch": branch,
        "dirty_files": dirty_files,
        "diff_stat": diff_stat,
        "status_porcelain": status,
    }


def load_workspace_context(
    workspace: str | Path,
    *,
    skill_names: list[str] | None = None,
    extra_context: str | None = None,
) -> dict[str, Any]:
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"workspace is not a directory: {root}")

    sections: list[dict[str, str]] = []
    sections.extend(_collect_agent_docs(root))
    sections.extend(_collect_rules(root))
    sections.extend(_collect_learnings(root))

    skills = _load_skills(root, skill_names)
    git_info = _git_snapshot(root)

    sources = [s["path"] for s in sections]
    sources.extend(s["path"] for s in skills if s.get("path"))

    extra = (extra_context or "").strip()
    return {
        "workspace": str(root),
        "sources": sources,
        "sections": sections,
        "skills": skills,
        "git": git_info,
        "extra_context": extra,
    }


def format_workspace_context_for_prompt(context: dict[str, Any] | None) -> str:
    if not context:
        return ""

    lines = [
        "Project context (read from the same files as the IDE client; follow exactly):",
        f"workspace: {context.get('workspace', '')}",
    ]
    sources = context.get("sources") or []
    if sources:
        lines.append("sources: " + ", ".join(sources))

    for section in context.get("sections") or []:
        path = section.get("path") or "unknown"
        content = section.get("content") or ""
        lines.append(f"\n--- FILE: {path} ---\n{content}")

    for skill in context.get("skills") or []:
        name = skill.get("name") or "skill"
        path = skill.get("path") or ""
        content = skill.get("content") or ""
        header = f"--- SKILL: {name}"
        if path:
            header += f" ({path})"
        lines.append(f"\n{header} ---\n{content}")

    git_info = context.get("git")
    if git_info:
        lines.append("\n--- GIT ---")
        lines.append(f"branch: {git_info.get('branch', '')}")
        dirty = git_info.get("dirty_files") or []
        if dirty:
            lines.append("dirty_files:")
            lines.extend(f"  - {item}" for item in dirty)
        diff_stat = (git_info.get("diff_stat") or "").strip()
        if diff_stat:
            lines.append(f"diff_stat:\n{diff_stat}")

    extra = (context.get("extra_context") or "").strip()
    if extra:
        lines.append(f"\n--- RUN EXTRA CONTEXT ---\n{extra}")

    return "\n".join(lines).strip()
