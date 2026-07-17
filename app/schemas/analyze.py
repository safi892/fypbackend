"""Request/response schemas for ``POST /analyze`` (extended, backward safe).

Problem solved: the original mobile client only knew ``input_code``,
``commented_code`` and ``explanation``. Every new field is **additive**
(optional response fields, optional request fields) so the old client keeps
working while new clients can opt into static analysis, suggestions,
documentation, change analysis and translation.

Why pydantic: gives us free validation (e.g. ``code`` must be non-empty) and a
single source of truth for the JSON contract shared by router + frontend.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    """Incoming analysis request. New fields default so old clients work."""

    code: str = Field(..., min_length=1, description="Source code to analyze")
    source: str | None = Field(None, description="Client identifier, e.g. mobile")
    language: str = Field("cpp", description="Source language (currently cpp)")
    output_language: str = Field(
        "english",
        description="Language for generated text: english | roman_urdu",
    )
    old_code: str | None = Field(
        None, description="Previous version of the code for change analysis"
    )


class FunctionInfo(BaseModel):
    """Per-function static facts extracted by the analyzer."""

    name: str
    start_line: int
    end_line: int
    length: int
    params: int
    recursive: bool
    max_loop_depth: int
    has_comment: bool
    has_doc: bool


class StaticAnalysis(BaseModel):
    """Aggregate static analysis result (deterministic, no AI)."""

    language: str = "cpp"
    functions: list[FunctionInfo] = Field(default_factory=list)
    function_count: int = 0
    recursive: bool = False
    max_nested_loops: int = 0
    long_functions: list[str] = Field(default_factory=list)
    missing_comments: int = 0
    missing_docs: int = 0
    duplicate_functions: list[str] = Field(default_factory=list)
    loops: int = 0
    conditionals: int = 0
    cyclomatic_complexity: int = 0
    parser: str = "tree-sitter"


class DocEntry(BaseModel):
    """One generated documentation block for a single function."""

    function: str
    description: str
    parameters: list[str] = Field(default_factory=list)
    returns: str = ""


class ChangeAnalysis(BaseModel):
    """Result of comparing an old vs new code version (Phase 4)."""

    added_functions: list[str] = Field(default_factory=list)
    removed_functions: list[str] = Field(default_factory=list)
    modified_functions: list[str] = Field(default_factory=list)
    complexity_delta: int = 0
    complexity_increased: bool = False


class AnalyzeResponse(BaseModel):
    """Combined analysis response. Core 3 fields are kept first & unchanged."""

    # --- Existing fields (kept first & unchanged for mobile compatibility) ---
    input_code: str
    commented_code: str
    explanation: str

    # --- New additive fields (Phases 3-11) ---
    analysis: StaticAnalysis | None = None
    suggestions: list[str] = Field(default_factory=list)
    documentation: list[DocEntry] = Field(default_factory=list)
    change_analysis: ChangeAnalysis | None = None
    translation: str | None = None
