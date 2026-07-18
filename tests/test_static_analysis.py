"""Static analysis (Phase 3) and diff (Phase 4) unit tests.

Problem solved: these deterministic stages have no AI dependency, so they can
be tested in isolation and fast. We assert the exact facts the analyzer should
extract for known snippets.
"""

from __future__ import annotations

from app.services import diff_service
from app.services.analyzer import analyze_code


def test_detects_recursion_and_parameters() -> None:
    code = """
    int factorial(int n) {
        if (n <= 1) return 1;
        return n * factorial(n - 1);
    }
    """
    analysis = analyze_code(code)
    assert analysis.function_count == 1
    assert analysis.recursive is True
    assert analysis.functions[0].name == "factorial"
    assert analysis.functions[0].params == 1
    assert analysis.cyclomatic_complexity >= 2


def test_detects_nested_loops_and_long_function() -> None:
    code = """
    void nested() {
        for (int i = 0; i < 10; i++) {
            for (int j = 0; j < 10; j++) {
                int x = i * j;
            }
        }
    }
    """
    analysis = analyze_code(code)
    assert analysis.max_nested_loops >= 2
    assert "nested" in analysis.functions[0].name


def test_missing_comments_and_docs_flagged() -> None:
    code = "int add(int a, int b) { return a + b; }"
    analysis = analyze_code(code)
    assert analysis.missing_comments == 1
    assert analysis.missing_docs == 1


def test_diff_reports_added_and_modified_functions() -> None:
    old_code = "int foo() { return 1; }"
    new_code = "int foo() { return 2; }\nint bar() { return 0; }"
    change = diff_service.compare(old_code, new_code)
    assert change.added_functions == ["bar"]
    assert change.modified_functions == ["foo"]
    assert change.removed_functions == []


def test_analyzer_falls_back_gracefully_on_empty_code() -> None:
    analysis = analyze_code("")
    assert analysis.function_count == 0
    assert analysis.parser in {"tree-sitter", "regex-fallback"}
