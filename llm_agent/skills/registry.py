from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import importlib
from pathlib import Path
from typing import Any

from .base import AgentSkill, SkillExecutionContext, SkillExecutionError


SKILLS_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class SkillBundle:
    name: str
    description: str
    body: str
    raw_text: str
    skills: list[AgentSkill]


@lru_cache(maxsize=1)
def get_skill_bundles() -> list[SkillBundle]:
    bundles: list[SkillBundle] = []
    for path in sorted(SKILLS_DIR.iterdir()):
        if not path.is_dir() or path.name.startswith("__"):
            continue
        skill_doc_path = path / "SKILL.md"
        skill_module_path = path / "skill.py"
        if not skill_doc_path.exists() or not skill_module_path.exists():
            continue
        raw_skill_doc = skill_doc_path.read_text(encoding="utf-8").strip()
        metadata, body = _parse_skill_markdown(raw_skill_doc)
        name = metadata.get("name") or path.name
        description = metadata.get("description") or ""
        if not description:
            continue
        module = importlib.import_module(f"llm_agent.skills.{path.name}.skill")
        get_skills = getattr(module, "get_skills", None)
        if not callable(get_skills):
            continue
        skills = get_skills(raw_skill_doc)
        if not isinstance(skills, list) or not skills:
            continue
        bundles.append(
            SkillBundle(
                name=name,
                description=description,
                body=body,
                raw_text=raw_skill_doc,
                skills=skills,
            )
        )
    return bundles


def get_registered_skills() -> dict[str, AgentSkill]:
    skills: dict[str, AgentSkill] = {}
    for bundle in get_skill_bundles():
        for skill in bundle.skills:
            skills[skill.definition.name] = skill
    return skills


def get_tool_definitions() -> list[dict[str, Any]]:
    return [skill.definition.as_tool() for skill in get_registered_skills().values()]


def build_skill_guidance() -> str:
    chunks: list[str] = []
    for bundle in get_skill_bundles():
        tool_names = ", ".join(skill.definition.name for skill in bundle.skills)
        suffix = f" Tools: {tool_names}" if tool_names else ""
        chunks.append(f"- {bundle.name}: {bundle.description}{suffix}")
    return "\n\n".join(chunks).strip()


def build_skill_context_for_tools(
    tool_names: list[str],
    *,
    loaded_bundle_names: set[str] | None = None,
) -> str:
    context, _ = select_skill_context_for_tools(
        tool_names,
        loaded_bundle_names=loaded_bundle_names,
    )
    return context


def select_skill_context_for_tools(
    tool_names: list[str],
    *,
    loaded_bundle_names: set[str] | None = None,
) -> tuple[str, set[str]]:
    selected_tools = {name for name in tool_names if name}
    if not selected_tools:
        return "", set()
    loaded_bundle_names = loaded_bundle_names or set()

    chunks: list[str] = []
    loaded_now: set[str] = set()
    for bundle in get_skill_bundles():
        if bundle.name in loaded_bundle_names:
            continue
        bundle_tool_names = {skill.definition.name for skill in bundle.skills}
        if not (bundle_tool_names & selected_tools):
            continue
        if bundle.body.strip():
            chunks.append(f"[Skill: {bundle.name}]\n{bundle.body.strip()}")
        loaded_now.add(bundle.name)
    return "\n\n".join(chunks).strip(), loaded_now


def execute_skill(
    name: str,
    arguments: dict[str, Any],
    context: SkillExecutionContext | None = None,
) -> dict[str, Any]:
    skill = get_registered_skills().get(name)
    if skill is None:
        return {
            "ok": False,
            "error": "unknown_skill",
            "detail": f"Skill '{name}' is not registered.",
        }

    try:
        result = skill.execute(arguments, context)
    except SkillExecutionError as exc:
        return {
            "ok": False,
            "error": exc.code,
            "detail": exc.detail or exc.code,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": "skill_execution_failed",
            "detail": str(exc),
        }

    return {
        "ok": True,
        "skill": name,
        "result": result,
    }


def _parse_skill_markdown(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text.strip()

    lines = text.splitlines()
    frontmatter_lines: list[str] = []
    end_index = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_index = index
            break
        frontmatter_lines.append(lines[index])

    if end_index is None:
        return {}, text.strip()

    metadata: dict[str, str] = {}
    for line in frontmatter_lines:
        if not line or line.startswith(" ") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key_text = key.strip()
        value_text = value.strip().strip("\"").strip("'")
        if key_text in {"name", "description", "metadata"}:
            metadata[key_text] = value_text

    body = "\n".join(lines[end_index + 1 :]).strip()
    return metadata, body
