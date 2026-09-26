"""Tests for consistent statement-level C++ cout comment generation.

Verifies:
1. One-line cout statement receives a statement-level comment placed before it.
2. Multiline cout statement receives equivalent coverage placed before the statement,
   without continuation-line comment fragmentation.
3. Comparison and logical expressions in cout receive meaningful pre-statement comments.
4. Ternary conditional expressions in cout receive meaningful pre-statement comments.
5. Simple output (trivial cout) does not receive excessive comments.
6. Suspicious values (e.g. discount > 100%) trigger needs_review=True with specific review_reasons.
7. Input code is preserved verbatim in commented_code.
"""

from __future__ import annotations

import pytest

from app.model_processing.anchors import Anchor, render_commented_code
from app.model_processing.statement_comments import (
    detect_suspicious_logic,
    find_cout_statements,
    generate_cout_comment,
    process_statement_comments,
)
from app.schemas.analyze import AnalyzeResponse
from app.services import model_service, qwen_service


EXAMPLE_A_ONE_LINE = """cout << "Total after discount: " << productPrice * quantity - productPrice * quantity * discountPercentage / 100.0 << endl;"""

EXAMPLE_B_MULTILINE = """cout << "Total after discount: "
     << productPrice * quantity
            - productPrice * quantity * discountPercentage / 100.0
     << endl;"""

EXAMPLE_COMPARISON_LOGICAL = """cout << "Is eligible: " << (age >= 18 && hasLicense) << endl;"""

EXAMPLE_TERNARY = """cout << "Status: " << (score >= 50 ? "Pass" : "Fail") << endl;"""

EXAMPLE_SIMPLE = """cout << "Hello, World!" << endl;"""


# --- Test 1: One-line cout statement ----------------------------------------- #


def test_one_line_cout_receives_pre_statement_comment() -> None:
    stmts = find_cout_statements(EXAMPLE_A_ONE_LINE)
    assert len(stmts) == 1
    stmt = stmts[0]
    assert stmt.is_non_trivial
    assert stmt.has_arithmetic
    assert stmt.has_endl
    assert stmt.has_discount

    # Start with empty anchors (simulate model skipping the line)
    anchors: list[Anchor] = []
    processed = process_statement_comments(EXAMPLE_A_ONE_LINE, anchors)

    assert len(processed) == 1
    assert processed[0].line == 1
    assert processed[0].placement == "before"
    assert "subtotal" in processed[0].comment.lower()
    assert "discount" in processed[0].comment.lower()

    rendered = render_commented_code(EXAMPLE_A_ONE_LINE, processed)
    lines = rendered.split("\n")
    # Comment appears before the statement line
    assert lines[0].startswith("//")
    assert lines[-1] == EXAMPLE_A_ONE_LINE


# --- Test 2: Multiline cout statement ---------------------------------------- #


def test_multiline_cout_consolidates_and_matches_one_line_coverage() -> None:
    stmts = find_cout_statements(EXAMPLE_B_MULTILINE)
    assert len(stmts) == 1
    stmt = stmts[0]
    assert stmt.is_multiline
    assert stmt.is_non_trivial
    assert stmt.start_line == 1
    assert stmt.end_line == 4

    # Simulate fragmented model output on continuation lines (the original bug)
    fragmented_raw_anchors = [
        Anchor(line=1, code='cout << "Total after discount: "', comment="Print a label"),
        Anchor(line=2, code="<< productPrice * quantity", comment="Compute original subtotal"),
        Anchor(
            line=3,
            code="- productPrice * quantity * discountPercentage / 100.0",
            comment="Apply discount",
        ),
        Anchor(line=4, code="<< endl;", comment="Output total"),
    ]

    processed = process_statement_comments(EXAMPLE_B_MULTILINE, fragmented_raw_anchors)

    # Must be consolidated into exactly ONE anchor placed before the statement
    assert len(processed) == 1
    assert processed[0].line == 1
    assert processed[0].placement == "before"
    assert "subtotal" in processed[0].comment.lower()
    assert "discount" in processed[0].comment.lower()

    rendered = render_commented_code(EXAMPLE_B_MULTILINE, processed)
    lines = rendered.split("\n")

    # The comment is placed before line 1
    assert lines[0].startswith("//")
    # Continuation lines must not have inline comments attached
    for line in lines[1:]:
        assert "  //" not in line

    # Semantic equivalence with Example A
    one_line_processed = process_statement_comments(EXAMPLE_A_ONE_LINE, [])
    assert processed[0].comment == one_line_processed[0].comment


