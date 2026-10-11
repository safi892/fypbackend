"""Tree-sitter based C++ parser wrapper.

Problem it solves
-----------------
The static analyzer and the diff service need a robust way to walk C++ source
code. Writing a hand-rolled C++ grammar with regex is fragile, so we delegate
parsing to the tree-sitter C++ grammar.

Why it is written this way
--------------------------
* The grammar is loaded **lazily and cached** behind a lock so the (relatively
  expensive) language build happens at most once and is thread-safe.
* If tree-sitter is unavailable at runtime (missing wheel / ABI mismatch),
  ``is_available`` returns ``False``. Callers then fall back to a regex
  analyzer and the endpoint stays alive instead of crashing.
* All node types come from ``tree_sitter.Node`` so every traversal function is
  statically typed.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - only for static type checkers
    from tree_sitter import Language, Node, Parser

# Guards one-time parser construction across threads.
_PARSER_LOCK = threading.Lock()

# Cached parser instance. ``None`` means "not loaded yet"; a failed load is
# recorded in ``_LOAD_ERROR`` so we avoid retrying on every call.
_PARSER: Parser | None = None
_LOAD_ERROR: str | None = None


def _load_parser() -> Parser | None:
    """Build (or return) the cached C++ parser, recording any load failure.

    Problem solved: constructing a tree-sitter ``Language`` is costly, so we
    do it once and reuse it. Why guarded: a ``threading.Lock`` + double-checked
    flag prevents two threads from building the grammar simultaneously.

    :return: the cached ``Parser`` instance, or ``None`` if tree-sitter could
        not be initialised (so callers can fall back to regex).
    """
    global _PARSER, _LOAD_ERROR

    if _PARSER is not None or _LOAD_ERROR is not None:
        return _PARSER

    with _PARSER_LOCK:
        if _PARSER is not None or _LOAD_ERROR is not None:
            return _PARSER

        try:
            import tree_sitter_cpp
            from tree_sitter import Language, Parser

            language: Language = Language(tree_sitter_cpp.language())
            _PARSER = Parser(language)
        except Exception as exc:  # pragma: no cover - environment dependent
            _LOAD_ERROR = str(exc)
            _PARSER = None

    return _PARSER


def is_available() -> bool:
    """Report whether the tree-sitter C++ parser is usable.

    Problem solved: callers (analyzer, diff) need a cheap way to decide
    between the AST path and the regex fallback without paying the cost of a
    full parse attempt.

    :return: ``True`` if a parser could be constructed, ``False`` otherwise.
    """
    return _load_parser() is not None


def load_error() -> str | None:
    """Return the last parser load error message, if any.

    Problem solved: when the AST path is unavailable we still want to surface
    the *reason* (e.g. missing grammar wheel) for debugging, without raising.

    :return: the captured error string, or ``None`` when loading succeeded.
    """
    _load_parser()
    return _LOAD_ERROR


def parse(code: str) -> Node | None:
    """Parse C++ source into a tree-sitter syntax tree root node.

    Problem solved: this is the single entry point that turns raw source text
    into a traversable AST. Why bytes: tree-sitter consumes UTF-8 bytes.

    :param code: the C++ source code to parse.
    :return: the root ``Node`` of the syntax tree, or ``None`` when no parser
        is available (caller should use the regex fallback).
    """
    parser: Parser | None = _load_parser()
    if parser is None:
        return None

    tree = parser.parse(bytes(code, "utf8"))
    return tree.root_node


def node_text(node: Node) -> str:
    """Decode a node's source bytes back into a Python ``str``.

    Problem solved: tree-sitter stores node text as raw bytes; every consumer
    needs the decoded string. Why errors="replace": malformed UTF-8 in a
    source snippet should not abort analysis.

    :param node: the tree-sitter node whose source slice to read.
    :return: the decoded source text covered by the node (empty if synthetic).
    """
    text = node.text
    if text is None:
        return ""
    return text.decode("utf8", errors="replace")


def iter_descendants(node: Node, types: set[str]) -> Iterator[Node]:
    """Yield every descendant (including ``node`` itself) whose type is wanted.

    Problem solved: many detectors (recursion, loops, functions) need a
    depth-first scan. Why a generator + explicit stack: it is allocation-light
    and version-robust, avoiding the churny tree-sitter ``Query`` API.

    :param node: the subtree root to scan.
    :param types: the set of node ``type`` strings to keep.
    :return: an iterator over matching descendant nodes.
    """
    stack: list[Node] = [node]
    while stack:
        current: Node = stack.pop()
        if current.type in types:
            yield current
        stack.extend(current.children)


def find_first(node: Node, types: set[str]) -> Node | None:
    """Return the first immediate child of ``node`` whose type is wanted.

    Problem solved: a couple of node shapes (e.g. ``parameter_list``) are not a
    named field, so we need a shallow search of direct children only.

    :param node: the node whose children to inspect.
    :param types: accepted child ``type`` strings.
    :return: the matching child node, or ``None`` if none match.
    """
    for child in node.children:
        if child.type in types:
            return child
    return None
