"""Say what a rewrite changed, and why, without asking the model why.

Problem solved: `/optimize` returns a verified rewrite and a note about the
*evidence* — "equivalent on 5 inputs" — which says nothing about what actually
changed. A user who pastes a function with a stray `int totral = 0;` gets it
back without the stray line and no statement that it was removed, let alone why.

Why the reason does not come from the model: it already has one for everything,
and 30% of its descriptions carry a confidently false claim. The reasons here
come from `defect_checks`, which only reports what the compiler, cppcheck or the
parse tree can establish. So a line is reported as removed when the diff says it
was removed, and it is given a *reason* only when a check supplies one. The
alternative — inventing a plausible motive for each edit — is how a tool starts
telling users confident things about their code that are not true.

Comment-only and blank lines are ignored. The rewrite arrives wrapped in a
generated doc block with an inline comment on most lines, so a plain line diff
reports twenty additions for one real change and buries it.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from app.model_processing.defect_checks import Finding

#: A line that carries no code: blank, `//`, or inside a `/* */` block. Matching
#: the common shapes is enough — a missed comment line costs one noisy row in a
#: list, not a wrong claim.
_COMMENT_ONLY = re.compile(r"^\s*(//|/\*|\*|\*/)?\s*$|^\s*//|^\s*/\*|^\s*\*")


@dataclass(frozen=True)
class Change:
    """One line the rewrite removed or added, and why, when that is known."""

    kind: str
    #: 1-based line in the code this change is *about*: the original for a
    #: removal, the rewrite for an addition.
    line: int
    #: The line verbatim, so the claim can be checked against the source.
    code: str
    #: From a `defect_checks` finding, or None when nothing established one.
    reason: str | None = None
    #: The rule that supplied the reason, for a client that wants to group.
    rule: str | None = None


def _without_trailing_comment(line: str) -> str:
    """The code on this line, with any `//` comment removed.

    String-aware, because `cout << "a // b"` must not be truncated at the
    quotes. Only `//` is handled: a trailing `/* */` on a code line is rare
    enough that mis-handling it costs one noisy row, not a wrong claim.

    This exists because the rewrite arrives with an inline comment on nearly
    every line, so comparing raw text reported *every* line of the function as
    removed-and-added. One real four-line change read as "9 removed, 13 added".
    """
    in_string = False
    quote = ""
    index = 0
    while index < len(line):
        character = line[index]
        if in_string:
            if character == "\\":
                index += 2
                continue
            if character == quote:
                in_string = False
        elif character in "\"'":
            in_string, quote = True, character
        elif character == "/" and line[index + 1 : index + 2] == "/":
            return line[:index].strip()
        index += 1
    return line.strip()


def _code_lines(source: str) -> list[tuple[int, str, str]]:
    """Numbered lines that carry code, as (number, display text, compare text).

    The two differ: what is shown is the line as written, what is compared is
    the line without its trailing comment.
    """
    rows: list[tuple[int, str, str]] = []
    for number, line in enumerate(source.split("\n"), start=1):
        if not line.strip() or _COMMENT_ONLY.match(line):
            continue
        comparable = _without_trailing_comment(line)
        if not comparable:
            continue
        rows.append((number, line.strip(), comparable))
    return rows


def explain(original: str, rewritten: str, findings: list[Finding]) -> list[Change]:
    """Diff the two versions and attach a checked reason where one exists.

    :param original: the code as submitted.
    :param rewritten: the accepted rewrite.
    :param findings: what `defect_checks.check` said about the *original*.
    :return: the real code changes, removals first, each with a reason if known.
    """
    if not rewritten.strip() or original.strip() == rewritten.strip():
        return []

    before = _code_lines(original)
    after = _code_lines(rewritten)
    # Keyed by the line text, because a reason belongs to a line of code rather
    # than to a position: the rewrite renumbers everything.
    reasons: dict[str, Finding] = {}
    for finding in findings:
        if finding.code:
            reasons.setdefault(_without_trailing_comment(finding.code), finding)
            reasons.setdefault(finding.code.strip(), finding)

    matcher = difflib.SequenceMatcher(
        a=[comparable for _, _, comparable in before],
        b=[comparable for _, _, comparable in after],
        autojunk=False,
    )
    changes: list[Change] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("delete", "replace"):
            for index in range(i1, i2):
                number, text, comparable = before[index]
                why = reasons.get(comparable) or reasons.get(text)
                changes.append(Change(
                    kind="removed", line=number, code=text,
                    reason=why.message if why else None,
                    rule=why.rule if why else None,
                ))
        if tag in ("insert", "replace"):
            for index in range(j1, j2):
                number, text, _ = after[index]
                changes.append(Change(kind="added", line=number, code=text))
    # Removals first: they are what a reader wants explained, and they are the
    # only kind that can carry a reason.
    changes.sort(key=lambda change: (change.kind != "removed", change.line))
    return changes


def summarise(changes: list[Change]) -> str:
    """One sentence a client can show above the list, or an empty string.

    Counts only what is defensible: how many lines went, how many of those have
    a checked reason, and how many arrived. No adjectives — "cleaner", "better"
    and "optimised" are judgements this cannot support.
    """
    removed = [change for change in changes if change.kind == "removed"]
    added = [change for change in changes if change.kind == "added"]
    explained = [change for change in removed if change.reason]
    if not removed and not added:
        return ""
    parts: list[str] = []
    if removed:
        tail = f", {len(explained)} with a reason from the checks" if explained else ""
        parts.append(f"{len(removed)} line{'s' if len(removed) != 1 else ''} removed{tail}")
    if added:
        parts.append(f"{len(added)} added")
    return "; ".join(parts) + "."


def most_informative(changes: list[Change], *, limit: int = 10) -> list[Change]:
    """The rows worth showing, when there are more than a reader will read.

    Ordered by what a reader can act on: a removal with a checked reason first,
    then other removals, then additions. Additions are last on purpose — "this
    line is new" is visible in the code itself, while "this line went, and here
    is why" is the part that is not.
    """
    if len(changes) <= limit:
        return changes

    def rank(change: Change) -> tuple[int, int]:
        if change.kind == "removed" and change.reason:
            return (0, change.line)
        if change.kind == "removed":
            return (1, change.line)
        return (2, change.line)

    return sorted(changes, key=rank)[:limit]
