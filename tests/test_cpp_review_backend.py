"""Tests for the C++ review inference backend: anchoring, chunking and backend selection.

None of these need llama-server or a model. The HTTP call is the only part that
does, and it is stubbed, so the logic around it stays testable in CI.
"""

from __future__ import annotations

import pytest

from app.model_processing.anchors import render_commented_code, repair_anchors
from app.parsers.cpp_chunking import chunk_code
from app.services import cpp_review_service, model_service, qwen_service

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


# --- comments that quote a real line and are still untrue ---------------------- #


@pytest.mark.parametrize("brace", ["}", "};", "{", "  }  "])
def test_a_comment_on_a_line_holding_only_punctuation_is_dropped(brace: str):
    """Measured failure: braces attract invention, because there is nothing to say."""
    code = f"int f()\n{{\n  return 0;\n{brace}"
    report = repair_anchors(code, [{"line": 4, "code": brace, "comment": "ends function"}])

    assert report.anchors == [] and report.dropped == 1
    assert report.dropped_punctuation == 1


def test_a_comment_that_contradicts_its_line_number_claim_is_dropped():
    """Measured failure: numeric constants get copied into comments where they don't belong."""
    code = "int total = 100;"
    report = repair_anchors(
        code, [{"line": 1, "code": "int total = 100;", "comment": "sets to 50"}]
    )

    assert report.anchors == [] and report.dropped == 1
    assert report.dropped_numeric == 1


# --- rendering ---------------------------------------------------------------- #


def test_rendering_attaches_comments_to_the_original_source():
    anchors = [
        repair_anchors(
            CODE, [{"line": 3, "code": "int total = a + b;", "comment": "calculate sum"}]
        ).anchors[0]
    ]
    rendered = render_commented_code(CODE, anchors)

    assert "int total = a + b;  // calculate sum" in rendered
    assert "return total;" in rendered


# --- chunking ----------------------------------------------------------------- #


def test_short_code_stays_as_a_single_chunk():
    chunks = chunk_code(CODE, max_tokens=300)
    assert len(chunks) == 1
    assert chunks[0].start_line == 1
    assert chunks[0].text == CODE


# --- backend selection & fallback --------------------------------------------- #


def test_run_model_uses_cpp_reviewer_when_selected(monkeypatch):
    monkeypatch.setattr(model_service, "MODEL_BACKEND", "cpp_reviewer_gguf")
    monkeypatch.setattr(
        cpp_review_service,
        "run",
        lambda code: cpp_review_service.ReviewModelOutput(
            commented_code="annotated", explanation="from cpp_reviewer"
        ),
    )

    result = model_service.run_model(CODE)

    assert result.explanation == "from cpp_reviewer"
    assert result.commented_code == "annotated"


def test_run_model_falls_back_to_codet5_when_llama_server_is_down(monkeypatch):
    """A mobile client should get a degraded answer, never a 500."""
    monkeypatch.setattr(model_service, "MODEL_BACKEND", "cpp_reviewer_gguf")

    def unavailable(_code: str):
        raise cpp_review_service.LlamaServerUnavailable("connection refused")

    monkeypatch.setattr(cpp_review_service, "run", unavailable)
    called: dict[str, bool] = {}

    def fake_codet5(code, analysis=None):
        called["yes"] = True
        return model_service.RawModelOutput(commented_code=code, explanation="from codet5")

    monkeypatch.setattr(model_service, "_run_codet5", fake_codet5)

    result = model_service.run_model(CODE)

    assert called.get("yes"), "the CodeT5 path should have answered"
    assert result.explanation == "from codet5"


def test_qwen_service_backward_compatibility():
    """Verify that legacy qwen_service re-exports cpp_review_service seamlessly."""
    assert qwen_service.ReviewModelOutput is cpp_review_service.ReviewModelOutput
    assert qwen_service.QwenOutput is cpp_review_service.ReviewModelOutput
    assert qwen_service.run is cpp_review_service.run
    assert qwen_service.annotate is cpp_review_service.annotate
    assert qwen_service.explain is cpp_review_service.explain
    assert qwen_service.optimize is cpp_review_service.optimize
    assert qwen_service.iterate is cpp_review_service.iterate
    assert qwen_service.LlamaServerUnavailable is cpp_review_service.LlamaServerUnavailable


# --- prompt shape --------------------------------------------------------------- #


@pytest.mark.parametrize("task", ["line_comments", "explanation", "optimize"])
def test_prompt_has_expected_markers(task: str):
    prompt = cpp_review_service.build_prompt(CODE, task)
    assert "<|im_start|>system" in prompt
    assert "<|im_end|>" in prompt
    assert "<|im_start|>user" in prompt
    assert "<|im_start|>assistant" in prompt
    assert "```cpp" in prompt
