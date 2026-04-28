from __future__ import annotations

import asyncio

from paper_saerch.app.domain.schemas import ProbeResult, SearchRequest, SearchResponse
from paper_saerch.app.services.deep_channel import run_deep_channel
from paper_saerch.app.services.progress import ProgressReporter
from paper_saerch.app.services.provider_registry import build_clients
from paper_saerch.app.services.quick_channel import run_quick_channel


async def run_provider_probes(source_names: list[str] | None = None) -> list[ProbeResult]:
    all_clients = build_clients()
    clients = []
    for name, client in all_clients.items():
        if source_names and name not in source_names:
            continue
        if not client.enabled:
            continue
        clients.append(client)
    probes = await asyncio.gather(*(client.probe() for client in clients))
    return list(probes)


async def quick_search(
    request: SearchRequest,
    reporter: ProgressReporter | None = None,
) -> SearchResponse:
    return await run_quick_channel(request, reporter=reporter)


async def deep_search(
    request: SearchRequest,
    reporter: ProgressReporter | None = None,
) -> SearchResponse:
    return await run_deep_channel(request, reporter=reporter)
