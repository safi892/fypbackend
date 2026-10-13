"""Findings the compiler, cppcheck and the parse tree can establish on their own.

Measured before this existed, on seven planted defects: `g++ -Wall -Wextra`
named **two**, and the shipped 1.5B named **one** — as an aside inside an
`Input:` line rather than as a problem report. The model also carries a
confidently-false description on 30% of answers. So nothing here asks the model,
and no retraining would change that: these are decidable properties of the
source, and the compiler already computes most of them internally. The numbers
are in the training repo's `docs/DEFECT_DETECTION_RESEARCH.md`.

Four tiers, in the order they are worth running:

    tier 1  the compiler      exact, free, already a dependency
    tier 2  cppcheck          exact, optional; adds the dead store
    tier 3  the parse tree     unreachable code, non-advancing loops, constants
    tier 4  a timeout          evidence of non-termination, with the input

Every finding carries the **line text verbatim**, not only a number. That is the
same contract as the line comments, for the same measured reason: line numbers
are wrong about 75% of the time in this project, and a quote can be checked
against the file.

`certain` separates what is proven from what is inferred, and the two must never
be rendered the same way. Tiers 1-3 only fire on cases they can prove.
Tier 4 cannot: a slow program and a non-terminating one look identical from
outside, so its finding is evidence carrying a reproducing input. The
false-positive literature is consistent that getting this backwards is how a
detector earns the reputation that gets every later warning ignored.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from app.core.compiler import find_cxx_compiler
from app.parsers import cpp_parser

if TYPE_CHECKING:  # pragma: no cover - only for static type checkers
    from tree_sitter import Node

#: Statements after which nothing in the same block can run.
_TERMINATORS = frozenset(
    {"return_statement", "break_statement", "continue_statement", "goto_statement"}
)

#: Anything here can leave a loop body without the condition ever changing, so a
#: loop containing one of them is not provably non-terminating.
_ESCAPES = frozenset(
    {"break_statement", "return_statement", "goto_statement", "throw_statement"}
)

#: A literal the compiler folds. `pp = 10` qualifies; `pp = n` does not.
_LITERALS = frozenset({"number_literal", "char_literal", "true", "false"})

#: Calls that end the program, so a loop around one does terminate.
_EXITS = re.compile(r"\b(exit|abort|terminate|_Exit|quick_exit|longjmp)\s*\(")

#: `file:line:col: warning: text [-Wflag]`, which is also gcc's error format.
_DIAGNOSTIC = re.compile(
    r"^[^:]+:(?P<line>\d+):(?P<col>\d+):\s*(?P<kind>warning|error):\s*(?P<text>.*?)"
    r"(?:\s*\[-W(?P<flag>[a-z0-9-]+)\])?$"
)


@dataclass(frozen=True)
class Finding:
    """One thing worth telling the user, and how sure we are of it."""

    rule: str
    line: int
    #: The source line, copied verbatim. Checkable where a number is not.
    code: str
    message: str
    #: True when the rule only fires on a case it can prove.
    certain: bool = True
    tier: int = 3


@dataclass
class CheckReport:
    findings: list[Finding] = field(default_factory=list)
    #: Set when the code does not compile. Every other rule is then unreliable,
    #: because tree-sitter builds a tree from broken source rather than refusing.
    compile_error: str | None = None

    @property
    def ok(self) -> bool:
        return not self.findings and self.compile_error is None


def _line_text(code: str, line: int) -> str:
    lines = code.split("\n")
    return lines[line - 1].strip() if 1 <= line <= len(lines) else ""


# --- tier 1: the compiler ---------------------------------------------------- #

#: gcc's flag names, mapped to rule ids this project owns. Only exact warnings
#: are listed: `-Wmaybe-uninitialized` is a guess by construction.
_COMPILER_RULES = {
    "unused-variable": "unused_variable",
    "unused-but-set-variable": "dead_store",
    "unused-parameter": "unused_parameter",
    "unused-value": "unused_value",
    "unused-function": "unused_function",
}


def from_compiler(code: str, *, timeout: float = 20.0) -> CheckReport:
    """Ask `c++` what it already knows, which is more than the model does.

    `-fsyntax-only` so nothing is linked and no `main` is required. Two flags
    are passed explicitly because gcc leaves them off even under `-Wextra`:
    `-Wunused-but-set-variable` is the dead-store warning, and without it the
    only defect gcc reports is the fully unused variable.

    `-Wunreachable-code` is deliberately absent. gcc lists it as `[ignored]`, so
    passing it reads in a build log as though unreachable code were being
    checked when nothing is. Tier 3 does that job.
    """
    report = CheckReport()
    compiler = find_cxx_compiler()
    if compiler is None:
        return report
    # `syntax_command` already picks GNU or MSVC flags. The warning flags below
    # are GNU spellings, and `_DIAGNOSTIC` parses the GNU diagnostic format, so
    # on MSVC this tier contributes nothing rather than guessing at a format it
    # cannot read. Saying so is `tiers_available`'s job.
    if compiler.is_msvc:
        return report
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "snippet.cpp"
        source.write_text(code, encoding="utf-8")
        command = [*compiler.syntax_command(source), "-Wall", "-Wextra",
                   "-Wunused-but-set-variable", "-Wunused-but-set-parameter"]
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=timeout,
            )
        except (subprocess.TimeoutExpired, OSError):
            return report

    for raw in completed.stderr.splitlines():
        match = _DIAGNOSTIC.match(raw.strip())
        if match is None:
            continue
        line = int(match.group("line"))
        text = match.group("text").strip()
        if match.group("kind") == "error":
            # Stop here rather than reporting style on code that does not
            # compile: the user's problem is the error.
            if report.compile_error is None:
                report.compile_error = f"line {line}: {text}"
            continue
        rule = _COMPILER_RULES.get(match.group("flag") or "")
        if rule is None:
            continue
        report.findings.append(
            Finding(rule=rule, line=line, code=_line_text(code, line),
                    message=text, certain=True, tier=1)
        )
    return report


# --- tier 2: cppcheck, when it is installed ---------------------------------- #

#: cppcheck's ids mapped to this project's. `unreadVariable` and
#: `redundantAssignment` are the dead store gcc has no warning for, and the one
#: planted defect class neither tier 1 nor tier 3 can reach.
_CPPCHECK_RULES = {
    "unusedVariable": "unused_variable",
    # "assigned a value that is never used" is the same defect gcc reports as
    # -Wunused-variable, so it maps to the same rule and the two collapse.
    # Mapping it to dead_store instead produced two findings for one problem.
    "unreadVariable": "unused_variable",
    # The id for an overwritten *initialiser* is `redundantInitialization`, not
    # `redundantAssignment`. Both are listed because they are different cases -
    # `int r = a; r = b;` against `r = a; r = b;` - and because guessing the
    # first one silently threw away the only class tier 2 was installed for.
    # Verified against cppcheck 2.7 output rather than its documentation.
    "redundantInitialization": "dead_store",
    "redundantAssignment": "dead_store",
    "unassignedVariable": "unassigned_variable",
    "unusedStructMember": "unused_struct_member",
    "unreachableCode": "unreachable_code",
    "duplicateBranch": "duplicate_branch",
    # Conditions tier 3 cannot decide, because they need value reasoning rather
    # than constant propagation: `n > 10 && n < 5` on a *parameter*, and an
    # unsigned compared against zero. These are the real gain from tier 2
    # beyond the dead store.
    "incorrectLogicOperator": "dead_branch",
    "unsignedLessThanZero": "impossible_condition",
    # `knownConditionTrueFalse` is deliberately absent. It fires on the same
    # constant flags `constant_condition` already handles, but anchors on the
    # condition rather than on the branch that cannot run, so the two did not
    # collapse: one `while (running) { if (running) ... else ... }` produced
    # four findings for two problems. Tier 3 names the consequence, which is
    # the more actionable half, so it wins the overlap.
}

#: From `--template`, because the default format wraps and is not parseable.
_CPPCHECK_LINE = re.compile(r"^[^:]*:(?P<line>\d+):(?P<id>[A-Za-z]+):(?P<text>.*)$")


def cppcheck_available() -> bool:
    return shutil.which("cppcheck") is not None


def from_cppcheck(code: str, *, timeout: float = 30.0) -> list[Finding]:
    """What cppcheck adds over the compiler, or nothing when it is absent.

    Returning an empty list rather than raising is deliberate: this tier is an
    optional improvement, and a deployment without cppcheck should lose two
    rules, not the endpoint. `tiers_available` exists so a caller can say which
    tiers actually ran instead of implying all four did.

    Install with `apt install cppcheck`.
    """
    if not cppcheck_available():
        return []
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "snippet.cpp"
        source.write_text(code, encoding="utf-8")
        try:
            completed = subprocess.run(
                ["cppcheck", "--enable=style,warning", "--inline-suppr", "--quiet",
                 "--template={file}:{line}:{id}:{message}", str(source)],
                capture_output=True, text=True, timeout=timeout,
            )
        except (subprocess.TimeoutExpired, OSError):
            return []
    findings: list[Finding] = []
    for raw in completed.stderr.splitlines():
        match = _CPPCHECK_LINE.match(raw.strip())
        if match is None:
            continue
        rule = _CPPCHECK_RULES.get(match.group("id"))
        if rule is None:
            continue
        line = int(match.group("line"))
        findings.append(Finding(
            rule=rule, line=line, code=_line_text(code, line),
            message=match.group("text").strip(), certain=True, tier=2,
        ))
    return findings


# --- tier 3: the parse tree -------------------------------------------------- #

def _identifiers(node: Node) -> list[Node]:
    return list(cpp_parser.iter_descendants(node, {"identifier"}))


def _assigned_names(node: Node) -> set[str]:
    """Names this subtree writes to: assignment, increment, or address taken.

    Address-of, non-const references and call arguments all count as writes,
    because the callee may write through them and the signature is not visible
    here. A rule that assumed otherwise would be wrong in the direction that
    matters — claiming a loop cannot terminate when it can.
    """
    written: set[str] = set()
    for kind in ("assignment_expression", "update_expression"):
        for expression in cpp_parser.iter_descendants(node, {kind}):
            target = expression.child_by_field_name("left") or expression.child_by_field_name(
                "argument"
            )
            if target is None:
                target = next((c for c in expression.children if c.type == "identifier"), None)
            if target is not None:
                written.update(cpp_parser.node_text(child) for child in _identifiers(target))
                if target.type == "identifier":
                    written.add(cpp_parser.node_text(target))
    for unary in cpp_parser.iter_descendants(node, {"pointer_expression"}):
        if cpp_parser.node_text(unary).lstrip().startswith("&"):
            written.update(cpp_parser.node_text(child) for child in _identifiers(unary))
    for call in cpp_parser.iter_descendants(node, {"call_expression"}):
        arguments = call.child_by_field_name("arguments")
        if arguments is not None:
            written.update(cpp_parser.node_text(child) for child in _identifiers(arguments))
    return written


def unreachable_after_terminator(code: str, root: Node) -> list[Finding]:
    """Statements following a `return` in the same block. Exact, not a guess."""
    findings: list[Finding] = []
    for block in cpp_parser.iter_descendants(root, {"compound_statement"}):
        seen_terminator = False
        for statement in block.children:
            if statement.type in ("{", "}", "comment"):
                continue
            if seen_terminator:
                line = statement.start_point[0] + 1
                findings.append(Finding(
                    rule="unreachable_code", line=line, code=_line_text(code, line),
                    message="this statement cannot be reached: the block already returned",
                    certain=True,
                ))
                break
            if statement.type in _TERMINATORS:
                seen_terminator = True
    return findings


def non_advancing_loop(code: str, root: Node) -> list[Finding]:
    """A loop whose condition can never change, and which cannot be escaped.

    Termination is the halting problem, so this cannot be complete. It is sound
    for its subset and silent everywhere else, which is the only honest way to
    report something undecidable: it fires when *nothing* in the body writes a
    name the condition reads, the body holds no `break`, `return`, `goto` or
    `throw`, and nothing in it calls a function that exits the program.
    """
    findings: list[Finding] = []
    for loop in cpp_parser.iter_descendants(root, {"while_statement", "for_statement"}):
        condition = loop.child_by_field_name("condition")
        body = loop.child_by_field_name("body")
        if body is None:
            continue
        escapes = cpp_parser.iter_descendants(body, set(_ESCAPES))
        if any(child.type in _ESCAPES for child in escapes):
            continue
        if _EXITS.search(cpp_parser.node_text(body)):
            continue
        # A `for` with an update clause advances by construction; only the
        # degenerate `for (;;)` shape is considered here.
        advances = loop.child_by_field_name("update") is not None
        if loop.type == "for_statement" and advances:
            continue
        if condition is None:
            line = loop.start_point[0] + 1
            findings.append(Finding(
                rule="infinite_loop", line=line, code=_line_text(code, line),
                message="this loop has no condition and no way out of its body",
                certain=True,
            ))
            continue
        read = {cpp_parser.node_text(child) for child in _identifiers(condition)}
        if not read:
            continue
        if read & _assigned_names(body):
            continue
        line = loop.start_point[0] + 1
        names = ", ".join(sorted(read))
        findings.append(Finding(
            rule="infinite_loop", line=line, code=_line_text(code, line),
            message=(f"this loop cannot terminate: nothing in the body changes {names}, "
                     "and the body has no break, return or throw"),
            certain=True,
        ))
    return findings


def _truthiness(literal: str) -> bool | None:
    """What a literal is worth in a condition, or None when it is not obvious."""
    text = literal.strip()
    if text == "true":
        return True
    if text == "false":
        return False
    try:
        return int(text, 0) != 0
    except ValueError:
        return None


def _known_constants(body: Node) -> dict[str, bool]:
    """Locals initialised to a literal and never written again, as truth values.

    Constant propagation at its smallest useful size. Nothing here tracks a
    value through arithmetic or across a call: a name qualifies only if its
    initialiser is a literal and `_assigned_names` never sees it written.
    """
    written = _assigned_names(body)
    constants: dict[str, bool] = {}
    for declarator in cpp_parser.iter_descendants(body, {"init_declarator"}):
        name_node = declarator.child_by_field_name("declarator")
        value_node = declarator.child_by_field_name("value")
        if name_node is None or value_node is None or name_node.type != "identifier":
            continue
        if value_node.type not in _LITERALS:
            continue
        name = cpp_parser.node_text(name_node)
        if name in written:
            continue
        truth = _truthiness(cpp_parser.node_text(value_node))
        if truth is not None:
            constants[name] = truth
    return constants


def _condition_subject(condition: Node) -> tuple[str, bool] | None:
    """Read `(flag)` or `(!flag)` as a name plus whether it is negated.

    Deliberately only these two shapes. `(a && b)` or `(n > 0)` would need a
    solver, and guessing there is how a detector gets switched off.
    """
    meaningful = [child for child in condition.children if child.type not in ("(", ")")]
    if len(meaningful) != 1:
        return None
    node = meaningful[0]
    if node.type == "identifier":
        return cpp_parser.node_text(node), False
    if node.type == "unary_expression" and cpp_parser.node_text(node).lstrip().startswith("!"):
        inner = node.child_by_field_name("argument")
        if inner is not None and inner.type == "identifier":
            return cpp_parser.node_text(inner), True
    return None


def constant_condition(code: str, root: Node) -> tuple[list[Finding], set[str]]:
    """A branch decided before the program runs, so one side is dead.

    `bool isOn = true; if (isOn) ... else ...` never takes the else. The
    compiler knows — it deletes the branch — and warns about none of it, because
    removing dead code is an optimisation and complaining about it is a style
    opinion the standard does not require.

    Returns the findings and the names they used, so `constant_used_once` can
    stay quiet about the same variable: "use the value directly" is the wrong
    advice for a flag whose real problem is an unreachable branch.
    """
    findings: list[Finding] = []
    consumed: set[str] = set()
    for function in cpp_parser.iter_descendants(root, {"function_definition"}):
        body = function.child_by_field_name("body")
        if body is None:
            continue
        constants = _known_constants(body)
        if not constants:
            continue
        for statement in cpp_parser.iter_descendants(body, {"if_statement"}):
            condition = statement.child_by_field_name("condition")
            if condition is None:
                continue
            subject = _condition_subject(condition)
            if subject is None:
                continue
            name, negated = subject
            if name not in constants:
                continue
            always = constants[name] != negated
            value = str(constants[name]).lower()
            alternative = statement.child_by_field_name("alternative")
            if always:
                if alternative is None:
                    continue
                line = alternative.start_point[0] + 1
                message = f"`{name}` is always {value} here, so this else branch can never run"
            else:
                if statement.child_by_field_name("consequence") is None:
                    continue
                line = statement.start_point[0] + 1
                message = (f"`{name}` is always {value} here, so the body of this if can "
                           "never run")
            consumed.add(name)
            findings.append(Finding(
                rule="dead_branch", line=line, code=_line_text(code, line),
                message=message, certain=True,
            ))
    return findings, consumed


def constant_used_once(code: str, root: Node, skip: set[str] | None = None) -> list[Finding]:
    """A local initialised to a literal, never written again, and read once.

    This is the checkable half of "unnecessary variable". The vague version has
    no ground truth: `int sum = a + b; return sum;` is arguably clearer than
    `return a + b;`, so there is nothing to verify and nothing to measure. This
    version is decidable — substituting the literal cannot change behaviour.

    It is what catches `int pp = 10;` read only as `temp /= pp`.
    """
    skip = skip or set()
    findings: list[Finding] = []
    for function in cpp_parser.iter_descendants(root, {"function_definition"}):
        body = function.child_by_field_name("body")
        if body is None:
            continue
        uses: dict[str, int] = {}
        for identifier in _identifiers(body):
            name = cpp_parser.node_text(identifier)
            uses[name] = uses.get(name, 0) + 1
        written = _assigned_names(body)
        for declaration in cpp_parser.iter_descendants(body, {"declaration"}):
            for declarator in declaration.children:
                if declarator.type != "init_declarator":
                    continue
                name_node = declarator.child_by_field_name("declarator")
                value_node = declarator.child_by_field_name("value")
                if name_node is None or value_node is None:
                    continue
                if name_node.type != "identifier" or value_node.type not in _LITERALS:
                    continue
                name = cpp_parser.node_text(name_node)
                # The declaration itself is one occurrence, so a single later
                # read totals two.
                if uses.get(name, 0) != 2 or name in written or name in skip:
                    continue
                line = declaration.start_point[0] + 1
                findings.append(Finding(
                    rule="constant_used_once", line=line, code=_line_text(code, line),
                    message=(f"`{name}` holds the constant {cpp_parser.node_text(value_node)} "
                             "and is read once; using the value directly removes the variable"),
                    certain=True,
                ))
    return findings


def from_parse_tree(code: str) -> list[Finding]:
    """Run the parse-tree rules, or none if tree-sitter is unavailable.

    `constant_condition` goes first because it decides what
    `constant_used_once` may say: one problem should produce one finding.
    """
    root = cpp_parser.parse(code)
    if root is None:
        return []
    findings, consumed = constant_condition(code, root)
    findings.extend(unreachable_after_terminator(code, root))
    findings.extend(non_advancing_loop(code, root))
    findings.extend(constant_used_once(code, root, skip=consumed))
    return findings


# --- tier 4: a timeout, which is evidence rather than a proof ---------------- #

def _signature_line(code: str, name: str) -> int:
    """The 1-based line the named function is declared on, or 1."""
    for index, line in enumerate(code.split("\n"), start=1):
        if re.search(rf"\b{re.escape(name)}\s*\(", line):
            return index
    return 1


def from_runtime(code: str, *, timeout: float = 10.0) -> list[Finding]:
    """Run the user's own code and report it if it does not come back.

    Termination is undecidable, so no analysis settles it in general. What *can*
    be produced is a witness: an input on which the program did not finish.
    That is the currency the termination literature deals in, and it beats a
    guess because the input is attached.

    This reuses the driver `equivalence` already builds for checking rewrites.
    Nothing new is compiled or invented; the only change is pointing it at the
    submitted code instead of only at the model's replacement.
    """
    from app.model_processing import equivalence

    compiler = find_cxx_compiler()
    if compiler is None:
        return []
    signature = equivalence.parse_signature(code)
    if signature is None or not signature.drivable:
        return []
    cases, _ = equivalence._cases(signature)
    if not cases:
        return []
    with tempfile.TemporaryDirectory() as directory:
        source = equivalence.HEADERS + code + equivalence._driver(signature, cases)
        try:
            output, error, _ = equivalence._build_and_run(
                source, Path(directory), "submitted", timeout, compiler
            )
        except (subprocess.TimeoutExpired, OSError):
            return []
    if output is not None or "longer than" not in error:
        return []
    line = _signature_line(code, signature.name)
    return [Finding(
        rule="does_not_terminate", line=line, code=_line_text(code, line),
        message=(f"{signature.name} did not finish within {timeout:g}s on input "
                 f"{cases[0]}; it may not terminate"),
        # Evidence, not proof: a slow program and a non-terminating one look
        # identical from outside.
        certain=False, tier=4,
    )]


# --- all four together ------------------------------------------------------- #

def tiers_available() -> dict[int, bool]:
    """Which tiers can actually run here, so a caller need not imply all four."""
    compiler = find_cxx_compiler()
    # Tier 1 reads GNU diagnostics, so MSVC counts as unavailable for it even
    # though a compiler exists. Tier 4 only needs to build and run, which the
    # abstraction handles either way.
    return {
        1: compiler is not None and not compiler.is_msvc,
        2: cppcheck_available(),
        3: cpp_parser.is_available(),
        4: compiler is not None,
    }


def check(code: str, *, run_code: bool = False) -> CheckReport:
    """Everything that can be established about ``code`` without asking the model.

    A compile error short-circuits the rest on purpose. The user's problem is
    the error, and tree-sitter builds a tree from broken source rather than
    refusing, so the rules would report structure that is not there.

    ``run_code`` is off by default, and that is a security decision rather than
    a performance one: tier 4 compiles and executes whatever was submitted, with
    a timeout as its only restraint and no sandbox. `/optimize` already accepts
    that risk for rewrites of code the user sent; a reviewing endpoint should
    accept it deliberately or not at all.

    Duplicates are collapsed by (rule, line) because the tiers overlap — gcc and
    cppcheck both report an unused variable — and one problem should produce one
    finding.
    """
    report = from_compiler(code)
    if report.compile_error is not None:
        return report
    report.findings.extend(from_cppcheck(code))
    report.findings.extend(from_parse_tree(code))
    if run_code:
        report.findings.extend(from_runtime(code))

    seen: set[tuple[str, int]] = set()
    unique: list[Finding] = []
    for finding in sorted(report.findings, key=lambda f: (f.line, f.rule, f.tier)):
        key = (finding.rule, finding.line)
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)
    report.findings = unique
    return report
