from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .client import CompletionUsage


SLUG_RE = re.compile(r"[^a-zA-Z0-9]+")


@dataclass(slots=True)
class PaperAsset:
    asset_key: str
    asset_type: str
    file_path: str
    relative_path: str
    caption: str = ""


@dataclass(slots=True)
class PaperSection:
    section_key: str
    section_order: int
    section_title: str
    section_text: str


@dataclass(slots=True)
class PaperPersistenceRecord:
    paper_key: str
    paper_name: str
    paper_dir: str
    title: str
    authors: Any
    sections: list[PaperSection]
    assets: list[PaperAsset]
    image_payload: dict[str, Any]
    text_payload: dict[str, Any]
    image_usage: CompletionUsage
    text_usage: CompletionUsage


def build_persistence_record(
    *,
    paper_dir: Path,
    image_payload: dict[str, Any],
    text_payload: dict[str, Any],
    image_usage: CompletionUsage,
    text_usage: CompletionUsage,
) -> PaperPersistenceRecord:
    structured = _read_structured_sections(paper_dir)
    paper_key = f"paper:{slugify(paper_dir.name)}"
    return PaperPersistenceRecord(
        paper_key=paper_key,
        paper_name=paper_dir.name,
        paper_dir=str(paper_dir.resolve()),
        title=str(text_payload.get("title") or structured.get("title") or paper_dir.name),
        authors=text_payload.get("authors") or structured.get("authors") or [],
        sections=_build_sections(paper_key, structured),
        assets=_build_assets(paper_key, paper_dir),
        image_payload=image_payload,
        text_payload=text_payload,
        image_usage=image_usage,
        text_usage=text_usage,
    )


def slugify(value: str, *, max_length: int = 80) -> str:
    slug = SLUG_RE.sub("_", value.strip()).strip("_")
    slug = slug or "item"
    return slug[:max_length]


def stable_key(*parts: Any) -> str:
    return ":".join(slugify(str(part), max_length=96) for part in parts if str(part))


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _read_structured_sections(paper_dir: Path) -> dict[str, Any]:
    path = paper_dir / "structured_sections.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _build_sections(paper_key: str, structured: dict[str, Any]) -> list[PaperSection]:
    sections: list[PaperSection] = []
    for index, item in enumerate(structured.get("sections", []) or [], start=1):
        sections.append(
            PaperSection(
                section_key=f"section:{paper_key}:{index}",
                section_order=index,
                section_title=str(item.get("title", "")),
                section_text=str(item.get("text", "")),
            )
        )
    return sections


def _build_assets(paper_key: str, paper_dir: Path) -> list[PaperAsset]:
    imgs_dir = paper_dir / "imgs"
    if not imgs_dir.exists():
        return []

    assets: list[PaperAsset] = []
    for path in sorted(item for item in imgs_dir.rglob("*") if item.is_file()):
        relative_path = path.relative_to(paper_dir).as_posix()
        asset_type = path.parent.name.lower() if path.parent != imgs_dir else "image"
        assets.append(
            PaperAsset(
                asset_key=f"asset:{paper_key}:{stable_key(relative_path)}",
                asset_type=asset_type,
                file_path=str(path.resolve()),
                relative_path=relative_path,
            )
        )
    return assets
