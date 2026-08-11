"""Tests for the Qwen backend: anchoring, chunking and backend selection.

None of these need llama-server or a model. The HTTP call is the only part that
does, and it is stubbed, so the logic around it stays testable in CI.
"""

from __future__ import annotations

import pytest

from app.model_processing.anchors import render_commented_code, repair_anchors
from app.parsers.cpp_chunking import chunk_code
from app.services import model_service, qwen_service

CODE = """int add(int a, int b)
{
  int total = a + b;
  return total;
}"""


# --- anchoring ---------------------------------------------------------------- #


def test_an_anchor_on_the_right_line_is_kept_as_is():
    report = repair_anchors(CODE, [{"line": 3, "code": "int total = a + b;", "comment": "sum"}])

    assert report.exact == 1 and report.relocated == 0 and report.dropped == 0
    assert report.anchors[0].line == 3


def test_a_miscounted_anchor_is_moved_to_the_line_it_quotes():
    """Models miscount lines far more often than they misquote them."""
    report = repair_anchors(CODE, [{"line": 1, "code": "return total;", "comment": "result"}])

    assert report.relocated == 1
    assert report.anchors[0].line == 4


def test_a_comment_about_a_line_that_is_not_there_is_dropped():
    report = repair_anchors(CODE, [{"line": 3, "code": "launch_missiles();", "comment": "no"}])

    assert report.anchors == [] and report.dropped == 1


def test_repeated_lines_attach_to_the_occurrence_nearest_the_claim():
    code = "int f()\n{\n  return 0;\n}\nint g()\n{\n  return 0;\n}"

    report = repair_anchors(code, [{"line": 7, "code": "return 0;", "comment": "from g"}])

    assert report.anchors[0].line == 7


def test_malformed_entries_do_not_raise():
    report = repair_anchors(CODE, [None, {}, {"line": 3}, {"code": "x", "comment": ""}])

    assert report.anchors == [] and report.dropped == 4


# --- the mobile contract ------------------------------------------------------- #


def test_commented_code_returns_the_users_own_source_verbatim():
    """The point of anchoring: the source is never regenerated, only annotated."""
    raw = [{"line": 3, "code": "int total = a + b;", "comment": "sum"}]
    anchors = repair_anchors(CODE, raw).anchors

    rendered = render_commented_code(CODE, anchors)

    original_lines = CODE.split("\n")
    for index, line in enumerate(rendered.split("\n")):
        assert line.split("  //")[0] == original_lines[index]


def test_rendering_adds_the_comment_to_the_right_line():
    raw = [{"line": 4, "code": "return total;", "comment": "hand back"}]
    anchors = repair_anchors(CODE, raw).anchors

    rendered = render_commented_code(CODE, anchors).split("\n")

    assert rendered[3].endswith("// hand back")
    assert "//" not in rendered[2]


def test_rendering_without_anchors_returns_the_source_unchanged():
    assert render_commented_code(CODE, []) == CODE


# --- chunking ------------------------------------------------------------------ #


def test_every_non_blank_line_lands_in_exactly_one_chunk():
    code = "\n\n".join(
        f"int f{n}(int x)\n{{\n  return x + {n};\n}}" for n in range(6)
    )
    lines = code.split("\n")

    chunks = chunk_code(code, max_tokens=60)
    covered = {n for chunk in chunks for n in range(chunk.start_line, chunk.end_line + 1)}

    missing = [n for n in range(1, len(lines) + 1) if n not in covered and lines[n - 1].strip()]
    assert not missing


def test_chunk_text_matches_the_lines_it_claims():
    code = "\n\n".join(f"int f{n}()\n{{\n  return {n};\n}}" for n in range(4))
    lines = code.split("\n")

    for chunk in chunk_code(code, max_tokens=40):
        assert chunk.text == "\n".join(lines[chunk.start_line - 1 : chunk.end_line])


def test_empty_source_produces_no_chunks():
    assert chunk_code("") == []


# --- backend selection --------------------------------------------------------- #


def test_run_model_falls_back_to_codet5_when_llama_server_is_down(monkeypatch):
    """A mobile client should get a degraded answer, never a 500."""
    monkeypatch.setattr(model_service, "MODEL_BACKEND", "qwen_gguf")

    def unavailable(_code: str):
        raise qwen_service.LlamaServerUnavailable("connection refused")

    monkeypatch.setattr(qwen_service, "run", unavailable)
    called: dict[str, bool] = {}

    def fake_codet5(code, analysis=None):
        called["yes"] = True
        return model_service.RawModelOutput(commented_code=code, explanation="from codet5")

    monkeypatch.setattr(model_service, "_run_codet5", fake_codet5)

    result = model_service.run_model(CODE)

    assert called.get("yes"), "the CodeT5 path should have answered"
    assert result.explanation == "from codet5"


def test_run_model_uses_qwen_when_selected(monkeypatch):
    monkeypatch.setattr(model_service, "MODEL_BACKEND", "qwen_gguf")
    monkeypatch.setattr(
        qwen_service,
        "run",
        lambda code: qwen_service.QwenOutput(commented_code="annotated", explanation="from qwen"),
    )

    result = model_service.run_model(CODE)

    assert result.explanation == "from qwen"
    assert result.commented_code == "annotated"


def test_backend_is_one_of_the_known_engines():
    """A typo in .env should not silently mean "neither".

    The code default is ``codet5``; asserting that here would only re-read
    whatever this machine's .env says, so what is checked is the property that
    survives configuration: the value is one the dispatcher understands.
    """
    from app.core import config

    assert config.MODEL_BACKEND in {"codet5", "qwen_gguf"}


# --- prompt shape --------------------------------------------------------------- #


@pytest.mark.parametrize("task", ["line_comments", "explanation", "optimize"])
def test_prompts_carry_the_chat_markers_the_checkpoint_expects(task):
    prompt = qwen_service.build_prompt(CODE, task)

    assert prompt.startswith("<|im_start|>system")
    assert prompt.endswith("<|im_start|>assistant\n")
    assert CODE in prompt


def test_unparseable_model_output_yields_no_anchors_rather_than_raising():
    assert qwen_service._field("not json at all", "line_comments") == []
    assert qwen_service._field("not json at all", "explanation") == ""
