from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    code: str = Field(..., min_length=1, description="Source code to analyze")
    source: str | None = Field(None, description="Client identifier, e.g. mobile")


class AnalyzeResponse(BaseModel):
    input_code: str
    commented_code: str
    explanation: str
