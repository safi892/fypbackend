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
SCALAR_TYPES = {"int", "long", "long long", "size_t", "unsigned", "double", "float", "bool"}

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
class Signature:
    """A parsed function signature."""

    return_type: str
    name: str
    params: tuple[tuple[str, str], ...]

    @property
    def drivable(self) -> bool:
        """Whether a caller can be generated for this shape."""
        if self.return_type.strip() == "void" or not self.params:
            return False
        return all(
            ptype.replace("const", "").replace("&", "").strip() in SCALAR_TYPES
            for ptype, _ in self.params
        )


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
        params: list[tuple[str, str]] = []
        if raw and raw != "void":
            for piece in raw.split(","):
                cleaned = re.sub(r"\[\s*\]", "", piece).strip()
                bits = cleaned.replace("&", " ").replace("*", " ").split()
                if len(bits) < 2:
                    return None
                params.append((" ".join(bits[:-1]), bits[-1]))
        return Signature(match.group("ret").strip(), name, tuple(params))
    return None


def _driver(signature: Signature, cases: list[tuple[int, ...]]) -> str:
    calls = "\n".join(
        f'  {{ auto r = {signature.name}({", ".join(str(v) for v in case)}); '
        f'std::cout << "{", ".join(str(v) for v in case)}" << " => " << r << "\\n"; }}'
        for case in cases
    )
    return f"\n\nint main() {{\n{calls}\n  return 0;\n}}\n"


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


def _cases(signature: Signature) -> tuple[list[tuple[int, ...]], tuple[int, ...]]:
    """Small inputs for correctness, and one large input for timing.

    They have to be different. Small inputs finish faster than a process takes
    to start, so timing them measures the operating system; large inputs make
    an exponential implementation visible.
    """
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
        return EquivalenceResult(
            reason=f"cannot generate a caller for {signature.name}(...) automatically"
        )

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
