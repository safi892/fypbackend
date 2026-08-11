"""Discard anchored comments that the syntax tree contradicts.

Problem solved: ``anchors.repair_anchors`` proves a comment is *attached* to a
line the user actually wrote. It proves nothing about whether the comment is
*true* of that line. Measured on the recorded sample (46 comments over two
programs, ``scripts/comment_validator_fixture.json``), five were factually
wrong while being perfectly anchored — the documented ~9% error rate. This
stage removes the subset of those that the tree can refute mechanically.

Why deterministic rather than a second model pass: asking the generator to
check its own answer doubles inference cost (~18 tok/s on CPU) and inherits its
blind spots. The syntax tree already holds the facts these rules need, and a
rejection that comes from the tree can be explained to the user; one that comes
from a model cannot.

Why the rules are scoped to the enclosing *function* and not to the anchored
*line*: the line-scoped version is what looks obvious and it rejects correct
comments. "Iterates over the array comparing adjacent elements" written on a
function's signature line is true of the function and false of the line, and a
line-scoped loop check throws it away. Dropping a correct comment is a visible
quality loss; missing a wrong one only leaves the status quo, so every rule
here is deliberately the weaker, near-certain form. That is also why the
per-line fact map the design called for collapsed into a per-scope one: none of
the surviving rules read a fact narrower than the function.

The third rule the design called for — rejecting comments on lines that hold no
statement — is not repeated here. It already lives in
``anchors._is_punctuation_only``, which runs earlier and drops those anchors
before this stage ever sees them.

``scripts/eval_comment_validator.py`` is the measurement that sets these
boundaries; re-run it before loosening any rule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.model_processing.anchors import Anchor
from app.parsers import cpp_parser

# Imported rather than copied even though it points from ``model_processing``
# up into ``services``: the analyzer already answers "is this a loop" and "does
# this function call itself" for the response the user reads, and two answers
# that could disagree is worse than one import that looks upside down.
from app.services.analyzer import _LOOP_TYPES, _function_name, _is_recursive

if TYPE_CHECKING:  # pragma: no cover - typing only
    from tree_sitter import Node

#: Words that assert the line makes work repeat. ``each`` and ``every`` are
#: excluded on purpose: "each entry holds a (neighbor, weight) pair" is prose
#: about a container, not a claim about control flow, and including them fired
#: on correct comments in the measured sample.
_LOOP_CLAIM = re.compile(
    r"\b(loop|loops|looping|looped"
    r"|iterate|iterates|iterated|iterating|iteration|iterations"
    r"|repeat|repeats|repeated|repeatedly"
    r"|traverse|traverses|traversed|traversing|traversal)\b",
    re.IGNORECASE,
)

#: Words that assert the code calls itself.
_RECURSION_CLAIM = re.compile(
    r"\b(recurse|recurses|recursed|recursing|recursion|recursive|recursively)\b"
    r"|\bcalls?\s+itself\b",
    re.IGNORECASE,
)

# A comment token is only checked against the code when the comment itself
# writes it *as* code. Three shapes qualify, and ordinary English matches none
# of them — which is the whole point, because a rule that reads prose as
# identifiers rejects correct comments faster than it catches wrong ones.
#: ``dp[i]``, ``dfs(next)`` — written as a call or a subscript.
_CALL_FORM = re.compile(r"(?<![\w.])([A-Za-z_]\w*)(?=[(\[])")
#: ``max_element``, ``numeric_limits`` — carries an underscore.
_SNAKE_CASE = re.compile(r"(?<![\w.])([A-Za-z]\w*_\w+)\b")
#: ``printAllPaths``, ``addEdge`` — carries an internal capital.
_CAMEL_CASE = re.compile(r"(?<![\w.])([a-z]+[A-Z]\w*)\b")

#: Every word-shaped run in a piece of source. Used to decide whether a name
#: the comment cites appears in the function at all; deliberately a superset of
#: what the tree calls an identifier, because over-including here can only make
#: the rule refuse to fire.
_WORD = re.compile(r"[A-Za-z_]\w*")

#: ``O(n)`` and ``f(x)`` are prose about complexity far more often than they are
#: citations of a symbol, so a single letter written in call form is ignored.
_MIN_CITED_NAME = 2


@dataclass(frozen=True)
class Rejection:
    """One comment the tree refutes, and the rule that refuted it."""

    anchor: Anchor
    rule: str
    detail: str


@dataclass
class ValidationReport:
    """What survived semantic validation, and why the rest did not."""

    anchors: list[Anchor] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)

    @property
    def rejected(self) -> int:
        return len(self.rejections)


@dataclass(frozen=True)
class _Scope:
    """The facts a rule may consult about the function a comment sits in."""

    #: What to call this scope when explaining a rejection.
    where: str
    #: Every word-shaped run in the scope's source text.
    words: frozenset[str]
    has_loop: bool
    has_self_call: bool


def validate(code: str, anchors: list[Anchor]) -> ValidationReport:
    """Drop anchored comments that contradict the code they describe.

    :param code: the submitted source, in whole-file coordinates.
    :param anchors: anchors already checked against that source.
    :return: the surviving anchors plus one ``Rejection`` per discarded comment.
    """
    root: Node | None = cpp_parser.parse(code)
    if root is None:
        # Fail open. This stage exists to reject comments the tree refutes, and
        # with no tree it refutes nothing; the regex fallback cannot resolve a
        # function's extent, which every rule here depends on.
        return ValidationReport(anchors=list(anchors))

    by_line, whole_file = _scopes(root, code)

    kept: list[Anchor] = []
    rejections: list[Rejection] = []
    for anchor in anchors:
        scope = by_line.get(anchor.line, whole_file)
        reason = _refutation(anchor.comment, scope)
        if reason is None:
            kept.append(anchor)
        else:
            rule, detail = reason
            rejections.append(Rejection(anchor=anchor, rule=rule, detail=detail))
    return ValidationReport(anchors=kept, rejections=rejections)


def _refutation(comment: str, scope: _Scope) -> tuple[str, str] | None:
    """Return the rule that refutes ``comment``, or ``None`` if none does.

    :param comment: the generated comment text.
    :param scope: facts about the function the comment is anchored inside.
    :return: ``(rule name, human-readable detail)``, or ``None`` to keep it.
    """
    if not scope.has_loop and _LOOP_CLAIM.search(comment):
        return "loop", f"claims repetition, but {scope.where} contains no loop"

    if not scope.has_self_call and _RECURSION_CLAIM.search(comment):
        return "recursion", f"claims recursion, but {scope.where} calls nothing of its own name"

    cited = sorted(name for name in _cited_names(comment) if name not in scope.words)
    if cited:
        return "scope", f"names {', '.join(cited)}, which {scope.where} never mentions"

    return None


def _cited_names(comment: str) -> set[str]:
    """Collect the tokens a comment writes as code rather than as prose.

    Why form and not a dictionary lookup: matching comment words against the
    file's identifiers reads ordinary English as code, because real programs
    are full of variables called ``path``, ``next`` and ``max``. A comment on
    ``main`` reading "compute shortest path distances" would then be rejected
    for citing ``path``, which is correct English and a correct comment.

    :param comment: the generated comment text.
    :return: the names the comment cites, possibly empty.
    """
    names: set[str] = set()
    for pattern in (_CALL_FORM, _SNAKE_CASE, _CAMEL_CASE):
        names.update(match.group(1) for match in pattern.finditer(comment))
    return {name for name in names if len(name) >= _MIN_CITED_NAME}


def _scopes(root: Node, code: str) -> tuple[dict[int, _Scope], _Scope]:
    """Map every line covered by a function to that function's facts.

    Why smallest span wins: a method body sits inside a ``class_specifier``
    whose own lines are not the method's, and a line claimed by two functions
    belongs to the inner one.

    :param root: the parsed syntax-tree root.
    :param code: the source the tree was built from.
    :return: ``(line -> scope, whole-file scope)``; the second is the fallback
        for lines outside every function, such as a member declaration.
    """
    functions = list(cpp_parser.iter_descendants(root, {"function_definition"}))

    whole_file = _Scope(
        where="the file",
        words=frozenset(_WORD.findall(code)),
        has_loop=any(True for _ in cpp_parser.iter_descendants(root, _LOOP_TYPES)),
        has_self_call=any(_is_recursive(fn, _function_name(fn)) for fn in functions),
    )

    by_line: dict[int, _Scope] = {}
    # Widest first, so an inner function overwrites the outer one's claim.
    for fn in sorted(functions, key=lambda node: node.end_byte - node.start_byte, reverse=True):
        name = _function_name(fn)
        body: Node | None = fn.child_by_field_name("body")
        scope = _Scope(
            where=f"{name}()" if name else "the enclosing function",
            words=frozenset(_WORD.findall(cpp_parser.node_text(fn))),
            has_loop=(
                body is not None
                and any(True for _ in cpp_parser.iter_descendants(body, _LOOP_TYPES))
            ),
            has_self_call=_is_recursive(fn, name),
        )
        for line in range(fn.start_point[0] + 1, fn.end_point[0] + 2):
            by_line[line] = scope

    return by_line, whole_file
