"""Comment generation task (Phase 7).

Problem solved: producing inline-commented C++ is one distinct NLP task. This
service owns the choice between the AI model output and the rule engine, then
formats the result for the editor.

Why one service per task: later a dedicated comment model can replace the
rule-based path without touching the router or any other task.
"""

from __future__ import annotations

from app.model_processing.comment_rules import generate_rule_based_comments, has_meaningful_comments
from app.model_processing.repair import repair_code


def generate(code: str, raw_commented_code: str = "") -> str:
    """Return editor-ready commented C++ code for the given source.

    Problem solved: choose the best available commented code. Why prefer the raw
    model output and only fall back to rules when it is empty: the model produces
    semantic, context-aware comments, and the deterministic rule engine emits
    generic templates that *replace* good comments. Why no reformatting step: the
    raw model output already preserves indentation and inline ``//`` placement
    better than moving every comment to its own line, so we pass it through as-is.

    :param code: the original C++ source.
    :param raw_commented_code: model-produced commented code (may be empty).
    :return: the final commented code string.
    """
    commented = (raw_commented_code or "").strip()

    if has_meaningful_comments(commented):
        return repair_code(commented)

    return generate_rule_based_comments(code.strip())
