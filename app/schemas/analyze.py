"""Request/response schemas for ``POST /analyze``.

Problem solved: the public mobile response stays small — ``input_code``,
``commented_code``, ``explanation`` and ``needs_review`` — while the router can
still carry internal static analysis, suggestions, documentation, change
analysis, translation metadata and anchors through the pipeline before FastAPI
filters the response.

Why pydantic: gives us free validation (e.g. ``code`` must be non-empty) and a
single source of truth for the JSON contract shared by router + frontend.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CodeValidationRequest(BaseModel):
    code: str = Field(..., max_length=100_000)


class CodeFixEdit(BaseModel):
    """One line-level before/after pair of a proposed fix.

    Lines are numbered against the *submitted* code so a preview row points at
    the user's own line; ``before`` is empty when the fix adds a line.
    """

    line: int = Field(..., ge=1, description="1-based line in the submitted code")
    before: str = Field("", description="That line before the fix (empty for an added line)")
    after: str = Field(..., description="That line after the fix")


class SuggestedFix(BaseModel):
    """A candidate punctuation fix, offered for preview and never auto-applied.

    ``code`` is the full source after the fix; the client must show ``edits``
    and apply it only on an explicit user action, because a fix that parses
    can still change what the snippet means.
    """

    code: str = Field(..., description="The full source with the fix applied")
    description: str = Field(..., description="One-line summary, e.g. the token and line")
    edits: list[CodeFixEdit] = Field(
        default_factory=list, description="Touched lines, for rendering the preview"
    )


class CodeValidationResponse(BaseModel):
    valid: bool
    message: str
    line: int | None = None
    suggested_fix: SuggestedFix | None = Field(
        None,
        description="Parser-proposed fix when the code is invalid and a safe "
        "punctuation fix exists; null otherwise. Preview only.",
    )


class DefectsRequest(BaseModel):
    """Ask what can be established about the code without the model."""

    code: str = Field(..., min_length=1, max_length=100_000,
                      description="Source code to check")
    run_code: bool = Field(
        False,
        description="Also compile and run the code to look for non-termination. "
        "Off by default: it executes what you send, with a timeout as the only "
        "restraint and no sandbox.",
    )


class DefectFinding(BaseModel):
    """One finding, with the line it quotes and how sure the checker is."""

    rule: str = Field(..., description="Stable id, e.g. unused_variable, infinite_loop")
    line: int = Field(..., description="1-based line in the submitted code")
    code: str = Field(..., description="That line, copied verbatim from the input")
    message: str
    certain: bool = Field(
        ...,
        description="True when the rule only fires on cases it can prove. False "
        "means evidence rather than proof - render the two differently.",
    )
    tier: int = Field(..., description="1 compiler, 2 cppcheck, 3 parse tree, 4 timeout")


class DefectsResponse(BaseModel):
    """What the compiler, cppcheck and the parse tree found on their own.

    ``compile_error`` short-circuits everything else: when the code does not
    compile, that is the user's problem, and the other tiers would describe
    structure that is not in the program.

    ``tiers_run`` exists so a client never implies all four ran. Tier 2 needs
    cppcheck installed and tier 1 reads GNU diagnostics, so a host can
    legitimately offer fewer.
    """

    input_code: str
    compile_error: str | None = None
    findings: list[DefectFinding] = Field(default_factory=list)
    tiers_run: dict[int, bool] = Field(default_factory=dict)


class AnalyzeRequest(BaseModel):
    """Incoming analysis request. New fields default so old clients work."""

    code: str = Field(..., min_length=1, description="Source code to analyze")
    source: str | None = Field(None, description="Client identifier, e.g. mobile")
    language: Literal["cpp"] = Field("cpp", description="Source language: C++ only")
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
    param_names: list[str] = Field(
        default_factory=list, description="Declared parameter names, in order"
    )
    returns: str = Field("", description="Declared return type, as written")
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
    placement: str = Field("inline", description="Placement of comment: inline or before")


class AnchorStats(BaseModel):
    """How many generated comments survived being checked against the code.

    Exposed because it is the honest quality signal for this response:
    ``dropped`` counts comments about lines the user never wrote and
    ``rejected_semantic`` comments the syntax tree refutes, both discarded
    rather than shown.

    ``kept`` is counted, not derived, so it need not equal
    ``proposed - dropped``: anchors are also discarded after repair, and where
    the file was split into chunks the same line may be commented twice and
    kept once.
    """

    proposed: int = 0
    kept: int = 0
    exact: int = Field(0, description="Anchors whose line number was already right")
    relocated: int = Field(0, description="Anchors moved to the line they quoted")
    dropped: int = Field(0, description="Anchors discarded for any reason")
    dropped_punctuation: int = Field(
        0, description="Anchors discarded for describing a line holding only punctuation"
    )
    dropped_numeric: int = Field(
        0, description="Anchors discarded for citing numbers their line does not contain"
    )
    rejected_semantic: int = Field(
        0, description="Anchors discarded for saying something the syntax tree refutes"
    )
    chunks: int = Field(0, description="Pieces the file was split into")


class ChangeAnalysis(BaseModel):
    """Result of comparing an old vs new code version (Phase 4)."""

    added_functions: list[str] = Field(default_factory=list)
    removed_functions: list[str] = Field(default_factory=list)
    modified_functions: list[str] = Field(default_factory=list)
    complexity_delta: int = 0
    complexity_increased: bool = False


class AnalyzeResponse(BaseModel):
    """Combined analysis result; ``/analyze`` exposes only the display fields."""

    # --- Public display fields ---
    input_code: str
    commented_code: str
    explanation: str

    # --- Internal fields (computed, but filtered from public /analyze) ---
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
        "syntax gate, dropped anchors, or suspicious code patterns were detected.",
    )
    review_reasons: list[str] = Field(
        default_factory=list,
        description="Specific reasons why human review is advised.",
    )


class OptimizeRequest(BaseModel):
    """Ask for a faster version of one function."""

    code: str = Field(..., min_length=1, description="Source code to optimize")
    source: str | None = Field(None, description="Client identifier, e.g. mobile")
    language: str = Field("cpp", description="Source language (currently cpp)")
    mode: str = Field("auto", description="Optimization mode: auto | loop | dp")


class ChangeExplanation(BaseModel):
    """One line the rewrite changed, and why, when a check established it."""

    kind: str = Field(..., description="removed | added")
    line: int = Field(
        ...,
        description="1-based: the original for a removal, the rewrite for an addition",
    )
    code: str = Field(..., description="That line verbatim, so the claim can be checked")
    reason: str | None = Field(
        None,
        description="Why, from the compiler/cppcheck/parse-tree checks. Null when "
        "nothing established a reason - the line still changed, but no claim is "
        "made about the motive.",
    )
    rule: str | None = Field(None, description="The check that supplied the reason")


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
    explanation: str = Field("", description="Plain-language explanation of what the code does")
    changes: list[ChangeExplanation] = Field(
        default_factory=list,
        description="What the rewrite changed, line by line. Reasons come from the "
        "deterministic checks, never from the model: it has a plausible reason for "
        "everything and 30% of its descriptions carry a false claim.",
    )
    changes_summary: str = Field(
        "", description="One sentence over the list, or empty when nothing changed"
    )