# --- Test 3: Comparison and logical operations ------------------------------- #


def test_comparison_and_logical_cout() -> None:
    stmts = find_cout_statements(EXAMPLE_COMPARISON_LOGICAL)
    assert len(stmts) == 1
    stmt = stmts[0]
    assert stmt.is_non_trivial
    assert stmt.has_comparison
    assert stmt.has_logical
    assert stmt.has_endl

    processed = process_statement_comments(EXAMPLE_COMPARISON_LOGICAL, [])
    assert len(processed) == 1
    assert processed[0].placement == "before"
    assert (
        "comparison" in processed[0].comment.lower() or "logical" in processed[0].comment.lower()
    )

    rendered = render_commented_code(EXAMPLE_COMPARISON_LOGICAL, processed)
    assert rendered.startswith("//")
    assert EXAMPLE_COMPARISON_LOGICAL in rendered


# --- Test 4: Ternary conditional expression ---------------------------------- #


def test_ternary_expression_cout() -> None:
    stmts = find_cout_statements(EXAMPLE_TERNARY)
    assert len(stmts) == 1
    stmt = stmts[0]
    assert stmt.is_non_trivial
    assert stmt.has_ternary
    assert stmt.has_endl

    processed = process_statement_comments(EXAMPLE_TERNARY, [])
    assert len(processed) == 1
    assert processed[0].placement == "before"
    assert "ternary" in processed[0].comment.lower()

    rendered = render_commented_code(EXAMPLE_TERNARY, processed)
    assert rendered.startswith("//")
    assert EXAMPLE_TERNARY in rendered


# --- Test 5: Simple output - no excessive comment --------------------------- #


def test_simple_output_is_trivial() -> None:
    stmts = find_cout_statements(EXAMPLE_SIMPLE)
    assert len(stmts) == 1
    stmt = stmts[0]
    # Simple string literal + endl is trivial
    assert not stmt.is_non_trivial

    # Should not invent or force comments
    processed = process_statement_comments(EXAMPLE_SIMPLE, [])
    assert len(processed) == 0

    rendered = render_commented_code(EXAMPLE_SIMPLE, processed)
    assert rendered == EXAMPLE_SIMPLE


# --- Test 6: Suspicious value check & review reasons ------------------------ #


def test_suspicious_discount_value_triggers_review() -> None:
    code = (
        "int discountPercentage = 200;\n"
        'cout << "Total after discount: "\n'
        "     << productPrice * quantity - productPrice * quantity * discountPercentage / 100.0\n"
        "     << endl;"
    )
    reasons = detect_suspicious_logic(code)
    assert len(reasons) >= 1
    assert "200%" in reasons[0]
    assert "exceeds 100%" in reasons[0]
    assert "negative total price" in reasons[0]


def test_normal_discount_does_not_trigger_suspicious_review() -> None:
    code = (
        "int discountPercentage = 20;\n"
        'cout << "Total after discount: " << productPrice * quantity * (1 - 0.2) << endl;'
    )
    reasons = detect_suspicious_logic(code)
    assert len(reasons) == 0


# --- Test 7: Verbatim input preservation in endpoint ----------------------- #


def test_analyze_endpoint_json_contract_with_review_reasons(client, monkeypatch) -> None:
    suspicious_code = (
        "int discountPercentage = 200;\n"
        'cout << "Total after discount: " << productPrice * quantity - productPrice * quantity * discountPercentage / 100.0 << endl;'
    )

    def fake_model(_code, analysis=None):
        return model_service.RawModelOutput(
            commented_code=suspicious_code,
            explanation="Calculates discount total.",
            verified=True,
        )

    monkeypatch.setattr(model_service, "run_model", fake_model)

    response = client.post("/analyze", json={"code": suspicious_code})
    assert response.status_code == 200

    data = response.json()
    assert data["needs_review"] is True
    assert isinstance(data["review_reasons"], list)
    assert len(data["review_reasons"]) >= 1
    assert any("200%" in r for r in data["review_reasons"])
    assert set(data.keys()) == {
        "input_code",
        "commented_code",
        "explanation",
        "needs_review",
        "review_reasons",
    }
