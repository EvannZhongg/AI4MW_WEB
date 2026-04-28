from __future__ import annotations

from typing import Any, Awaitable, Callable

from paper_saerch.app.domain.schemas import CriterionJudgment, PaperResult, QueryBundleItem, SearchIntent


ProgressReporter = Callable[[dict[str, Any]], Awaitable[None]]


async def emit_progress(
    reporter: ProgressReporter | None,
    event_type: str,
    **payload: Any,
) -> None:
    if reporter is None:
        return
    await reporter({"type": event_type, **payload})


def serialize_paper_result(result: PaperResult) -> dict[str, Any]:
    return {
        "source": result.source,
        "source_id": result.source_id,
        "title": result.title,
        "abstract": result.abstract,
        "year": result.year,
        "doi": result.doi,
        "url": result.url,
        "pdf_url": result.pdf_url,
        "is_oa": result.is_oa,
        "authors": list(result.authors or []),
        "score": result.score,
        "scores": dict(result.scores or {}),
        "decision": result.decision,
        "confidence": result.confidence,
        "reason": result.reason,
    }


def serialize_judgment(judgment: CriterionJudgment) -> dict[str, Any]:
    return {
        "criterion_id": judgment.criterion_id,
        "description": judgment.description,
        "required": judgment.required,
        "supported": judgment.supported,
        "score": judgment.score,
        "confidence": judgment.confidence,
        "evidence": list(judgment.evidence or []),
        "reason": judgment.reason,
    }


def serialize_intent(intent: SearchIntent) -> dict[str, Any]:
    return {
        "planner": intent.planner,
        "rewritten_query": intent.rewritten_query,
        "logic": intent.logic,
        "reasoning": intent.reasoning,
        "criteria": [
            {
                "id": item.id,
                "description": item.description,
                "required": item.required,
                "terms": list(item.terms or []),
            }
            for item in intent.criteria
        ],
    }


def serialize_query_bundle(bundle: list[QueryBundleItem]) -> list[dict[str, Any]]:
    return [
        {
            "label": item.label,
            "query": item.query,
            "purpose": item.purpose,
        }
        for item in bundle
    ]
