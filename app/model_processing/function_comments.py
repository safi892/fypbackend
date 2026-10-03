"""Function-level doc comment generation for C++ functions.

Problem solved:
When analyzing files (especially those containing multiple helper and driver
functions), users need a structured, comprehensive multi-line explanation placed directly
above each function definition explaining:
- Function identity and short summary (how it works / purpose)
- Inputs (parameters it takes or explicitly "None (takes no parameters)")
- Process (how it processes: loops, recursion, function calls, conditional updates)
- Returns (return type or void)

Why Javadoc/Doxygen block comments:
/**
 * Function: {name}
 * Summary: {summary}
 * Inputs: {inputs}
 * Process: {process}
 * Returns: {returns}
 */
is the C++ standard documentation pattern, recognized as a docstring by IDEs,
compilers, and the tree-sitter static analyzer.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from app.model_processing.anchors import Anchor
from app.parsers import cpp_parser
from app.services.analyzer import (
    _CONDITION_TYPES,
    _LOOP_TYPES,
    _function_declarator,
    _function_name,
    _has_leading_comment,
    _is_recursive,
    _max_loop_depth,
    _return_type,
)

if TYPE_CHECKING:
    from tree_sitter import Node

LOGGER = logging.getLogger(__name__)


def _callees(body: Node | None, fn_name: str) -> list[str]:
    """Extract list of non-self function names called inside body, in source order."""
    if body is None:
        return []
    raw_calls: list[tuple[int, int, str]] = []
    for call in cpp_parser.iter_descendants(body, {"call_expression"}):
        c_fn = call.child_by_field_name("function")
        if c_fn is not None:
            callee = cpp_parser.node_text(c_fn).strip()
            if callee and callee != fn_name:
                raw_calls.append((call.start_point[0], call.start_point[1], callee))
    raw_calls.sort()
    calls: list[str] = []
    for _, _, callee in raw_calls:
        if callee not in calls:
            calls.append(callee)
    return calls


def extract_function_inputs(fn_node: Node) -> str:
    """Extract the declared parameters as a readable comma-separated string."""
    func_decl = _function_declarator(fn_node)
    if func_decl is None:
        return "None (takes no parameters)"
    param_list = func_decl.child_by_field_name("parameters")
    if param_list is None:
        param_list = cpp_parser.find_first(func_decl, {"parameter_list"})
    if param_list is None:
        return "None (takes no parameters)"

    params: list[str] = []
    for child in param_list.children:
        if child.type in {"parameter_declaration", "optional_parameter_declaration"}:
            text = cpp_parser.node_text(child).strip()
            if text and text != "void":
                params.append(text)
    return ", ".join(params) if params else "None (takes no parameters)"


def extract_function_returns(fn_node: Node) -> str:
    """Extract the declared return type."""
    ret = _return_type(fn_node).strip()
    if not ret or ret == "void":
        return "void (no return value)"
    return ret


def extract_function_description(
    fn_name: str,
    text: str,
    total_functions: int = 1,
    fn_node: Node | None = None,
) -> str:
    """Extract or synthesize a concise single-sentence summary for a function."""
    if fn_name == "main":
        return "Main entry point of the program."

    # Pattern 1: Function name followed by an action verb or explanation
    patterns = [
        rf'[`"]?{re.escape(fn_name)}[`"]?\s+(?:finds|computes|calculates|returns|recursively|iterates|scans|combines|checks|handles|processes|sorts|counts|determines|searches|updates)[^;.\n]+',
        rf'[`"]?{re.escape(fn_name)}[`"]?\s*[:–-]\s*[^;.\n]+',
        rf'(?:Function|function)\s+[`"]?{re.escape(fn_name)}[`"]?\s*[:–-]?\s*[^;.\n]+',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            clean = m.group(0).strip('`"').strip()
            clean = re.sub(
                r'^[`"]*' + re.escape(fn_name) + r'[`"]*\s*[:–-]?\s*',
                '',
                clean,
                flags=re.IGNORECASE,
            )
            clean = clean.rstrip(' .;,')
            if clean:
                return clean[:1].upper() + clean[1:] + "."

    # Pattern 2: Single-function submission with Purpose field
    if total_functions == 1:
        purpose_m = re.search(r'Purpose:\s*([^\n;]+)', text, re.IGNORECASE)
        if purpose_m:
            clean = purpose_m.group(1).strip().rstrip(' .;,')
            if clean:
                return clean[:1].upper() + clean[1:] + "."

    # Fallback to AST heuristics
    if fn_node is not None and _is_recursive(fn_node, fn_name):
        return f"Recursively processes input for function {fn_name}."

    return f"Computes and returns result for function {fn_name}."


def extract_function_process(
    fn_name: str,
    fn_node: Node,
    text: str,
    total_functions: int = 1,
) -> str:
    """Explain how the function processes its logic and algorithm."""
    if fn_name == "main":
        return "Initializes program execution and coordinates operations."

    if total_functions == 1:
        algo_m = re.search(r'Algorithm:\s*([^\n]+)', text, re.IGNORECASE)
        if algo_m:
            algo_text = algo_m.group(1).strip()
            if 10 < len(algo_text) <= 250:
                return algo_text.rstrip(' .;,') + "."
            sentences = re.split(r'(?<=[.!?])\s+', algo_text)
            if sentences:
                short = " ".join(sentences[:2]).strip().rstrip(' .;,')
                if short:
                    return short + "."

    body = fn_node.child_by_field_name("body")
    calls = _callees(body, fn_name)
    is_rec = _is_recursive(fn_node, fn_name)
    loop_depth = _max_loop_depth(body) if body else 0
    loops = list(cpp_parser.iter_descendants(body, _LOOP_TYPES)) if body else []
    conditionals = (
        list(cpp_parser.iter_descendants(body, _CONDITION_TYPES)) if body else []
    )

    if calls:
        calls_str = ", ".join(calls)
        return f"Calls {calls_str} to compute intermediate values and combines their results."
    if is_rec:
        if loop_depth > 0:
            return "Recursively processes elements while using loops for sub-computations."
        if conditionals:
            return "Checks the base case and recursively processes the remaining elements."
        return "Recursively processes elements until reaching the base case."
    if loop_depth > 1:
        return "Traverses elements using nested loops to perform comparisons or updates."
    if loops:
        if conditionals:
            return "Iterates through elements in a loop, applying conditional updates."
        return "Iterates through elements in a loop to compute the result."
    if conditionals:
        return "Evaluates conditional branches and returns the corresponding result."
    return "Executes sequential operations and returns the result."


def attach_function_doc_comments(
    code: str,
    anchors: list[Anchor],
    explanation: str = "",
) -> list[Anchor]:
    """Generate and attach detailed Javadoc/Doxygen doc comments above each function.

    Includes:
    - Function name
    - Summary
    - Inputs (parameters or 'None (takes no parameters)')
    - Process (how it processes logic)
    - Returns (return type or void)

    :param code: original submitted C++ source.
    :param anchors: existing line/statement anchors.
    :param explanation: high-level prose explanation from the model.
    :return: anchors list containing before-placement function docstrings.
    """
    root = cpp_parser.parse(code)
    if root is None:
        return anchors

    fn_nodes = list(cpp_parser.iter_descendants(root, {"function_definition"}))
    if not fn_nodes:
        return anchors

    fn_nodes.sort(key=lambda n: n.start_point[0])
    lines = code.splitlines()
    existing_before = {
        a.line for a in anchors if getattr(a, "placement", "inline") == "before"
    }

    result_anchors = list(anchors)
    total_fns = len(fn_nodes)

    for fn in fn_nodes:
        name = _function_name(fn)
        if not name:
            continue

        # If user code already has a leading comment/docblock, don't overwrite
        has_comment, has_doc = _has_leading_comment(fn)
        if has_comment or has_doc:
            continue

        start_line = fn.start_point[0] + 1
        if start_line in existing_before:
            continue

        desc = extract_function_description(name, explanation, total_fns, fn)
        inputs_desc = extract_function_inputs(fn)
        process_desc = extract_function_process(name, fn, explanation, total_fns)
        returns_desc = extract_function_returns(fn)

        doc_comment = (
            "/**\n"
            f" * Function: {name}\n"
            f" * Summary: {desc}\n"
            f" * Inputs: {inputs_desc}\n"
            f" * Process: {process_desc}\n"
            f" * Returns: {returns_desc}\n"
            " */"
        )
        start_code = lines[start_line - 1].strip() if start_line <= len(lines) else ""

        result_anchors.append(
            Anchor(
                line=start_line,
                code=start_code,
                comment=doc_comment,
                placement="before",
            )
        )

    result_anchors.sort(
        key=lambda a: (a.line, 0 if getattr(a, "placement", "inline") == "before" else 1)
    )
    return result_anchors
