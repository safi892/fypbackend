"""Tests for the findings that do not need the model.

Each rule gets a case it must fire on and a case it must stay silent on. The
silent half matters more: the false-positive literature is consistent that a
detector which cries wolf gets switched off, and this project already measured
that cost once — the defect-aware prompt bought one extra problem named and two
extra false claims, and was withdrawn for it.
"""

from __future__ import annotations

import pytest

from app.core.compiler import find_cxx_compiler
from app.model_processing.defect_checks import (
    check,
    cppcheck_available,
    from_parse_tree,
    from_runtime,
)

needs_compiler = pytest.mark.skipif(
    find_cxx_compiler() is None, reason="needs a C++ compiler"
)


def rules(code: str) -> list[str]:
    return [finding.rule for finding in from_parse_tree(code)]


# --- the examples this module was written for -------------------------------- #

REVERSE_DIGITS = """#include <iostream>
using namespace std;

int main() {
    int num, reversed = 0;
    cout << "Enter a number: ";
    cin >> num;
    int pp = 10;
    int temp = num;
    while (temp != 0) {
        reversed = reversed * 10 + temp % 10;
        temp /= pp;
    }
    cout << "Reversed: " << reversed << endl;
    return 0;
}"""

HARDCODED_FLAG = """#include <iostream>
using namespace std;
int main() {
    bool isOn = true;
    if (isOn) {
        cout << "The switch is ON." << endl;
    } else {
        cout << "The switch is OFF." << endl;
    }
    return 0;
}"""

FLAG_NEVER_CLEARED = """#include <iostream>
using namespace std;
int main() {
    bool running = true;
    while (running) {
        if (running) {
            cout << "Loop is running..." << endl;
        } else {
            cout << "Loop stopped." << endl;
        }
    }
    return 0;
}"""


def test_a_constant_read_once_is_reported():
    """`pp` holds 10 and is read once, so the literal can replace it.

    The compiler says nothing here, correctly: `pp` *is* read, so
    `-Wunused-variable` does not apply. This is the checkable half of
    "unnecessary variable".
    """
    findings = [f for f in from_parse_tree(REVERSE_DIGITS) if f.rule == "constant_used_once"]
    assert len(findings) == 1
    assert findings[0].code == "int pp = 10;"
    assert "pp" in findings[0].message


def test_a_constant_read_twice_is_left_alone():
    code = """int f(int n) {
    int step = 2;
    return (n / step) + (n % step);
}"""
    assert "constant_used_once" not in rules(code)


def test_a_variable_that_is_reassigned_is_left_alone():
    code = """int f(int n) {
    int acc = 1;
    acc = acc + n;
    return acc;
}"""
    assert "constant_used_once" not in rules(code)


def test_a_variable_initialised_from_another_name_is_left_alone():
    """Only a literal can be substituted without thinking about scope."""
    code = """int f(int n) {
    int copy = n;
    return copy;
}"""
    assert "constant_used_once" not in rules(code)


# --- conditions decided before the program runs ------------------------------ #

def test_an_else_after_an_always_true_flag_is_reported():
    findings = [f for f in from_parse_tree(HARDCODED_FLAG) if f.rule == "dead_branch"]
    assert len(findings) == 1
    assert "isOn" in findings[0].message
    assert "always true" in findings[0].message


def test_the_flag_is_not_also_reported_as_a_variable_to_inline():
    """One problem, one finding.

    `isOn` does satisfy `constant_used_once` — a literal, never reassigned, read
    once — but "use the value directly" is the wrong advice for a flag whose
    real problem is that a branch is unreachable.
    """
    assert "constant_used_once" not in rules(HARDCODED_FLAG)


def test_a_loop_on_an_always_true_flag_reports_both_problems():
    """Two genuine defects: the loop cannot end *and* the else is dead."""
    found = set(rules(FLAG_NEVER_CLEARED))
    assert "infinite_loop" in found
    assert "dead_branch" in found


def test_a_flag_that_is_cleared_somewhere_is_left_alone():
    """The whole rule rests on the variable never being written."""
    code = """#include <iostream>
int main() {
    bool running = true;
    int n = 0;
    while (running) {
        std::cout << n;
        if (n > 3) { running = false; }
        n = n + 1;
    }
    return 0;
}"""
    assert rules(code) == []


def test_a_negated_constant_condition_is_read_correctly():
    code = """#include <iostream>
int main() {
    bool done = false;
    if (!done) {
        std::cout << "working";
    } else {
        std::cout << "finished";
    }
    return 0;
}"""
    findings = [f for f in from_parse_tree(code) if f.rule == "dead_branch"]
    assert len(findings) == 1
    assert "always false" in findings[0].message


