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

import logging
import os
import re
import threading
from dataclasses import dataclass
from dataclasses import field as dataclass_field

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

from app.core.config import (
    FALLBACK_TOKENIZER_PATH,
    MODEL_BACKEND,
    MODEL_PATH,
    PROMPT_PREFIX,
    RAW_DO_SAMPLE,
    RAW_MAX_NEW_TOKENS,
    RAW_NUM_BEAMS,
    RAW_REPETITION_PENALTY,
    RAW_TEMPERATURE,
    RAW_TOP_P,
    TOKENIZER_PATH,
    TORCH_COMPILE,
    TORCH_THREADS,
    USE_MPS,
)
from app.model_processing.code_formatting import clean_duplicate_code
from app.schemas.analyze import StaticAnalysis

LOGGER = logging.getLogger(__name__)

# Guards one-time model load across threads.
_MODEL_LOCK = threading.Lock()
_MODEL_CACHE: tuple[AutoTokenizer, AutoModelForSeq2SeqLM, torch.device] | None = None


@dataclass
class RawModelOutput:
    """Raw model output split into sections (either may be empty).

    ``line_comments`` and ``verified`` are populated only by backends that
    anchor their comments to real lines. The CodeT5 path rewrites the source,
    so it can offer neither.
    """

    commented_code: str = ""
    explanation: str = ""
    raw_text: str = ""
    #: ``{"line", "code", "comment"}`` records already checked against the input.
    line_comments: list[dict] = dataclass_field(default_factory=list)
    #: How many anchors were correct, corrected, or discarded as invented.
    anchor_stats: dict = dataclass_field(default_factory=dict)
    #: True when ``commented_code`` is the caller's own source with comments
    #: attached, rather than a model's reconstruction of it. Downstream repair
    #: and rule-based fallbacks must not touch it when this is set.
    verified: bool = False


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
        r"###\s*(COMMENTED CODE|LOGIC ANALYSIS|ISSUES|VERIFICATION|EXPLANATION)\s*\n",
        re.IGNORECASE,
    )
    matches = list(section_pattern.finditer(normalized))

    if matches:
        # Everything before the first header is the model's commented code. The
        # model sometimes emits a "### VERIFICATION"/"### EXPLANATION" trailer
        # without a "### COMMENTED CODE" header, so we must not discard the
        # pre-header text (that is the real comment).
        first_start = matches[0].start()
        commented_code = normalized[:first_start].strip()
        explanation = ""
        for index, match in enumerate(matches):
            title = match.group(1).upper()
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
            if title == "EXPLANATION":
                explanation = normalized[start:end].strip()
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

    if not explanation:
        explanation_match = re.search(r"\bEXPLANATION\s*:\s*", normalized, re.IGNORECASE)
        if explanation_match:
            explanation = normalized[explanation_match.end() :].strip()

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


def _configure_threads() -> int:
    """Set torch intra-op thread count for CPU inference.

    Problem solved: torch defaults to all cores, which can oversubscribe and slow
    down a single inference on multi-core CPUs. Why cap at 8: beyond that,
    contention outweighs parallelism for a 220M model. Why configurable: operators
    can tune ``TORCH_THREADS`` for their exact CPU.

    :return: the number of threads torch will use.
    """
    if TORCH_THREADS > 0:
        threads = TORCH_THREADS
    else:
        threads = min(os.cpu_count() or 4, 8)
    torch.set_num_threads(threads)
    return threads


def _select_device() -> torch.device:
    """Pick the fastest available torch backend.

    Problem solved: inference speed depends heavily on the device. Why cuda first:
    a real NVIDIA GPU is the biggest speed win. Why MPS is opt-in: on torch 2.0.1
    the MPS beam-decode path is dramatically slower than CPU for this seq2seq
    model, so we only use it when ``USE_MPS`` is explicitly set. Why a helper: the
    choice must be made once at load time.

    :return: the torch device to run the model on.
    """
    if torch.cuda.is_available():
        return torch.device("cuda")
    if USE_MPS and hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def active_device() -> str:
    """Return the device string the cached model runs on.

    Problem solved: operators need to confirm whether inference uses a GPU/MPS
    backend (the main speed lever) without loading the model manually. Why a
    public helper: the inspector scripts call it to print the active backend.

    :return: the device type, e.g. ``"cuda"``, ``"mps"`` or ``"cpu"``.
    """
    _, _, device = _load_model()
    return str(device)


