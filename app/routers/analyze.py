from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query

from app.schemas.analyze import AnalyzeRequest, AnalyzeResponse
from app.schemas.history import HistoryListResponse
from app.services.auth_service import require_user
from app.services.history_service import list_history, record_history
from app.services.model_service import analyze_code


router = APIRouter()


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(payload: AnalyzeRequest, authorization: Optional[str] = Header(default=None)) -> AnalyzeResponse:
    user = require_user(authorization)
    try:
        response = analyze_code(payload.code)
    except (FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

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
    authorization: Optional[str] = Header(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> HistoryListResponse:
    user = require_user(authorization)
    items, total = list_history(user_id=user.id, limit=limit, offset=offset)
    return HistoryListResponse(items=items, total=total, limit=limit, offset=offset)
