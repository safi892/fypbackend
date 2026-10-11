"""Test recursion-to-loop optimization with real C++ examples.

Each test pair has:
  - RECURSIVE: the original code (what the user submits)
  - ITERATIVE: the loop version the optimizer should produce

The equivalence checker compiles and runs both with the same inputs,
so these tests prove the loop version is provably correct, not just
syntactically similar.

Requires a C++ compiler. Skipped automatically when none is found.
"""

from __future__ import annotations

import pytest

from app.core.compiler import find_cxx_compiler
from app.model_processing.equivalence import check
from app.services import optimization_service

needs_compiler = pytest.mark.skipif(
    find_cxx_compiler() is None, reason="needs a C++ compiler"
)


# ---------------------------------------------------------------------------
# 1. Fibonacci
# ---------------------------------------------------------------------------

FIB_RECURSIVE = """\
int fib(int n) {
    if (n <= 1) return n;
    return fib(n - 1) + fib(n - 2);
}"""

FIB_ITERATIVE = """\
int fib(int n) {
    if (n <= 1) return n;
    int a = 0, b = 1;
    for (int i = 2; i <= n; ++i) {
        int c = a + b;
        a = b;
        b = c;
    }
    return b;
}"""

FIB_WRONG = """\
int fib(int n) {
    if (n <= 1) return n;
    int a = 0, b = 1;
    for (int i = 2; i <= n; ++i) {
        b = a + b;   // bug: a not updated, always 0 after first step
        a = b;
    }
    return b;
}"""


@needs_compiler
def test_fib_iterative_matches_recursive():
    result = check(FIB_RECURSIVE, FIB_ITERATIVE)
    assert result.verified, result.reason
    assert result.equivalent, result.summary()


@needs_compiler
def test_fib_wrong_loop_is_rejected():
    result = check(FIB_RECURSIVE, FIB_WRONG)
    assert result.verified, result.reason
    assert not result.equivalent, "a wrong fib loop must not pass"


# ---------------------------------------------------------------------------
# 2. Factorial
# ---------------------------------------------------------------------------

FACTORIAL_RECURSIVE = """\
int factorial(int n) {
    if (n <= 1) return 1;
    return n * factorial(n - 1);
}"""

FACTORIAL_ITERATIVE = """\
int factorial(int n) {
    int result = 1;
    for (int i = 2; i <= n; ++i)
        result *= i;
    return result;
}"""

FACTORIAL_WRONG = """\
int factorial(int n) {
    int result = 1;
    for (int i = 1; i < n; ++i)   // bug: misses multiplying by n
        result *= i;
    return result;
}"""


@needs_compiler
def test_factorial_iterative_matches_recursive():
    result = check(FACTORIAL_RECURSIVE, FACTORIAL_ITERATIVE)
    assert result.verified, result.reason
    assert result.equivalent, result.summary()


@needs_compiler
def test_factorial_wrong_loop_is_rejected():
    result = check(FACTORIAL_RECURSIVE, FACTORIAL_WRONG)
    assert result.verified, result.reason
    assert not result.equivalent, "wrong factorial must be rejected"


# ---------------------------------------------------------------------------
# 3. Sum of array (linear recursion)
# ---------------------------------------------------------------------------

SUM_RECURSIVE = """\
int sumArray(int arr[], int n) {
    if (n == 0) return 0;
    return arr[n - 1] + sumArray(arr, n - 1);
}"""

SUM_ITERATIVE = """\
int sumArray(int arr[], int n) {
    int total = 0;
    for (int i = 0; i < n; ++i)
        total += arr[i];
    return total;
}"""


@needs_compiler
def test_sum_array_iterative_matches_recursive():
    result = check(SUM_RECURSIVE, SUM_ITERATIVE)
    assert result.verified, result.reason
    assert result.equivalent, result.summary()


# ---------------------------------------------------------------------------
# 4. Power (exponentiation)
# ---------------------------------------------------------------------------

POWER_RECURSIVE = """\
int power(int base, int exp) {
    if (exp == 0) return 1;
    return base * power(base, exp - 1);
}"""

POWER_ITERATIVE = """\
int power(int base, int exp) {
    int result = 1;
    for (int i = 0; i < exp; ++i)
        result *= base;
    return result;
}"""