def _load_tokenizer_fallback(original_exc: Exception) -> AutoTokenizer:
    """Load the default checkpoint's tokenizer after the chosen one fails.

    Problem solved: some fine-tune exports (e.g. ``checkpoint_best_updated``) ship a
    corrupted ``tokenizer.json``. Because every checkpoint is the same CodeT5p base,
    the default tokenizer is a safe substitute. Why a warning: the operator should know
    a fallback was used so they can repair the export.

    :param original_exc: the exception from the first tokenizer load attempt.
    :return: a tokenizer loaded from ``FALLBACK_TOKENIZER_PATH``.
    :raises RuntimeError: if even the fallback tokenizer cannot load.
    """
    import warnings

    warnings.warn(
        f"Tokenizer at {TOKENIZER_PATH} failed to load ({original_exc}); "
        f"falling back to default tokenizer at {FALLBACK_TOKENIZER_PATH}.",
        stacklevel=2,
    )
    try:
        return AutoTokenizer.from_pretrained(FALLBACK_TOKENIZER_PATH, use_fast=True)
    except Exception as exc:
        message = (
            "Fallback tokenizer load also failed. Ensure the default checkpoint "
            f"{FALLBACK_TOKENIZER_PATH} is intact. Error: {exc}"
        )
        raise RuntimeError(message) from exc


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

        threads = _configure_threads()

        try:
            tokenizer = AutoTokenizer.from_pretrained(TOKENIZER_PATH, use_fast=True)
        except Exception as exc:
            if TOKENIZER_PATH == FALLBACK_TOKENIZER_PATH:
                message = (
                    "Tokenizer load failed. Ensure tokenizer.json (or vocab.json + merges.txt, "
                    "or spiece.model) matches the model and is not corrupted. "
                    f"Tokenizer source: {TOKENIZER_PATH}. Error: {exc}"
                )
                raise RuntimeError(message) from exc
            tokenizer = _load_tokenizer_fallback(exc)

        model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_PATH)
        device = _select_device()
        model.to(device)
        model.eval()
        if TORCH_COMPILE:
            model = torch.compile(model)

        _MODEL_CACHE = (tokenizer, model, device)
        print(f"[model] loaded on {device} (threads={threads})")
        return _MODEL_CACHE


def generate_text(
    prompt: str, max_new_tokens: int = RAW_MAX_NEW_TOKENS, num_beams: int = RAW_NUM_BEAMS
) -> str:
    """Run one model generation on an arbitrary prompt and return decoded text.

    Problem solved: task services like the optimizer need to prompt the model
    with a custom instruction (not the comments/explanation template), but the
    model load + generation logic must stay in this single engine. Why a public
    helper: keeps ``run_model`` (comments/explanation) and any future task
    sharing one cached model and one generation path.

    :param prompt: the full prompt to send to the model.
    :param max_new_tokens: max generated tokens (output only).
    :param num_beams: beam-search width.
    :return: the decoded output string.
    """
    tokenizer, model, device = _load_model()
    return _generate_output(
        tokenizer,
        model,
        device,
        prompt,
        generation_kwargs={
            "max_new_tokens": max_new_tokens,
            "num_beams": num_beams,
            "early_stopping": True,
            "no_repeat_ngram_size": 3,
            "repetition_penalty": 1.2,
        },
    )


