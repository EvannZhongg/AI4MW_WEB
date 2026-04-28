from __future__ import annotations

from typing import Any

from django.conf import settings

from .base import AgentTool, ToolDefinition, ToolExecutionContext, ToolExecutionError


class SubagentDispatchTool(AgentTool):
    read_only = False
    definition = ToolDefinition(
        name="spawn_subagent",
        description=(
            "Dispatch a focused internal subagent for a narrow repository or backend-tool investigation. "
            "The subagent runs with read-only workspace tools and skill tools, cannot spawn further subagents, "
            "and returns its result to the main assistant in the same web turn."
        ),
        parameters={
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Specific task for the subagent to complete, including boundaries and expected output.",
                    "minLength": 10,
                    "maxLength": 4000,
                },
                "label": {
                    "type": "string",
                    "description": "Optional short label for the delegated task.",
                    "maxLength": 80,
                },
            },
            "required": ["task"],
            "additionalProperties": False,
        },
        source="builtin",
    )

    def execute(
        self,
        arguments: dict[str, Any],
        context: ToolExecutionContext | None = None,
    ) -> dict[str, Any]:
        task = str(arguments.get("task") or "").strip()
        if not task:
            raise ToolExecutionError("missing_subagent_task", detail="task is required")
        label = str(arguments.get("label") or "").strip()

        from llm_agent.services.agent_runtime import AgentRuntime
        from llm_agent.services.context_builder import AgentContextBuilder
        from llm_agent.tools.registry import build_tool_registry

        runtime_config = _build_subagent_runtime_config(settings.LLM_CONFIG)
        subagent_registry = build_tool_registry(include_subagents=False)
        messages = AgentContextBuilder().build_subagent_messages(task=task, label=label)
        runtime = AgentRuntime(
            runtime_config,
            max_tool_rounds=getattr(settings, "LLM_AGENT_MAX_SUBAGENT_TOOL_ROUNDS", 4),
            skill_context=context.skill_context if context else None,
            tool_registry=subagent_registry,
            max_tool_result_chars=getattr(settings, "LLM_AGENT_MAX_TOOL_RESULT_CHARS", 120_000),
        )
        result = runtime.run(messages)
        return {
            "label": label,
            "task": task,
            "response": result.text,
            "interface": result.interface,
            "tool_calls": result.tool_calls,
        }


def _build_subagent_runtime_config(base_config: dict[str, Any]) -> dict[str, Any]:
    runtime_config = dict(base_config)
    runtime_config["API_INTERFACE"] = "auto"
    runtime_config["API_INTERFACE_PREFERENCE"] = "chat_completions"
    return runtime_config
