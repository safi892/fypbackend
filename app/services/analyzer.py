"""Deterministic static analysis for C++ source (Phase 3).

Problem solved
--------------
Before any AI runs, we need structured, *ground-truth* facts about the code
(functions, recursion, loop nesting, missing docs, complexity). These facts
feed the response itself, the suggestion generator, the documentation service
and the comment validator. They reach no LLM prompt on either backend: both
checkpoints are fine-tuned on fixed wording and drift on anything prepended to
it. Doing this deterministically (not via the model) keeps it cheap,
debuggable and stable.

Why this design
---------------
* Primary path uses tree-sitter AST traversal; if the parser is unavailable we
  fall back to a regex analyzer so the endpoint never hard-fails.
* Manual recursion over ``node.children`` (not the churny ``Query`` API) keeps
  the code robust across tree-sitter versions.
* Output is a fully-typed ``StaticAnalysis`` pydantic model so downstream
  services never guess field names.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.parsers import cpp_parser
from app.schemas.analyze import FunctionInfo, StaticAnalysis

if TYPE_CHECKING:  # pragma: no cover - typing only
    from tree_sitter import Node

# A function longer than this (in source lines) is flagged for splitting.
LONG_FUNCTION_LINES = 40

_LOOP_TYPES = {"for_statement", "while_statement", "do_statement", "for_range_loop"}
_CONDITION_TYPES = {"if_statement", "case_statement", "conditional_expression"}
# Every branch/loop/boolean op is one decision point for cyclomatic complexity.
_DECISION_TYPES = _LOOP_TYPES | _CONDITION_TYPES | {"catch_clause"}


def analyze_code(code: str, language: str = "cpp") -> StaticAnalysis:
    """Run static analysis on C++ source and return structured facts.

    Problem solved: single public entry point used by the router and the diff
    service. Why it picks AST vs regex: prefer accuracy (AST) but degrade
    gracefully when tree-sitter is unavailable.

    :param code: the C++ source to analyze.
    :param language: source language tag (currently only ``"cpp"``).
    :return: a ``StaticAnalysis`` with per-function info and aggregate metrics.
    """
    root: Node | None = cpp_parser.parse(code)
    if root is None:
        return _regex_analyze(code, language)
    return _ast_analyze(root, code, language)


# --------------------------------------------------------------------------- #
# AST-based helpers (tree-sitter)
# --------------------------------------------------------------------------- #
def _function_declarator(fn_node: Node) -> Node | None:
    """Walk down pointer/reference wrappers to the real ``function_declarator``.

    Problem solved: in C++ a function definition may be wrapped in
    ``pointer_declarator`` / ``reference_declarator`` layers, so the name and
    parameter list are not directly on ``function_definition``. Why a bounded
    loop: prevents infinite descent on malformed trees.

    :param fn_node: the ``function_definition`` node.
    :return: the inner ``function_declarator`` node, or ``None`` if absent.
    """
    declarator: Node | None = fn_node.child_by_field_name("declarator")
    seen = 0
    while declarator is not None and declarator.type != "function_declarator" and seen < 8:
        declarator = declarator.child_by_field_name("declarator")
        seen += 1
    is_func_decl = declarator is not None and declarator.type == "function_declarator"
    return declarator if is_func_decl else None


def _function_name(fn_node: Node) -> str:
    """Extract the function's identifier name from its declarator.

    Problem solved: the model, suggestions and documentation all key off the
    function name. Why via the declarator: the name lives on the innermost
    declarator, not the definition node.

    :param fn_node: the ``function_definition`` node.
    :return: the function name, or ``""`` when it cannot be resolved.
    """
    func_decl: Node | None = _function_declarator(fn_node)
    if func_decl is None:
        return ""
    name_node: Node | None = func_decl.child_by_field_name("declarator")
    if name_node is None:
        return ""
    return cpp_parser.node_text(name_node)


def _count_params(fn_node: Node) -> int:
    """Count the declared parameters of a function definition.

    Problem solved: parameter count drives the "group into a struct"
    suggestion. Why check ``optional_parameter_declaration`` too: C++ default
    arguments must be counted as real parameters.

    :param fn_node: the ``function_definition`` node.
    :return: number of parameters (0 when none or unresolvable).
    """
    func_decl: Node | None = _function_declarator(fn_node)
    if func_decl is None:
        return 0
    param_list: Node | None = func_decl.child_by_field_name("parameters")
    if param_list is None:
        param_list = cpp_parser.find_first(func_decl, {"parameter_list"})
    if param_list is None:
        return 0
    return sum(
        1
        for child in param_list.children
        if child.type in {"parameter_declaration", "optional_parameter_declaration"}
    )


def _max_loop_depth(node: Node, depth: int = 0) -> int:
    """Compute the deepest nesting of loops under ``node``.

    Problem solved: deeply nested loops are a readability/maintenance smell and
    trigger a review suggestion. Why recursive max: we need the *maximum*
    nesting, not just "is nested".

    :param node: subtree to scan.
    :param depth: current loop-nesting depth (used while recursing).
    :return: the maximum loop-nesting depth found.
    """
    best = depth
    for child in node.children:
        child_depth = depth + 1 if child.type in _LOOP_TYPES else depth
        best = max(best, _max_loop_depth(child, child_depth))
    return best


def _param_names(fn_node: Node) -> list[str]:
    """Read the declared parameter names, in order.

    Problem solved: the generated documentation used to list ``param1``,
    ``param2`` while the real names sat in the tree unread, which made the
    block useless to anyone reading it next to the code.

    Why a positional fallback: an unnamed parameter is legal C++
    (``void f(int)``), and the position is then the only thing left to say.

    :param fn_node: the ``function_definition`` node.
    :return: one name per declared parameter.
    """
    func_decl: Node | None = _function_declarator(fn_node)
    if func_decl is None:
        return []
    param_list: Node | None = func_decl.child_by_field_name("parameters")
    if param_list is None:
        param_list = cpp_parser.find_first(func_decl, {"parameter_list"})
    if param_list is None:
        return []

    names: list[str] = []
    for child in param_list.children:
        if child.type not in {"parameter_declaration", "optional_parameter_declaration"}:
            continue
        declarator: Node | None = child.child_by_field_name("declarator")
        identifier = (
            next(iter(cpp_parser.iter_descendants(declarator, {"identifier"})), None)
            if declarator is not None
            else None
        )
        names.append(
            cpp_parser.node_text(identifier) if identifier is not None else f"param{len(names) + 1}"
        )
    return names


def _return_type(fn_node: Node) -> str:
    """Read the declared return type, including pointer and reference markers.

    Problem solved: the documentation block said "See function signature for
    the return type" while holding the syntax tree that contains it.

    Why the declarator is walked: ``const std::string& f()`` keeps ``const
    std::string`` in the type field and the ``&`` on a ``reference_declarator``
    wrapping the function declarator, so the type field alone reads as a value
    return when it is not.

    :param fn_node: the ``function_definition`` node.
    :return: the return type as written, or ``""`` when unresolvable.
    """
    type_node: Node | None = fn_node.child_by_field_name("type")
    if type_node is None:
        return ""
    suffix = ""
    declarator: Node | None = fn_node.child_by_field_name("declarator")
    seen = 0
    while declarator is not None and declarator.type != "function_declarator" and seen < 8:
        if declarator.type == "pointer_declarator":
            suffix += "*"
        elif declarator.type == "reference_declarator":
            suffix += "&"
        declarator = declarator.child_by_field_name("declarator")
        seen += 1
    return cpp_parser.node_text(type_node) + suffix


def _recursive_lambda(body: Node) -> bool:
    """Detect a lambda in ``body`` that calls itself through its own variable.

    Problem solved: measured on a real submission, ``printAllPaths`` was
    reported as non-recursive while the ``std::function dfs`` inside it called
    ``dfs`` on every branch. Matching call sites against the *enclosing*
    function's name cannot see that, so the exponential traversal in the file
    went unflagged and the optimisation prompt was never given the fact.

    :param body: the enclosing function's body node.
    :return: ``True`` if a locally declared callable calls itself.
    """
    for declarator in cpp_parser.iter_descendants(body, {"init_declarator"}):
        name_node: Node | None = declarator.child_by_field_name("declarator")
        value: Node | None = declarator.child_by_field_name("value")
        if name_node is None or value is None:
            continue
        if value.type != "lambda_expression":
            value = next(iter(cpp_parser.iter_descendants(value, {"lambda_expression"})), None)
            if value is None:
                continue
        name = cpp_parser.node_text(name_node)
        if not name:
            continue
        for call in cpp_parser.iter_descendants(value, {"call_expression"}):
            callee: Node | None = call.child_by_field_name("function")
            if callee is not None and cpp_parser.node_text(callee) == name:
                return True
    return False


def _is_recursive(fn_node: Node, name: str) -> bool:
    """Detect whether a function's body contains recursion.

    Problem solved: recursion is the signal for the memoization/iterative
    suggestion. Why scan only the body: self-calls outside the function body do
    not make it recursive.

    Both direct self-calls and self-calling local lambdas count. The second is
    not recursion of *this* function in the strict sense, but it is recursion
    the reader has to reason about and the caller of this flag wants told.

    :param fn_node: the ``function_definition`` node.
    :param name: the resolved function name to match against call sites.
    :return: ``True`` if the function body contains a call to itself or to a
        self-calling local lambda.
    """
    body: Node | None = fn_node.child_by_field_name("body")
    if body is None:
        return False
    if name:
        for call in cpp_parser.iter_descendants(body, {"call_expression"}):
            callee: Node | None = call.child_by_field_name("function")
            if callee is not None and cpp_parser.node_text(callee) == name:
                return True
    return _recursive_lambda(body)


def _has_leading_comment(fn_node: Node) -> tuple[bool, bool]:
    """Inspect the comment immediately above a function for presence + doc style.

    Problem solved: missing inline comments and missing doc blocks are separate
    review signals, so we return both flags. Why "direct previous sibling": a
    doc block is conventionally placed on the line right above the definition.

    :param fn_node: the ``function_definition`` node.
    :return: ``(has_comment, has_doc)`` booleans.
    """
    prev: Node | None = fn_node.prev_sibling
    if prev is None or prev.type != "comment":
        return False, False
    text = cpp_parser.node_text(prev).strip()
    is_doc = text.startswith("/**") or text.startswith("///")
    return True, is_doc


def _cyclomatic_complexity(root: Node) -> int:
    """Compute cyclomatic complexity = decision points + 1.

    Problem solved: complexity is a well-known proxy for testability/risk and
    drives a high-complexity suggestion. Why add boolean ``&&``/``||`` counts:
    each binary logical operator is an extra decision branch.

    :param root: the syntax-tree root.
    :return: the cyclomatic complexity integer.
    """
    decisions = sum(1 for _ in cpp_parser.iter_descendants(root, _DECISION_TYPES))
    logical = 0
    for node in cpp_parser.iter_descendants(root, {"binary_expression"}):
        op_text = cpp_parser.node_text(node)
        logical += op_text.count("&&") + op_text.count("||")
    return decisions + logical + 1


def _ast_analyze(root: Node, code: str, language: str) -> StaticAnalysis:
    """Build a ``StaticAnalysis`` from a tree-sitter syntax tree.

    Problem solved: aggregates all per-function facts into the response model
    and computes the global metrics. Why a ``signatures`` counter: duplicate
    definition detection needs a name histogram.

    :param root: the parsed syntax-tree root node.
    :param code: the original source (kept for language tagging only).
    :param language: source language tag.
    :return: the fully populated ``StaticAnalysis``.
    """
    functions: list[FunctionInfo] = []
    signatures: dict[str, int] = {}

    fn_nodes = list(cpp_parser.iter_descendants(root, {"function_definition"}))
    total_loops = sum(1 for _ in cpp_parser.iter_descendants(root, _LOOP_TYPES))
    total_conditionals = sum(1 for _ in cpp_parser.iter_descendants(root, _CONDITION_TYPES))

    max_nested = 0
    for fn in fn_nodes:
        name = _function_name(fn) or "<anonymous>"
        start_line = fn.start_point[0] + 1
        end_line = fn.end_point[0] + 1
        length = end_line - start_line + 1
        params = _count_params(fn)
        recursive = _is_recursive(fn, name)
        body: Node | None = fn.child_by_field_name("body")
        loop_depth = _max_loop_depth(body) if body is not None else 0
        max_nested = max(max_nested, loop_depth)
        has_comment, has_doc = _has_leading_comment(fn)

        functions.append(
            FunctionInfo(
                name=name,
                start_line=start_line,
                end_line=end_line,
                length=length,
                params=params,
                param_names=_param_names(fn),
                returns=_return_type(fn),
                recursive=recursive,
                max_loop_depth=loop_depth,
                has_comment=has_comment,
                has_doc=has_doc,
            )
        )
        signatures[name] = signatures.get(name, 0) + 1

    long_functions = [f.name for f in functions if f.length > LONG_FUNCTION_LINES]
    duplicate_functions = [
        name for name, count in signatures.items() if count > 1 and name != "<anonymous>"
    ]
    missing_comments = sum(1 for f in functions if not f.has_comment)
    missing_docs = sum(1 for f in functions if not f.has_doc)

    return StaticAnalysis(
        language=language,
        functions=functions,
        function_count=len(functions),
        recursive=any(f.recursive for f in functions),
        max_nested_loops=max_nested,
        long_functions=long_functions,
        missing_comments=missing_comments,
        missing_docs=missing_docs,
        duplicate_functions=duplicate_functions,
        loops=total_loops,
        conditionals=total_conditionals,
        cyclomatic_complexity=_cyclomatic_complexity(root),
        parser="tree-sitter",
    )


# --------------------------------------------------------------------------- #
# Regex fallback (used only if tree-sitter is unavailable)
# --------------------------------------------------------------------------- #
_FUNC_RE = re.compile(
    r"^[\w:<>,&*\s]+?\b(\w+)\s*\([^;{]*\)\s*(?:const)?\s*\{",
    re.MULTILINE,
)


def _regex_analyze(code: str, language: str) -> StaticAnalysis:
    """Best-effort analysis using regex when no parser is available.

    Problem solved: guarantees the endpoint still returns a usable
    ``StaticAnalysis`` even in degenerate environments. Why coarse: regex cannot
    truly resolve scopes/loop depth, so those fields are left at safe defaults.

    :param code: the C++ source to scan.
    :param language: source language tag.
    :return: a ``StaticAnalysis`` with regex-derived (lower-confidence) facts.
    """
    names: list[str] = _FUNC_RE.findall(code)
    loops = len(re.findall(r"\b(for|while)\b", code))
    conditionals = len(re.findall(r"\b(if|case|switch)\b", code))
    signatures: dict[str, int] = {}
    for name in names:
        signatures[name] = signatures.get(name, 0) + 1

    functions = [
        FunctionInfo(
            name=name,
            start_line=0,
            end_line=0,
            length=0,
            params=0,
            recursive=len(re.findall(rf"\b{re.escape(name)}\s*\(", code)) > 1,
            max_loop_depth=0,
            has_comment=False,
            has_doc=False,
        )
        for name in names
    ]

    return StaticAnalysis(
        language=language,
        functions=functions,
        function_count=len(functions),
        recursive=any(f.recursive for f in functions),
        max_nested_loops=0,
        long_functions=[],
        missing_comments=len(functions),
        missing_docs=len(functions),
        duplicate_functions=[n for n, c in signatures.items() if c > 1],
        loops=loops,
        conditionals=conditionals,
        cyclomatic_complexity=loops + conditionals + 1,
        parser="regex-fallback",
    )