def run_model(code: str, analysis: StaticAnalysis | None = None) -> RawModelOutput:
    """Run the configured engine and return the raw commented-code/explanation.

    Problem solved: this stays the single AI entry point while which model
    answers becomes configuration. ``MODEL_BACKEND=qwen_gguf`` routes to the
    Qwen checkpoint served by llama-server; anything else keeps the original
    CodeT5 path. Why a switch rather than a replacement: the two can be
    compared on identical requests, and a bad deploy is undone by one
    environment variable instead of a rollback.

    Why the Qwen path falls back rather than failing: llama-server is a
    separate process, and a mobile client should get a degraded answer instead
    of an error when it is not running.

    Why the fallback's own failure is not the error reported: on a machine that
    has only the Qwen model, falling back reaches a CodeT5 checkpoint that is
    not installed, and "Model path not found: .../checkpoint_best" names
    something the operator did not choose and cannot act on. The cause is that
    llama-server is down, so that is what gets raised.

    :param code: the C++ source to analyze.
    :param analysis: static facts, passed through to the engine that wants them.
    :return: a ``RawModelOutput`` (either section may be empty).
    """
    if MODEL_BACKEND == "qwen_gguf":
        from app.services import qwen_service

        try:
            result = qwen_service.run(code)
        except qwen_service.LlamaServerUnavailable as exc:
            LOGGER.error("qwen backend unavailable, trying codet5: %s", exc)
            try:
                return _run_codet5(code, analysis)
            except (FileNotFoundError, RuntimeError) as fallback_error:
                LOGGER.error("codet5 fallback also unavailable: %s", fallback_error)
                raise RuntimeError(str(exc)) from exc
        else:
            return RawModelOutput(
                commented_code=result.commented_code,
                explanation=result.explanation,
                raw_text=result.raw_text,
                line_comments=[
                    {"line": a.line, "code": a.code, "comment": a.comment} for a in result.anchors
                ],
                anchor_stats={
                    "kept": result.report.kept,
                    "proposed": result.report.total,
                    "exact": result.report.exact,
                    "relocated": result.report.relocated,
                    "dropped": result.report.dropped,
                    "chunks": result.chunks,
                },
                verified=True,
            )
    return _run_codet5(code, analysis)


def _run_codet5(code: str, analysis: StaticAnalysis | None = None) -> RawModelOutput:
    """Run CodeT5 on the code and return the raw commented-code/explanation.

    Problem solved: this is the single AI entry point. Why prepend the training
    prompt prefix ``"comment and explain: "``: without it the model emits only a
    commented function plus a VERIFICATION trailer and never reaches the
    ``### EXPLANATION`` section, so the explanation service falls back to rules.
    The prefix is exactly what the checkpoint was fine-tuned with, so it elicits
    the full three-section output. Why beam search + a gentle repetition penalty:
    greedy decoding hallucinated identifiers (``elem[mid]``, ``a[left]``) and
    dropped the explanation; matching the training run (num_beams=4,
    repetition_penalty~1.05) produces faithful code and a real explanation. Why
    ``do_sample`` is off by default: keeps the API deterministic while matching
    the training quality.

    :param code: the C++ source to analyze.
    :param analysis: accepted for API compatibility; not used in the prompt
        (the fixed training prefix already shapes the output).
    :return: a ``RawModelOutput`` (either section may be empty).
    """
    tokenizer, model, device = _load_model()

    prompt = f"{PROMPT_PREFIX}{code}"

    generation_kwargs: dict[str, object] = {
        "max_new_tokens": RAW_MAX_NEW_TOKENS,
        "num_beams": RAW_NUM_BEAMS,
        "early_stopping": True,
        "repetition_penalty": RAW_REPETITION_PENALTY,
        "do_sample": RAW_DO_SAMPLE,
    }
    if RAW_DO_SAMPLE:
        generation_kwargs["temperature"] = RAW_TEMPERATURE
        generation_kwargs["top_p"] = RAW_TOP_P

    full_output = _generate_output(
        tokenizer,
        model,
        device,
        prompt,
        generation_kwargs=generation_kwargs,
    )

    parsed = _parse_sections(full_output)
    return RawModelOutput(
        commented_code=parsed.commented_code,
        explanation=parsed.explanation,
        raw_text=full_output,
    )
