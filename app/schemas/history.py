from pydantic import BaseModel, Field


class HistoryEntry(BaseModel):
    id: int
    input_code: str = Field(..., description="Original submitted code")
    commented_code: str = Field(..., description="Model output with inline comments")
    explanation: str = Field(..., description="Model explanation summary")
    source: str | None = Field(None, description="Client identifier")
    created_at: str = Field(..., description="ISO timestamp")


class HistoryListResponse(BaseModel):
    items: list[HistoryEntry]
    total: int
    limit: int
    offset: int
