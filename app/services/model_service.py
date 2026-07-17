"""CodeT5 inference engine (shared AI backend).

Problem solved: every generated output (comments + explanation) comes from one
trained seq2seq model. To keep a single model load and a single code path, this
module *only* runs the model and splits its raw output into sections. It does
NOT apply rule-based fallbacks or formatting — those belong to the task-specific
services (``comment_service``, ``explanation_service``) that consume this output.

Why this separation: a later, dedicated model can replace ``run_model`` without
touching any caller, and the raw output stays testable in isolation.
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

from app.core.config import (
    MODEL_PATH,
    PROMPT_MAX_LENGTH,
    PROMPT_NUM_BEAMS,
    RAW_MAX_LENGTH,
    RAW_NUM_BEAMS,
    TOKENIZER_PATH,
)
from app.model_processing.code_formatting import clean_duplicate_code
from app.schemas.analyze import StaticAnalysis

# Guards one-time model load across threads.
_MODEL_LOCK = threading.Lock()
_MODEL_CACHE: tuple[AutoTokenizer, AutoModelForSeq2SeqLM, torch.device] | None = None


@dataclass
class RawModelOutput:
    """Raw model output split into sections (either may be empty)."""

    commented_code: str = ""
    explanation: str = ""


def _facts_block(analysis: StaticAnalysis | None) -> str:
    """Render analyzer facts as a prompt preamble for the model.

    Problem solved: feeding the model explicit ground-truth facts (instead of
    letting it rediscover them) improves suggestion accuracy and lowers
    inference cost. Why only a few key facts: keep the prompt short so the
    model focuses on reasoning, not on re-parsing structure.

    :param analysis: the static analysis, or ``None`` when not computed.
    :return: a multi-line facts block, or ``""`` when no analysis exists.
    """
    if analysis is None:
        return ""
    facts: list[str] = [
        f"- Functions: {analysis.function_count}",
        f"- Recursive: {analysis.recursive}",
        f"- Max nested loops: {analysis.max_nested_loops}",
        f"- Cyclomatic complexity: {analysis.cyclomatic_complexity}",
    ]
    if analysis.long_functions:
        facts.append(f"- Long functions: {', '.join(analysis.long_functions)}")
    if analysis.missing_comments:
        facts.append(f"- Functions missing comments: {analysis.missing_comments}")
    return "\nSTATIC ANALYSIS FACTS (ground truth):\n" + "\n".join(facts) + "\n"


def build_prompt(code: str, analysis: StaticAnalysis | None = None) -> str:
    """Assemble the CodeT5 prompt from source code plus analyzer facts.

    Problem solved: the model performs best with an explicit instruction
    template (comment rules + output format). Why inject facts here: the router
    passes the same structure every time, so formatting lives with the engine.

    :param code: the C++ source to review.
    :param analysis: optional static analysis to embed as ground-truth facts.
    :return: the complete prompt string for the model.
    """
    facts = _facts_block(analysis)
    return f"""
You are an expert C++ code reviewer.
{facts}
Analyze the following code strictly based on LOGIC, not function or variable names.

INSTRUCTIONS:
1. First, explain what each condition or expression actually checks.
2. Then describe what the function really does.
3. If the logic contradicts the function name, report it as an issue.
4. Add clear inline comments to the code.
5. Be precise and avoid generic explanations.

COMMENT RULES:
- Comment important declarations and initializations, not just loops and if statements.
- Use context-aware comments that explain why a value is stored or checked.
- Cover common edge cases such as empty input, null pointers, first/last
  index setup, and early returns.
- Keep comments short and natural. Avoid repeating the code word-for-word.

OUTPUT FORMAT:

### COMMENTED CODE
<code with inline comments>


### EXPLANATION
<final clean summary>

