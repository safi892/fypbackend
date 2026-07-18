"""Tests for the C++ syntax gate (gcc -fsyntax-only)."""

from __future__ import annotations

from app.model_processing.syntax_check import check_cpp_syntax


def test_clean_code_passes() -> None:
    ok, err = check_cpp_syntax(
        "int sum(vector<int>& a) {\n"
        "    int s = 0;\n"
        "    for (int i = 0; i < a.size(); i++) s = s + a[i];\n"
        "    return s;\n}"
    )
    assert ok is True
    assert err is None


def test_clean_code_with_prose_passes() -> None:
    ok, _ = check_cpp_syntax(
        "int f(int n) { return n; }\n### VERIFICATION\nLogic is consistent."
    )
    assert ok is True


def test_invented_identifier_fails() -> None:
    ok, err = check_cpp_syntax(
        "int binarySearch(int arr[], int n, int target) {\n"
        "    else if (elem[mid>target) left = mid + 1;\n"
        "    return -1;\n}"
    )
    assert ok is False
    assert err is not None


def test_extra_paren_fails() -> None:
    ok, _ = check_cpp_syntax("bool isEven(int n) { if (n%2 == 0)) return true; }")
    assert ok is False


def test_undeclared_left_fails() -> None:
    ok, _ = check_cpp_syntax(
        "void reverse(int a[], int n) {\n"
        "    a[left] = a[r];\n"
        "}"
    )
    assert ok is False


def test_pure_prose_passes() -> None:
    ok, _ = check_cpp_syntax("### VERIFICATION\nLogic flow is consistent.")
    assert ok is True
