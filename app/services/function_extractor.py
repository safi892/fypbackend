"""Extract per-function analysis and optimization breakdowns for C++ code.

Problem solved: when a file contains multiple C++ functions, users and client UIs
(like Android or Web) benefit from inspecting each function in isolation: its
own code, comments, documentation, and (on optimize) speedup, verification,
and focused diff.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.parsers import cpp_parser
from app.schemas.analyze import (
    ChangeExplanation,
    DiffRow,
    DocEntry,
    FunctionAnalysisItem,
    FunctionOptimizationItem,
    StaticAnalysis,
)
from app.services import change_explanation
from app.services.analyzer import _function_name, analyze_code
from app.services.optimization_service import OptimizationResult

if TYPE_CHECKING:  # pragma: no cover
    from tree_sitter import Node


def _extract_function_nodes(root: Node | None) -> list[tuple[str, int, int, Node]]:
    """Return (name, start_line, end_line, node) for every top-level function in AST."""
    if root is None:
        return []
    functions: list[tuple[str, int, int, Node]] = []
    for child in cpp_parser.iter_descendants(root, {"function_definition"}):
        name = _function_name(child)
        if not name:
            continue
        start_line = child.start_point[0] + 1
        end_line = child.end_point[0] + 1
        functions.append((name, start_line, end_line, child))
    return functions


def _get_leading_comments_start_line(fn_node: Node) -> int:
    """Find the 1-based start line of any comments directly preceding fn_node."""
    start_line = fn_node.start_point[0] + 1
    curr = fn_node.prev_sibling
    while curr is not None and curr.type == "comment":
        start_line = curr.start_point[0] + 1
        curr = curr.prev_sibling
    return start_line


def extract_analysis_functions(
    code: str,
    commented_code: str,
    analysis: StaticAnalysis | None,
    docs: list[DocEntry],
    global_explanation: str = "",
) -> list[FunctionAnalysisItem]:
    """Build isolated per-function documentation and commented code entries."""
    if not code.strip():
        return []

    code_lines = code.split("\n")
    commented_lines = commented_code.split("\n")

    # If analysis was not provided, compute it
    if analysis is None:
        analysis = analyze_code(code)

    if not analysis.functions:
        return []

    # Map documentation entries by function name
    docs_by_name: dict[str, DocEntry] = {d.function: d for d in docs}

    # Map commented functions from commented_code AST
    commented_root = cpp_parser.parse(commented_code)
    commented_map: dict[str, str] = {}
    if commented_root is not None:
        for name, _start, end_line, node in _extract_function_nodes(commented_root):
            doc_start_line = _get_leading_comments_start_line(node)
            slice_lines = commented_lines[doc_start_line - 1 : end_line]
            commented_map[name] = "\n".join(slice_lines)

    # Prepare sentences from global explanation to find function mentions
    explanation_sentences = [
        s.strip() for s in re.split(r"(?<=[.!?])\s+", global_explanation) if s.strip()
    ]

    items: list[FunctionAnalysisItem] = []
    # Sort functions in source order
    sorted_fns = sorted(analysis.functions, key=lambda f: f.start_line)

    for fn in sorted_fns:
        if fn.name == "<anonymous>":
            continue

        orig_slice = code_lines[fn.start_line - 1 : fn.end_line]
        fn_code = "\n".join(orig_slice)

        fn_commented = commented_map.get(fn.name) or fn_code
        doc_entry = docs_by_name.get(fn.name)

        # Build focused explanation
        matching_sentences = [
            s for s in explanation_sentences if re.search(rf"\b{re.escape(fn.name)}\b", s)
        ]
        if matching_sentences:
            fn_explanation = " ".join(matching_sentences[:2])
        elif doc_entry and doc_entry.description:
            fn_explanation = doc_entry.description
        else:
            fn_explanation = f"Logic and implementation for function '{fn.name}'."

        items.append(
            FunctionAnalysisItem(
                name=fn.name,
                start_line=fn.start_line,
                end_line=fn.end_line,
                code=fn_code,
                commented_code=fn_commented,
                documentation=doc_entry,
                explanation=fn_explanation,
            )
        )

    return items


def extract_optimization_functions(
    code: str,
    optimized_code: str,
    result: OptimizationResult,
    changes: list[ChangeExplanation] | None = None,
) -> list[FunctionOptimizationItem]:
    """Build isolated per-function optimization items with individual diffs and speedups."""
    if not code.strip():
        return []

    orig_lines = code.split("\n")
    opt_lines = optimized_code.split("\n")

    orig_analysis = analyze_code(code)
    if not orig_analysis.functions:
        return []

    # Parse functions from optimized code
    opt_root = cpp_parser.parse(optimized_code)
    opt_map: dict[str, str] = {}
    if opt_root is not None:
        for name, _start, end_line, node in _extract_function_nodes(opt_root):
            doc_start_line = _get_leading_comments_start_line(node)
            slice_lines = opt_lines[doc_start_line - 1 : end_line]
            opt_map[name] = "\n".join(slice_lines)

    items: list[FunctionOptimizationItem] = []
    sorted_fns = sorted(orig_analysis.functions, key=lambda f: f.start_line)

    overall_changed = getattr(result, "changed", False)
    overall_verified = getattr(result, "verified", False)
    overall_speedup = round(float(getattr(result, "speedup", 1.0) or 1.0), 2)
    overall_note = getattr(result, "note", "")
    target_fn_name = getattr(result, "target_fn_name", None)
    isolated_proposal = getattr(result, "isolated_proposal", None)

    for fn in sorted_fns:
        if fn.name == "<anonymous>":
            continue

        orig_slice = orig_lines[fn.start_line - 1 : fn.end_line]
        fn_orig_code = "\n".join(orig_slice)

        fn_opt_code = opt_map.get(fn.name)
        if not fn_opt_code and target_fn_name == fn.name and isolated_proposal:
            fn_opt_code = isolated_proposal
        if not fn_opt_code:
            fn_opt_code = fn_orig_code

        # Strip comments and empty lines to check if underlying logic changed
        raw_orig = re.sub(r"/\*[\s\S]*?\*/|//[^\n]*", "", fn_orig_code)
        raw_opt = re.sub(r"/\*[\s\S]*?\*/|//[^\n]*", "", fn_opt_code)
        norm_orig = [line.strip() for line in raw_orig.splitlines() if line.strip()]
        norm_opt = [line.strip() for line in raw_opt.splitlines() if line.strip()]

        if target_fn_name is not None and overall_changed:
            is_fn_changed = fn.name == target_fn_name
        elif overall_changed:
            is_fn_changed = norm_orig != norm_opt
        else:
            is_fn_changed = False

        if is_fn_changed:
            fn_speedup = overall_speedup if overall_speedup > 1.0 else 1.0
            fn_verified = overall_verified
            fn_note = (
                overall_note
                or f"Optimized function '{fn.name}' for improved algorithmic efficiency."
            )
            # Compute isolated function diff
            try:
                unified_rows = change_explanation.unified(fn_orig_code, fn_opt_code)
                fn_diff = [
                    DiffRow(
                        kind=r.kind,
                        old_line=r.old_line,
                        new_line=r.new_line,
                        text=r.text,
                    )
                    for r in unified_rows
                ]
            except Exception:
                fn_diff = []
        else:
            fn_speedup = 1.0
            fn_verified = True
            fn_note = "Function already optimal. No changes needed."
            fn_diff = []

        items.append(
            FunctionOptimizationItem(
                name=fn.name,
                start_line=fn.start_line,
                end_line=fn.end_line,
                original_code=fn_orig_code,
                optimized_code=fn_opt_code,
                changed=is_fn_changed,
                verified=fn_verified,
                speedup=fn_speedup,
                note=fn_note,
                diff=fn_diff,
            )
        )

    return items
