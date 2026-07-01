from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .client import CompletionUsage, OpenRouterClient
from .config import AgentConfig
from .image_extractor import ImageExtractionModule
from .nebula_store import NebulaGraphStore
from .persistence_models import PaperPersistenceRecord, build_persistence_record
from .postgres_store import PostgresStore
from .report_writer import ReportWriter
from .text_extractor import TextExtractionModule


@dataclass(slots=True)
class PaperProcessingResult:
    paper_dir: Path
    image_payload: dict[str, Any]
    text_payload: dict[str, Any]
    image_usage: CompletionUsage
    text_usage: CompletionUsage
    persistence_record: PaperPersistenceRecord


class FSSExtractionAgent:
    def __init__(self, root_dir: Path, config: AgentConfig | None = None) -> None:
        self.root_dir = Path(root_dir)
        self.config = config or AgentConfig()
        self.client = OpenRouterClient(self.config)
        self.image_module = ImageExtractionModule(self.client, self.config)
        self.text_module = TextExtractionModule(self.client, self.config)
        self.postgres_store = PostgresStore(self.config) if self.config.persist_to_postgres else None
        self.nebula_store = NebulaGraphStore(self.config) if self.config.persist_to_nebula else None
        self._paper_semaphore = asyncio.Semaphore(self.config.paper_concurrency)

    async def run(self) -> None:
        paper_dirs = self.discover_paper_dirs()
        try:
            self._initialize_stores()
            results = await asyncio.gather(*(self._process_one_paper(path) for path in paper_dirs))
            self._write_report(results)
        finally:
            if self.nebula_store is not None:
                self.nebula_store.close()
            await self.client.aclose()

    def discover_paper_dirs(self) -> list[Path]:
        return sorted(
            path
            for path in self.root_dir.iterdir()
            if path.is_dir() and (path / "structured_sections.json").exists()
        )

    async def _process_one_paper(self, paper_dir: Path) -> PaperProcessingResult:
        async with self._paper_semaphore:
            image_result = await self.image_module.extract_from_paper_dir(paper_dir)
            text_result = await self.text_module.extract_from_paper_dir(paper_dir, image_result.payload)
            self._write_json(paper_dir / self.config.output_image_json_name, image_result.payload)
            self._write_json(paper_dir / self.config.output_text_json_name, text_result.payload)
            persistence_record = build_persistence_record(
                paper_dir=paper_dir,
                image_payload=image_result.payload,
                text_payload=text_result.payload,
                image_usage=image_result.usage,
                text_usage=text_result.usage,
            )
            self._persist_record(persistence_record)
            return PaperProcessingResult(
                paper_dir=paper_dir,
                image_payload=image_result.payload,
                text_payload=text_result.payload,
                image_usage=image_result.usage,
                text_usage=text_result.usage,
                persistence_record=persistence_record,
            )

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_report(self, results: list[PaperProcessingResult]) -> None:
        rows = [
            ReportWriter.build_row(
                paper_dir=result.paper_dir,
                image_payload=result.image_payload,
                text_payload=result.text_payload,
                image_usage=result.image_usage,
                text_usage=result.text_usage,
            )
            for result in results
        ]
        ReportWriter.write_csv(self.root_dir / self.config.output_report_name, rows)

    def _initialize_stores(self) -> None:
        if self.postgres_store is not None:
            self.postgres_store.initialize()
        if self.nebula_store is not None:
            self.nebula_store.initialize()

    def _persist_record(self, record: PaperPersistenceRecord) -> None:
        if self.postgres_store is not None:
            self.postgres_store.save_record(record)
        if self.nebula_store is not None:
            self.nebula_store.save_record(record)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FSS paper extraction agent")
    parser.add_argument("--root", default=".", help="Root directory containing paper folders")
    parser.add_argument("--paper-concurrency", type=int, default=None, help="Parallel paper worker count")
    parser.add_argument("--skip-postgres", action="store_true", help="Do not write extracted data to PostgreSQL")
    parser.add_argument("--skip-nebula", action="store_true", help="Do not write extracted data to NebulaGraph")
    return parser


async def _main() -> None:
    args = build_arg_parser().parse_args()
    config = AgentConfig()
    if args.paper_concurrency is not None:
        config.paper_concurrency = args.paper_concurrency
    if args.skip_postgres:
        config.persist_to_postgres = False
    if args.skip_nebula:
        config.persist_to_nebula = False
    agent = FSSExtractionAgent(Path(args.root), config=config)
    await agent.run()


if __name__ == "__main__":
    asyncio.run(_main())
