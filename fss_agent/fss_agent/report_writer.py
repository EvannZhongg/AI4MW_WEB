from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .client import CompletionUsage


@dataclass(slots=True)
class PaperReportRow:
    paper_name: str
    paper_dir: str
    image_extraction_json: str
    text_extraction_json: str
    final_extraction_json: str
    ground_truth: str
    image_prompt_tokens: int
    image_completion_tokens: int
    image_total_tokens: int
    text_prompt_tokens: int
    text_completion_tokens: int
    text_total_tokens: int
    all_total_tokens: int


class ReportWriter:
    HEADER = [
        "paper_name",
        "paper_dir",
        "image_extraction_json",
        "text_extraction_json",
        "final_extraction_json",
        "ground_truth",
        "image_prompt_tokens",
        "image_completion_tokens",
        "image_total_tokens",
        "text_prompt_tokens",
        "text_completion_tokens",
        "text_total_tokens",
        "all_total_tokens",
    ]

    @classmethod
    def build_row(
        cls,
        *,
        paper_dir: Path,
        image_payload: dict,
        text_payload: dict,
        image_usage: CompletionUsage,
        text_usage: CompletionUsage,
    ) -> PaperReportRow:
        image_json = json.dumps(image_payload, ensure_ascii=False)
        text_json = json.dumps(text_payload, ensure_ascii=False)
        return PaperReportRow(
            paper_name=paper_dir.name,
            paper_dir=str(paper_dir.resolve()),
            image_extraction_json=image_json,
            text_extraction_json=text_json,
            final_extraction_json=text_json,
            ground_truth="",
            image_prompt_tokens=image_usage.prompt_tokens,
            image_completion_tokens=image_usage.completion_tokens,
            image_total_tokens=image_usage.total_tokens,
            text_prompt_tokens=text_usage.prompt_tokens,
            text_completion_tokens=text_usage.completion_tokens,
            text_total_tokens=text_usage.total_tokens,
            all_total_tokens=image_usage.total_tokens + text_usage.total_tokens,
        )

    @classmethod
    def write_csv(cls, output_path: Path, rows: list[PaperReportRow]) -> None:
        with output_path.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=cls.HEADER)
            writer.writeheader()
            for row in rows:
                writer.writerow(asdict(row))
