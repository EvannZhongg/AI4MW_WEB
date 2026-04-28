from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from llm_agent.skills.base import SkillExecutionContext


_JSON_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


class ToolExecutionError(Exception):
    def __init__(self, code: str, *, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    source: str = "builtin"

    def as_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


@dataclass(frozen=True)
class ToolExecutionContext:
    skill_context: SkillExecutionContext | None = None


class AgentTool:
    definition: ToolDefinition
    read_only = False

    @property
    def name(self) -> str:
        return self.definition.name

    def cast_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        schema = self.definition.parameters or {}
        if schema.get("type", "object") != "object":
            return arguments
        return _cast_object(arguments, schema)

    def validate_arguments(self, arguments: dict[str, Any]) -> list[str]:
        if not isinstance(arguments, dict):
            return [f"arguments must be an object, got {type(arguments).__name__}"]
        schema = self.definition.parameters or {}
        if schema.get("type", "object") != "object":
            return ["tool parameters schema must be an object"]
        return validate_json_schema_value(arguments, {**schema, "type": "object"})

    def execute(
        self,
        arguments: dict[str, Any],
        context: ToolExecutionContext | None = None,
    ) -> Any:
        raise NotImplementedError


def validate_json_schema_value(value: Any, schema: dict[str, Any], path: str = "") -> list[str]:
    raw_type = schema.get("type")
    nullable = (isinstance(raw_type, list) and "null" in raw_type) or schema.get("nullable", False)
    json_type = _resolve_type(raw_type)
    label = path or "arguments"

    if nullable and value is None:
        return []
    if json_type == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
        return [f"{label} should be integer"]
    if json_type == "number" and (
        not isinstance(value, _JSON_TYPE_MAP["number"]) or isinstance(value, bool)
    ):
        return [f"{label} should be number"]
    if (
        json_type in _JSON_TYPE_MAP
        and json_type not in {"integer", "number"}
        and not isinstance(value, _JSON_TYPE_MAP[json_type])
    ):
        return [f"{label} should be {json_type}"]

    errors: list[str] = []
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{label} must be one of {schema['enum']}")

    if json_type in {"integer", "number"}:
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{label} must be >= {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{label} must be <= {schema['maximum']}")
    elif json_type == "string":
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{label} must be at least {schema['minLength']} chars")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{label} must be at most {schema['maxLength']} chars")
    elif json_type == "object":
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        for key in schema.get("required") or []:
            if key not in value:
                errors.append(f"missing required {_join_path(path, str(key))}")
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    errors.append(f"unexpected argument {_join_path(path, str(key))}")
        for key, item in value.items():
            item_schema = properties.get(key)
            if isinstance(item_schema, dict):
                errors.extend(validate_json_schema_value(item, item_schema, _join_path(path, str(key))))
    elif json_type == "array":
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{label} must have at least {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{label} must have at most {schema['maxItems']} items")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(validate_json_schema_value(item, item_schema, f"{label}[{index}]"))
    return errors


def _cast_object(value: Any, schema: dict[str, Any]) -> Any:
    if not isinstance(value, dict):
        return value
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    return {
        key: _cast_value(item, properties[key]) if key in properties else item
        for key, item in value.items()
    }


def _cast_value(value: Any, schema: dict[str, Any]) -> Any:
    json_type = _resolve_type(schema.get("type"))

    if json_type == "string":
        return value if value is None else str(value)
    if json_type == "integer" and isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return value
    if json_type == "number" and isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return value
    if json_type == "boolean" and isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    if json_type == "array" and isinstance(value, list) and isinstance(schema.get("items"), dict):
        return [_cast_value(item, schema["items"]) for item in value]
    if json_type == "object" and isinstance(value, dict):
        return _cast_object(value, schema)
    return value


def _resolve_type(value: Any) -> str | None:
    if isinstance(value, list):
        for item in value:
            if item != "null":
                return str(item)
        return None
    return str(value) if value is not None else None


def _join_path(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key
