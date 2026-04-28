from __future__ import annotations

from typing import Any

from paper_saerch.app.connectors.base import BaseSourceClient
from paper_saerch.app.domain.schemas import PaperResult, QueryBundleItem, SearchMode


class CoreClient(BaseSourceClient):
    def render_query_for_mode(self, mode: SearchMode, query_item: QueryBundleItem) -> str:
        rendered = super().render_query_for_mode(mode, query_item)
        if mode != "deep":
            return rendered
        if query_item.label.startswith("criterion-"):
            return rendered
        return " ".join(rendered.split()[:10]).strip()

    async def quick_search(self, query: str, limit: int = 5) -> list[PaperResult]:
        async def fetch(normalized_query: str, normalized_limit: int) -> list[PaperResult]:
            headers: dict[str, str] = {}
            params: dict[str, Any] = {
                "q": f'title:"{normalized_query}"',
                "limit": min(normalized_limit, self.settings.get("default_limit", 25)),
            }
            if self.settings.get("api_key"):
                headers["x-api-key"] = self.settings["api_key"]

            url = f"{self.settings['base_url']}{self.settings['works_search_path']}/"
            payload = await self.get_json(url, params=params, headers=headers)

            results: list[PaperResult] = []
            for item in payload.get("results", []):
                authors = []
                for author in item.get("authors", []):
                    if isinstance(author, dict) and author.get("name"):
                        authors.append(author["name"])
                    elif isinstance(author, str):
                        authors.append(author)
                results.append(
                    PaperResult(
                        source=self.name,
                        source_id=str(item.get("id")) if item.get("id") is not None else None,
                        title=item.get("title") or "",
                        abstract=item.get("abstract"),
                        year=item.get("yearPublished"),
                        doi=item.get("doi"),
                        url=item.get("downloadUrl") or (item.get("outputs", [None])[0] if item.get("outputs") else None),
                        pdf_url=item.get("downloadUrl"),
                        is_oa=None,
                        authors=authors,
                        raw=item,
                    )
                )
            return results

        return await self.execute_quick_search(query, limit, fetch)

    async def deep_search(self, query_item: QueryBundleItem, limit: int = 5) -> list[PaperResult]:
        async def fetch(rendered_query: str, normalized_limit: int) -> list[PaperResult]:
            headers: dict[str, str] = {}
            params: dict[str, Any] = {
                "q": rendered_query,
                "limit": min(normalized_limit, self.settings.get("default_limit", 25)),
            }
            if self.settings.get("api_key"):
                headers["x-api-key"] = self.settings["api_key"]

            url = f"{self.settings['base_url']}{self.settings['works_search_path']}/"
            payload = await self.get_json(url, params=params, headers=headers)

            results: list[PaperResult] = []
            for item in payload.get("results", []):
                authors = []
                for author in item.get("authors", []):
                    if isinstance(author, dict) and author.get("name"):
                        authors.append(author["name"])
                    elif isinstance(author, str):
                        authors.append(author)
                results.append(
                    PaperResult(
                        source=self.name,
                        source_id=str(item.get("id")) if item.get("id") is not None else None,
                        title=item.get("title") or "",
                        abstract=item.get("abstract"),
                        year=item.get("yearPublished"),
                        doi=item.get("doi"),
                        url=item.get("downloadUrl") or (item.get("outputs", [None])[0] if item.get("outputs") else None),
                        pdf_url=item.get("downloadUrl"),
                        is_oa=None,
                        authors=authors,
                        raw=item,
                    )
                )
            return results

        return await self.execute_deep_search(query_item, limit, fetch)
