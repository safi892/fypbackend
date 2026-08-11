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


class LineComment(BaseModel):
    """One comment bound to a line of the submitted code.

    ``code`` is that line copied from the request, so a client can show the
    comment against the user's own text and can check the binding itself
    instead of trusting it.
    """

    line: int = Field(..., ge=1, description="1-based line number in the submitted code")
    code: str = Field(..., description="That line, exactly as submitted")
    comment: str = Field(..., description="What the model says about it")


class AnchorStats(BaseModel):
    """How many generated comments survived being checked against the code.

    Exposed because it is the honest quality signal for this response:
    ``dropped`` counts comments about lines the user never wrote, which were
    discarded rather than shown.
    """

    proposed: int = 0
    kept: int = 0
    exact: int = Field(0, description="Anchors whose line number was already right")
    relocated: int = Field(0, description="Anchors moved to the line they quoted")
    dropped: int = Field(0, description="Anchors quoting code absent from the input")
    chunks: int = Field(0, description="Pieces the file was split into")


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
    # Structured form of ``commented_code``, when the backend anchors its
    # comments. Empty on the CodeT5 path, which rewrites the source instead of
    # annotating it, so nothing can be bound to a line.
    line_comments: list[LineComment] = Field(default_factory=list)
    anchor_stats: AnchorStats | None = None
    verified_comments: bool = Field(
        False,
        description="True when commented_code is the submitted source with comments "
        "attached, rather than a model's rewrite of it.",
    )
    needs_review: bool = Field(
        False,
        description="True when the generated commented code failed the C++ "
        "syntax gate and should be checked by a human before being trusted.",
    )


class OptimizeRequest(BaseModel):
    """Ask for a faster version of one function."""

    code: str = Field(..., min_length=1, description="Source code to optimize")
    source: str | None = Field(None, description="Client identifier, e.g. mobile")
    language: str = Field("cpp", description="Source language (currently cpp)")


class OptimizeResponse(BaseModel):
    """The rewrite, and the evidence for it.

    ``verified`` is the field that matters. The optimizer compiles the proposal
    next to the original and runs both on the same inputs; a rewrite that
    disagrees is discarded and ``code`` comes back as the caller sent it. A
    client should show ``verified`` rather than implying every rewrite was
    proven, because some shapes cannot be checked automatically.
    """

    input_code: str
    code: str = Field(..., description="The rewrite, or the original when none was accepted")
    changed: bool = Field(False, description="True when the returned code differs from the input")
    verified: bool = Field(
        False,
        description="True when the rewrite was compiled, executed and matched the original",
    )
    speedup: float = Field(
        0.0, description="Measured ratio, 0 when the work was too small to time reliably"
    )
    note: str = Field("", description="Human-readable summary of what was checked")
