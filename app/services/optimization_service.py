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

import logging
import re
from dataclasses import dataclass

from app.core.config import MODEL_BACKEND, RAW_MAX_NEW_TOKENS, RAW_NUM_BEAMS
from app.model_processing import equivalence
from app.schemas.analyze import StaticAnalysis
from app.services.analyzer import analyze_code
from app.services.model_service import generate_text

LOGGER = logging.getLogger(__name__)

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


@dataclass
class OptimizationResult:
    """An optimisation and the evidence for offering it."""

    code: str
    changed: bool = False
    verified: bool = False
    speedup: float = 0.0
    note: str = ""


def optimize_checked(code: str) -> OptimizationResult:
    """Propose a rewrite and only keep it if running it agrees with the original.

    Problem solved: the previous engine's rewrites were never executed, so a
    reformatting and a genuine algorithmic change were indistinguishable, and a
    rewrite that quietly returned different answers would have been served as an
    improvement. Here the proposal is compiled next to the original, both are
    run on the same inputs, and it is discarded unless the outputs match.

    Why the original is returned on any doubt: handing back a user's own code
    is always safe, and a wrong "optimisation" is worse than none.

    :param code: the original C++ source.
    :return: the code to show, plus whether it was changed and checked.
    """
    if MODEL_BACKEND == "qwen_gguf":
        from app.services import qwen_service

        try:
            proposal = qwen_service.optimize(code)
        except qwen_service.LlamaServerUnavailable as exc:
            LOGGER.error("optimizer: llama-server unavailable: %s", exc)
            proposal = ""
    else:
        analysis: StaticAnalysis | None = analyze_code(code)
        prompt = build_optimization_prompt(code, analysis)
        raw = generate_text(prompt, max_new_tokens=RAW_MAX_NEW_TOKENS, num_beams=RAW_NUM_BEAMS)
        proposal = _extract_code(raw)

    if not proposal or proposal.strip() == code.strip():
        return OptimizationResult(code=code, note="no rewrite was offered")

    verdict = equivalence.check(code, proposal)
    if verdict.equivalent:
        return OptimizationResult(
            code=proposal,
            changed=True,
            verified=True,
            speedup=verdict.speedup,
            note=verdict.summary(),
        )
    if not verdict.verified:
        # Could not be checked here - offer it, but say so rather than imply it
        # was proven.
        return OptimizationResult(code=proposal, changed=True, note=verdict.summary())

    LOGGER.warning("optimizer: rewrite rejected (%s)", verdict.summary())
    return OptimizationResult(code=code, note=verdict.summary())


def optimize(code: str) -> str:
    """Return an optimized rewrite of the given C++ code.

    Kept for callers that want a plain string. Prefer ``optimize_checked``,
    which also says whether the rewrite was executed and compared.

    :param code: the original C++ source.
    :return: the optimized code, or the original code with a fallback note.
    """
    result = optimize_checked(code)
    if not result.changed:
        return code + f"\n\n// (optimizer: {result.note}; original kept)"
    return result.code
