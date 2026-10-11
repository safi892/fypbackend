"""Documentation generation task (Phase 8).

Problem solved: producing per-function documentation (description / parameters
/ returns) is a distinct NLP task. This service is currently a deterministic
rule engine driven by analyzer facts; a trained documentation model can replace
``generate`` later without changing callers.

Why rule-engine now: function signatures already tell us the name, parameter
count and structural traits, which is enough for a baseline doc block.
"""

from __future__ import annotations

from app.schemas.analyze import DocEntry, FunctionInfo, StaticAnalysis


def generate(analysis: StaticAnalysis) -> list[DocEntry]:
    """Build one documentation block per analysed function.

    Problem solved: give the frontend ready-to-render docs. Why skip
    ``<anonymous>``: unnamed constructs cannot be documented meaningfully.

    :param analysis: the static analysis whose functions to document.
    :return: a list of ``DocEntry`` objects (one per named function).
    """
    docs: list[DocEntry] = []
    for fn in analysis.functions:
        if fn.name == "<anonymous>":
            continue
        # Prefer the names the author wrote. The positional fallback stays for
        # analyses produced before `param_names` existed and for the regex
        # parser, which cannot see into a parameter list.
        parameters = fn.param_names or [f"param{i + 1}" for i in range(fn.params)]
        description = _describe(fn)
        docs.append(
            DocEntry(
                function=fn.name,
                description=description,
                parameters=parameters,
                returns=fn.returns or "See function signature for the return type.",
            )
        )
    return docs


def _describe(fn: FunctionInfo) -> str:
    """Compose a one-line description from a function's structural traits.

    Problem solved: derive a readable summary without a model by joining the
    traits the analyzer already computed (recursion, loop depth).

    :param fn: the function facts to summarise.
    :return: a human-readable description sentence.
    """
    parts = [f"Function '{fn.name}'"]
    if fn.recursive:
        parts.append("uses recursion")
    if fn.max_loop_depth >= 1:
        parts.append(f"contains loops (depth {fn.max_loop_depth})")
    if len(parts) == 1:
        parts.append("performs a computation")
    return " ".join(parts) + "."
