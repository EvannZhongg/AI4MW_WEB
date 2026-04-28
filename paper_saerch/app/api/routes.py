from __future__ import annotations

from fastapi import APIRouter, Query

from paper_saerch.app.domain.schemas import ProvidersStatusResponse, SearchRequest, SearchResponse
from paper_saerch.app.services.provider_registry import list_provider_summaries
from paper_saerch.app.services.search_service import deep_search, quick_search, run_provider_probes


router = APIRouter(prefix="/v1")


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/providers")
async def providers() -> dict[str, object]:
    return {"providers": [item.model_dump() for item in list_provider_summaries()]}


@router.get("/providers/status", response_model=ProvidersStatusResponse)
async def provider_status(
    sources: list[str] | None = Query(default=None),
) -> ProvidersStatusResponse:
    probes = await run_provider_probes(source_names=sources)
    return ProvidersStatusResponse(mode="quick", providers=probes)


@router.post("/search/quick", response_model=SearchResponse)
async def search_quick(request: SearchRequest) -> SearchResponse:
    return await quick_search(request)


@router.post("/search/deep", response_model=SearchResponse)
async def search_deep(request: SearchRequest) -> SearchResponse:
    return await deep_search(request)
