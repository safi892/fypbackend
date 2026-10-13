"""Tests for saying what a rewrite changed, and why.

The reason is the interesting half. It must come from `defect_checks` — the
compiler, cppcheck or the parse tree — and never be invented, because the model
has a plausible reason for everything and 30% of its descriptions carry a false
claim. So: a line is reported as removed when the diff says so, and it carries a
motive only when a check supplied one.
"""

from __future__ import annotations

from app.model_processing.defect_checks import Finding, check
from app.services.change_explanation import explain, summarise

ORIGINAL = """int sumArray(const int numbers[], int size) {
    int total = 0;
   int totral = 0;
    for (int i = 0; i < size; ++i) {
        total += numbers[i];
    }
    return total;
}"""

#: What /optimize actually returned for it: the stray line gone, and a generated
#: doc block plus an inline comment on nearly every line.
REWRITE = """/**
 * Function: sumArray
 * Summary: Computes the sum of an integer array.
 */
int sumArray(const int numbers[], int size) {
    // Initialize total before accumulating values
    int total = 0;
    // Iterate through values using a loop
    for (int i = 0; i < size; ++i) {
        // Add the current value to the running sum
        total += numbers[i];
    }
    // Return the computed value to the caller
    return total;
}"""


def test_the_removed_line_is_named_with_the_reason_from_the_checks():
    findings = [Finding(rule="unused_variable", line=3, code="int totral = 0;",
                        message="unused variable 'totral'", certain=True, tier=1)]
    changes = explain(ORIGINAL, REWRITE, findings)
    removed = [c for c in changes if c.kind == "removed"]
    assert len(removed) == 1
    assert removed[0].code == "int totral = 0;"
    assert removed[0].line == 3
    assert removed[0].rule == "unused_variable"
    assert "totral" in removed[0].reason


def test_generated_comments_are_not_reported_as_changes():
    """The rewrite adds a doc block and an inline comment on most lines.

    A plain line diff reports twenty additions for one real change and buries
    it, which is the difference between a useful list and a wall.
    """
    changes = explain(ORIGINAL, REWRITE, [])
    assert all("//" not in c.code and not c.code.startswith("*") for c in changes)
    assert len([c for c in changes if c.kind == "removed"]) == 1


def test_a_change_with_no_established_reason_makes_no_claim():
    """Reported as changed, with `reason` left null rather than guessed."""
    changes = explain(ORIGINAL, REWRITE, [])
    removed = [c for c in changes if c.kind == "removed"]
    assert removed and all(c.reason is None and c.rule is None for c in removed)


def test_an_unchanged_rewrite_explains_nothing():
    assert explain(ORIGINAL, ORIGINAL, []) == []
    assert explain(ORIGINAL, "", []) == []
    assert summarise([]) == ""


def test_the_summary_counts_only_what_it_can_defend():
    """No adjectives: "cleaner" and "optimised" are judgements this cannot make."""
    findings = [Finding(rule="unused_variable", line=3, code="int totral = 0;",
                        message="unused variable 'totral'", certain=True, tier=1)]
    sentence = summarise(explain(ORIGINAL, REWRITE, findings))
    assert "1 line removed" in sentence
    assert "with a reason from the checks" in sentence
    for adjective in ("cleaner", "better", "optimis", "optimiz", "improved"):
        assert adjective not in sentence.lower()


def test_the_reason_survives_renumbering():
    """A reason belongs to a line of code, not to a position.

    The rewrite prepends a four-line doc block, so the matching line moves; if
    reasons were keyed by number the explanation would attach to the wrong line
    or vanish.
    """
    findings = check(ORIGINAL).findings
    changes = explain(ORIGINAL, REWRITE, findings)
    with_reason = [c for c in changes if c.reason]
    assert with_reason, "the checks found the unused variable but it was not matched"
    assert with_reason[0].code == "int totral = 0;"


# --- the coloured diff ------------------------------------------------------- #

def test_a_comment_only_change_is_context_not_a_change():
    """The model comments nearly every line.

    If those counted as changes the whole function would be red and green, and
    the one real edit would be invisible — which is exactly what the first
    version of this did.
    """
    from app.services.change_explanation import unified

    original = "int f(int n) {\n    int t = 0;\n    return t + n;\n}"
    commented = "int f(int n) {\n    int t = 0;   // accumulator\n    return t + n;   // done\n}"
    assert unified(original, commented) == []


def test_the_diff_marks_only_the_real_edit():
    from app.services.change_explanation import unified

    original = "int f(int n) {\n    int t = 0;\n    int unused = 1;\n    return t + n;\n}"
    rewritten = "int f(int n) {\n    int t = 0;   // accumulator\n    return t + n;\n}"
    rows = unified(original, rewritten)
    marked = [row for row in rows if row.kind != "context"]
    assert len(marked) == 1
    assert marked[0].kind == "removed"
    assert marked[0].text == "int unused = 1;"
    assert marked[0].old_line == 3 and marked[0].new_line is None


def test_an_identical_rewrite_produces_no_diff():
    from app.services.change_explanation import unified

    code = "int f(int n) {\n    return n;\n}"
    assert unified(code, code) == []
    assert unified(code, "") == []
