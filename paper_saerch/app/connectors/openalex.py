from __future__ import annotations

from typing import Any

from paper_saerch.app.connectors.base import BaseSourceClient
from paper_saerch.app.domain.schemas import PaperResult, QueryBundleItem, SearchMode


def _reconstruct_openalex_abstract(inverted_index: dict[str, list[int]] | None) -> str | None:
    if not inverted_index:
        return None

    words: list[tuple[int, str]] = []
    for token, positions in inverted_index.items():
        for position in positions:
            words.append((position, token))
    words.sort(key=lambda item: item[0])
    return " ".join(token for _, token in words)


class OpenAlexClient(BaseSourceClient):
    def render_query_for_mode(self, mode: SearchMode, query_item: QueryBundleItem) -> str:
        rendered = super().render_query_for_mode(mode, query_item)
        if mode != "deep":
            return rendered
        if query_item.label.startswith("criterion-"):
            return rendered
        return " ".join(rendered.split()[:12]).strip()

    async def quick_search(self, query: str, limit: int = 5) -> list[PaperResult]:
        async def fetch(normalized_query: str, normalized_limit: int) -> list[PaperResult]:
            params: dict[str, Any] = {
                "search": normalized_query,
                "per-page": min(normalized_limit, self.settings.get("max_per_page", 100)),
            }
            if self.settings.get("api_key"):
                params["api_key"] = self.settings["api_key"]

            url = f"{self.settings['base_url']}{self.settings['works_path']}"
            payload = await self.get_json(url, params=params)

            results: list[PaperResult] = []
            for item in payload.get("results", []):
                primary_location = item.get("primary_location") or {}
                best_oa_location = item.get("best_oa_location") or {}
                open_access = item.get("open_access") or {}
                pdf_url = (
                    (best_oa_location.get("pdf_url") if isinstance(best_oa_location, dict) else None)
                    or (primary_location.get("pdf_url") if isinstance(primary_location, dict) else None)
                )
                results.append(
                    PaperResult(
                        source=self.name,
                        source_id=item.get("id"),
                        title=item.get("display_name") or "",
                        abstract=_reconstruct_openalex_abstract(item.get("abstract_inverted_index")),
                        year=item.get("publication_year"),
                        doi=item.get("doi"),
                        url=(primary_location.get("landing_page_url") if isinstance(primary_location, dict) else None)
                        or item.get("id"),
                        pdf_url=pdf_url,
                        is_oa=open_access.get("is_oa"),
                        authors=[
                            authorship.get("author", {}).get("display_name")
                            for authorship in item.get("authorships", [])
                            if authorship.get("author", {}).get("display_name")
                        ],
                        raw=item,
                    )
                )
            return results

        return await self.execute_quick_search(query, limit, fetch)

    async def deep_search(self, query_item: QueryBundleItem, limit: int = 5) -> list[PaperResult]:
        async def fetch(rendered_query: str, normalized_limit: int) -> list[PaperResult]:
            params: dict[str, Any] = {
                "search": rendered_query,
                "per-page": min(normalized_limit, self.settings.get("max_per_page", 100)),
            }
            if self.settings.get("api_key"):
                params["api_key"] = self.settings["api_key"]

            url = f"{self.settings['base_url']}{self.settings['works_path']}"
            payload = await self.get_json(url, params=params)

            results: list[PaperResult] = []
            for item in payload.get("results", []):
                primary_location = item.get("primary_location") or {}
                best_oa_location = item.get("best_oa_location") or {}
                open_access = item.get("open_access") or {}
                pdf_url = (
                    (best_oa_location.get("pdf_url") if isinstance(best_oa_location, dict) else None)
                    or (primary_location.get("pdf_url") if isinstance(primary_location, dict) else None)
                )
                results.append(
                    PaperResult(
                        source=self.name,
                        source_id=item.get("id"),
                        title=item.get("display_name") or "",
                        abstract=_reconstruct_openalex_abstract(item.get("abstract_inverted_index")),
                        year=item.get("publication_year"),
                        doi=item.get("doi"),
                        url=(primary_location.get("landing_page_url") if isinstance(primary_location, dict) else None)
                        or item.get("id"),
                        pdf_url=pdf_url,
                        is_oa=open_access.get("is_oa"),
                        authors=[
                            authorship.get("author", {}).get("display_name")
                            for authorship in item.get("authorships", [])
                            if authorship.get("author", {}).get("display_name")
                        ],
                        raw=item,
                    )
                )
            return results

        return await self.execute_deep_search(query_item, limit, fetch)
