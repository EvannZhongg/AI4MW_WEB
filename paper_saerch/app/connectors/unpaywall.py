from __future__ import annotations

import time

import httpx

from paper_saerch.app.connectors.base import BaseSourceClient
from paper_saerch.app.domain.schemas import PaperResult, ProbeResult, QueryBundleItem


class UnpaywallClient(BaseSourceClient):
    async def probe(self) -> ProbeResult:
        if not self.enabled:
            return ProbeResult(
                name=self.name,
                status="disabled",
                message="provider disabled in config",
                used_credentials=self.has_credentials(),
            )

        email = self.settings.get("email")
        if not email:
            return ProbeResult(
                name=self.name,
                status="error",
                message="UNPAYWALL_EMAIL not configured",
                used_credentials=False,
            )

        url = f"{self.settings['base_url']}/10.1038/nature12373"
        start = time.perf_counter()
        try:
            async with self.build_client() as client:
                response = await client.get(url, params={"email": email})
                response.raise_for_status()
                payload = response.json()
            latency_ms = int((time.perf_counter() - start) * 1000)
            return ProbeResult(
                name=self.name,
                status="ok",
                message="doi lookup probe succeeded",
                http_status=response.status_code,
                latency_ms=latency_ms,
                used_credentials=True,
                sample_title=payload.get("title"),
            )
        except httpx.HTTPStatusError as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            return ProbeResult(
                name=self.name,
                status="error",
                message=str(exc),
                http_status=exc.response.status_code,
                latency_ms=latency_ms,
                used_credentials=True,
            )
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            return ProbeResult(
                name=self.name,
                status="error",
                message=str(exc),
                latency_ms=latency_ms,
                used_credentials=True,
            )

    async def quick_search(self, query: str, limit: int = 5) -> list[PaperResult]:
        async def fetch(normalized_query: str, normalized_limit: int) -> list[PaperResult]:
            email = self.settings.get("email")
            if not email:
                raise RuntimeError("UNPAYWALL_EMAIL not configured")

            url = f"{self.settings['base_url']}{self.settings['search_path']}"
            params = {
                "query": normalized_query,
                "page": 1,
                "email": email,
            }
            payload = await self.get_json(url, params=params)

            items = payload if isinstance(payload, list) else payload.get("results", payload.get("data", []))
            results: list[PaperResult] = []
            for item in items[:normalized_limit]:
                best_oa = item.get("best_oa_location") or {}
                results.append(
                    PaperResult(
                        source=self.name,
                        source_id=item.get("doi"),
                        title=item.get("title") or "",
                        abstract=None,
                        year=item.get("year"),
                        doi=item.get("doi"),
                        url=best_oa.get("url_for_landing_page") or item.get("doi_url"),
                        pdf_url=best_oa.get("url_for_pdf"),
                        is_oa=item.get("is_oa"),
                        authors=[author.get("family") for author in item.get("z_authors", []) if author.get("family")],
                        raw=item,
                    )
                )
            return results

        return await self.execute_quick_search(query, limit, fetch)

    async def deep_search(self, query_item: QueryBundleItem, limit: int = 5) -> list[PaperResult]:
        async def fetch(rendered_query: str, normalized_limit: int) -> list[PaperResult]:
            email = self.settings.get("email")
            if not email:
                raise RuntimeError("UNPAYWALL_EMAIL not configured")

            url = f"{self.settings['base_url']}{self.settings['search_path']}"
            params = {
                "query": rendered_query,
                "page": 1,
                "email": email,
            }
            payload = await self.get_json(url, params=params)

            items = payload if isinstance(payload, list) else payload.get("results", payload.get("data", []))
            results: list[PaperResult] = []
            for item in items[:normalized_limit]:
                best_oa = item.get("best_oa_location") or {}
                results.append(
                    PaperResult(
                        source=self.name,
                        source_id=item.get("doi"),
                        title=item.get("title") or "",
                        abstract=None,
                        year=item.get("year"),
                        doi=item.get("doi"),
                        url=best_oa.get("url_for_landing_page") or item.get("doi_url"),
                        pdf_url=best_oa.get("url_for_pdf"),
                        is_oa=item.get("is_oa"),
                        authors=[author.get("family") for author in item.get("z_authors", []) if author.get("family")],
                        raw=item,
                    )
                )
            return results

        return await self.execute_deep_search(query_item, limit, fetch)
