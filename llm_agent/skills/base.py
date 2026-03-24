from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class SkillExecutionError(Exception):
    def __init__(self, code: str, *, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    description: str
    parameters: dict[str, Any]

    def as_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


@dataclass(frozen=True)
class SkillExecutionContext:
    conversation_id: int | None = None
    current_turn_attachments: list[dict[str, str]] = field(default_factory=list)


class AgentSkill:
    definition: SkillDefinition

    def execute(
        self,
        arguments: dict[str, Any],
        context: SkillExecutionContext | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError
