from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from paper_saerch.app.connectors.base import BaseSourceClient
from paper_saerch.app.domain.schemas import PaperResult, QueryBundleItem, SearchMode


ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


class ArxivClient(BaseSourceClient):
    def _format_arxiv_term(self, text: str) -> str:
        cleaned = self.normalize_query(text).strip('"')
        if not cleaned:
            return ""
        return f'all:"{cleaned}"' if " " in cleaned else f"all:{cleaned}"

    def render_query_for_mode(self, mode: SearchMode, query_item: QueryBundleItem) -> str:
        normalized = self.normalize_query(query_item.query)
        if mode != "deep":
            return normalized

        if query_item.label == "criteria-and":
            parts = [part.strip() for part in re.split(r"\s+AND\s+", normalized, flags=re.IGNORECASE) if part.strip()]
            rendered_parts = [self._format_arxiv_term(part) for part in parts if self._format_arxiv_term(part)]
            return " AND ".join(rendered_parts) if rendered_parts else self._format_arxiv_term(normalized)

        if query_item.label == "criteria-or":
            parts = [part.strip() for part in re.split(r"\s+OR\s+", normalized, flags=re.IGNORECASE) if part.strip()]
            rendered_parts = [self._format_arxiv_term(part) for part in parts if self._format_arxiv_term(part)]
            return " OR ".join(rendered_parts) if rendered_parts else self._format_arxiv_term(normalized)

        softened = super().render_query_for_mode(mode, query_item)
        return self._format_arxiv_term(softened)

    async def quick_search(self, query: str, limit: int = 5) -> list[PaperResult]:
        async def fetch(normalized_query: str, normalized_limit: int) -> list[PaperResult]:
            params = {
                "search_query": f"all:{normalized_query}",
                "start": 0,
                "max_results": min(normalized_limit, self.settings.get("max_page_size", 2000)),
            }
            xml_text = await self.get_text(self.settings["base_url"], params=params)

            root = ET.fromstring(xml_text)
            results: list[PaperResult] = []
            for entry in root.findall("atom:entry", ATOM_NS):
                pdf_url = None
                entry_url = None
                for link in entry.findall("atom:link", ATOM_NS):
                    if link.get("title") == "pdf":
                        pdf_url = link.get("href")
                    if link.get("rel") == "alternate":
                        entry_url = link.get("href")

                authors = [
                    author.findtext("atom:name", default="", namespaces=ATOM_NS)
                    for author in entry.findall("atom:author", ATOM_NS)
                ]
                entry_id = entry.findtext("atom:id", default="", namespaces=ATOM_NS)
                published = entry.findtext("atom:published", default="", namespaces=ATOM_NS)
                updated = entry.findtext("atom:updated", default="", namespaces=ATOM_NS)
                year = int(published[:4]) if published[:4].isdigit() else None
                doi = entry.findtext("arxiv:doi", default=None, namespaces=ATOM_NS)
                categories = [item.get("term") for item in entry.findall("atom:category", ATOM_NS) if item.get("term")]
                primary_category = None
                primary_category_node = entry.find("arxiv:primary_category", ATOM_NS)
                if primary_category_node is not None:
                    primary_category = primary_category_node.get("term")

                results.append(
                    PaperResult(
                        source=self.name,
                        source_id=entry_id,
                        title=(entry.findtext("atom:title", default="", namespaces=ATOM_NS) or "").strip(),
                        abstract=(entry.findtext("atom:summary", default="", namespaces=ATOM_NS) or "").strip(),
                        year=year,
                        doi=doi,
                        url=entry_url,
                        pdf_url=pdf_url,
                        is_oa=True,
                        authors=[author for author in authors if author],
                        raw={
                            "id": entry_id,
                            "published": published,
                            "updated": updated,
                            "primary_category": primary_category,
                            "categories": categories,
                        },
                    )
                )
            return results

        return await self.execute_quick_search(query, limit, fetch)

    async def deep_search(self, query_item: QueryBundleItem, limit: int = 5) -> list[PaperResult]:
        async def fetch(rendered_query: str, normalized_limit: int) -> list[PaperResult]:
            params = {
                "search_query": rendered_query,
                "start": 0,
                "max_results": min(normalized_limit, self.settings.get("max_page_size", 2000)),
            }
            xml_text = await self.get_text(self.settings["base_url"], params=params)

            root = ET.fromstring(xml_text)
            results: list[PaperResult] = []
            for entry in root.findall("atom:entry", ATOM_NS):
                pdf_url = None
                entry_url = None
                for link in entry.findall("atom:link", ATOM_NS):
                    if link.get("title") == "pdf":
                        pdf_url = link.get("href")
                    if link.get("rel") == "alternate":
                        entry_url = link.get("href")

                authors = [
                    author.findtext("atom:name", default="", namespaces=ATOM_NS)
                    for author in entry.findall("atom:author", ATOM_NS)
                ]
                entry_id = entry.findtext("atom:id", default="", namespaces=ATOM_NS)
                published = entry.findtext("atom:published", default="", namespaces=ATOM_NS)
                updated = entry.findtext("atom:updated", default="", namespaces=ATOM_NS)
                year = int(published[:4]) if published[:4].isdigit() else None
                doi = entry.findtext("arxiv:doi", default=None, namespaces=ATOM_NS)
                categories = [item.get("term") for item in entry.findall("atom:category", ATOM_NS) if item.get("term")]
                primary_category = None
                primary_category_node = entry.find("arxiv:primary_category", ATOM_NS)
                if primary_category_node is not None:
                    primary_category = primary_category_node.get("term")

                results.append(
                    PaperResult(
                        source=self.name,
                        source_id=entry_id,
                        title=(entry.findtext("atom:title", default="", namespaces=ATOM_NS) or "").strip(),
                        abstract=(entry.findtext("atom:summary", default="", namespaces=ATOM_NS) or "").strip(),
                        year=year,
                        doi=doi,
                        url=entry_url,
                        pdf_url=pdf_url,
                        is_oa=True,
                        authors=[author for author in authors if author],
                        raw={
                            "id": entry_id,
                            "published": published,
                            "updated": updated,
                            "primary_category": primary_category,
                            "categories": categories,
                        },
                    )
                )
            return results

        return await self.execute_deep_search(query_item, limit, fetch)
