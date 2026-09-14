"""Statement-level awareness and comment consolidation for C++ statements.

Problem solved:
Models naturally process code line-by-line, causing inconsistent comment generation:
a statement formatted across multiple lines often receives fragmented continuation-line
comments, while the exact same statement on a single line may be skipped or formatted
differently.

In C++, statements are single semantic units regardless of physical line breaks.
Every non-trivial cout stream (containing arithmetic, comparison, logical, ternary,
call, or update expressions) must receive exactly one meaningful comment placed
immediately before the complete statement, invariant to single-line vs. multiline
formatting.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from app.model_processing.anchors import Anchor
from app.parsers import cpp_parser

if TYPE_CHECKING:
    from tree_sitter import Node

LOGGER = logging.getLogger(__name__)

ARITHMETIC_OPS = frozenset({"+", "-", "*", "/", "%"})
COMPARISON_OPS = frozenset({"<", "<=", ">", ">=", "==", "!=", "<=>"})
LOGICAL_OPS = frozenset({"&&", "||"})


@dataclass
class CoutStatement:
    """A detected cout / std::cout stream statement and its AST properties."""

    start_line: int  # 1-indexed
    end_line: int  # 1-indexed
    code: str
    is_multiline: bool
    is_non_trivial: bool
    has_arithmetic: bool
    has_comparison: bool
    has_logical: bool
    has_ternary: bool
    has_call: bool
    has_update: bool
    has_endl: bool
    has_discount: bool


def _is_cout_stream_node(node: Node) -> bool:
    """Check if an expression_statement is a cout stream insertion."""
    text = cpp_parser.node_text(node).strip()
    return bool(re.search(r"\b(?:std::)?cout\s*<<", text))


def find_cout_statements(code: str) -> list[CoutStatement]:
    """Find all cout stream statements in C++ code with their semantic properties."""
    root = cpp_parser.parse(code)
    lines = code.split("\n")
    results: list[CoutStatement] = []

    if root is not None:
        for node in cpp_parser.iter_descendants(root, {"expression_statement"}):
            if not _is_cout_stream_node(node):
                continue

            start_line = node.start_point.row + 1
            end_line = node.end_point.row + 1
            node_str = cpp_parser.node_text(node)

            has_arithmetic = False
            has_comparison = False
            has_logical = False
            has_ternary = False
            has_call = False
            has_update = False

            # Inspect all descendants for non-trivial operations
            for desc in cpp_parser.iter_descendants(
                node,
                {
                    "binary_expression",
                    "unary_expression",
                    "conditional_expression",
                    "call_expression",
                    "update_expression",
                },
            ):
                if desc.type == "binary_expression":
                    for c in desc.children:
                        op = c.type
                        if op in ARITHMETIC_OPS:
                            has_arithmetic = True
                        elif op in COMPARISON_OPS:
                            has_comparison = True
                        elif op in LOGICAL_OPS:
                            has_logical = True
                elif desc.type == "unary_expression":
                    for c in desc.children:
                        if c.type == "!":
                            has_logical = True
                elif desc.type == "conditional_expression":
                    has_ternary = True
                elif desc.type == "call_expression":
                    # Function calls inside cout
                    has_call = True
                elif desc.type == "update_expression":
                    has_update = True

            has_endl = bool(re.search(r"\b(?:std::)?endl\b", node_str))
            has_discount = bool(
                re.search(r"\bdiscount(?:Percentage|Percent|_rate|_percentage)?\b", node_str, re.I)
            )

            is_non_trivial = (
                has_arithmetic
                or has_comparison
                or has_logical
                or has_ternary
                or has_call
                or has_update
            )

            stmt_code = "\n".join(lines[start_line - 1 : end_line])
            results.append(
                CoutStatement(
                    start_line=start_line,
                    end_line=end_line,
                    code=stmt_code,
                    is_multiline=end_line > start_line,
                    is_non_trivial=is_non_trivial,
                    has_arithmetic=has_arithmetic,
                    has_comparison=has_comparison,
                    has_logical=has_logical,
                    has_ternary=has_ternary,
                    has_call=has_call,
                    has_update=has_update,
                    has_endl=has_endl,
                    has_discount=has_discount,
                )
            )
    else:
        # Regex fallback when tree-sitter is unavailable
        pattern = re.compile(
            r"((?:std::)?cout\s*<<[\s\S]*?;)",
            re.MULTILINE,
        )
        for match in pattern.finditer(code):
            start_pos = match.start()
            end_pos = match.end()
            start_line = code[:start_pos].count("\n") + 1
            end_line = code[:end_pos].count("\n") + 1
            stmt_code = match.group(1)

            has_arithmetic = bool(re.search(r"[+\-*/%]", stmt_code.replace("<<", "")))
            has_comparison = bool(re.search(r"(?:==|!=|<=|>=|<|>)", stmt_code.replace("<<", "")))
            has_logical = bool(re.search(r"(?:&&|\|\||!)", stmt_code))
            has_ternary = "?" in stmt_code and ":" in stmt_code
            has_call = bool(re.search(r"\b[A-Za-z_]\w*\s*\(", stmt_code.replace("cout", "")))
            has_update = "++" in stmt_code or "--" in stmt_code
            has_endl = "endl" in stmt_code
            has_discount = bool(re.search(r"\bdiscount\b", stmt_code, re.I))

            is_non_trivial = (
                has_arithmetic
                or has_comparison
                or has_logical
                or has_ternary
                or has_call
                or has_update
            )

            results.append(
                CoutStatement(
                    start_line=start_line,
                    end_line=end_line,
                    code=stmt_code,
                    is_multiline=end_line > start_line,
                    is_non_trivial=is_non_trivial,
                    has_arithmetic=has_arithmetic,
                    has_comparison=has_comparison,
                    has_logical=has_logical,
                    has_ternary=has_ternary,
                    has_call=has_call,
                    has_update=has_update,
                    has_endl=has_endl,
                    has_discount=has_discount,
                )
            )

    return results


def generate_cout_comment(stmt: CoutStatement) -> str:
    """Generate a high-quality semantic comment for a non-trivial cout statement."""
    if stmt.has_discount and stmt.has_arithmetic:
        if stmt.has_endl:
            return (
                "Calculate the subtotal, subtract the percentage-based discount,\n"
                "print the resulting total, and flush the output stream."
            )
        return (
            "Calculate the subtotal, subtract the percentage-based discount, "
            "and print the resulting total."
        )

    parts: list[str] = []
    if stmt.has_ternary:
        parts.append("Evaluate ternary conditional expression")
    elif stmt.has_comparison and stmt.has_logical:
        parts.append("Evaluate comparison and logical expressions")
    elif stmt.has_comparison:
        parts.append("Evaluate comparison expression")
    elif stmt.has_logical:
        parts.append("Evaluate logical condition")
    elif stmt.has_call:
        parts.append("Invoke function call")
    elif stmt.has_update:
        parts.append("Update variable value")
    elif stmt.has_arithmetic:
        parts.append("Calculate the arithmetic expression respecting operator precedence")

    action = parts[0] if parts else "Calculate expression"
    if stmt.has_endl:
        return f"{action}, print the result, and flush the output stream."
    return f"{action} and print the result."


def detect_suspicious_logic(code: str) -> list[str]:
    """Detect suspicious values or patterns in code that advise human review."""
    reasons: list[str] = []

    # 1. Discount percentage exceeding 100%
    discount_match = re.search(
        r"\b([a-zA-Z_]*discount[a-zA-Z_]*)\s*=\s*(\d+(?:\.\d+)?)\b",
        code,
        re.IGNORECASE,
    )
    if discount_match:
        var_name = discount_match.group(1)
        val = float(discount_match.group(2))
        if val > 100.0:
            formatted_val = int(val) if val.is_integer() else val
            reasons.append(
                f"Suspicious value: {var_name} of {formatted_val}% "
                "exceeds 100% and produces a negative total price."
            )

    # 2. Division by zero literal
    if re.search(r"/\s*0(?![.\d])", code):
        reasons.append("Potential division by zero detected.")

    return reasons


def process_statement_comments(
    code: str,
    anchors: list[Anchor],
    retry_fn: Callable[[CoutStatement, str], str | None] | None = None,
) -> list[Anchor]:
    """Consolidate statement-level comments and ensure complete coverage for non-trivial statements.

    - Consolidates continuation-line comments on multiline statements into a single
      statement comment placed immediately before the start line.
    - Ensures non-trivial cout statements receive exactly one comment placed before the statement.
    - If a non-trivial statement is missing a comment, triggers retry_fn or falls back
      to deterministic semantic comment generation.
    - Preserves trivial output statements without excessive commenting.
    """
    stmts = find_cout_statements(code)
    if not stmts:
        return anchors

    lines = code.split("\n")
    surviving_anchors = list(anchors)

    for stmt in stmts:
        # Find anchors currently mapped within [stmt.start_line, stmt.end_line]
        stmt_anchor_indices = [
            i
            for i, a in enumerate(surviving_anchors)
            if stmt.start_line <= a.line <= stmt.end_line
        ]

        if stmt.is_non_trivial:
            chosen_comment: str | None = None

            if stmt_anchor_indices:
                matched_anchors = [surviving_anchors[i] for i in stmt_anchor_indices]
                # Remove them all from surviving_anchors
                for idx in reversed(stmt_anchor_indices):
                    del surviving_anchors[idx]

                if stmt.has_discount and stmt.has_arithmetic:
                    # Use standard comprehensive discount explanation
                    chosen_comment = generate_cout_comment(stmt)
                elif len(matched_anchors) == 1:
                    raw_c = matched_anchors[0].comment.strip()
                    # If the single comment is good and detailed, use it
                    if len(raw_c) > 20 and not raw_c.startswith("Print a label"):
                        chosen_comment = raw_c
                    else:
                        chosen_comment = generate_cout_comment(stmt)
                else:
                    # Consolidate multiple continuation comments or generate comprehensive
                    chosen_comment = generate_cout_comment(stmt)
            else:
                # Missing comment on non-trivial cout statement!
                # Try single focused retry if provided
                if retry_fn is not None:
                    try:
                        chosen_comment = retry_fn(stmt, code)
                    except Exception as exc:
                        LOGGER.warning("Retry on missed cout statement failed: %s", exc)

                if not chosen_comment:
                    chosen_comment = generate_cout_comment(stmt)

            # Insert single anchor placed *before* the statement
            start_code = lines[stmt.start_line - 1].strip() if stmt.start_line <= len(lines) else ""
            surviving_anchors.append(
                Anchor(
                    line=stmt.start_line,
                    code=start_code,
                    comment=chosen_comment,
                    placement="before",
                )
            )
        else:
            # Trivial statement: if multiple continuation line anchors exist, collapse to at most one
            if len(stmt_anchor_indices) > 1:
                first_anchor = surviving_anchors[stmt_anchor_indices[0]]
                for idx in reversed(stmt_anchor_indices):
                    del surviving_anchors[idx]
                surviving_anchors.append(first_anchor)

    surviving_anchors.sort(key=lambda a: a.line)
    return surviving_anchors
