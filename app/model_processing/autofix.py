"""Suggest a minimal punctuation fix for a tree-sitter syntax error.

Problem solved: the playground tells the user *where* C++ is broken but not
*what* to type, and the most common breakage (a forgotten ``;``, ``)``, ``}``)
is mechanical. This module proposes the fix the parser itself was expecting.

Why MISSING tokens instead of heuristics: tree-sitter records every token it
wanted but did not see as a ``MISSING`` node at the exact byte offset it
belongs at, so the position and the token are the parser's own answer rather
than a guess. The complement matters: errors that produce only ``ERROR`` nodes
(no ``MISSING``) get no suggestion at all, because inventing a fix for those
means guessing what the user meant. That is why this returns ``None`` for most
shape errors — a missing fix is the honest answer, and ``/validate-code`` still
reports the offending line.

Why a candidate is never auto-applied: the user submitted this code and the
caller must never rewrite it silently. The candidate is returned alongside the
original, the frontend shows it as a before/after diff, and the replacement
happens only on an explicit click. Every candidate is re-validated by the same
gate that rejected the original before it is offered, so a "fix" that does not
pass the syntax check never reaches the response.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.parsers import cpp_parser

if TYPE_CHECKING:  # pragma: no cover - only for static type checkers
    from tree_sitter import Node

# Tokens whose absence tree-sitter reports precisely enough to re-insert.
# Braces/brackets/semicolons/colons/commas are grammar punctuation with one
# obvious placement; anything else (operators, keywords, identifiers) would
# require inventing text, which this module refuses to do.
_FIXABLE: frozenset[str] = frozenset({";", ")", "}", "]", ":", ",", "(", "{", "["})

# One insertion per pass; a handful of passes covers multi-error snippets and
# bounds the work on the 100k-character request limit.
_MAX_PASSES = 8

# The fix must fit back into the request/editor limit (100k) or the client
# could not re-validate or re-submit what it just applied.
_MAX_CODE = 100_000

# A fix preview is a handful of touched lines; a diff longer than this means
# the reparse restructured the file and the preview would misrepresent it.
_MAX_EDITS = 10


@dataclass(frozen=True)
class FixEdit:
    """One line-level before/after pair, in the submitted code's coordinates.

    ``before`` is empty for a line the fix creates (for example a ``}`` moved
    onto its own line); ``after`` is never empty.
    """

    line: int
    before: str
    after: str


@dataclass(frozen=True)
class FixCandidate:
    """A whole-file fix proposal: the fixed source plus what changed.

    ``edits`` is computed against the *original* input so a client can render
    a preview without diffing two 100k strings itself.
    """

    code: str
    description: str
    edits: tuple[FixEdit, ...]


def _first_insertable(root: Node) -> Node | None:
    """Return the first (document-order) MISSING node whose type we can re-insert.

    Problem solved: error recovery can leave several ``MISSING`` nodes and any
    one of them may be un-fixable; we need the leftmost insertable one to start
    the repair loop. Why document order: fixing left-to-right keeps byte
    offsets of the remaining nodes valid relative to earlier insertions.

    :param root: the tree-sitter root node.
    :return: the node to insert, or ``None`` when the error has no safe fix.
    """
    stack: list[Node] = [root]
    while stack:
        node = stack.pop()
        if node.is_missing and node.type in _FIXABLE:
            return node
        # Reversed push visits children left-to-right (document order).
        stack.extend(reversed(node.children))
    return None


def _insertion_text(token: str, source: str, offset: int) -> str:
    """Build the exact text to splice in at ``offset``, with spacing rules.

    Problem solved: inserting the bare token produces technically-valid but
    ugly output (``return 0;return x``, ``(true{``). Why a few spacing rules
    rather than a formatter: only the inserted token's immediate neighbours
    matter, and a full formatter would rewrite the user's own lines — which
    this feature must never do.

    :param token: the MISSING token type (``;``, ``)``, ``}``, ...).
    :param source: the code the token is being inserted into.
    :param offset: byte offset where the token belongs.
    :return: the text (token plus any needed whitespace) to splice in.
    """
    following = source[offset : offset + 1]
    if token == "}":
        # A brace the parser wants at end-of-input reads better on its own line.
        rest_of_line = source[offset:].split("\n", 1)[0]
        if source[:offset].strip() and not rest_of_line.strip():
            return "\n}"
        return token
    if token in {")", "]", "}"}:
        if not following or following.isspace() or following in ")}],;":
            return token
        return token + " "
    if token in {";", ":", ","}:
        return token if not following or following.isspace() else token + " "
    # Openers need no spacing after them; the reparse gate judges the result.
    return token


def _syntax_ok(code: str) -> bool:
    """Apply the same acceptance rule the validator uses for submitted code.

    Problem solved: the fix must pass *the* gate that rejected the original —
    clean parse, or clean parse once wrapped as a statement snippet — or it is
    not a fix. Why duplicated here rather than imported: the validator lives in
    the router and raises HTTP errors; this module stays pure so it can be
    unit-tested without a client.

    :param code: the candidate source.
    :return: ``True`` when the validator would call this code valid.
    """
    root = cpp_parser.parse(code)
    if root is None:
        return False
    if not root.has_error:
        return True
    wrapped_root = cpp_parser.parse(f"void __snippet__() {{\n{code}\n}}")
    return wrapped_root is not None and not wrapped_root.has_error


def _line_edits(original: str, fixed: str) -> tuple[FixEdit, ...] | None:
    """Diff original against fixed at line granularity for the preview.

    Problem solved: the client needs "what changed and where" without doing
    its own diff, and it must be in the original file's line numbers so a
    preview row points at the user's own line. Why ``SequenceMatcher`` on
    lines: fixes touch whole lines, so line ops are exact and cheap.

    :param original: the code as submitted.
    :param fixed: the proposed fixed code.
    :return: the touched lines, or ``None`` when the diff is implausibly wide.
    """
    before_lines = original.splitlines()
    after_lines = fixed.splitlines()
    matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines, autojunk=False)
    edits: list[FixEdit] = []
    for tag, a1, a2, b1, b2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        edits.append(
            FixEdit(
                line=a1 + 1,
                before="\n".join(before_lines[a1:a2]),
                after="\n".join(after_lines[b1:b2]),
            )
        )
        if len(edits) > _MAX_EDITS:
            return None
    return tuple(edits)


def _describe(tokens: list[str], edits: tuple[FixEdit, ...]) -> str:
    """Summarise the proposal for the UI in one honest sentence.

    Problem solved: the preview needs a title that names the token and the
    line, so the user can judge the fix without reading the diff. Why line
    only for the single-token case: multi-token fixes span lines that shift,
    and the diff rows already carry those numbers.

    :param tokens: the MISSING token types inserted, in insertion order.
    :param edits: the line-level changes they produced.
    :return: the description text.
    """
    if len(tokens) == 1 and len(edits) == 1:
        return f"Add the missing '{tokens[0]}' at line {edits[0].line}."
    unique = list(dict.fromkeys(tokens))
    if len(unique) == 1:
        return f"Add {len(tokens)} missing '{unique[0]}' tokens."
    listed = ", ".join(f"'{t}'" for t in unique)
    return f"Add missing {listed} tokens."


def suggest_quick_fix(code: str) -> FixCandidate | None:
    """Propose the parser's expected punctuation for a broken snippet.

    Problem solved: turns a tree-sitter syntax error into a concrete,
    previewable edit. Why iterative: one parse can report several MISSING
    tokens and fixing one may reveal (or shift) the next, so each pass inserts
    the leftmost missing token and re-parses. Why a repeat-position guard: if
    the same token is still wanted at the same byte after we inserted it, the
    insertion did not help and looping would stack duplicates.

    :param code: the source as submitted.
    :return: a ``FixCandidate`` whose ``code`` passes the validator's syntax
        rule, or ``None`` when no safe punctuation fix exists (already-valid
        code, only ``ERROR`` nodes, parser unavailable, or oversized input).
    """
    if not code or len(code) > _MAX_CODE:
        return None

    current = code
    tokens: list[str] = []
    last_position: tuple[int, str] | None = None

    for _ in range(_MAX_PASSES):
        root = cpp_parser.parse(current)
        if root is None:
            return None
        if not root.has_error:
            break
        node = _first_insertable(root)
        if node is None:
            # Only ERROR nodes: the shape of the mistake is unknown, so we
            # would be guessing what the user meant. Offer nothing.
            return None
        position = (node.start_byte, node.type)
        if position == last_position:
            return None
        text = _insertion_text(node.type, current, node.start_byte)
        raw = bytearray(current.encode("utf8"))
        raw[node.start_byte : node.start_byte] = text.encode("utf8")
        current = raw.decode("utf8")
        if len(current) > _MAX_CODE:
            return None
        tokens.append(node.type)
        last_position = position
    else:
        # Ran out of passes without a clean reparse.
        return None

    if not tokens or not _syntax_ok(current):
        return None

    edits = _line_edits(code, current)
    if not edits:
        return None
    return FixCandidate(
        code=current,
        description=_describe(tokens, edits),
        edits=edits,
    )
