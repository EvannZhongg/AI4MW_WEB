from __future__ import annotations

from typing import Any

from paper_saerch.app.connectors.base import BaseSourceClient
from paper_saerch.app.domain.schemas import PaperResult, QueryBundleItem, SearchMode


class SemanticScholarClient(BaseSourceClient):
    def render_query_for_mode(self, mode: SearchMode, query_item: QueryBundleItem) -> str:
        rendered = super().render_query_for_mode(mode, query_item)
        if mode != "deep":
            return rendered
        if query_item.label.startswith("criterion-"):
            return rendered
        return " ".join(rendered.split()[:14]).strip()

    async def quick_search(self, query: str, limit: int = 5) -> list[PaperResult]:
        async def fetch(normalized_query: str, normalized_limit: int) -> list[PaperResult]:
            headers: dict[str, str] = {}
            if self.settings.get("api_key"):
                headers["x-api-key"] = self.settings["api_key"]

            params: dict[str, Any] = {
                "query": normalized_query,
                "limit": min(normalized_limit, self.settings.get("max_limit", 100)),
                "fields": "paperId,title,abstract,year,url,externalIds,isOpenAccess,openAccessPdf,authors",
            }

            url = f"{self.settings['graph_base_url']}{self.settings['paper_search_path']}"
            payload = await self.get_json(url, params=params, headers=headers)

            results: list[PaperResult] = []
            for item in payload.get("data", []):
                pdf_obj = item.get("openAccessPdf") or {}
                external_ids = item.get("externalIds") or {}
                results.append(
                    PaperResult(
                        source=self.name,
                        source_id=item.get("paperId"),
                        title=item.get("title") or "",
                        abstract=item.get("abstract"),
                        year=item.get("year"),
                        doi=external_ids.get("DOI"),
                        url=item.get("url"),
                        pdf_url=pdf_obj.get("url"),
                        is_oa=item.get("isOpenAccess"),
                        authors=[author.get("name") for author in item.get("authors", []) if author.get("name")],
                        raw=item,
                    )
                )
            return results

        return await self.execute_quick_search(query, limit, fetch)

    async def deep_search(self, query_item: QueryBundleItem, limit: int = 5) -> list[PaperResult]:
        async def fetch(rendered_query: str, normalized_limit: int) -> list[PaperResult]:
            headers: dict[str, str] = {}
            if self.settings.get("api_key"):
                headers["x-api-key"] = self.settings["api_key"]

            params: dict[str, Any] = {
                "query": rendered_query,
                "limit": min(normalized_limit, self.settings.get("max_limit", 100)),
                "fields": "paperId,title,abstract,year,url,externalIds,isOpenAccess,openAccessPdf,authors",
            }

            url = f"{self.settings['graph_base_url']}{self.settings['paper_search_path']}"
            payload = await self.get_json(url, params=params, headers=headers)

            results: list[PaperResult] = []
            for item in payload.get("data", []):
                pdf_obj = item.get("openAccessPdf") or {}
                external_ids = item.get("externalIds") or {}
                results.append(
                    PaperResult(
                        source=self.name,
                        source_id=item.get("paperId"),
                        title=item.get("title") or "",
                        abstract=item.get("abstract"),
                        year=item.get("year"),
                        doi=external_ids.get("DOI"),
                        url=item.get("url"),
                        pdf_url=pdf_obj.get("url"),
                        is_oa=item.get("isOpenAccess"),
                        authors=[author.get("name") for author in item.get("authors", []) if author.get("name")],
                        raw=item,
                    )
                )
            return results

        return await self.execute_deep_search(query_item, limit, fetch)
