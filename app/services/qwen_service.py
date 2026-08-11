"""Qwen2.5-Coder backend, served by llama-server over HTTP.

Problem solved: the replacement for the CodeT5 engine. It answers the same
``run_model`` question and returns the same ``RawModelOutput``, so the router,
the services and the mobile contract are untouched.

Why HTTP to llama-server rather than loading the model in-process: the quantised
model is a gigabyte that must be loaded once and reused, which does not fit a
worker that may be forked or restarted. It also keeps ``torch`` out of this path
entirely — the backend pins torch 2.0.1 for CodeT5, and nothing here needs it.
Measured on CPU, the quantised server answers at roughly 17 tokens/second
against 2 for the unquantised model in-process.

Why the file is split before being sent: the model was trained on functions of
about fifteen lines and answers those well; a whole file is neither a shape it
has seen nor one that fits its context. Splitting on syntax boundaries keeps
every request the shape it handles, and the answers are stitched back into file
coordinates afterwards.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

from app.core.config import (
    LLAMA_CHUNK_TOKENS,
    LLAMA_MAX_NEW_TOKENS,
    LLAMA_MODEL_PATH,
    LLAMA_SERVER_URL,
    LLAMA_TIMEOUT,
)
from app.model_processing.anchors import Anchor, AnchorReport, render_commented_code, repair_anchors
from app.parsers.cpp_chunking import Chunk, chunk_code

LOGGER = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a senior C++ code review assistant. Produce accurate, structured, "
    "actionable review output for the given source code."
)

#: Instruction text per task. Kept verbatim from the training prompts, because
#: the model answers the wording it was trained on and drifts on paraphrases.
TASK_INSTRUCTIONS = {
    "line_comments": (
        'Line-by-line comments (array of {"line", "code", "comment"} objects, where "line" is '
        'the 1-based line number and "code" is that line copied verbatim from the input. Never '
        "reformat or rewrite the code, and only comment lines that carry meaning)"
    ),
    "explanation": "Explanation",
    "optimize": (
        "Improved code (if this function recomputes the same subproblems, rewrite it so each is "
        "solved once, using memoisation or a dynamic-programming table. Keep the signature and "
        "the results identical, and size any table from the arguments rather than a fixed "
        "constant. If there are no overlapping subproblems, return the code unchanged)"
    ),
}

FIELD_FOR_TASK = {
    "line_comments": "line_comments",
    "explanation": "explanation",
    "optimize": "improved_code",
}


class LlamaServerUnavailable(RuntimeError):
    """Raised when llama-server cannot be reached, so the caller can fall back."""


@dataclass
class QwenOutput:
    """Everything the Qwen path produced for one request."""

    commented_code: str = ""
    explanation: str = ""
    anchors: list[Anchor] = None  # type: ignore[assignment]
    report: AnchorReport = None  # type: ignore[assignment]
    chunks: int = 0
    raw_text: str = ""

    def __post_init__(self) -> None:
        if self.anchors is None:
            self.anchors = []
        if self.report is None:
            self.report = AnchorReport()


def build_prompt(code: str, task: str) -> str:
    """Render the chat prompt the checkpoint was trained with.

    Written out rather than produced by a tokenizer's chat template so this
    module needs no ``transformers`` import; the markers are fixed by the Qwen
    template and do not vary per request.
    """
    instruction = (
        "Analyze the following C++ code.\n\nLanguage: cpp\n\n"
        f"Generate:\n- {TASK_INSTRUCTIONS[task]}\n\n"
        "Return a single JSON object using the requested field names."
    )
    return (
        f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n"
        f"<|im_start|>user\n{instruction}\n\n### Code\n\n```cpp\n{code}\n```<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )


def complete(prompt: str, max_new_tokens: int | None = None) -> str:
    """Send one completion request to llama-server.

    :param prompt: the fully rendered prompt.
    :param max_new_tokens: answer budget; too small truncates the JSON.
    :return: the generated text.
    :raises LlamaServerUnavailable: when the server cannot be reached.
    """
    payload = json.dumps(
        {
            "prompt": prompt,
            "n_predict": max_new_tokens or LLAMA_MAX_NEW_TOKENS,
            "temperature": 0,
            "cache_prompt": False,
        }
    ).encode()
    request = urllib.request.Request(
        f"{LLAMA_SERVER_URL}/completion",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=LLAMA_TIMEOUT) as response:
            return json.load(response).get("content", "")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # Name the fix, not just the failure: this is the error a teammate hits
        # when they start the API without starting the model server.
        raise LlamaServerUnavailable(
            f"llama-server at {LLAMA_SERVER_URL} is not answering ({exc}). "
            f"Start it with ./run_model_server.sh --bg (model: {LLAMA_MODEL_PATH})."
        ) from exc


def _field(text: str, task: str) -> object:
    """Pull the requested field out of the model's JSON, or return a default."""
    try:
        parsed = json.loads(text) or {}
    except json.JSONDecodeError:
        LOGGER.warning("qwen backend: unparseable JSON for task %s (%d chars)", task, len(text))
        return [] if task == "line_comments" else ""
    return parsed.get(FIELD_FOR_TASK[task], [] if task == "line_comments" else "")