def test_an_always_false_condition_condemns_the_if_body_not_the_else():
    code = """#include <iostream>
int main() {
    bool enabled = false;
    if (enabled) {
        std::cout << "on";
    }
    return 0;
}"""
    findings = [f for f in from_parse_tree(code) if f.rule == "dead_branch"]
    assert len(findings) == 1
    assert "body of this if" in findings[0].message


def test_a_condition_that_needs_a_solver_is_left_alone():
    """`n > 0 && n < 0` is unreachable, and saying so needs more than this.

    Staying silent is the honest answer: the alternative is a rule that
    sometimes guesses, and a detector that guesses gets switched off.
    """
    code = """int main() {
    int n = 5;
    if (n > 0 && n < 0) { return 1; }
    return 0;
}"""
    assert "dead_branch" not in rules(code)


# --- unreachable code -------------------------------------------------------- #

def test_a_statement_after_return_is_reported():
    code = """int f(int n) {
    return n;
    int extra = n * n;
    return extra;
}"""
    assert "unreachable_code" in rules(code)


def test_a_return_inside_a_branch_does_not_condemn_what_follows():
    """`return` under an `if` ends that branch, not the block.

    Getting this wrong would flag the most ordinary shape in C++ and make the
    whole feature untrustworthy.
    """
    code = """int f(int n) {
    if (n > 0) {
        return n;
    }
    return -n;
}"""
    assert "unreachable_code" not in rules(code)


# --- loops ------------------------------------------------------------------- #

def test_a_loop_whose_condition_never_changes_is_reported():
    code = """#include <iostream>
int f(int n) {
    int i = 0;
    while (i < n) {
        std::cout << i;
    }
    return i;
}"""
    findings = [f for f in from_parse_tree(code) if f.rule == "infinite_loop"]
    assert len(findings) == 1
    assert findings[0].certain
    assert "i" in findings[0].message


def test_a_loop_that_advances_is_left_alone():
    code = """int f(int n) {
    int i = 0;
    while (i < n) {
        i = i + 1;
    }
    return i;
}"""
    assert "infinite_loop" not in rules(code)


def test_a_loop_with_a_break_is_left_alone():
    """It can leave without the condition ever becoming false."""
    code = """#include <iostream>
int f(int n) {
    int i = 0;
    while (i < n) {
        if (n > 5) break;
        std::cout << i;
    }
    return i;
}"""
    assert "infinite_loop" not in rules(code)


def test_a_loop_whose_counter_is_passed_to_a_call_is_left_alone():
    """The callee may take it by reference, and the signature is not visible."""
    code = """void bump(int& v);
int f(int n) {
    int i = 0;
    while (i < n) {
        bump(i);
    }
    return i;
}"""
    assert "infinite_loop" not in rules(code)


def test_a_counted_for_loop_is_left_alone():
    code = """int f(int n) {
    int total = 0;
    for (int i = 0; i < n; ++i) {
        total += i;
    }
    return total;
}"""
    assert "infinite_loop" not in rules(code)


# --- the compiler tier, and the rule about broken code ----------------------- #

@needs_compiler
def test_the_compiler_tier_reports_an_unused_variable():
    code = """int f(int n) {
    int scratch = 42;
    return n;
}"""
    report = check(code)
    assert report.compile_error is None
    assert any(f.rule == "unused_variable" and f.tier == 1 for f in report.findings)


@needs_compiler
def test_code_that_does_not_compile_reports_only_that():
    """The user's problem is the error.

    Tree-sitter builds a tree from broken source rather than refusing, so the
    parse-tree rules would describe structure that is not in the program. The
    example this module was written for was pasted with a missing semicolon,
    which is the common case and not an edge case.
    """
    broken = REVERSE_DIGITS.replace("int pp = 10;", "int pp = 10")
    report = check(broken)
    assert report.compile_error is not None
    assert "expected" in report.compile_error
    assert report.findings == []


@needs_compiler
def test_clean_code_produces_nothing():
    code = """int sumEven(int n) {
    int total = 0;
    for (int i = 0; i <= n; ++i) {
        if (i % 2 == 0) total += i;
    }
    return total;
}"""
    assert check(code).ok


# --- tier 4: evidence, not a proof ------------------------------------------- #

HANGS = """int f(int a[], int n) {
    int i = 0;
    int s = 0;
    while (i < n) { s += a[i]; }
    return s;
}"""