CODE:
{code}
"""


def _looks_like_prompt_echo(output: str) -> bool:
    """Detect when the model merely echoed the prompt template back.

    Problem solved: CodeT5 sometimes returns the literal placeholder text
    ("<code with inline comments>") instead of real output. Why this matters:
    such output is useless and must be discarded so the caller uses its
    rule-engine fallback.

    :param output: the raw model text.
    :return: ``True`` if the output looks like a template echo.
    """
    markers = (
        "<code with inline comments>",
        "<step-by-step explanation",
        "<final clean summary>",
        "OUTPUT FORMAT",
    )
    return any(marker in output for marker in markers)


def _parse_sections(output: str) -> RawModelOutput:
    """Split raw model text into commented-code and explanation sections.

    Problem solved: the model emits a few section headers; we normalise them
    into a typed ``RawModelOutput``. Why multiple fallback strategies: different
    checkpoints emit slightly different separators, so we try the known formats
    in order before falling back to "all code".

    :param output: the raw decoded model output.
    :return: a ``RawModelOutput`` with whatever sections were found.
    """
    cleaned_output = clean_duplicate_code(output).strip()
    normalized = cleaned_output.replace("\r\n", "\n")

    commented_code = ""
    explanation = ""

    section_pattern = re.compile(
        r"###\s*(COMMENTED CODE|LOGIC ANALYSIS|ISSUES|EXPLANATION)\s*\n",
        re.IGNORECASE,
    )
    matches = list(section_pattern.finditer(normalized))

    if matches:
        sections: dict[str, str] = {}
        for index, match in enumerate(matches):
            title = match.group(1).upper()
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
            sections[title] = normalized[start:end].strip()

        commented_code = sections.get("COMMENTED CODE", "")
        explanation = sections.get("EXPLANATION", "")
    elif "===EXPLANATION===" in normalized:
        commented_code, explanation = normalized.split("===EXPLANATION===", 1)
        commented_code = commented_code.strip()
        explanation = explanation.strip()
    else:
        explanation_match = re.search(r"\bEXPLANATION\s*:\s*", normalized, re.IGNORECASE)
        if explanation_match:
            commented_code = normalized[: explanation_match.start()].strip()
            explanation = normalized[explanation_match.end() :].strip()
        else:
            commented_code = normalized

    return RawModelOutput(commented_code=commented_code, explanation=explanation)


def _generate_output(
    tokenizer: AutoTokenizer,
    model: AutoModelForSeq2SeqLM,
    device: torch.device,
    text: str,
    generation_kwargs: dict[str, object],
) -> str:
    """Run one model generation and decode the output ids to text.

    Problem solved: centralises tokenization + ``model.generate`` + decode so
    ``run_model`` only decides *which* prompt to send. Why ``torch.no_grad()``:
    inference needs no gradients, saving memory and compute.

    :param tokenizer: the loaded tokenizer.
    :param model: the loaded seq2seq model.
    :param device: the torch device the model lives on.
    :param text: the prompt to encode.
    :param generation_kwargs: beam/length options forwarded to ``generate``.
    :return: the decoded output string.
    """
    inputs = tokenizer(
        text,
        return_tensors="pt",
        max_length=512,
        truncation=True,
    ).to(device)

    with torch.no_grad():
        output_ids = model.generate(
            **inputs,
            **generation_kwargs,
        )

    return str(tokenizer.decode(output_ids[0], skip_special_tokens=True))


def _load_model() -> tuple[AutoTokenizer, AutoModelForSeq2SeqLM, torch.device]:
    """Lazily load and cache the tokenizer + model on first use.

    Problem solved: loading a torch model is slow and memory heavy, so it must
    happen once. Why a lock + double-check: concurrent requests must not each
    load their own copy. Why explicit error messages: a missing/corrupt model
    directory must fail clearly rather than with an opaque stack trace.

    :return: a cached ``(tokenizer, model, device)`` tuple.
    :raises FileNotFoundError: if the model/tokenizer directory is absent.
    :raises RuntimeError: if the tokenizer/model fails to load.
    """
    global _MODEL_CACHE
    if _MODEL_CACHE is not None:
        return _MODEL_CACHE

    with _MODEL_LOCK:
        if _MODEL_CACHE is not None:
            return _MODEL_CACHE

        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(f"Model path not found: {MODEL_PATH}")
        if not os.path.isdir(MODEL_PATH):
            raise FileNotFoundError(f"Model directory not found: {MODEL_PATH}")

        try:
            tokenizer = AutoTokenizer.from_pretrained(TOKENIZER_PATH, use_fast=True)
        except Exception as exc:
            message = (
                "Tokenizer load failed. Ensure tokenizer.json (or vocab.json + merges.txt, "
                "or spiece.model) matches the model and is not corrupted. "
                f"Tokenizer source: {TOKENIZER_PATH}. Error: {exc}"
            )
            raise RuntimeError(message) from exc

        model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_PATH)
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model.to(device)
        model.eval()

        _MODEL_CACHE = (tokenizer, model, device)
        return _MODEL_CACHE


def run_model(code: str, analysis: StaticAnalysis | None = None) -> RawModelOutput:
    """Run CodeT5 on the code and return the raw commented-code/explanation.

    Problem solved: this is the single AI entry point. Why two strategies: if
    the model already emitted sections for the raw code we use them; otherwise
    we send the richer fact-augmented prompt. Why detect a prompt echo: a bad
    output yields an empty ``RawModelOutput`` so the caller falls back cleanly.

    :param code: the C++ source to analyze.
    :param analysis: optional static analysis injected into the prompt.
    :return: a ``RawModelOutput`` (either section may be empty).
    """
    tokenizer, model, device = _load_model()

    full_output = _generate_output(
        tokenizer,
        model,
        device,
        code,
        generation_kwargs={
            "max_length": RAW_MAX_LENGTH,
            "num_beams": RAW_NUM_BEAMS,
        },
    )

    if "###" in full_output:
        return _parse_sections(full_output)

    if "===EXPLANATION===" in full_output or full_output.strip() != code.strip():
        return _parse_sections(full_output)

    prompt = build_prompt(code, analysis)
    full_output = _generate_output(
        tokenizer,
        model,
        device,
        prompt,
        generation_kwargs={
            "max_length": PROMPT_MAX_LENGTH,
            "num_beams": PROMPT_NUM_BEAMS,
            "no_repeat_ngram_size": 3,
            "early_stopping": True,
        },
    )

    if _looks_like_prompt_echo(full_output):
        return RawModelOutput(commented_code="", explanation="")

    return _parse_sections(full_output)
