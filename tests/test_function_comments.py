"""Tests for function-level doc comment generation."""

from __future__ import annotations

from app.model_processing.anchors import Anchor, render_commented_code
from app.model_processing.function_comments import (
    attach_function_doc_comments,
    extract_function_description,
    extract_function_inputs,
    extract_function_process,
    extract_function_returns,
)
from app.parsers import cpp_parser
from app.services.analyzer import _function_name


MULTI_FN_CODE = """\
#include <iostream>
using namespace std;

int f(int a[], int n) {
    int x = a[0];
    for (int i = 1; i < n; i++)
        if (a[i] > x)
            x = a[i];
    return x;
}

int g(int a[], int n) {
    int x = a[0];
    for (int i = 1; i < n; i++)
        if (a[i] < x)
            x = a[i];
    return x;
}

int h(int a[], int n) {
    if (n == 0)
        return 0;
    return a[n - 1] + h(a, n - 1);
}

int k(int a[], int n) {
    int x = f(a, n);
    int y = g(a, n);
    int z = h(a, n);
    return x - y + z;
}
"""

EXPLANATION = """\
Purpose: Computes an expression over an array.
Algorithm: `f` finds the maximum element; `g` finds the minimum element; `h` recursively sums the last element with the rest; `k` combines these three results.
"""


def test_extract_function_description_from_explanation():
    assert "maximum" in extract_function_description("f", EXPLANATION).lower()
    assert "minimum" in extract_function_description("g", EXPLANATION).lower()
    assert "recursively" in extract_function_description("h", EXPLANATION).lower()
    assert "combines" in extract_function_description("k", EXPLANATION).lower()


def test_attach_function_doc_comments_renders_details_on_all_functions():
    anchors = attach_function_doc_comments(MULTI_FN_CODE, [], EXPLANATION)
    assert len(anchors) == 4

    rendered = render_commented_code(MULTI_FN_CODE, anchors)
    assert "Function: f" in rendered
    assert "Summary: Finds the maximum element." in rendered
    assert "Inputs: int a[], int n" in rendered
    assert "Process:" in rendered
    assert "Returns: int" in rendered

    assert "Function: g" in rendered
    assert "Summary: Finds the minimum element." in rendered

    assert "Function: h" in rendered
    assert "Summary: Recursively sums the last element" in rendered

    assert "Function: k" in rendered
    assert "Summary: Combines these three results." in rendered
    assert "Calls f, g, h" in rendered


def test_function_with_no_inputs_and_void_returns():
    code = """\
void greet() {
    cout << "Hello" << endl;
}
"""
    root = cpp_parser.parse(code)
    fn = next(cpp_parser.iter_descendants(root, {"function_definition"}))
    assert extract_function_inputs(fn) == "None (takes no parameters)"
    assert extract_function_returns(fn) == "void (no return value)"


def test_does_not_overwrite_existing_function_comments():
    code_with_existing = """\
// Existing comment for f
int f(int a[], int n) {
    return a[0];
}
"""
    anchors = attach_function_doc_comments(code_with_existing, [], EXPLANATION)
    # Since f already has a comment, no doc comment anchor should be added
    assert len(anchors) == 0
