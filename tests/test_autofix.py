"""Deterministic punctuation fixes for tree-sitter's MISSING-token reports."""

from app.model_processing.autofix import FixEdit, suggest_quick_fix
from app.parsers import cpp_parser


def _parses_clean(code: str) -> bool:
    root = cpp_parser.parse(code)
    return root is not None and not root.has_error


def test_missing_semicolon_is_offered_with_its_line():
    fix = suggest_quick_fix("int main() {\n    return 0\n}")
    assert fix is not None
    assert _parses_clean(fix.code)
    assert fix.description == "Add the missing ';' at line 2."
    assert fix.edits == (FixEdit(line=2, before="    return 0", after="    return 0;"),)


def test_missing_closing_paren_is_offered():
    code = "int main() {\n    if (true {\n        return 0;\n    }\n    return 1;\n}"
    fix = suggest_quick_fix(code)
    assert fix is not None
    assert _parses_clean(fix.code)
    assert "if (true)" in fix.code
    assert fix.edits[0].after == "    if (true) {"


def test_missing_closing_brace_is_appended_on_its_own_line():
    fix = suggest_quick_fix("int main() {\n    return 0;\n")
    assert fix is not None
    assert _parses_clean(fix.code)
    # The brace lands on its own line instead of gluing to the last statement.
    assert fix.code == "int main() {\n    return 0;\n}\n"
    assert fix.edits[-1] == FixEdit(line=3, before="", after="}")


def test_two_missing_semicolons_are_fixed_in_one_proposal():
    fix = suggest_quick_fix("void f() {\n    int x = 5\n    int y = 6\n}")
    assert fix is not None
    assert _parses_clean(fix.code)
    assert fix.code.count("int x = 5;") == 1
    assert fix.code.count("int y = 6;") == 1
    assert fix.description == "Add 2 missing ';' tokens."


def test_valid_code_gets_no_fix():
    assert suggest_quick_fix("int main() { return 0; }") is None


def test_error_only_shapes_get_no_fix_instead_of_a_guess():
    # An extra ')' produces ERROR nodes with no MISSING token: the mistake's
    # shape is unknown, so the honest answer is "no suggestion".
    assert suggest_quick_fix("int main() {\n    return (0));\n}") is None
    # Missing semicolon where error recovery swallows the next statement.
    assert suggest_quick_fix("int add(int a, int b) {\n    int c = a + b\n    return c;\n}") is None


def test_non_cpp_gets_no_fix():
    assert suggest_quick_fix("def add(a, b):\n    return a + b") is None
    assert suggest_quick_fix("// Just a comment") is None
    assert suggest_quick_fix("") is None


def test_oversized_input_is_rejected_before_parsing():
    assert suggest_quick_fix("x" * 100_001) is None
