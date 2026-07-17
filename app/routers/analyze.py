"""``/analyze`` endpoint — orchestrates the full hybrid review pipeline.

Problem solved: a single request must fan out to static analysis, the shared AI
model, and the per-task services, then combine everything into one backward
-compatible response. This router wires those stages together in order.

Why orchestrate here (not in the services): keeps each service focused on one
task and makes the pipeline order explicit and easy to follow/test.
"""

from fastapi import APIRouter, Header, HTTPException, Query

from app.schemas.analyze import AnalyzeRequest, AnalyzeResponse
from app.schemas.history import HistoryListResponse
from app.services import (
    comment_service,
    diff_service,
    documentation_service,
    explanation_service,
    model_service,
    review_service,
    translation_service,
)
from app.services.analyzer import analyze_code as static_analyze
from app.services.auth_service import require_user
from app.services.history_service import list_history, record_history

router = APIRouter()


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(
    payload: AnalyzeRequest,
    authorization: str | None = Header(default=None),
) -> AnalyzeResponse:
    """Run the full code-review pipeline and persist history.

    Problem solved: this is the one entry point the mobile client calls. Why
    additive pipeline: static analysis (fast) feeds the model prompt, the model
    feeds the comment/explanation tasks, and optional stages (diff, translation)
    only run when requested — so old clients and new clients both work.

    :param payload: the validated analysis request.
    :param authorization: bearer token header (may be ``None`` -> 401).
    :return: the combined ``AnalyzeResponse`` with core 3 fields + new ones.
    :raises HTTPException: 401 if unauthenticated, 503 if the model cannot load.
    """
    user = require_user(authorization)

    # Phase 3 — deterministic static analysis (cheap, feeds the prompt).
    analysis = static_analyze(payload.code, language=payload.language)

    # Shared AI backend (CodeT5): a single inference returning raw sections.
    try:
        raw = model_service.run_model(payload.code, analysis=analysis)
    except (FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # Task-specific NLP services (each owns its rule-engine / AI-model choice).
    commented_code = comment_service.generate(payload.code, raw.commented_code)
    explanation = explanation_service.generate(payload.code, raw.explanation)
    suggestions = review_service.generate_suggestions(analysis)
    documentation = documentation_service.generate(analysis)

    # Phase 4 — only when the client sent a previous version.
    change_analysis = None
    if payload.old_code:
        change_analysis = diff_service.compare(payload.old_code, payload.code)

    # Phase 10 — only when Roman Urdu was requested.
    translation = None
    if translation_service.is_roman_urdu(payload.output_language):
        translation = translation_service.to_roman_urdu(explanation)

    response = AnalyzeResponse(
        input_code=payload.code.strip(),
        commented_code=commented_code,
        explanation=explanation,
        analysis=analysis,
        suggestions=suggestions,
        documentation=documentation,
        change_analysis=change_analysis,
        translation=translation,
    )

    record_history(
        user_id=user.id,
        input_code=response.input_code,
        commented_code=response.commented_code,
        explanation=response.explanation,
        source=payload.source,
    )

    return response


@router.get("/analyze/history", response_model=HistoryListResponse)
def analyze_history(
    authorization: str | None = Header(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> HistoryListResponse:
    """Return paginated analysis history for the authenticated user.

    Problem solved: lets the client show past reviews. Why paginated: history
    can grow large, so we bound the response with ``limit``/``offset``.

    :param authorization: bearer token header.
    :param limit: max items to return (1-100).
    :param offset: items to skip from the start.
    :return: a page of history items with total count.
    :raises HTTPException: 401 if unauthenticated.
    """
    user = require_user(authorization)
    items, total = list_history(user_id=user.id, limit=limit, offset=offset)
    return HistoryListResponse(items=items, total=total, limit=limit, offset=offset)