@needs_compiler
def test_power_iterative_matches_recursive():
    result = check(POWER_RECURSIVE, POWER_ITERATIVE)
    assert result.verified, result.reason
    assert result.equivalent, result.summary()


# ---------------------------------------------------------------------------
# 5. GCD (Euclidean algorithm)
# ---------------------------------------------------------------------------

GCD_RECURSIVE = """\
int gcd(int a, int b) {
    if (b == 0) return a;
    return gcd(b, a % b);
}"""

GCD_ITERATIVE = """\
int gcd(int a, int b) {
    while (b != 0) {
        int t = b;
        b = a % b;
        a = t;
    }
    return a;
}"""


@needs_compiler
def test_gcd_iterative_matches_recursive():
    result = check(GCD_RECURSIVE, GCD_ITERATIVE)
    assert result.verified, result.reason
    assert result.equivalent, result.summary()


# ---------------------------------------------------------------------------
# 6. Binary search (recursive → iterative)
# ---------------------------------------------------------------------------

BSEARCH_RECURSIVE = """\
int bsearch(int arr[], int lo, int hi, int target) {
    if (lo > hi) return -1;
    int mid = lo + (hi - lo) / 2;
    if (arr[mid] == target) return mid;
    if (arr[mid] < target) return bsearch(arr, mid + 1, hi, target);
    return bsearch(arr, lo, mid - 1, target);
}"""

BSEARCH_ITERATIVE = """\
int bsearch(int arr[], int lo, int hi, int target) {
    while (lo <= hi) {
        int mid = lo + (hi - lo) / 2;
        if (arr[mid] == target) return mid;
        if (arr[mid] < target) lo = mid + 1;
        else hi = mid - 1;
    }
    return -1;
}"""


@needs_compiler
def test_bsearch_iterative_matches_recursive():
    result = check(BSEARCH_RECURSIVE, BSEARCH_ITERATIVE)
    assert result.verified, result.reason
    assert result.equivalent, result.summary()


# ---------------------------------------------------------------------------
# 7. optimize_checked accepts a correct loop rewrite (service-level test)
# ---------------------------------------------------------------------------

@needs_compiler
def test_service_accepts_correct_fib_loop(monkeypatch):
    """The optimization service must return the loop when the checker approves it."""
    from app.services import qwen_service

    monkeypatch.setattr(qwen_service, "optimize", lambda code: FIB_ITERATIVE)
    monkeypatch.setattr(qwen_service, "iterate", lambda code: FIB_ITERATIVE)

    result = optimization_service.optimize_checked(FIB_RECURSIVE)

    assert result.changed, "iterative fib should be marked as changed"
    assert result.verified, "iterative fib should pass the equivalence check"
    assert result.code == FIB_ITERATIVE


@needs_compiler
def test_service_rejects_wrong_fib_loop(monkeypatch):
    """The service must NOT return a loop that produces wrong answers."""
    from app.services import qwen_service

    monkeypatch.setattr(qwen_service, "optimize", lambda code: FIB_WRONG)
    monkeypatch.setattr(qwen_service, "iterate", lambda code: FIB_WRONG)

    result = optimization_service.optimize_checked(FIB_RECURSIVE)

    assert not result.changed, "wrong loop must not be returned to the user"
    assert result.code == FIB_RECURSIVE, "original code must come back untouched"


@needs_compiler
def test_service_accepts_correct_factorial_loop(monkeypatch):
    """Factorial: service accepts the correct iterative version."""
    from app.services import qwen_service

    monkeypatch.setattr(qwen_service, "optimize", lambda code: FACTORIAL_ITERATIVE)
    monkeypatch.setattr(qwen_service, "iterate", lambda code: FACTORIAL_ITERATIVE)

    result = optimization_service.optimize_checked(FACTORIAL_RECURSIVE)

    assert result.changed and result.verified
    assert result.code == FACTORIAL_ITERATIVE


@needs_compiler
def test_service_accepts_correct_gcd_loop(monkeypatch):
    """GCD: service accepts the correct while-loop version."""
    from app.services import qwen_service

    monkeypatch.setattr(qwen_service, "optimize", lambda code: GCD_ITERATIVE)
    monkeypatch.setattr(qwen_service, "iterate", lambda code: GCD_ITERATIVE)

    result = optimization_service.optimize_checked(GCD_RECURSIVE)

    assert result.changed and result.verified
    assert result.code == GCD_ITERATIVE
