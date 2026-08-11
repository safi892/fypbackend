"""Compile an optimised rewrite alongside the original and compare their output.

Problem solved: an optimisation that changes the answer is not an optimisation,
and reading the code cannot tell you which you have. The previous engine's
"improved code" was never executed, which is exactly how it came to return
reformatting and added ``const`` references rather than anything faster. Nothing
here is offered to a client until it has been run.

The check is behavioural: identical output on generated inputs proves agreement
on those inputs and nothing more. That is enough to reject a rewrite that
changes the result, which is the failure that matters to a user.

Why it degrades rather than refuses: a signature the driver cannot supply
arguments for, or a machine with no compiler, yields ``verified=False`` and the
original code. A user is never handed an unchecked rewrite, and never handed an
error either.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

#: Argument types the generated driver knows how to supply values for.
SCALAR_TYPES = {
    "int", "long", "long long", "size_t", "unsigned", "double", "float", "bool",
    "char", "unsigned char", "short", "unsigned long",
}

#: Spellings of the same scalar. Refusing a function over its author's choice
#: of prefix declines a large slice of ordinary C++ for no reason.
TYPE_ALIASES = {
    "std::size_t": "size_t", "unsigned int": "unsigned", "signed int": "int",
    "ll": "long long", "ull": "long long", "int64_t": "long long",
    "std::string": "string", "uint": "unsigned", "lli": "long long",
}

#: Driven as words rather than numbers.
STRING_TYPES = {"string"}

#: One argument for one call: a scalar, the contents of a sequence, or text.
Value = int | tuple[int, ...] | str

SIGNATURE_RE = re.compile(
    r"^\s*(?P<ret>[A-Za-z_][\w:<>,\s*&]*?)\s+(?P<name>[A-Za-z_]\w*)\s*\((?P<params>[^)]*)\)\s*\{?",
    re.MULTILINE,
)

HEADERS = (
    "#include <iostream>\n#include <vector>\n#include <string>\n#include <map>\n"
    "#include <unordered_map>\n#include <algorithm>\n#include <climits>\n#include <cmath>\n"
)

#: Work below this, once process start-up is removed, is too small to time.
NOISE_FLOOR_SECONDS = 0.05


@dataclass(frozen=True)
class Parameter:
    """One declared argument, and what the driver can do with it."""

    type: str
    name: str
    is_array: bool = False
    is_reference: bool = False
    is_const: bool = False

    @property
    def is_vector(self) -> bool:
        return "vector" in self.type

    @property
    def element_type(self) -> str:
        """The scalar type a value of this parameter is made of.

        The inner match is greedy on purpose: stopping at the first ``>`` reads
        ``std::vector<std::vector<int>>`` as being made of ``vector<int``, a
        type that does not exist, so a nested sequence gets refused under a
        mangled name instead of its real one.
        """
        inner = re.search(r"<\s*(.+)\s*>", self.type)
        base = inner.group(1) if inner else self.type
        cleaned = base.replace("const", "").replace("&", "").replace("*", "").strip()
        return TYPE_ALIASES.get(cleaned, cleaned)

    @property
    def is_string(self) -> bool:
        return self.element_type in STRING_TYPES

    @property
    def is_buffer(self) -> bool:
        """A numeric sequence. A string is a sequence too, but prints itself."""
        return (self.is_array or self.is_vector) and not self.is_string

    @property
    def is_output(self) -> bool:
        """Whether the callee can write through this parameter.

        This is what makes a ``void`` function checkable: the answer is not
        returned, so it has to be read back out of the arguments.
        """
        if self.is_const:
            return False
        return self.is_array or self.is_reference

    @property
    def drivable(self) -> bool:
        return self.element_type in SCALAR_TYPES or self.is_string


@dataclass(frozen=True)
class Signature:
    """A parsed function signature."""

    return_type: str
    name: str
    params: tuple[Parameter, ...]

    @property
    def returns_value(self) -> bool:
        return self.return_type.strip() != "void"

    @property
    def observable(self) -> bool:
        """Whether calling this produces anything that can be compared.

        A ``void`` function taking everything by value prints nothing, and
        nothing compares equal to nothing — so accepting the shape would report
        every such rewrite as verified. A check that always passes is worse
        than no check, because the user is told the rewrite was proven.
        """
        return self.returns_value or any(p.is_output for p in self.params)

    @property
    def drivable(self) -> bool:
        """Whether a caller can be generated for this shape."""
        if not self.params:
            return False
        return all(p.drivable for p in self.params) and self.observable


@dataclass
class EquivalenceResult:
    """The verdict on one proposed rewrite."""

    verified: bool = False
    equivalent: bool = False
    cases: int = 0
    agreed: int = 0
    speedup: float = 0.0
    timing_reliable: bool = False
    reason: str = ""

    def summary(self) -> str:
        if not self.verified:
            return f"not verified: {self.reason}"
        if not self.equivalent:
            return f"rejected: output differs on {self.cases - self.agreed} of {self.cases} inputs"
        if not self.timing_reliable:
            return f"equivalent on {self.cases} inputs; too fast to time reliably"
        return f"equivalent on {self.cases} inputs, {self.speedup:.1f}x faster"


def parse_signature(code: str) -> Signature | None:
    """Read the first real function definition out of ``code``."""
    for match in SIGNATURE_RE.finditer(code):
        name = match.group("name")
        if name in {"main", "if", "for", "while", "switch", "return", "sizeof"}:
            continue
        raw = match.group("params").strip()
        params: list[Parameter] = []
        if raw and raw != "void":
            for piece in _split_params(raw):
                piece = piece.strip()
                is_array = "[" in piece
                is_reference = "&" in piece or "*" in piece
                is_const = bool(re.match(r"\bconst\b", piece))
                cleaned = re.sub(r"\[[^\]]*\]", "", piece).strip()
                bits = cleaned.replace("&", " ").replace("*", " ").split()
                if len(bits) < 2:
                    return None
                params.append(
                    Parameter(
                        type=" ".join(bits[:-1]),
                        name=bits[-1],
                        is_array=is_array,
                        is_reference=is_reference,
                        is_const=is_const,
                    )
                )
        return Signature(match.group("ret").strip(), name, tuple(params))
    return None


def _split_params(raw: str) -> list[str]:
    """Split on the commas that separate parameters, not the ones inside types.

    ``std::map<int, int> counts`` holds a comma belonging to the template
    argument list, and splitting on it yields two nonsense parameters that then
    parse as plausible ones.
    """
    pieces: list[str] = []
    depth = 0
    current = ""
    for character in raw:
        if character in "<([":
            depth += 1
        elif character in ">)]":
            depth -= 1
        if character == "," and depth == 0:
            pieces.append(current)
            current = ""
            continue
        current += character
    if current.strip():
        pieces.append(current)
    return pieces


def _render_case(signature: Signature, values: tuple[Value, ...], index: int) -> str:
    """Set up the arguments for one call, make it, and print what came back.

    Sequences are backed by a ``std::vector`` whatever the parameter says:
    ``vector`` carries its own length, can be empty without becoming an illegal
    zero-sized array, and hands a plain pointer to an ``int[]`` parameter via
    ``.data()``. One representation covers both shapes.

    Everything the call could have changed is printed, not only the return
    value — a ``void`` function's whole answer is in its arguments.
    """
    setup: list[str] = []
    arguments: list[str] = []
    label: list[str] = []

    for position, (parameter, value) in enumerate(zip(signature.params, values, strict=True)):
        local = f"a{index}_{position}"
        if isinstance(value, str):
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            setup.append(f'    std::string {local} = "{escaped}";')
            arguments.append(local)
            # Single quotes: this label is pasted inside a C++ double-quoted
            # literal, and a double quote here would end it early.
            label.append(f"'{value}'")
        elif isinstance(value, tuple):
            literal = ", ".join(str(item) for item in value)
            setup.append(f"    std::vector<{parameter.element_type}> {local} = {{{literal}}};")
            arguments.append(local if parameter.is_vector else f"{local}.data()")
            label.append("[" + ",".join(str(item) for item in value) + "]")
        else:
            setup.append(f"    {parameter.element_type} {local} = {value};")
            arguments.append(local)
            label.append(str(value))

    call = f"{signature.name}({', '.join(arguments)})"
    lines = [*setup, f"    auto r = {call};" if signature.returns_value else f"    {call};"]
    lines.append(f'    std::cout << "{" | ".join(label)}" << " => ";')
    if signature.returns_value:
        lines.append('    std::cout << r << " ; ";')
    # After the call, deliberately: before it, these are the inputs.
    for position, parameter in enumerate(signature.params):
        if not parameter.is_output:
            continue
        local = f"a{index}_{position}"
        if isinstance(values[position], tuple):
            lines.append(f'    for (auto v : {local}) std::cout << v << ",";')
            lines.append('    std::cout << " ; ";')
        else:
            lines.append(f'    std::cout << {local} << " ; ";')
    lines.append('    std::cout << "\\n";')
    return "  {\n" + "\n".join(lines) + "\n  }"


def _driver(signature: Signature, cases: list[tuple[Value, ...]]) -> str:
    body = "\n".join(_render_case(signature, values, index) for index, values in enumerate(cases))
    return f"\n\nint main() {{\n{body}\n  return 0;\n}}\n"


def _build_and_run(
    source: str, workdir: Path, tag: str, timeout: float, runs: int = 3
) -> tuple[str | None, str, float]:
    """Compile once, run several times, and keep the fastest run.

    The minimum is the run least disturbed by whatever else the machine was
    doing: noise can only make a run slower.
    """
    path = workdir / f"{tag}.cpp"
    path.write_text(source, encoding="utf-8")
    binary = workdir / tag
    build = subprocess.run(
        ["c++", "-std=c++17", "-O2", "-o", str(binary), str(path)],
        capture_output=True, text=True, timeout=timeout,
    )
    if build.returncode != 0:
        return None, f"compile failed: {build.stderr.strip().splitlines()[-1][:200]}", 0.0
    best = float("inf")
    result = None
    for _ in range(runs):
        started = time.perf_counter()
        try:
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return None, f"ran longer than {timeout:g}s", timeout
        best = min(best, time.perf_counter() - started)
        if result.returncode != 0:
            return None, f"exited {result.returncode}", best
    return result.stdout, "", best


#: Sequence inputs in the order a reviewer would try them. The empty case earns
#: its place: it is where ``size() - 1`` on an unsigned type wraps.
BUFFER_CASES: tuple[tuple[int, ...], ...] = (
    (), (7,), (1, 2, 3, 4), (4, 3, 2, 1), (5, 1, 5, 1, 5), (-3, 8, 0, -1, 2),
)

#: Text inputs chosen the same way: empty, single, palindrome, mixed case with
#: a space, repeats.
STRING_CASES: tuple[str, ...] = ("", "a", "abc", "racecar", "Hello World", "aabbcc")


def _fill(
    signature: Signature, buffer: tuple[int, ...], scalar: int, text: str
) -> tuple[Value, ...]:
    """Build one argument tuple, sizing any length parameter from its sequence.

    An integer directly after a sequence is that sequence's length —
    ``f(int arr[], int n)`` is close to universal. A length invented
    independently would index past the end, where the comparison stops
    measuring the code and starts measuring undefined behaviour.

    Misreading the convention is safe in the direction that matters: if that
    integer was really something else, both versions still receive the same
    small value, so the verdict stays sound and only the input gets less
    interesting. Guessing too *large* is the dangerous error, and deriving the
    value from the sequence cannot do that.
    """
    values: list[Value] = []
    previous_length: int | None = None
    for parameter in signature.params:
        if parameter.is_string:
            values.append(text)
            previous_length = len(text)
        elif parameter.is_buffer:
            values.append(buffer)
            previous_length = len(buffer)
        elif previous_length is not None and parameter.element_type != "double":
            values.append(previous_length)
            previous_length = None
        else:
            values.append(scalar)
    return tuple(values)


def _cases(signature: Signature) -> tuple[list[tuple[Value, ...]], tuple[Value, ...]]:
    """Small inputs for correctness, and one large input for timing.

    They have to be different. Small inputs finish faster than a process takes
    to start, so timing them measures the operating system; large inputs make
    an expensive implementation visible. For sequences the same argument
    applies to *length*: a quadratic sort and a linearithmic one are
    indistinguishable on four elements.
    """
    if any(p.is_buffer or p.is_string for p in signature.params):
        small = [_fill(signature, b, 2, t) for b, t in zip(BUFFER_CASES, STRING_CASES, strict=True)]
        large = tuple((index * 7919) % 2003 for index in range(1500))
        return small, _fill(signature, large, 2, "abcdefghij" * 150)

    width = len(signature.params)
    if width == 1:
        return [(n,) for n in (0, 1, 2, 3, 5, 10, 15, 20)], (38,)
    if width == 2:
        return [(1, 1), (1, 5), (2, 3), (4, 4), (6, 5), (10, 8)], (18, 16)
    return [tuple(1 for _ in range(width)), tuple(3 for _ in range(width))], tuple(
        8 for _ in range(width)
    )


def check(original: str, optimized: str, *, timeout: float = 20.0) -> EquivalenceResult:
    """Decide whether ``optimized`` may be shown to the user.

    :param original: the code the user submitted.
    :param optimized: the model's proposed rewrite.
    :param timeout: seconds allowed for any single compile or run.
    :return: the verdict; ``equivalent`` is false unless proven otherwise.
    """
    if not optimized.strip() or optimized.strip() == original.strip():
        return EquivalenceResult(reason="no rewrite was offered")
    if shutil.which("c++") is None:
        return EquivalenceResult(reason="no C++ compiler on this host")

    signature = parse_signature(original)
    if signature is None:
        return EquivalenceResult(reason="could not read a function signature")
    if not signature.drivable:
        if signature.params and not signature.observable:
            why = (
                "it returns nothing and takes every argument by value, so a call "
                "leaves nothing to compare"
            )
        elif not signature.params:
            why = "it takes no arguments, so there is nothing to vary"
        else:
            why = "its arguments are not shapes the driver can supply values for"
        return EquivalenceResult(reason=f"cannot check {signature.name}(...): {why}")

    cases, timing_case = _cases(signature)
    driver = _driver(signature, cases)
    timing_driver = _driver(signature, [timing_case])
    result = EquivalenceResult(cases=len(cases))

    with tempfile.TemporaryDirectory() as directory:
        workdir = Path(directory)
        expected, error, _ = _build_and_run(HEADERS + original + driver, workdir, "orig", timeout)
        if expected is None:
            return EquivalenceResult(reason=f"original {error}", cases=len(cases))
        actual, error, _ = _build_and_run(HEADERS + optimized + driver, workdir, "opt", timeout)
        if actual is None:
            return EquivalenceResult(reason=f"rewrite {error}", cases=len(cases))

        result.verified = True
        expected_lines = expected.strip().split("\n")
        actual_lines = actual.strip().split("\n")
        result.agreed = sum(
            1
            for index, line in enumerate(expected_lines)
            if index < len(actual_lines) and actual_lines[index] == line
        )
        result.equivalent = result.agreed == result.cases
        if not result.equivalent:
            return result

        empty, _, baseline = _build_and_run(
            HEADERS + "int main(){return 0;}", workdir, "base", timeout
        )
        baseline = baseline if empty is not None else 0.0
        _, _, slow = _build_and_run(HEADERS + original + timing_driver, workdir, "slow", timeout)
        _, _, fast = _build_and_run(HEADERS + optimized + timing_driver, workdir, "fast", timeout)

    original_work = max(0.0, slow - baseline)
    optimized_work = max(0.0, fast - baseline)
    result.timing_reliable = original_work >= NOISE_FLOOR_SECONDS
    if result.timing_reliable:
        result.speedup = original_work / max(optimized_work, NOISE_FLOOR_SECONDS)
    return result
