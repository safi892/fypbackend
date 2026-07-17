"""Explanation generation task (Phase 9).

Problem solved: turning code into a plain-language explanation is a distinct
NLP task. This service prefers the AI model output and falls back to the rule
engine only when the model text is not meaningful.

Why a dedicated service: a later explanation model can be swapped in behind
``generate`` without changing the router or other tasks.
"""

from __future__ import annotations

from app.model_processing.explanation_rules import (
    generate_rule_based_explanation,
    has_meaningful_explanation,
)


def generate(code: str, raw_explanation: str = "") -> str:
    """Return a natural-language explanation of the given C++ code.

    Problem solved: pick the strongest available explanation. Why fall back to
    rules when the model output is weak: an empty/"null" explanation is worse
    than a deterministic one, so the client always gets readable text.

    :param code: the C++ source to explain.
    :param raw_explanation: model-produced explanation (may be empty).
    :return: the final explanation string.
    """
    explanation = (raw_explanation or "").strip()

    if not has_meaningful_explanation(explanation):
        explanation = generate_rule_based_explanation(code.strip())

    return explanation