def annotate(code: str) -> tuple[list[Anchor], AnchorReport, int]:
    """Comment every chunk of ``code`` and stitch the results into file lines.

    Anchors are repaired inside the chunk the model saw, then shifted. Doing it
    in that order matters: a line such as ``return 0;`` occurs in many
    functions, and searching the whole file for it would let a comment written
    about one attach to another.

    :param code: the submitted source.
    :return: ``(anchors, report, chunk_count)`` in whole-file coordinates.
    """
    chunks: list[Chunk] = chunk_code(code, max_tokens=LLAMA_CHUNK_TOKENS)
    combined = AnchorReport()
    anchors: list[Anchor] = []
    claimed: set[int] = set()

    for chunk in chunks:
        raw = _field(complete(build_prompt(chunk.text, "line_comments")), "line_comments")
        report = repair_anchors(chunk.text, raw if isinstance(raw, list) else [])
        combined.exact += report.exact
        combined.relocated += report.relocated
        combined.dropped += report.dropped
        for anchor in report.anchors:
            line = anchor.line + chunk.start_line - 1
            if line in claimed:
                continue
            claimed.add(line)
            anchors.append(Anchor(line=line, code=anchor.code, comment=anchor.comment))

    anchors.sort(key=lambda anchor: anchor.line)
    # Final gate: whatever leaves here matches the user's file, whatever the
    # chunking did.
    lines = [line.strip() for line in code.split("\n")]
    anchors = [
        anchor
        for anchor in anchors
        if 1 <= anchor.line <= len(lines) and lines[anchor.line - 1] == anchor.code.strip()
    ]
    combined.anchors = anchors
    return anchors, combined, len(chunks)


def explain(code: str) -> str:
    """Generate the prose explanation for the whole submission."""
    value = _field(complete(build_prompt(code, "explanation")), "explanation")
    return value if isinstance(value, str) else ""


def optimize(code: str) -> str:
    """Generate an optimised rewrite, or an empty string when none is offered."""
    value = _field(complete(build_prompt(code, "optimize")), "optimize")
    return value if isinstance(value, str) else ""


def run(code: str) -> QwenOutput:
    """Produce commented code and an explanation for one submission.

    :param code: the C++ source to analyze.
    :return: a ``QwenOutput``; ``commented_code`` is the user's own source with
        verified comments attached, never a regenerated copy.
    """
    anchors, report, chunks = annotate(code)
    explanation = explain(code)
    LOGGER.info(
        "qwen backend: %d chunks, %d/%d anchors kept (%d exact, %d relocated, %d dropped)",
        chunks, report.kept, report.total, report.exact, report.relocated, report.dropped,
    )
    return QwenOutput(
        commented_code=render_commented_code(code, anchors),
        explanation=explanation,
        anchors=anchors,
        report=report,
        chunks=chunks,
    )
