"""Tests for the execution-checked optimizer.

The checker compiles and runs real C++, so these are slower than the rest of
the suite and skip where no compiler exists. The model itself is stubbed: what
is under test is whether a rewrite is accepted or rejected, not what the model
proposes.
"""

from __future__ import annotations

import shutil

import pytest

from app.model_processing.equivalence import check, parse_signature
from app.services import optimization_service

needs_compiler = pytest.mark.skipif(shutil.which("c++") is None, reason="needs a C++ compiler")

NAIVE = "int fib(int n)\n{\n  if (n <= 1)\n    return n;\n  return fib(n - 1) + fib(n - 2);\n}"

MEMOISED = """int fib(int n)
{
    if (n <= 1) return n;
    std::vector<int> dp(n + 1, 0);
    dp[1] = 1;
    for (int i = 2; i <= n; ++i) dp[i] = dp[i - 1] + dp[i - 2];
    return dp[n];
}"""

WRONG = NAIVE.replace("fib(n - 2)", "fib(n - 2) + 1")


# --- signature reading --------------------------------------------------------- #


def test_reads_a_scalar_signature():
    signature = parse_signature(NAIVE)

    assert signature is not None
    assert signature.name == "fib" and signature.drivable


def test_refuses_shapes_it_cannot_call():
    """`void run(int n)` is the dangerous one: it prints nothing, and nothing
    compares equal to nothing, so accepting it would verify every rewrite."""
    assert not parse_signature("void run(int n) { }").drivable
    assert not parse_signature("int seed() { return 4; }").drivable
    assert not parse_signature("int walk(TreeNode* root) { return 0; }").drivable


def test_drives_the_shapes_real_submissions_are_written_in():
    assert parse_signature("int total(std::vector<int> xs) { return 0; }").drivable
    assert parse_signature("void sortValues(int data[], int n) { }").drivable
    assert parse_signature("std::string flip(std::string s) { return s; }").drivable
    assert parse_signature("void twice(int& x) { }").drivable


def test_a_rewrite_that_corrupts_an_array_is_rejected():
    """The measured case: a bubble sort whose swap has no temporary.

    The function returns nothing, so this is caught only by reading the array
    back after the call.
    """
    correct = (
        "void sortValues(int d[], int n) {\n"
        "  for (int i = 0; i < n - 1; i++)\n"
        "    for (int j = 0; j < n - i - 1; j++)\n"
        "      if (d[j] > d[j+1]) { int t = d[j]; d[j] = d[j+1]; d[j+1] = t; }\n"
        "}"
    )
    broken = correct.replace(
        "int t = d[j]; d[j] = d[j+1]; d[j+1] = t;", "d[j] = d[j+1]; d[j+1] = d[j];"
    )

    verdict = check(correct, broken)

    assert verdict.verified, verdict.reason
    assert not verdict.equivalent, "a rewrite that loses data must not be shown"


# --- the verdict --------------------------------------------------------------- #


@needs_compiler
def test_a_correct_rewrite_is_accepted():
    result = check(NAIVE, MEMOISED, timeout=60)

    assert result.verified and result.equivalent
    assert result.agreed == result.cases


@needs_compiler
def test_a_rewrite_that_changes_the_answer_is_rejected():
    result = check(NAIVE, WRONG, timeout=60)

    assert result.verified
    assert not result.equivalent
    assert "differs" in result.summary()


@needs_compiler
def test_a_rewrite_that_does_not_compile_is_rejected():
    result = check(NAIVE, "int fib(int n) { return fib(n-1) }", timeout=60)

    assert not result.equivalent
    assert "compile failed" in result.summary()


def test_an_identical_rewrite_is_not_treated_as_an_improvement():
    assert not check(NAIVE, NAIVE).equivalent
    assert not check(NAIVE, "").equivalent


def test_an_uncallable_signature_says_so_rather_than_claiming_success():
    result = check("void go(int n) { }", "void go(int n) { return; }")

    assert not result.verified and not result.equivalent
    assert "cannot check" in result.summary()
    assert "nothing to compare" in result.summary(), "say why it was refused, not just that it was"


# --- what the service does with the verdict -------------------------------------- #


@needs_compiler
def test_a_verified_rewrite_is_returned_to_the_caller(monkeypatch):
    monkeypatch.setattr(optimization_service, "MODEL_BACKEND", "qwen_gguf")
    from app.services import qwen_service

    monkeypatch.setattr(qwen_service, "optimize", lambda code: MEMOISED)

    result = optimization_service.optimize_checked(NAIVE)

    assert result.changed and result.verified
    assert result.code == MEMOISED


@needs_compiler
def test_a_rewrite_that_changes_the_answer_never_reaches_the_caller(monkeypatch):
    """The failure that matters: a wrong answer served as an improvement."""
    monkeypatch.setattr(optimization_service, "MODEL_BACKEND", "qwen_gguf")
    from app.services import qwen_service

    monkeypatch.setattr(qwen_service, "optimize", lambda code: WRONG)

    result = optimization_service.optimize_checked(NAIVE)

    assert not result.changed
    assert result.code == NAIVE, "the user's own code must come back untouched"


def test_an_unavailable_model_server_returns_the_original(monkeypatch):
    monkeypatch.setattr(optimization_service, "MODEL_BACKEND", "qwen_gguf")
    from app.services import qwen_service

    def down(_code: str) -> str:
        raise qwen_service.LlamaServerUnavailable("connection refused")

    monkeypatch.setattr(qwen_service, "optimize", down)

    result = optimization_service.optimize_checked(NAIVE)

    assert not result.changed and result.code == NAIVE


def test_the_string_api_still_returns_something_compilable(monkeypatch):
    """``optimize`` predates this work and callers still expect a plain string."""
    monkeypatch.setattr(optimization_service, "MODEL_BACKEND", "qwen_gguf")
    from app.services import qwen_service

    monkeypatch.setattr(qwen_service, "optimize", lambda code: "")

    out = optimization_service.optimize(NAIVE)

    assert out.startswith(NAIVE)
    assert "optimizer:" in out
