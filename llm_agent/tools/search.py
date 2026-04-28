from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .base import AgentTool, ToolDefinition, ToolExecutionContext, ToolExecutionError
from .filesystem import (
    WorkspaceFileSystem,
    is_binary,
    match_glob,
    matches_type,
    paginate,
)


class GlobTool(AgentTool):
    read_only = True
    definition = ToolDefinition(
        name="glob",
        description=(
            "Find files or directories in the server-side project workspace using a glob pattern. "
            "Use this to discover relevant files before reading or grepping."
        ),
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern such as '*.py' or 'docs/**/*.md'.", "minLength": 1},
                "path": {"type": "string", "description": "Directory to search from.", "default": "."},
                "head_limit": {
                    "type": "integer",
                    "description": "Maximum matches to return; 0 means no limit.",
                    "minimum": 0,
                    "maximum": 1000,
                    "default": 200,
                },
                "offset": {"type": "integer", "description": "Skip this many matches.", "minimum": 0, "maximum": 100000, "default": 0},
                "entry_type": {
                    "type": "string",
                    "enum": ["files", "dirs", "both"],
                    "description": "Whether to match files, directories, or both.",
                    "default": "files",
                },
            },
            "required": ["pattern"],
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
        pattern = str(arguments.get("pattern") or "").strip()
        root = self.fs.resolve(str(arguments.get("path") or "."))
        if not root.exists():
            raise ToolExecutionError("path_not_found", detail=str(arguments.get("path") or "."))
        if not root.is_dir():
            raise ToolExecutionError("not_a_directory", detail=str(arguments.get("path") or "."))

        entry_type = str(arguments.get("entry_type") or "files")
        include_files = entry_type in {"files", "both"}
        include_dirs = entry_type in {"dirs", "both"}
        matches: list[tuple[str, float]] = []
        for entry in self.fs.iter_entries(root, include_files=include_files, include_dirs=include_dirs):
            rel_path = entry.relative_to(root).as_posix()
            if not match_glob(rel_path, entry.name, pattern):
                continue
            display = self.fs.display_path(entry)
            if entry.is_dir():
                display += "/"
            try:
                mtime = entry.stat().st_mtime
            except OSError:
                mtime = 0.0
            matches.append((display, mtime))

        matches.sort(key=lambda item: (-item[1], item[0]))
        ordered = [name for name, _ in matches]
        head_limit = _safe_int(arguments.get("head_limit"), 200, minimum=0, maximum=1000)
        offset = _safe_int(arguments.get("offset"), 0, minimum=0, maximum=100000)
        paged, truncated = paginate(ordered, None if head_limit == 0 else head_limit, offset)
        return {
            "pattern": pattern,
            "path": self.fs.display_path(root),
            "matches": paged,
            "total": len(ordered),
            "offset": offset,
            "truncated": truncated,
        }


