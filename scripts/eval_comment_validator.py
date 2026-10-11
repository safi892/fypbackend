"""Measure what the comment-rejection rules catch, and what they get wrong.

Problem solved: every rule that discards a generated comment trades a visible
quality loss (a correct comment disappears) against an invisible gain (a wrong
one does). Tuning that trade by eye is guesswork, so this replays every comment
the backend has actually produced — hand-labelled correct or wrong in
``scripts/comment_validator_fixture.json`` — through the same rejection path a
request takes, and reports precision and recall for the decision.

Why a script and not a test: the numbers are evidence to cite and to re-derive
after a rule changes, not a pass/fail gate. A test that asserted "precision
stays at 1.0" would fail the moment the fixture grew, which is the one thing
this measurement wants to encourage. ``tests/test_comment_validation.py``
pins the individual rules instead.

Read the disagreements, not just the headline. A false positive is a correct
comment the service now throws away, and one of those is worth more attention
than several missed wrong ones.

Usage:
    uv run python scripts/eval_comment_validator.py
    uv run python scripts/eval_comment_validator.py path/to/other_fixture.json
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

# Make the project root importable when run as a standalone script.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.model_processing.anchors import repair_anchors  # noqa: E402
from app.model_processing.comment_validation import validate  # noqa: E402

_FIXTURE = Path(__file__).resolve().parent / "comment_validator_fixture.json"

#: How the two stages report a rejection. The anchor stage counts its reasons;
#: the validator names its rule directly.
_ANCHOR_REASONS = (
    ("dropped_punctuation", "punctuation", "the line carries no statement to describe"),
    ("dropped_numeric", "numeric", "cites numbers the line does not contain"),
)


@dataclass(frozen=True)
class Decision:
    """What the pipeline did with one labelled comment, and why."""

    program: str
    line: int
    code: str
    comment: str
    wrong: bool
    why: str
    rejected: bool
    rule: str
    detail: str


def judge(code: str, record: dict[str, object]) -> tuple[bool, str, str]:
    """Run one comment through the full rejection path a request would take.

    Both stages are exercised, because "did the service keep this comment" is
    the decision worth measuring — attributing a catch to the anchor stage or
    to the validator is what the ``rule`` field is for.

    :param code: the program the comment is about.
    :param record: one ``{"line", "code", "comment"}`` entry from the fixture.
    :return: ``(rejected, rule, detail)``; ``rule`` is ``""`` when kept.
    """
    proposed = {"line": record["line"], "code": record["code"], "comment": record["comment"]}
    report = repair_anchors(code, [proposed])
    if report.dropped:
        for counter, rule, detail in _ANCHOR_REASONS:
            if getattr(report, counter):
                return True, rule, detail
        return True, "unanchored", "quotes a line that is not in the file"

    validated = validate(code, report.anchors)
    if validated.rejections:
        rejection = validated.rejections[0]
        return True, rejection.rule, rejection.detail
    return False, "", ""


def evaluate(fixture: dict[str, object]) -> list[Decision]:
    """Replay every labelled comment in the fixture.

    :param fixture: the parsed fixture file.
    :return: one ``Decision`` per comment, in fixture order.
    """
    decisions: list[Decision] = []
    for program in fixture["programs"]:  # type: ignore[index]
        code = program["code"]
        for record in program["comments"]:
            rejected, rule, detail = judge(code, record)
            decisions.append(
                Decision(
                    program=program["name"],
                    line=record["line"],
                    code=record["code"],
                    comment=record["comment"],
                    wrong=record["label"] == "wrong",
                    why=record["why"],
                    rejected=rejected,
                    rule=rule,
                    detail=detail,
                )
            )
    return decisions


def _show(title: str, decisions: list[Decision]) -> None:
    """Print one group of decisions in full, or say the group is empty."""
    print(f"\n{title} ({len(decisions)})")
    print("-" * 78)
    if not decisions:
        print("  none")
        return
    for d in decisions:
        print(f"  {d.program}:{d.line}  {d.code}")
        print(f"    comment : {d.comment}")
        if d.rule:
            print(f"    rule    : {d.rule} — {d.detail}")
        if d.why:
            print(f"    label   : wrong — {d.why}")
        print()


def report(decisions: list[Decision]) -> None:
    """Print precision, recall and every disagreement in full."""
    caught = [d for d in decisions if d.rejected and d.wrong]
    false_alarms = [d for d in decisions if d.rejected and not d.wrong]
    missed = [d for d in decisions if not d.rejected and d.wrong]

    total = len(decisions)
    wrong = len(caught) + len(missed)
    rejected = len(caught) + len(false_alarms)

    print("=" * 78)
    print("COMMENT REJECTION — measured against hand-labelled output")
    print("=" * 78)
    print(f"  comments        : {total}")
    print(f"  labelled wrong  : {wrong} ({wrong / total:.1%})" if total else "  labelled wrong  : 0")
    print(f"  rejected        : {rejected}")
    precision = len(caught) / rejected if rejected else float("nan")
    recall = len(caught) / wrong if wrong else float("nan")
    print(f"  precision       : {precision:.2f}   (of what was rejected, how much was wrong)")
    print(f"  recall          : {recall:.2f}   (of what was wrong, how much was rejected)")

    by_rule: dict[str, int] = {}
    for d in decisions:
        if d.rejected:
            by_rule[d.rule] = by_rule.get(d.rule, 0) + 1
    print(f"  rules that fired: {by_rule or 'none'}")

    _show("CAUGHT — wrong comments the rules rejected", caught)
    _show("FALSE ALARMS — correct comments the rules threw away", false_alarms)
    _show("MISSED — wrong comments the rules kept", missed)

    if missed:
        print("A missed comment is not automatically a rule to add. An inverted claim")
        print('("moves the larger element" where the code moves the smaller) needs real')
        print("semantics; no mechanical rule reaches it, and pretending otherwise costs")
        print("precision. Add a rule only when the tree can refute the comment outright.")


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else _FIXTURE
    with open(path, encoding="utf-8") as handle:
        fixture = json.load(handle)

    report(evaluate(fixture))
    print(f"\nfixture: {path}")
    print(fixture.get("note", ""))


if __name__ == "__main__":
    main()
