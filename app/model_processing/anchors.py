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
must stay deployable on its own. The logic is small and stable; the alternative
is a dependency conflict at the top of the stack.
"""

from __future__ import annotations

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

    @property
    def total(self) -> int:
        return self.exact + self.relocated + self.dropped

    @property
    def kept(self) -> int:
        return self.exact + self.relocated


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

        if isinstance(number, int) and 1 <= number <= len(lines) and lines[number - 1] == quoted:
            report.anchors.append(Anchor(line=number, code=quoted, comment=comment.strip()))
            report.exact += 1
            continue

        candidates = positions.get(quoted)
        if not candidates:
            report.dropped += 1
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
