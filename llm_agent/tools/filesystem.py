from __future__ import annotations

import fnmatch
import os
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from django.conf import settings

from .base import AgentTool, ToolDefinition, ToolExecutionContext, ToolExecutionError


_NOISE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".npm-cache",
    "node_modules",
    "dist",
    "build",
    ".next",
    "htmlcov",
    "storage",
}
_SENSITIVE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    "db.sqlite3",
    "id_rsa",
    "id_ed25519",
}
_SENSITIVE_PATTERNS = (
    ".env*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.sqlite",
    "*.sqlite3",
    "*.db",
)
_TYPE_GLOB_MAP = {
    "py": ("*.py", "*.pyi"),
    "python": ("*.py", "*.pyi"),
    "js": ("*.js", "*.jsx", "*.mjs", "*.cjs"),
    "ts": ("*.ts", "*.tsx", "*.mts", "*.cts"),
    "tsx": ("*.tsx",),
    "jsx": ("*.jsx",),
    "json": ("*.json",),
    "md": ("*.md", "*.mdx"),
    "markdown": ("*.md", "*.mdx"),
    "yaml": ("*.yaml", "*.yml"),
    "yml": ("*.yaml", "*.yml"),
    "toml": ("*.toml",),
    "html": ("*.html", "*.htm"),
    "css": ("*.css", "*.scss", "*.sass"),
}


class WorkspaceFileSystem:
    def __init__(self, workspace: Path | None = None) -> None:
        configured = getattr(settings, "LLM_AGENT_TOOL_WORKSPACE", None)
        root = workspace or Path(str(configured or settings.BASE_DIR))
        if not root.is_absolute():
            root = settings.BASE_DIR / root
        self.workspace = root.expanduser().resolve()

    def resolve(self, path: str | None = None) -> Path:
        raw = (path or ".").strip() or "."
        target = Path(raw).expanduser()
        if not target.is_absolute():
            target = self.workspace / target
        resolved = target.resolve()
        if not _is_under(resolved, self.workspace):
            raise ToolExecutionError(
                "path_outside_workspace",
                detail=f"Path is outside the configured workspace: {raw}",
            )
        if self.is_blocked(resolved):
            raise ToolExecutionError(
                "path_blocked",
                detail=f"Path is blocked by public-web safety rules: {raw}",
            )
        return resolved

    def is_blocked(self, path: Path) -> bool:
        try:
            relative = path.resolve().relative_to(self.workspace)
        except ValueError:
            return True
        parts = set(relative.parts)
        if parts & _NOISE_DIRS:
            return True
        lowered_name = path.name.lower()
        if lowered_name in _SENSITIVE_NAMES:
            return True
        return any(fnmatch.fnmatch(lowered_name, pattern.lower()) for pattern in _SENSITIVE_PATTERNS)

    def display_path(self, path: Path, root: Path | None = None) -> str:
        base = root or self.workspace
        try:
            return path.relative_to(self.workspace).as_posix()
        except ValueError:
            return path.relative_to(base).as_posix()

    def iter_files(self, root: Path) -> Iterable[Path]:
        if root.is_file():
            if not self.is_blocked(root):
                yield root
            return
        for dirpath, dirnames, filenames in os.walk(root):
            current = Path(dirpath)
            dirnames[:] = [
                item
                for item in sorted(dirnames)
                if item not in _NOISE_DIRS and not self.is_blocked(current / item)
            ]
            for filename in sorted(filenames):
                candidate = current / filename
                if not self.is_blocked(candidate):
                    yield candidate

    def iter_entries(self, root: Path, *, include_files: bool, include_dirs: bool) -> Iterable[Path]:
        if root.is_file():
            if include_files and not self.is_blocked(root):
                yield root
            return
        for dirpath, dirnames, filenames in os.walk(root):
            current = Path(dirpath)
            dirnames[:] = [
                item
                for item in sorted(dirnames)
                if item not in _NOISE_DIRS and not self.is_blocked(current / item)
            ]
            if include_dirs:
                for dirname in dirnames:
                    yield current / dirname
            if include_files:
                for filename in sorted(filenames):
                    candidate = current / filename
                    if not self.is_blocked(candidate):
                        yield candidate


