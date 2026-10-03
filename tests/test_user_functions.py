"""Test the user's specific functions:

  r(int a[], int l, int h)      — recursive range-max (divide & conquer)
  f(int a[][5], int n, int x)   — 2D-array sum-of-absolute-differences with recursion

Also tests a file that has BOTH functions together (multi-function input).
"""

from __future__ import annotations

import pytest

from app.core.compiler import find_cxx_compiler
from app.model_processing.equivalence import check, parse_signature
from app.services import optimization_service

needs_compiler = pytest.mark.skipif(
    find_cxx_compiler() is None, reason="needs a C++ compiler"
)


# ===========================================================================
# 1.  r(int a[], int l, int h) — recursive range-max
# ===========================================================================

R_RECURSIVE = """\
int r(int a[], int l, int h) {
    if (l >= h)
        return a[l];

    int m = (l + h) / 2;
    int x = r(a, l, m);
    int y = r(a, m + 1, h);

    if (x > y)
        return x;
    else
        return y;
}"""

# Iterative version using an explicit stack (same semantics)
R_ITERATIVE = """\
#include <stack>
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

# Simple wrong version — returns first leaf, never compares halves
R_WRONG = """\
#include <stack>
int r(int a[], int l, int h) {
    std::stack<std::pair<int, int>> st;
    st.push({l, h});
    while (!st.empty()) {
        auto [cl, ch] = st.top();
        st.pop();
        if (cl >= ch) return a[cl];   // bug: returns immediately, misses rest
        int m = (cl + ch) / 2;
        st.push({cl, m});
        st.push({m + 1, ch});
    }
    return 0;
}"""

# Even simpler linear scan — correct but different algorithm
R_LINEAR_SCAN = """\
int r(int a[], int l, int h) {
    int result = a[l];
    for (int i = l + 1; i <= h; ++i)
        if (a[i] > result) result = a[i];
    return result;
}"""


def test_r_signature_is_drivable():
    """Checker can generate test cases for r(int[], int, int)."""
    sig = parse_signature(R_RECURSIVE)
    assert sig is not None
    assert sig.name == "r"
    assert sig.drivable


@needs_compiler
def test_r_stack_loop_is_equivalent():
    """Explicit-stack iterative version produces same max as divide-and-conquer."""
    result = check(R_RECURSIVE, R_ITERATIVE)
    assert result.verified, result.reason
    assert result.equivalent, result.summary()


@needs_compiler
def test_r_linear_scan_is_equivalent():
    """A plain O(n) linear scan is also equivalent — different algorithm, same answer."""
    result = check(R_RECURSIVE, R_LINEAR_SCAN)
    assert result.verified, result.reason
    assert result.equivalent, result.summary()


@needs_compiler
def test_r_wrong_loop_is_rejected():
    """A loop that returns on the first leaf found gives wrong answers — must be caught."""
    result = check(R_RECURSIVE, R_WRONG)
    assert result.verified, result.reason
    assert not result.equivalent, "broken stack loop must be rejected"


@needs_compiler
def test_service_accepts_r_linear_scan(monkeypatch):
    """optimization_service accepts the correct linear-scan rewrite of r."""
    from app.services import qwen_service

    monkeypatch.setattr(qwen_service, "optimize", lambda code: R_LINEAR_SCAN)
    monkeypatch.setattr(qwen_service, "iterate", lambda code: R_LINEAR_SCAN)

    result = optimization_service.optimize_checked(R_RECURSIVE)

    assert result.changed and result.verified
    assert result.code == R_LINEAR_SCAN


@needs_compiler
def test_service_rejects_r_wrong_loop(monkeypatch):
    """optimization_service must not return the broken loop version of r."""
    from app.services import qwen_service

    monkeypatch.setattr(qwen_service, "optimize", lambda code: R_WRONG)
    monkeypatch.setattr(qwen_service, "iterate", lambda code: R_WRONG)

    result = optimization_service.optimize_checked(R_RECURSIVE)

    assert not result.changed
    assert result.code == R_RECURSIVE


# ===========================================================================
# 2.  f(int a[][5], int n, int x) — 2-D array sum-of-absolute-differences
#     The checker cannot drive multidimensional arrays (int a[][5] needs
#     int(*)[5], not int*). It must report this clearly instead of crashing
#     or saying "original compile failed".
# ===========================================================================

F_RECURSIVE = """\
int f(int a[][5], int n, int x = 0) {
    if (x >= n)
        return 0;

    int s = 0;

    for (int i = 0; i < n; i++) {
        for (int j = i; j < n; j++) {
            if (a[x][i] > a[x][j])
                s += a[x][i] - a[x][j];
            else
                s += a[x][j] - a[x][i];
        }
    }

    return s + f(a, n, x + 1);
}"""

F_ITERATIVE = """\
int f(int a[][5], int n, int x = 0) {
    int total = 0;
    for (int row = x; row < n; ++row) {
        for (int i = 0; i < n; i++) {
            for (int j = i; j < n; j++) {
                if (a[row][i] > a[row][j])
                    total += a[row][i] - a[row][j];
                else
                    total += a[row][j] - a[row][i];
            }
        }
    }
    return total;
}"""


def test_f_signature_not_drivable():
    """int a[][5] is a multidimensional pointer; the checker refuses it by design
    rather than generating out-of-bounds test cases or blaming the user's code."""
    sig = parse_signature(F_RECURSIVE)
    assert sig is not None
    assert sig.params[0].dimensions == 2, "first param must be detected as 2-D"
    assert not sig.drivable, "2-D arrays must be marked not-drivable"


def test_f_check_reports_undrivable_clearly():
    """check() must say 'multidimensional' in the reason, not 'compile failed'."""
    result = check(F_RECURSIVE, F_ITERATIVE)
    assert not result.verified
    assert "multidimensional" in result.reason, (
        f"expected 'multidimensional' in reason, got: {result.reason!r}"
    )


# ===========================================================================
# 3.  Multi-function input — both r and f in one translation unit
#     The optimizer must handle a file with multiple functions.
# ===========================================================================

MULTI_FUNCTION_CODE = F"{R_RECURSIVE}\n\n{F_RECURSIVE}"

# Optimized version: r replaced with linear scan, f unrolled to loops
MULTI_FUNCTION_OPTIMIZED = F"{R_LINEAR_SCAN}\n\n{F_ITERATIVE}"


def test_multi_function_file_parses():
    """parse_signature picks the FIRST drivable function (r) from a multi-function file."""
    sig = parse_signature(MULTI_FUNCTION_CODE)
    assert sig is not None
    # The first function `r` is drivable; `f` is not
    assert sig.name == "r"
    assert sig.drivable


@needs_compiler
def test_multi_function_r_is_checked_correctly():
    """When a file has two functions, the checker tests the drivable one (r)."""
    result = check(MULTI_FUNCTION_CODE, MULTI_FUNCTION_OPTIMIZED)
    # r is equivalent between the two versions
    assert result.verified, result.reason
    assert result.equivalent, result.summary()


@needs_compiler
def test_service_handles_multi_function_file(monkeypatch):
    """optimize_checked works on a file with multiple functions."""
    from app.services import qwen_service

    monkeypatch.setattr(qwen_service, "optimize", lambda code: MULTI_FUNCTION_OPTIMIZED)
    monkeypatch.setattr(qwen_service, "iterate", lambda code: MULTI_FUNCTION_OPTIMIZED)

    result = optimization_service.optimize_checked(MULTI_FUNCTION_CODE)

    assert result.changed and result.verified
    assert result.code == MULTI_FUNCTION_OPTIMIZED
