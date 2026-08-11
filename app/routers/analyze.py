"""``/analyze`` endpoint — orchestrates the full hybrid review pipeline.

Problem solved: a single request must fan out to static analysis, the shared AI
model, and the per-task services, then combine everything into one backward
-compatible response. This router wires those stages together in order.

Why orchestrate here (not in the services): keeps each service focused on one
task and makes the pipeline order explicit and easy to follow/test.
"""

from fastapi import APIRouter, Header, HTTPException, Query

from app.model_processing.syntax_check import check_cpp_syntax
from app.schemas.analyze import (
    AnalyzeRequest,
    AnalyzeResponse,
    AnchorStats,
    LineComment,
    OptimizeRequest,
    OptimizeResponse,
)
from app.schemas.history import HistoryListResponse
from app.services import (
    comment_service,
    diff_service,
    documentation_service,
    explanation_service,
    model_service,
    optimization_service,
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
    commented_code = comment_service.generate(
        payload.code, raw.commented_code, verified=raw.verified
    )
    explanation = explanation_service.generate(payload.code, raw.explanation)
    suggestions = review_service.generate_suggestions(analysis)
    documentation = documentation_service.generate(analysis)

    # Safety gate: flag commented code the compiler rejects so clearly broken
    # model output is surfaced for human review rather than trusted blindly.
    # An anchored backend never regenerates the source, so its output can only
    # fail this if the submission itself does not compile.
    syntax_ok, _ = check_cpp_syntax(commented_code)

    # `needs_review` keeps its name and type because an Android client reads it,
    # but the old rule made it a poor signal: an anchored backend can only fail
    # the syntax gate if the *submission* does not compile, so it answered false
    # on every well-formed request — including ones where comments were thrown
    # away for being untrue of their line. Discarded anchors mean the model was
    # drifting on this input, and what survived deserves a second look.
    discarded = raw.anchor_stats.get("dropped", 0) if raw.anchor_stats else 0
    needs_review = (not syntax_ok and not raw.verified) or discarded > 0

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
        line_comments=[LineComment(**item) for item in raw.line_comments],
        anchor_stats=AnchorStats(**raw.anchor_stats) if raw.anchor_stats else None,
        verified_comments=raw.verified,
        needs_review=needs_review,
    )

    record_history(
        user_id=user.id,
        input_code=response.input_code,
        commented_code=response.commented_code,
        explanation=response.explanation,
        source=payload.source,
    )

    return response


@router.post("/optimize", response_model=OptimizeResponse)
def optimize(
    payload: OptimizeRequest,
    authorization: str | None = Header(default=None),
) -> OptimizeResponse:
    """Return a faster version of the submitted code, if one can be proven.

    Problem solved: commenting and explaining describe code; this changes it,
    which is a different promise. A rewrite that is merely plausible is worse
    than none, so the proposal is compiled beside the original, both are run on
    the same inputs, and it is only returned when the outputs agree.

    Why the original comes back on failure rather than an error: a client
    asking for a faster version should never be handed code that computes
    something else, and should never be handed nothing either. ``changed`` and
    ``verified`` say which case this is.

    :param payload: the code to optimize.
    :param authorization: bearer token header (may be ``None`` -> 401).
    :return: the code to show plus the evidence for it.
    :raises HTTPException: 401 if unauthenticated.
    """
    require_user(authorization)

    result = optimization_service.optimize_checked(payload.code)
    return OptimizeResponse(
        input_code=payload.code.strip(),
        code=result.code,
        changed=result.changed,
        verified=result.verified,
        speedup=round(result.speedup, 2),
        note=result.note,
    )


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
