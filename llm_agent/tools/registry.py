from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.conf import settings

from llm_agent.skills.base import SkillExecutionContext, SkillExecutionError
from llm_agent.skills.registry import get_registered_skills, get_skill_bundles

from .base import AgentTool, ToolExecutionContext, ToolExecutionError
from .filesystem import ListDirTool, ReadFileTool, WorkspaceFileSystem
from .search import GlobTool, GrepTool
from .skill_adapter import SkillToolAdapter


_DEFAULT_ENABLED_BUILTINS = ("glob", "grep", "list_dir", "read_file")


@dataclass(frozen=True)
class PreparedToolCall:
    tool: AgentTool
    arguments: dict[str, Any]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, AgentTool] = {}
        self._cached_definitions: list[dict[str, Any]] | None = None

    def register(self, tool: AgentTool) -> None:
        self._tools[tool.name] = tool
        self._cached_definitions = None

    def get(self, name: str) -> AgentTool | None:
        return self._tools.get(name)

    def get_definitions(self) -> list[dict[str, Any]]:
        if self._cached_definitions is not None:
            return self._cached_definitions
        definitions = [tool.definition.as_tool() for tool in self._tools.values()]
        definitions.sort(key=lambda item: str(item.get("name") or ""))
        self._cached_definitions = definitions
        return definitions

    @property
    def tool_names(self) -> list[str]:
        return sorted(self._tools)

    def prepare_call(self, name: str, arguments: dict[str, Any]) -> tuple[PreparedToolCall | None, str | None]:
        tool = self._tools.get(name)
        if tool is None:
            available = ", ".join(self.tool_names) or "(none)"
            return None, f"unknown_tool: Tool '{name}' is not registered. Available tools: {available}"
        if not isinstance(arguments, dict):
            return None, f"invalid_tool_arguments: expected object, got {type(arguments).__name__}"
        cast_arguments = tool.cast_arguments(arguments)
        errors = tool.validate_arguments(cast_arguments)
        if errors:
            return None, "invalid_tool_arguments: " + "; ".join(errors)
        return PreparedToolCall(tool=tool, arguments=cast_arguments), None

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        context: SkillExecutionContext | None = None,
    ) -> dict[str, Any]:
        prepared, error = self.prepare_call(name, arguments)
        if error:
            return _error_result(name, error.split(":", 1)[0], error)
        assert prepared is not None
        try:
            result = prepared.tool.execute(
                prepared.arguments,
                ToolExecutionContext(skill_context=context),
            )
        except SkillExecutionError as exc:
            return _error_result(name, exc.code, exc.detail or exc.code)
        except ToolExecutionError as exc:
            return _error_result(name, exc.code, exc.detail or exc.code)
        except Exception as exc:  # noqa: BLE001
            return _error_result(name, "tool_execution_failed", str(exc))
        return {
            "ok": True,
            "tool": name,
            "source": prepared.tool.definition.source,
            "result": result,
        }


def build_tool_registry(*, include_subagents: bool = True) -> ToolRegistry:
    registry = ToolRegistry()
    fs = WorkspaceFileSystem()
    enabled_builtins = set(_configured_enabled_builtins())
    builtin_tools: dict[str, AgentTool] = {
        "glob": GlobTool(fs),
        "grep": GrepTool(fs),
        "list_dir": ListDirTool(fs),
        "read_file": ReadFileTool(fs),
    }
    for name in _DEFAULT_ENABLED_BUILTINS:
        if name in enabled_builtins:
            registry.register(builtin_tools[name])
    if include_subagents and getattr(settings, "LLM_AGENT_ENABLE_SUBAGENTS", True):
        from .subagent import SubagentDispatchTool

        registry.register(SubagentDispatchTool())
    for skill in get_registered_skills().values():
        registry.register(SkillToolAdapter(skill))
    return registry


def build_agent_tool_guidance(*, include_subagents: bool = True) -> str:
    registry = build_tool_registry(include_subagents=include_subagents)
    builtin_lines: list[str] = []
    subagent_lines: list[str] = []
    skill_lines: list[str] = []
    for name in registry.tool_names:
        tool = registry.get(name)
        if tool is None:
            continue
        description = tool.definition.description.strip()
        if tool.definition.source == "skill":
            skill_lines.append(f"- `{name}`: {description}")
        elif name == "spawn_subagent":
            subagent_lines.append(f"- `{name}`: {description}")
        else:
            builtin_lines.append(f"- `{name}`: {description}")

    chunks: list[str] = []
    if builtin_lines:
        chunks.append(
            "Available read-only workspace tools. Use them only when the user asks about project files, "
            "code, docs, or repository-local information. These tools cannot access sensitive blocked paths.\n"
            + "\n".join(builtin_lines)
        )
    if subagent_lines:
        chunks.append(
            "Available subagent dispatch tool. Use only for narrow independent investigations.\n"
            + "\n".join(subagent_lines)
        )

    skill_bundle_lines: list[str] = []
    for bundle in get_skill_bundles():
        tool_names = ", ".join(f"`{skill.definition.name}`" for skill in bundle.skills)
        skill_bundle_lines.append(f"- `{bundle.name}`: {bundle.description} Tools: {tool_names}")
    if skill_bundle_lines:
        chunks.append(
            "Available backend skills. Skill details are loaded automatically after the model selects a skill tool.\n"
            + "\n".join(skill_bundle_lines)
        )
    elif skill_lines:
        chunks.append("Available backend skill tools.\n" + "\n".join(skill_lines))

    return "\n\n".join(chunks).strip()


def _configured_enabled_builtins() -> tuple[str, ...]:
    configured = getattr(settings, "LLM_AGENT_ENABLED_BUILTIN_TOOLS", None)
    if configured is None:
        return _DEFAULT_ENABLED_BUILTINS
    if isinstance(configured, str):
        values = [item.strip() for item in configured.split(",") if item.strip()]
    else:
        values = [str(item).strip() for item in configured if str(item).strip()]
    if not values:
        return ()
    if "*" in values or "all" in values:
        return _DEFAULT_ENABLED_BUILTINS
    allowed = set(_DEFAULT_ENABLED_BUILTINS)
    return tuple(name for name in _DEFAULT_ENABLED_BUILTINS if name in allowed and name in values)


def _error_result(name: str, code: str, detail: str) -> dict[str, Any]:
    return {
        "ok": False,
        "tool": name,
        "error": code,
        "detail": detail,
        "hint": "Analyze the error and try a different allowed approach if needed.",
    }
