"""Test the code-optimizer: give recursive code, see if it becomes iterative.

Problem solved: a standalone harness to eyeball whether the optimizer task
turns recursion into loops and otherwise improves the code. It prints the
original vs optimized source, the latency, and a simple before/after verdict
based on static analysis (recursion flag, max loop depth).

Usage:
    uv run python scripts/inspect_optimization.py
    uv run python scripts/inspect_optimization.py my_code.cpp
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Make the project root importable when run as a standalone script.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.core.config import MODEL_CHECKPOINT, MODEL_PATH  # noqa: E402
from app.services import optimization_service  # noqa: E402
from app.services.analyzer import analyze_code  # noqa: E402

SAMPLES: list[tuple[str, str]] = [
    (
        "factorial_recursive",
        "int factorial(int n) {\n    if (n <= 1) return 1;\n    return n * factorial(n - 1);\n}",
    ),
    (
        "fibonacci_recursive",
        "int fib(int n) {\n    if (n <= 1) return n;\n    return fib(n - 1) + fib(n - 2);\n}",
    ),
    (
        "sum_recursive",
        "int sum(int a[], int n) {\n    if (n == 0) return 0;\n"
        "    return a[n - 1] + sum(a, n - 1);\n}",
    ),
    (
        "power_recursive",
        "int power(int x, int n) {\n    if (n == 0) return 1;\n    return x * power(x, n - 1);\n}",
    ),
]


def verdict(original: str, optimized: str) -> str:
    """Summarise whether the rewrite removed recursion / added loops.

    :param original: the original source.
    :param optimized: the optimized source.
    :return: a short human-readable verdict string.
    """
    before = analyze_code(original)
    after = analyze_code(optimized)
    if before.recursive and not after.recursive:
        if after.max_nested_loops >= 1:
            return "IMPROVED: recursion -> loop"
        return "IMPROVED: recursion removed"
    if before.recursive and after.recursive:
        return "UNCHANGED: still recursive"
    if after.max_nested_loops > before.max_nested_loops:
        return "NOTE: deeper nesting introduced"
    return "KEPT (no recursion to remove)"


def inspect_one(label: str, code: str) -> None:
    print("\n" + "=" * 78)
    print(f"OPTIMIZE: {label}")
    print("=" * 78)

    start = time.perf_counter()
    optimized = optimization_service.optimize(code)
    elapsed_ms = (time.perf_counter() - start) * 1000

    print(f"[optimizer] {elapsed_ms:.1f} ms")
    print("-" * 78)
    print("ORIGINAL:\n")
    print(code)
    print("-" * 78)
    print("OPTIMIZED:\n")
    print(optimized)
    print("-" * 78)
    print("VERDICT:", verdict(code, optimized))


def main() -> None:
    print(f"[model] checkpoint='{MODEL_CHECKPOINT}'  path={MODEL_PATH}")
    if len(sys.argv) > 1:
        path = sys.argv[1]
        with open(path, encoding="utf-8") as handle:
            inspect_one(f"file:{path}", handle.read())
        return

    for label, code in SAMPLES:
        inspect_one(label, code)


if __name__ == "__main__":
    main()
