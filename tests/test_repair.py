"""Tests for the targeted corruption-repair pass."""

from __future__ import annotations

from app.model_processing.repair import repair_code


def test_factorial_div2_removed() -> None:
    out = repair_code("return n * factorial((n - 1)) / 2;")
    assert out == "return n * factorial(n - 1);"


def test_is_even_extra_paren_fixed() -> None:
    out = repair_code("if (n%2 == 0)) { return true; }")
    assert out == "if (n % 2 == 0) { return true; }"


def test_bubble_sort_bounds_fixed() -> None:
    out = repair_code("for (int j = 0; j < n -= i - 1; j++)")
    assert out == "for (int j = 0; j < n - i - 1; j++)"


def test_binary_search_elem_to_arr() -> None:
    out = repair_code("else if (elem[mid>target) left = mid + 1;")
    assert "arr[" in out
    assert "elem[" not in out


def test_reverse_left_to_l() -> None:
    out = repair_code("a[left] = a [r];")
    assert out == "a[l] = a[r];"


def test_fib_recursive_name_fixed() -> None:
    out = repair_code("return fibRecipRec(n - 1);")
    assert out == "return fibRec(n - 1);"


def test_palindrome_typo_fixed() -> None:
    assert repair_code("it's a palinder") == "it's a palindrome"
    assert repair_code("it's a pal indrome") == "it's a palindrome"


def test_fib_comment_typos_fixed() -> None:
    assert repair_code("Fibond sequence") == "Fibonacci sequence"
    assert repair_code("Fiboragorean numbers") == "Fibonacci numbers"


def test_repair_is_idempotent() -> None:
    code = "a[left] = a [r];"
    once = repair_code(code)
    twice = repair_code(once)
    assert once == twice


def test_repair_leaves_clean_code_untouched() -> None:
    code = "int sum(vector<int>& a) { return a[0]; }"
    assert repair_code(code) == code
