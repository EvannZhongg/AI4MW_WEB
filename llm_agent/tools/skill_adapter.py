from __future__ import annotations

from typing import Any

from llm_agent.skills.base import AgentSkill, SkillExecutionError

from .base import AgentTool, ToolDefinition, ToolExecutionContext


class SkillToolAdapter(AgentTool):
    read_only = False

    def __init__(self, skill: AgentSkill) -> None:
        self.skill = skill
        definition = skill.definition
        self.definition = ToolDefinition(
            name=definition.name,
            description=definition.description,
            parameters=definition.parameters,
            source="skill",
        )

    def execute(
        self,
        arguments: dict[str, Any],
        context: ToolExecutionContext | None = None,
    ) -> dict[str, Any]:
        skill_context = context.skill_context if context else None
        try:
            return self.skill.execute(arguments, skill_context)
        except SkillExecutionError:
            raise
