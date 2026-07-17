"""Comment generation task (Phase 7).

Problem solved: producing inline-commented C++ is one distinct NLP task. This
service owns the choice between the AI model output and the rule engine, then
formats the result for the editor.

Why one service per task: later a dedicated comment model can replace the
rule-based path without touching the router or any other task.
"""

from __future__ import annotations

from app.model_processing.code_formatting import format_commented_code_for_editor
from app.model_processing.comment_rules import generate_rule_based_comments, has_meaningful_comments


def generate(code: str, raw_commented_code: str = "") -> str:
    """Return editor-ready commented C++ code for the given source.

    Problem solved: choose the best available commented code. Why prefer model
    output but fall back to rules: the model may return empty/low-value text,
    and we must never hand the client uncommented code when a fallback exists.
    Why format last: the editor expects one consistent ``//`` placement.

    :param code: the original C++ source.
    :param raw_commented_code: model-produced commented code (may be empty).
    :return: the final commented code string.
    """
    commented = (raw_commented_code or "").strip()

    if not commented:
        commented = code.strip()

    if not has_meaningful_comments(commented):
        commented = generate_rule_based_comments(code.strip())

    return format_commented_code_for_editor(commented)
