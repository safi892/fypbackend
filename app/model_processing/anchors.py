"""Bind model-generated comments to real lines of the submitted code.

Problem solved: the Qwen backend returns comments as ``{"line", "code",
"comment"}`` records rather than as a rewritten copy of the source. That is the
whole point — an anchor can be checked against the file it describes, so a
comment about a line the user never wrote is detectable instead of plausible.
The old CodeT5 path returned a rewritten copy, which is why the syntax gate and
``needs_review`` flag had to exist.

Why the quoted code is trusted over the line number: models miscount lines and
quote them accurately. Measured on the trained checkpoint, 43% of anchors
arrived with the right number, while 100% quoted a line that genuinely exists —
so relocating by the quote recovers the rest instead of discarding it.

Why this is duplicated from the training repository rather than imported: that
package pins ``transformers`` 4.57 and this service pins 4.46, and the backend
must stay deployable on its own. The alternative is a dependency conflict at
the top of the stack.

The two copies have now diverged on purpose. This one additionally discards
anchors that cannot be *true* of the line they name — see
``_is_punctuation_only`` and ``_contradicts_its_line``. The training copy must
not: it measures how well the model anchors, and silently repairing the output
there would flatter the metric it exists to report.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Anchor:
    """A comment bound to one line of the submitted source."""

    line: int
    code: str
    comment: str


@dataclass
class AnchorReport:
    """Anchors that survived checking, and what happened to the rest."""

    anchors: list[Anchor] = field(default_factory=list)
    exact: int = 0
    relocated: int = 0
    dropped: int = 0
    dropped_punctuation: int = 0
    dropped_numeric: int = 0
    #: Anchors discarded after repair by ``comment_validation``, for saying
    #: something the syntax tree refutes rather than for quoting a line that
    #: does not exist.
    rejected_semantic: int = 0

    @property
    def total(self) -> int:
        return self.exact + self.relocated + self.dropped

    @property
    def kept(self) -> int:
        """How many anchors actually survived to the response.

        Counted rather than derived from ``exact + relocated``, which is what
        this used to be and what it can no longer mean: anchors are also
        discarded *after* repair — by semantic validation, by the whole-file
        gate, and by chunk-overlap deduplication — and that sum keeps counting
        them. ``kept + dropped`` therefore need not equal ``total``.
        """
        return len(self.anchors)


def _is_punctuation_only(line: str) -> bool:
    """Say whether a line carries no name, keyword or number to describe.

    A comment anchored to ``}`` or ``};`` has nothing to be about, and the
    model fills the gap with invention: measured examples include "No action
    needed for the last element of the current pass" on a function's closing
    brace, and "the class is trivially destructible" on a class that holds a
    ``std::vector`` and therefore is not.

    ``else`` and ``break`` are deliberately *not* punctuation — comments on
    those are routinely useful ("target lies in the lower half").
    """
    return not any(character.isalnum() for character in line)


#: Integer literals, ignoring those glued to identifiers (``arr2`` is a name,
#: not the number two). Used to compare a comment's numbers against its line's.
_INTEGER = re.compile(r"(?<![\w.])\d+(?![\w.])")


def _contradicts_its_line(comment: str, line: str) -> bool:
    """Say whether a comment cites numbers that its line does not contain.

    This catches the one failure mode quoting cannot: the model pairs the right
    quoted line with the *wrong* comment. Measured on a real file, a comment
    reading "0 -> 1: weight 4" was attached to ``graph.addEdge(0, 2, 2);`` —
    the quote was exact and unique, so relocation had nothing to correct, and
    the comment described the previous line's edge.

    Deliberately narrow. It applies only when both sides carry integer
    literals, so ordinary prose about a numeric line is untouched, and it asks
    only that the comment's numbers appear in the line — a comment may say less
    than the line, never more. Checked against every correct comment in the
    measured sample: it fires on none of them.
    """
    quoted = set(_INTEGER.findall(comment))
    if not quoted:
        return False
    present = set(_INTEGER.findall(line))
    if not present:
        return False
    return not quoted <= present


def repair_anchors(code: str, raw: list[dict[str, Any]]) -> AnchorReport:
    """Place each generated comment on the line it actually quotes.

    An anchor quoting text that appears nowhere in ``code`` is a hallucination
    and is dropped rather than guessed at. Where the quoted line occurs several
    times, the occurrence nearest the claimed number wins, so a repeated
    ``return 0;`` attaches to the one the model was describing.

    :param code: the source the comments are about.
    :param raw: the model's ``line_comments`` array.
    :return: the surviving anchors plus counts of what was corrected.
    """
    lines = [line.strip() for line in code.split("\n")]
    positions: dict[str, list[int]] = {}
    for index, text in enumerate(lines, start=1):
        if text:
            positions.setdefault(text, []).append(index)

    report = AnchorReport()
    for item in raw or []:
        if not isinstance(item, dict):
            report.dropped += 1
            continue
        number = item.get("line")
        quoted = item.get("code")
        comment = item.get("comment")
        if not isinstance(quoted, str) or not isinstance(comment, str) or not comment.strip():
            report.dropped += 1
            continue
        quoted = quoted.strip()

        # Checked before locating the line: a brace is a brace wherever it is,
        # and relocating a comment that cannot be true of any of them wastes
        # the effort and then keeps the result.
        if _is_punctuation_only(quoted):
            report.dropped += 1
            report.dropped_punctuation += 1
            continue

        if isinstance(number, int) and 1 <= number <= len(lines) and lines[number - 1] == quoted:
            if _contradicts_its_line(comment, quoted):
                report.dropped += 1
                report.dropped_numeric += 1
                continue
            report.anchors.append(Anchor(line=number, code=quoted, comment=comment.strip()))
            report.exact += 1
            continue

        candidates = positions.get(quoted)
        if not candidates:
            report.dropped += 1
            continue
        if _contradicts_its_line(comment, quoted):
            report.dropped += 1
            report.dropped_numeric += 1
            continue
        target = (
            min(candidates, key=lambda c: abs(c - number))
            if isinstance(number, int)
            else candidates[0]
        )
        report.anchors.append(Anchor(line=target, code=quoted, comment=comment.strip()))
        report.relocated += 1

    report.anchors.sort(key=lambda anchor: anchor.line)
    return report


def render_commented_code(code: str, anchors: list[Anchor]) -> str:
    """Rebuild the source with each surviving comment appended to its line.

    This is what keeps the mobile contract intact: the app asks for
    ``commented_code`` and still receives the whole program as a string. The
    difference is invisible to the client and important anyway — the code is
    the user's own, copied verbatim, with comments attached, rather than a
    model's reconstruction of it. Nothing can be silently reworded, reindented
    or dropped, because the source lines are never regenerated.

    :param code: the submitted source.
    :param anchors: anchors already checked against that source.
    :return: the source with ``// comment`` appended to annotated lines.
    """
    by_line: dict[int, list[str]] = {}
    for anchor in anchors:
        by_line.setdefault(anchor.line, []).append(anchor.comment)

    out: list[str] = []
    for number, line in enumerate(code.split("\n"), start=1):
        comments = by_line.get(number)
        if not comments:
            out.append(line)
            continue
        joined = "; ".join(comment.rstrip(" .") for comment in comments)
        out.append(f"{line}  // {joined}" if line.strip() else line)
    return "\n".join(out)