class GrepTool(AgentTool):
    read_only = True
    _MAX_FILE_BYTES = 2_000_000
    _MAX_RESULT_CHARS = 120_000
    definition = ToolDefinition(
        name="grep",
        description=(
            "Search UTF-8 text files in the server-side project workspace. "
            "Default output_mode returns matching file paths; use content for matching lines with context."
        ),
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex or plain-text pattern to search for.", "minLength": 1},
                "path": {"type": "string", "description": "File or directory to search in.", "default": "."},
                "glob": {"type": "string", "description": "Optional file glob filter, e.g. '*.py'."},
                "type": {"type": "string", "description": "Optional file type shorthand, e.g. py, ts, md, json."},
                "case_insensitive": {"type": "boolean", "description": "Case-insensitive search.", "default": False},
                "fixed_strings": {"type": "boolean", "description": "Treat pattern as plain text.", "default": False},
                "output_mode": {
                    "type": "string",
                    "enum": ["content", "files_with_matches", "count"],
                    "description": "content, files_with_matches, or count.",
                    "default": "files_with_matches",
                },
                "context_before": {"type": "integer", "minimum": 0, "maximum": 10, "default": 0},
                "context_after": {"type": "integer", "minimum": 0, "maximum": 10, "default": 0},
                "head_limit": {
                    "type": "integer",
                    "description": "Maximum result entries; 0 means no pagination limit.",
                    "minimum": 0,
                    "maximum": 1000,
                    "default": 200,
                },
                "offset": {"type": "integer", "minimum": 0, "maximum": 100000, "default": 0},
            },
            "required": ["pattern"],
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
        pattern = str(arguments.get("pattern") or "")
        target = self.fs.resolve(str(arguments.get("path") or "."))
        if not target.exists():
            raise ToolExecutionError("path_not_found", detail=str(arguments.get("path") or "."))
        if not (target.is_file() or target.is_dir()):
            raise ToolExecutionError("unsupported_path", detail=str(arguments.get("path") or "."))

        flags = re.IGNORECASE if bool(arguments.get("case_insensitive", False)) else 0
        try:
            needle = re.escape(pattern) if bool(arguments.get("fixed_strings", False)) else pattern
            regex = re.compile(needle, flags)
        except re.error as exc:
            raise ToolExecutionError("invalid_regex", detail=str(exc)) from exc

        output_mode = str(arguments.get("output_mode") or "files_with_matches")
        head_limit = _safe_int(arguments.get("head_limit"), 200, minimum=0, maximum=1000)
        limit = None if head_limit == 0 else head_limit
        offset = _safe_int(arguments.get("offset"), 0, minimum=0, maximum=100000)
        before = _safe_int(arguments.get("context_before"), 0, minimum=0, maximum=10)
        after = _safe_int(arguments.get("context_after"), 0, minimum=0, maximum=10)
        glob_pattern = str(arguments.get("glob") or "").strip()
        file_type = str(arguments.get("type") or "").strip()

        root = target if target.is_dir() else target.parent
        files_with_matches: list[str] = []
        file_mtimes: dict[str, float] = {}
        counts: dict[str, int] = {}
        content_blocks: list[dict[str, Any]] = []
        seen_content_matches = 0
        content_chars = 0
        truncated = False
        size_truncated = False
        skipped_binary = 0
        skipped_large = 0

        for file_path in self.fs.iter_files(target):
            rel_path = file_path.relative_to(root).as_posix()
            if glob_pattern and not match_glob(rel_path, file_path.name, glob_pattern):
                continue
            if file_type and not matches_type(file_path.name, file_type):
                continue

            raw = file_path.read_bytes()
            if len(raw) > self._MAX_FILE_BYTES:
                skipped_large += 1
                continue
            if is_binary(raw):
                skipped_binary += 1
                continue
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                skipped_binary += 1
                continue

            lines = text.replace("\r\n", "\n").splitlines()
            display = self.fs.display_path(file_path)
            matched_in_file = False
            for line_number, line in enumerate(lines, start=1):
                if not regex.search(line):
                    continue
                matched_in_file = True
                counts[display] = counts.get(display, 0) + 1
                if display not in file_mtimes:
                    try:
                        file_mtimes[display] = file_path.stat().st_mtime
                    except OSError:
                        file_mtimes[display] = 0.0
                if output_mode == "files_with_matches":
                    break
                if output_mode == "count":
                    continue
                seen_content_matches += 1
                if seen_content_matches <= offset:
                    continue
                if limit is not None and len(content_blocks) >= limit:
                    truncated = True
                    break
                block = _build_match_block(display, lines, line_number, before, after)
                block_chars = len(str(block))
                if content_chars + block_chars > self._MAX_RESULT_CHARS:
                    size_truncated = True
                    break
                content_blocks.append(block)
                content_chars += block_chars
            if matched_in_file and display not in files_with_matches:
                files_with_matches.append(display)
            if truncated or size_truncated:
                break

        if output_mode == "content":
            return {
                "pattern": pattern,
                "path": self.fs.display_path(target),
                "mode": output_mode,
                "matches": content_blocks,
                "total_seen_matches": seen_content_matches,
                "offset": offset,
                "truncated": truncated,
                "size_truncated": size_truncated,
                "skipped_binary": skipped_binary,
                "skipped_large": skipped_large,
            }

        ordered_files = sorted(files_with_matches, key=lambda name: (-file_mtimes.get(name, 0.0), name))
        paged_files, page_truncated = paginate(ordered_files, limit, offset)
        if output_mode == "count":
            items: list[dict[str, Any]] = [{"path": name, "count": counts.get(name, 0)} for name in paged_files]
        else:
            items = [{"path": name} for name in paged_files]
        return {
            "pattern": pattern,
            "path": self.fs.display_path(target),
            "mode": output_mode,
            "matches": items,
            "total_files": len(ordered_files),
            "offset": offset,
            "truncated": page_truncated,
            "skipped_binary": skipped_binary,
            "skipped_large": skipped_large,
        }


def _build_match_block(
    display_path: str,
    lines: list[str],
    match_line: int,
    before: int,
    after: int,
) -> dict[str, Any]:
    start = max(1, match_line - before)
    end = min(len(lines), match_line + after)
    return {
        "path": display_path,
        "line": match_line,
        "context": [
            {
                "line": line_number,
                "text": lines[line_number - 1],
                "match": line_number == match_line,
            }
            for line_number in range(start, end + 1)
        ],
    }


def _safe_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))
