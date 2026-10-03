"""Tests for the execution-checked optimizer.

The checker compiles and runs real C++, so these are slower than the rest of
the suite and skip where no compiler exists. The model itself is stubbed: what
is under test is whether a rewrite is accepted or rejected, not what the model
proposes.
"""

from __future__ import annotations

import pytest

from app.core.compiler import find_cxx_compiler
from app.model_processing.equivalence import _cases, check, parse_signature
from app.services import optimization_service

needs_compiler = pytest.mark.skipif(find_cxx_compiler() is None, reason="needs a C++ compiler")

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


def test_reads_modern_trailing_return_type():
    sig = parse_signature("auto add(int a, int b) -> int { return a + b; }")
    assert sig is not None
    assert sig.name == "add"
    assert sig.return_type == "int"
    assert sig.drivable
    assert len(sig.params) == 2


def test_reads_template_function_signature():
    sig = parse_signature("template <typename T>\nvoid sortValues(int data[], int n) { }")
    assert sig is not None
    assert sig.name == "sortValues"
    assert sig.return_type == "void"
    assert sig.drivable


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
    monkeypatch.setattr(qwen_service, "iterate", lambda code: MEMOISED)

    result = optimization_service.optimize_checked(NAIVE)

    assert result.changed and result.verified
    assert result.code == MEMOISED


@needs_compiler
def test_a_rewrite_that_changes_the_answer_never_reaches_the_caller(monkeypatch):
    """The failure that matters: a wrong answer served as an improvement."""
    monkeypatch.setattr(optimization_service, "MODEL_BACKEND", "qwen_gguf")
    from app.services import qwen_service

    monkeypatch.setattr(qwen_service, "optimize", lambda code: WRONG)
    monkeypatch.setattr(qwen_service, "iterate", lambda code: WRONG)

    result = optimization_service.optimize_checked(NAIVE)

    assert not result.changed
    assert result.code == NAIVE, "the user's own code must come back untouched"


def test_an_unavailable_model_server_returns_the_original(monkeypatch):
    monkeypatch.setattr(optimization_service, "MODEL_BACKEND", "qwen_gguf")
    from app.services import qwen_service

    def down(_code: str) -> str:
        raise qwen_service.LlamaServerUnavailable("connection refused")

    monkeypatch.setattr(qwen_service, "optimize", down)
    monkeypatch.setattr(qwen_service, "iterate", down)

    result = optimization_service.optimize_checked(NAIVE)

    assert not result.changed and result.code == NAIVE


def test_an_unverifiable_rewrite_never_reaches_the_caller(monkeypatch):
    monkeypatch.setattr(optimization_service, "MODEL_BACKEND", "qwen_gguf")
    from app.services import qwen_service

    original = "void go(int n) { int total = n + 1; }"
    proposal = "void go(int n) { int total = n; }"
    monkeypatch.setattr(qwen_service, "optimize", lambda code: proposal)
    monkeypatch.setattr(qwen_service, "iterate", lambda code: proposal)

    result = optimization_service.optimize_checked(original)

    assert not result.changed
    assert not result.verified
    assert result.code == original
    assert "not verified" in result.note


def test_the_string_api_still_returns_something_compilable(monkeypatch):
    """``optimize`` predates this work and callers still expect a plain string."""
    monkeypatch.setattr(optimization_service, "MODEL_BACKEND", "qwen_gguf")
    from app.services import qwen_service

    monkeypatch.setattr(qwen_service, "optimize", lambda code: "")
    monkeypatch.setattr(qwen_service, "iterate", lambda code: "")

    out = optimization_service.optimize(NAIVE)

    assert out.startswith(NAIVE)
    assert "optimizer:" in out


# --- Four defects found by pointing the checker at real submissions ----------
#
# Each of these made the checker report something untrue: three made it blame
# the user's code for a limitation of the driver, and one let a rewrite through
# that is wrong for every argument except the one value it was tested with.

RANGE_MAX = """int r(int a[], int l, int h) {
    if (l >= h) return a[l];
    int m = (l + h) / 2;
    int x = r(a, l, m);
    int y = r(a, m + 1, h);
    return x > y ? x : y;
}"""

RANGE_MAX_AS_A_LOOP = """#include <stack>
#include <algorithm>
int r(int a[], int l, int h) {
    int result = a[l];
    std::stack<std::pair<int, int>> st;
    st.push({l, h});
    while (!st.empty()) {
        auto [cl, ch] = st.top();
        st.pop();
        if (cl >= ch) result = std::max(result, a[cl]);
        else {
            int m = (cl + ch) / 2;
            st.push({cl, m});
            st.push({m + 1, ch});
        }
    }
    return result;
}"""

