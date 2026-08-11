"""Tests for the semantic validator: comments the syntax tree can refute.

Anchoring proves a comment names a line the user wrote. These rules ask the
next question — can the comment be *true* of that line — and each test comes in
a pair: the wrong comment the rule exists to catch, and the correct comment a
sloppier version of the same rule would throw away. The second half of each
pair is the point. On the measured sample the rules reject three comments and
spare forty-three, and a rule that starts rejecting correct ones is worse than
no rule at all.

Nothing here needs a model or llama-server; the validator is deterministic.
"""

from __future__ import annotations

import json

from app.model_processing.anchors import Anchor, repair_anchors
from app.model_processing.comment_validation import validate
from app.parsers import cpp_parser
from app.services import qwen_service

NO_LOOP = """int add(int a, int b)
{
  int total = a + b;
  return total;
}"""

WITH_LOOP = """void bubbleSort(int arr[], int n)
{
  for (int i = 0; i < n - 1; i++)
    swap(arr[i], arr[i + 1]);
}"""

RECURSIVE_LAMBDA = """void walk(int start)
{
  std::function<void(int)> dfs = [&](int current) {
    dfs(current - 1);
  };
  dfs(start);
}"""


def anchor(line: int, code: str, comment: str) -> Anchor:
    return Anchor(line=line, code=code, comment=comment)


# --- rule: a claim of repetition in a function that never repeats -------------- #


def test_a_loop_claim_in_a_function_without_loops_is_rejected():
    report = validate(NO_LOOP, [anchor(3, "int total = a + b;", "Loop over the operands")])

    assert report.anchors == []
    assert report.rejected == 1
    assert report.rejections[0].rule == "loop"


def test_a_loop_claim_on_a_signature_line_survives():
    """Why the rule asks about the function and not the line.

    This comment is true of ``bubbleSort`` and false of line 1, which carries
    no loop and sits inside none. The obvious line-scoped rule rejects it.
    """
    kept = validate(
        WITH_LOOP,
        [anchor(1, "void bubbleSort(int arr[], int n)", "Iterates over the array in passes")],
    )

    assert kept.rejected == 0


def test_a_container_described_as_holding_each_thing_is_not_a_loop_claim():
    """``each`` and ``every`` are prose about data, not claims about control flow."""
    kept = validate(NO_LOOP, [anchor(3, "int total = a + b;", "each operand is added once")])

    assert kept.rejected == 0


# --- rule: a claim of recursion where nothing calls itself --------------------- #


def test_a_recursion_claim_in_a_flat_function_is_rejected():
    report = validate(NO_LOOP, [anchor(4, "return total;", "recurses until the base case")])

    assert report.rejected == 1
    assert report.rejections[0].rule == "recursion"


def test_recursion_through_a_local_lambda_counts_as_recursion():
    """The self-call is to the lambda's variable, not to ``walk``.

    Matching call sites against the enclosing function's name alone would
    reject this correct comment, which is why the rule reuses the analyzer's
    recursion check rather than re-deriving a simpler one.
    """
    comment = anchor(4, "dfs(current - 1);", "recurse into the neighbour")

    kept = validate(RECURSIVE_LAMBDA, [comment])

    assert kept.rejected == 0


# --- rule: a name cited as code that the function never mentions --------------- #


def test_a_cited_name_the_function_never_mentions_is_rejected():
    report = validate(
        NO_LOOP, [anchor(3, "int total = a + b;", "the cached merge_sort(a) result")]
    )

    assert report.rejected == 1
    assert report.rejections[0].rule == "scope"
    assert "merge_sort" in report.rejections[0].detail


def test_a_cited_name_the_function_does_mention_survives():
    code = "int longest(int nums[], int n)\n{\n  int dp[8];\n  return dp[0];\n}"

    kept = validate(code, [anchor(3, "int dp[8];", "dp[i] holds the best length so far")])

    assert kept.rejected == 0


def test_an_english_word_that_happens_to_be_an_identifier_elsewhere_survives():
    """The rule that would reject this is the one the design warns about.

    ``path`` is a variable in ``walk`` and ordinary English in a comment about
    ``main``. Matching comment words against the file's identifiers reads the
    prose as a citation and throws a correct comment away; requiring the
    comment to *write* the name as code is what prevents that.
    """
    code = "void walk(int path)\n{\n  record(path);\n}\n\nint main()\n{\n  walk(0);\n  return 0;\n}"

    kept = validate(code, [anchor(8, "walk(0);", "compute the shortest path from the source")])

    assert kept.rejected == 0


def test_complexity_prose_is_not_read_as_a_citation():
    """``O(1)`` is a claim about cost, not a call to a function named ``O``."""
    kept = validate(NO_LOOP, [anchor(3, "int total = a + b;", "runs in O(1) time")])

    assert kept.rejected == 0


# --- scope resolution ----------------------------------------------------------- #


def test_a_line_outside_every_function_is_judged_against_the_whole_file():
    """A member declaration belongs to no function, so the file is the scope."""
    code = "int counter;\n\nvoid tick()\n{\n  for (int i = 0; i < 3; i++)\n    counter++;\n}"

    kept = validate(code, [anchor(1, "int counter;", "counts the iterations of the loop below")])

    assert kept.rejected == 0


def test_without_a_parser_nothing_is_rejected(monkeypatch):
    """Fail open: with no tree there is nothing to contradict a comment."""
    monkeypatch.setattr(cpp_parser, "parse", lambda code: None)
    proposed = [anchor(3, "int total = a + b;", "Loop over the operands")]

    kept = validate(NO_LOOP, proposed)

    assert kept.anchors == proposed and kept.rejected == 0


# --- the rule that lives one stage earlier -------------------------------------- #


def test_a_comment_on_a_class_close_never_reaches_the_validator():
    """The design proposed sparing ``};`` after a class. The measurement did not.

    An end-of-declaration note reads as conventional, but the one the model
    actually wrote — "the class is trivially destructible" — is false of a
    class holding a ``vector``. ``anchors._is_punctuation_only`` drops it
    before this stage, so the validator has no rule for statement-free lines.
    """
    code = "class Graph\n{\n  vector<int> adj;\n};"

    report = repair_anchors(
        code, [{"line": 4, "code": "};", "comment": "the class is trivially destructible"}]
    )

    assert report.anchors == [] and report.dropped_punctuation == 1


# --- wiring --------------------------------------------------------------------- #


def test_a_refuted_comment_is_counted_and_kept_out_of_the_response(monkeypatch):
    """The stage has to be visible in the stats, or it is a silent quality change."""
    answer = json.dumps(
        {
            "line_comments": [
                {"line": 3, "code": "int total = a + b;", "comment": "Loop over the operands"},
                {"line": 4, "code": "return total;", "comment": "hand the sum back"},
            ]
        }
    )
    monkeypatch.setattr(qwen_service, "complete", lambda prompt, max_new_tokens=None: answer)

    anchors, report, _ = qwen_service.annotate(NO_LOOP)

    assert [a.line for a in anchors] == [4]
    assert report.rejected_semantic == 1
    assert report.kept == 1, "kept must count survivors, not exact + relocated"