class ListDirTool(AgentTool):
    read_only = True
    definition = ToolDefinition(
        name="list_dir",
        description=(
            "List files and directories under the server-side project workspace. "
            "Read-only and blocked from sensitive paths such as .env, databases, uploads, and .git."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path relative to the workspace.", "default": "."},
                "recursive": {"type": "boolean", "description": "Whether to list recursively.", "default": False},
                "max_entries": {
                    "type": "integer",
                    "description": "Maximum entries to return.",
                    "minimum": 1,
                    "maximum": 500,
                    "default": 120,
                },
            },
            "additionalProperties": False,
        },
    )

    def __init__(self, fs: WorkspaceFileSystem | None = None) -> None:
        self.fs = fs or WorkspaceFileSystem()

    def execute(
        self,
        arguments: dict[str, Any],
        context: ToolExecutionContext | None = None,
    ) -> dict[str, Any]:
        _ = context
        root = self.fs.resolve(str(arguments.get("path") or "."))
        if not root.exists():
            raise ToolExecutionError("path_not_found", detail=str(arguments.get("path") or "."))
        if not root.is_dir():
            raise ToolExecutionError("not_a_directory", detail=str(arguments.get("path") or "."))

        recursive = bool(arguments.get("recursive", False))
        max_entries = _safe_int(arguments.get("max_entries"), 120, minimum=1, maximum=500)
        entries: list[str] = []
        total = 0
        iterator = self.fs.iter_entries(root, include_files=True, include_dirs=True) if recursive else root.iterdir()
        for item in sorted(iterator, key=lambda path: path.as_posix()):
            if self.fs.is_blocked(item):
                continue
            total += 1
            if len(entries) >= max_entries:
                continue
            label = self.fs.display_path(item)
            if item.is_dir():
                label += "/"
            entries.append(label)
        return {
            "path": self.fs.display_path(root),
            "entries": entries,
            "total": total,
            "truncated": total > len(entries),
        }


class ReadFileTool(AgentTool):
    read_only = True
    _MAX_FILE_BYTES = 1_000_000
    _MAX_CHARS = 80_000
    definition = ToolDefinition(
        name="read_file",
        description=(
            "Read a UTF-8 text file from the server-side project workspace with line pagination. "
            "Read-only and blocked from sensitive paths."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to the workspace.", "minLength": 1},
                "offset": {
                    "type": "integer",
                    "description": "1-based starting line number.",
                    "minimum": 1,
                    "default": 1,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum lines to return.",
                    "minimum": 1,
                    "maximum": 1000,
                    "default": 300,
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    )

    def __init__(self, fs: WorkspaceFileSystem | None = None) -> None:
        self.fs = fs or WorkspaceFileSystem()

    def execute(
        self,
        arguments: dict[str, Any],
        context: ToolExecutionContext | None = None,
    ) -> dict[str, Any]:
        _ = context
        path_text = str(arguments.get("path") or "")
        file_path = self.fs.resolve(path_text)
        if not file_path.exists():
            raise ToolExecutionError("path_not_found", detail=path_text)
        if not file_path.is_file():
            raise ToolExecutionError("not_a_file", detail=path_text)
        size = file_path.stat().st_size
        if size > self._MAX_FILE_BYTES:
            raise ToolExecutionError("file_too_large", detail=f"{path_text} is larger than 1 MB")
        raw = file_path.read_bytes()
        if b"\x00" in raw:
            raise ToolExecutionError("binary_file_blocked", detail=path_text)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ToolExecutionError("non_utf8_file", detail=path_text) from exc

        lines = text.replace("\r\n", "\n").splitlines()
        offset = _safe_int(arguments.get("offset"), 1, minimum=1, maximum=max(len(lines), 1))
        limit = _safe_int(arguments.get("limit"), 300, minimum=1, maximum=1000)
        start = min(offset - 1, len(lines))
        end = min(start + limit, len(lines))
        numbered = [f"{index + 1}| {line}" for index, line in enumerate(lines[start:end], start=start)]
        content = "\n".join(numbered)
        truncated_by_chars = False
        if len(content) > self._MAX_CHARS:
            content = content[: self._MAX_CHARS]
            truncated_by_chars = True
        return {
            "path": self.fs.display_path(file_path),
            "offset": offset,
            "end_line": end,
            "total_lines": len(lines),
            "content": content,
            "has_more": end < len(lines) or truncated_by_chars,
        }


def _is_under(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def match_glob(rel_path: str, name: str, pattern: str) -> bool:
    normalized = (pattern or "").strip().replace("\\", "/")
    if not normalized:
        return False
    if "/" in normalized or normalized.startswith("**"):
        return PurePosixPath(rel_path).match(normalized)
    return fnmatch.fnmatch(name, normalized)


def matches_type(name: str, file_type: str | None) -> bool:
    if not file_type:
        return True
    lowered = file_type.strip().lower()
    if not lowered:
        return True
    patterns = _TYPE_GLOB_MAP.get(lowered, (f"*.{lowered}",))
    return any(fnmatch.fnmatch(name.lower(), pattern.lower()) for pattern in patterns)


def is_binary(raw: bytes) -> bool:
    if b"\x00" in raw:
        return True
    sample = raw[:4096]
    if not sample:
        return False
    non_text = sum(byte < 9 or 13 < byte < 32 for byte in sample)
    return (non_text / len(sample)) > 0.2


def paginate(items: list[Any], limit: int | None, offset: int) -> tuple[list[Any], bool]:
    if limit is None:
        return items[offset:], False
    sliced = items[offset : offset + limit]
    return sliced, len(items) > offset + limit


def _safe_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))
