"""Review suggestions task (Phase 6).

Problem solved: converting static-analysis facts into actionable review
suggestions is a reasoning task. This service is currently a deterministic rule
engine keyed off ``StaticAnalysis``; a trained review model can later replace
``generate_suggestions`` without changing callers.

Why rule-engine now: the facts already carry clear, mechanical advice
(recursion -> memoize, deep nesting -> flatten, long function -> split), which
does not need a model and is fully explainable.
"""

from __future__ import annotations

from app.schemas.analyze import StaticAnalysis
from app.services.analyzer import LONG_FUNCTION_LINES


def generate_suggestions(analysis: StaticAnalysis) -> list[str]:
    """Build a list of human-readable review suggestions from analysis facts.

    Problem solved: map each detected structural issue to a concrete, ranked
    suggestion the frontend can show. Why one suggestion per issue category:
    avoids noise while covering recursion, nesting, length, docs, duplication,
    complexity and parameter count.

    :param analysis: the static analysis produced by the analyzer.
    :return: a list of suggestion strings (never empty; a "no issues" note when
        clean).
    """
    suggestions: list[str] = []

    if analysis.recursive:
        recursive_names = [f.name for f in analysis.functions if f.recursive]
        target = ", ".join(recursive_names) if recursive_names else "recursive functions"
        suggestions.append(
            f"Recursive logic detected ({target}). Consider memoization or an "
            "iterative version to avoid deep call stacks."
        )

    if analysis.max_nested_loops >= 2:
        suggestions.append(
            f"Nested loops up to depth {analysis.max_nested_loops} found. "
            "Reduce nesting or extract inner loops into helper functions."
        )

    for name in analysis.long_functions:
        suggestions.append(
            f"Function '{name}' is longer than {LONG_FUNCTION_LINES} lines. "
            "Split it into smaller, single-responsibility functions."
        )

    if analysis.missing_comments:
        suggestions.append(
            f"{analysis.missing_comments} function(s) lack inline comments. "
            "Add short comments explaining non-obvious logic."
        )

    if analysis.missing_docs:
        suggestions.append(
            f"{analysis.missing_docs} function(s) lack documentation blocks. "
            "Add a description, parameters and return value."
        )

    if analysis.duplicate_functions:
        suggestions.append(
            "Duplicate function definitions detected: "
            f"{', '.join(analysis.duplicate_functions)}. Consolidate them."
        )

    if analysis.cyclomatic_complexity >= 10:
        suggestions.append(
            f"High cyclomatic complexity ({analysis.cyclomatic_complexity}). "
            "Simplify branching and consider early returns."
        )

    high_params = [f.name for f in analysis.functions if f.params > 4]
    for name in high_params:
        suggestions.append(
            f"Function '{name}' takes many parameters. Group related arguments into a struct."
        )

    if not suggestions:
        suggestions.append("No major structural issues detected by static analysis.")

    return suggestions
