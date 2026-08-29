"""Explanation generation task (Phase 9).

Problem solved: turning code into a plain-language explanation is a distinct
NLP task. This service prefers the AI model output and falls back to the rule
engine only when the model text is not meaningful.

Why a dedicated service: a later explanation model can be swapped in behind
``generate`` without changing the router or other tasks.
"""

from __future__ import annotations

import re

from app.model_processing.explanation_rules import (
    generate_rule_based_explanation,
    has_meaningful_explanation,
)

_COMPLEXITY_LINE = re.compile(
    r"(?im)^\s*(?:time\s+complexity|space\s+complexity|complexity)\s*:\s*.*(?:\r?\n|$)"
)
_COMPLEXITY_SENTENCE = re.compile(
    r"(?i)(?:^|(?<=[.!?])\s+)[^.\n]*"
    r"(?:time\s+complexity|space\s+complexity|complexity)[^.\n]*"
    r"O\([^)\n]+\)[^.\n]*[.!?]?"
)
_TRAILING_COMPLEXITY_CLAUSE = re.compile(
    r"(?i),?\s*(?:resulting in|leading to|giving|with)\s+[^.\n]*"
    r"(?:O\([^)\n]+\)[^.\n]*(?:time|space|complexity)|"
    r"(?:time|space|complexity)[^.\n]*O\([^)\n]+\))[^.\n]*"
)


def _without_complexity_details(explanation: str) -> str:
    """Remove time/space-cost prose from the public explanation."""
    cleaned = _COMPLEXITY_LINE.sub("", explanation)
    cleaned = _TRAILING_COMPLEXITY_CLAUSE.sub("", cleaned)
    cleaned = _COMPLEXITY_SENTENCE.sub("", cleaned)
    cleaned = re.sub(r"\s+([.,;:])", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def generate(code: str, raw_explanation: str = "") -> str:
    """Return a natural-language explanation of the given C++ code.

    Problem solved: pick the strongest available explanation. Why prefer the raw
    model output and only fall back to rules when it is empty/placeholder: the
    model produces the most specific, name-aware text, and the deterministic
    fallback is a last resort so the client always gets readable text.

    :param code: the C++ source to explain.
    :param raw_explanation: model-produced explanation (may be empty).
    :return: the final explanation string.
    """
    explanation = (raw_explanation or "").strip()

    if not has_meaningful_explanation(explanation):
        explanation = generate_rule_based_explanation(code.strip())

    return _without_complexity_details(explanation)


_GENERIC_EXPLANATION_MARKERS = (
    "performs the following steps",
    "returns a result",
    "processes the given input",
    "processes the given code",
)


def is_generic_explanation(explanation: str, min_words: int = 15) -> bool:
    """Flag an explanation as generic/low-value for the quality gate.

    Problem solved: the quality gate must detect templated or trivial text so
    the inspector (and any caller) can favour the raw model output instead. Why
    the same word floor as before: a real explanation is substantive.

    :param explanation: the explanation text to check.
    :param min_words: minimum word count to be considered substantive.
    :return: ``True`` if the text is too short or uses a banned template phrase.
    """
    normalized = explanation.strip()
    if not normalized:
        return True
    if any(marker in normalized.lower() for marker in _GENERIC_EXPLANATION_MARKERS):
        return True
    return len(normalized.split()) < min_words