@needs_compiler
def test_a_program_that_does_not_finish_is_reported_with_its_input():
    """Termination is undecidable, so the finding is a witness, not a verdict.

    `certain` must be False: a slow program and a non-terminating one look
    identical from outside, and the message has to carry the input so the
    reader can reproduce it.
    """
    findings = from_runtime(HANGS, timeout=5.0)
    assert len(findings) == 1
    assert findings[0].rule == "does_not_terminate"
    assert not findings[0].certain
    assert findings[0].tier == 4
    assert "did not finish" in findings[0].message


@needs_compiler
def test_a_program_that_finishes_is_not_reported():
    code = """int f(int a[], int n) {
    int s = 0;
    for (int i = 0; i < n; ++i) { s += a[i]; }
    return s;
}"""
    assert from_runtime(code, timeout=5.0) == []


@needs_compiler
def test_nothing_is_executed_unless_the_caller_asks():
    """`run_code` is a security decision: tier 4 runs submitted code unsandboxed."""
    assert all(f.tier != 4 for f in check(HANGS).findings)
    assert any(f.tier == 4 for f in check(HANGS, run_code=True).findings)


# --- tier 2: the one class the other tiers cannot reach ---------------------- #

needs_cppcheck = pytest.mark.skipif(
    not cppcheck_available(), reason="needs cppcheck (apt install cppcheck)"
)

OVERWRITTEN_BEFORE_READ = """int f(int n) {
    int result = n * 2;
    result = n + 1;
    return result;
}"""


@needs_cppcheck
def test_an_overwritten_initialiser_is_reported():
    """The dead store, which is tier 2's whole reason for existing.

    gcc will not warn: `result` *is* read, so -Wunused-variable does not apply,
    and the liveness analysis that deletes the first store at -O2 has no warning
    attached to it. The parse-tree rules do not do liveness either.

    cppcheck calls this `redundantInitialization`, not `redundantAssignment`.
    The mapping originally guessed the latter, which silently discarded the only
    class tier 2 was installed for and left coverage at 6/7 while appearing to
    work. This test is why that is now 7/7.
    """
    findings = [f for f in check(OVERWRITTEN_BEFORE_READ).findings if f.rule == "dead_store"]
    assert len(findings) == 1
    assert findings[0].tier == 2
    # cppcheck anchors this at the line that *overwrites*, not the dead write
    # one line above. Asserted rather than normalised: it is where the
    # redundancy becomes visible, the quoted line still matches the file, and
    # silently shifting another tool's line number would break the one contract
    # these findings have.
    assert findings[0].line == 3
    assert findings[0].code == "result = n + 1;"


@needs_cppcheck
def test_an_assigned_but_never_read_variable_is_one_finding_not_two():
    """gcc and cppcheck both see it; the user should be told once.

    cppcheck's `unreadVariable` is the same defect as gcc's -Wunused-variable,
    so it maps to the same rule and the two collapse. Mapping it to `dead_store`
    produced two findings for one problem.
    """
    code = """int f(const int* v, int n) {
    int total = 0;
    int scratch = 42;
    for (int i = 0; i < n; ++i) total += v[i];
    return total;
}"""
    rule_names = [f.rule for f in check(code).findings]
    assert rule_names.count("unused_variable") == 1
    assert "dead_store" not in rule_names


SOLVER_CASES = """int f(int n) {
    int x = 5;
    if (x > 0 && x < 0) { return n; }
    return 0;
}
int g(int n) {
    if (n > 10 && n < 5) { return 1; }
    return 0;
}
unsigned h(unsigned u) {
    if (u < 0) { return 1; }
    return 0;
}"""


@needs_cppcheck
def test_conditions_needing_value_reasoning_are_reached_by_tier_2():
    """What tier 2 adds beyond the dead store.

    `constant_condition` refuses these on purpose: deciding `n > 10 && n < 5`
    needs value reasoning rather than constant propagation, and on `n` it is a
    parameter with no known value at all. cppcheck does it.
    """
    assert "dead_branch" not in rules(SOLVER_CASES)
    findings = {(f.rule, f.tier) for f in check(SOLVER_CASES).findings}
    assert ("dead_branch", 2) in findings
    assert ("impossible_condition", 2) in findings


@needs_cppcheck
def test_a_constant_flag_produces_one_finding_not_four():
    """The overlap between the tiers must collapse.

    cppcheck's `knownConditionTrueFalse` sees the same constant flags, but
    anchors on the condition rather than the branch that cannot run, so the two
    did not dedupe: `while (running) { if (running) ... else ... }` produced
    four findings for two problems. It is excluded from the mapping for that
    reason, and this test is what would catch its return.
    """
    report = check(FLAG_NEVER_CLEARED)
    assert len(report.findings) == 2
    assert {f.rule for f in report.findings} == {"infinite_loop", "dead_branch"}
    assert all(f.tier == 3 for f in report.findings)