#: Returns the first leaf it pops instead of comparing the halves.
RANGE_MAX_BROKEN = """#include <stack>
int r(int a[], int l, int h) {
    std::stack<std::pair<int, int>> st;
    st.push({l, h});
    while (!st.empty()) {
        auto [cl, ch] = st.top();
        st.pop();
        if (cl >= ch) return a[cl];
        int m = (cl + ch) / 2;
        st.push({cl, m});
        st.push({m + 1, ch});
    }
    return 0;
}"""

TALLY_FROM = """int tally(int a[], int n, int from = 0) {
    int s = 0;
    for (int i = from; i < n; ++i) s += a[i];
    return s;
}"""

#: Ignores `from`, so it agrees exactly when `from` is 0 and nowhere else.
TALLY_IGNORING_THE_DEFAULT = """int tally(int a[], int n, int from = 0) {
    int s = 0;
    for (int i = 0; i < n; ++i) s += a[i];
    return s;
}"""


def test_a_defaulted_parameter_is_still_a_parameter():
    """Tree-sitter calls it `optional_parameter_declaration`, and it was skipped.

    Dropping it left `f(int a[][5], int n, int x = 0)` looking like a
    two-argument function, so every generated case ran with `x = 0`.
    """
    signature = parse_signature(TALLY_FROM)
    assert [p.name for p in signature.params] == ["a", "n", "from"]
    assert signature.params[-1].default == "0"


def test_an_index_is_never_filled_past_the_end_of_what_it_indexes():
    """`l` is an index, not a length.

    The old rule read "an integer after a sequence is its length", so a
    four-element array was called with `l = 4` and the function returned
    `a[4]`. Both versions then read out of bounds, and two undefined behaviours
    can agree without meaning anything.
    """
    signature = parse_signature(RANGE_MAX)
    cases, _ = _cases(signature)
    assert cases, "every case was discarded"
    for buffer, low, high in cases:
        assert buffer, "an empty sequence has no valid subscript"
        assert 0 <= low < len(buffer)
        assert 0 <= high < len(buffer)


def test_a_low_index_is_not_pinned_to_one_value():
    """Otherwise a rewrite that ignores it passes every case.

    This is the same mistake as the one above wearing different clothes: a
    parameter that takes a single value across the whole case list is not being
    tested, whether that value came from the sequence length or from a constant.
    """
    signature = parse_signature(TALLY_FROM)
    cases, _ = _cases(signature)
    assert len({low for _, _, low in cases}) > 1


def test_a_multidimensional_array_is_refused_by_name():
    """The driver passes `vector<int>::data()`, an `int*`.

    A parameter declared `int a[][5]` wants `int (*)[5]`, so the generated
    program does not compile and the verdict used to read "original compile
    failed" — a statement about the harness that the caller reads as a
    statement about their own code.
    """
    code = "int f(int a[][5], int n) { return a[0][0] + n; }"
    signature = parse_signature(code)
    assert signature.params[0].dimensions == 2
    assert not signature.drivable
    result = check(code, "int f(int a[][5], int n) { return 0; }")
    assert not result.verified
    assert "multidimensional" in result.reason


@needs_compiler
def test_a_function_whose_name_collides_with_the_drivers_result_is_checkable():
    """The driver used to write `auto r = r(...)`.

    Single-letter names are the norm in these submissions, and a function named
    `r` produced "use of 'r' before deduction of 'auto'" — so it could never be
    checked, and the failure was reported against the user's code.
    """
    result = check(RANGE_MAX, RANGE_MAX_AS_A_LOOP)
    assert result.verified, result.reason
    assert result.equivalent, result.summary()


@needs_compiler
def test_the_broken_loop_rewrite_is_still_rejected():
    """The fix must not turn into "accept everything"."""
    result = check(RANGE_MAX, RANGE_MAX_BROKEN)
    assert result.verified, result.reason
    assert not result.equivalent


@needs_compiler
def test_a_rewrite_wrong_only_away_from_the_default_is_rejected():
    """The defect this whole group exists for.

    `TALLY_IGNORING_THE_DEFAULT` returns the same answer whenever `from` is 0.
    While the defaulted parameter was invisible, that was every case, and the
    rewrite was served as proven equivalent.
    """
    result = check(TALLY_FROM, TALLY_IGNORING_THE_DEFAULT)
    assert result.verified, result.reason
    assert not result.equivalent, "a rewrite that ignores `from` must not pass"
