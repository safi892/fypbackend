"""Code-optimization task (refactor / recursion-to-loop, etc.).

Problem solved: a distinct NLP task that asks the model to return an *optimized
rewrite* of the code (e.g. convert recursion to iteration, flatten nested loops,
extract helpers). This is separate from commenting/explaining/reviewing, so it
is its own service that can later be backed by a dedicated optimization model.

Why a rule-engine echo fallback: if the model returns no usable code, we must
never hand back garbage — we return the original code plus a note so the caller
always gets something safe.
"""

from __future__ import annotations

import re

from app.core.config import RAW_MAX_NEW_TOKENS, RAW_NUM_BEAMS
from app.schemas.analyze import StaticAnalysis
from app.services.analyzer import analyze_code
from app.services.model_service import generate_text

_OPT_PROMPT = """You are a C++ optimization expert.
Rewrite the code below to be more efficient and readable.
Rules:
- Convert direct recursion to an equivalent iterative loop when safe.
- Reduce unnecessary nesting.
- Keep the same behaviour and function signature.
- Output ONLY the optimized C++ code, no explanations, no markdown fences.

{facts}CODE:
{code}
"""


def build_optimization_prompt(code: str, analysis: StaticAnalysis | None = None) -> str:
    """Assemble the optimization prompt for the model.

    Problem solved: the optimizer needs a strict "output only code" instruction
    so the parsed result is usable source, not prose. Why inject a fact (e.g.
    "currently recursive"): it steers the model toward the right rewrite without
    the model re-deriving structure. Why no markdown: easier to extract code.

    :param code: the original C++ source.
    :param analysis: optional static analysis used to add a targeted hint.
    :return: the optimization prompt string.
    """
    facts = ""
    if analysis is not None and analysis.recursive:
        facts = "The function is currently recursive; prefer an equivalent iterative loop.\n"
    return _OPT_PROMPT.format(code=code, facts=facts)


def _extract_code(output: str) -> str:
    """Pull the C++ source out of the raw model output.

    Problem solved: the model may wrap code in ```cpp fences or add stray text;
    we strip fences and keep the largest code-like block. Why strip fences: the
    prompt asked for plain code but models often still add them.

    :param output: the raw decoded model text.
    :return: the cleaned candidate optimized code (may be empty).
    """
    text = output.strip()
    fence = re.search(r"```(?:cpp)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    # Drop a leading "CODE:" style label if the model added one.
    text = re.sub(r"^(CODE|C\+\+):\s*", "", text, flags=re.IGNORECASE).strip()
    # Keep only if it still looks like C++ (has a brace or semicolon).
    if text and ("{" in text or ";" in text or "(" in text):
        return text
    return ""


def optimize(code: str) -> str:
    """Return an optimized rewrite of the given C++ code.

    Problem solved: single entry point for the optimization task. Why fall back
    to the original code with a note: a weak/empty model output must not destroy
    the user's code — we always return something compilable.

    :param code: the original C++ source.
    :return: the optimized code, or the original code with a fallback note.
    """
    analysis: StaticAnalysis | None = analyze_code(code)
    prompt = build_optimization_prompt(code, analysis)
    raw = generate_text(prompt, max_new_tokens=RAW_MAX_NEW_TOKENS, num_beams=RAW_NUM_BEAMS)
    optimized = _extract_code(raw)

    if not optimized:
        return code + "\n\n// (optimizer: model returned no usable rewrite; original kept)"
    return optimized
