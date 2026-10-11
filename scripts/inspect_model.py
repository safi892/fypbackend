"""Inspect what the model returns, with timing and naming-robustness checks.

Problem solved: a single command to eyeball model quality across difficulty
levels and to measure latency. It also re-runs the *same logic* under different
variable names to show whether the model depends on identifier names (it
shouldn't, per the project's "reason over logic, not names" rule).

Usage:
    uv run python scripts/inspect_model.py
    uv run python scripts/inspect_model.py my_code.cpp        # one file
    uv run python scripts/inspect_model.py --category hard    # easy|medium|hard
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from pathlib import Path

# Make the project root importable when run as a standalone script.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.core.config import DEBUG_MODEL, MODEL_CHECKPOINT, MODEL_PATH  # noqa: E402
from app.model_processing.comment_rules import is_generic_comment  # noqa: E402
from app.services import comment_service, explanation_service, model_service  # noqa: E402
from app.services.analyzer import analyze_code  # noqa: E402
from app.services.explanation_service import is_generic_explanation  # noqa: E402

# --------------------------------------------------------------------------- #
# Samples by difficulty
# --------------------------------------------------------------------------- #
SAMPLES: list[tuple[str, str, str]] = [
    # (category, label, code)
    # ----------------------------- EASY -----------------------------
    ("easy", "add", "int add(int a, int b) { return a + b; }"),
    (
        "easy",
        "factorial_recursive",
        "int factorial(int n) {\n    if (n <= 1) return 1;\n    return n * factorial(n - 1);\n}",
    ),
    (
        "easy",
        "max_of_two",
        "int max(int a, int b) {\n    if (a > b) return a;\n    return b;\n}",
    ),
    (
        "easy",
        "sum_array",
        "int sum(int a[], int n) {\n    int s = 0;\n    for (int i = 0; i < n; i++) s = s + a[i];\n    return s;\n}",
    ),
    (
        "easy",
        "is_even",
        "bool isEven(int n) {\n    if (n % 2 == 0) return true;\n    return false;\n}",
    ),
    # ----------------------------- MEDIUM -----------------------------
    (
        "medium",
        "binarySearch",
        "int binarySearch(int arr[], int n, int target) {\n"
        "    int left = 0, right = n - 1;\n"
        "    while (left <= right) {\n"
        "        int mid = left + (right - left) / 2;\n"
        "        if (arr[mid] == target) return mid;\n"
        "        else if (arr[mid] < target) left = mid + 1;\n"
        "        else right = mid - 1;\n"
        "    }\n"
        "    return -1;\n}",
    ),
    (
        "medium",
        "bubbleSort",
        "void bubbleSort(int a[], int n) {\n"
        "    for (int i = 0; i < n - 1; i++)\n"
        "        for (int j = 0; j < n - i - 1; j++)\n"
        "            if (a[j] > a[j + 1]) { int t = a[j]; a[j] = a[j+1]; a[j+1] = t; }\n}",
    ),
    (
        "medium",
        "linearSearch",
        "int linearSearch(int a[], int n, int key) {\n"
        "    for (int i = 0; i < n; i++)\n"
        "        if (a[i] == key) return i;\n"
        "    return -1;\n}",
    ),
    (
        "medium",
        "gcd_euclidean",
        "int gcd(int a, int b) {\n"
        "    while (b != 0) { int t = b; b = a % b; a = t; }\n"
        "    return a;\n}",
    ),
    (
        "medium",
        "fibonacci_iterative",
        "int fib(int n) {\n"
        "    int a = 0, b = 1;\n"
        "    for (int i = 2; i <= n; i++) { int t = a + b; a = b; b = t; }\n"
        "    return b;\n}",
    ),
    (
        "medium",
        "reverse_array",
        "void reverse(int a[], int n) {\n"
        "    int l = 0, r = n - 1;\n"
        "    while (l < r) { int t = a[l]; a[l] = a[r]; a[r] = t; l++; r--; }\n}",
    ),
    # ----------------------------- HARD -----------------------------
    (
        "hard",
        "matrix_rotate_nested",
        "void rotate(int m[3][3]) {\n"
        "    for (int i = 0; i < 3; i++)\n"
        "        for (int j = i + 1; j < 3; j++) { int t = m[i][j]; m[i][j] = m[j][i]; m[j][i] = t; }\n"
        "    for (int i = 0; i < 3; i++)\n"
        "        for (int j = 0; j < 3 / 2; j++) { int t = m[i][j]; m[i][j] = m[i][2 - j]; m[i][2 - j] = t; }\n}",
    ),
    (
        "hard",
        "permutations_recursive",
        "void permute(int a[], int l, int r) {\n"
        "    if (l == r) { for (int i = 0; i <= r; i++) printf(\"%d \", a[i]); printf(\"\\n\"); return; }\n"
        "    for (int i = l; i <= r; i++) { int t = a[l]; a[l] = a[i]; a[i] = t; permute(a, l + 1, r); "
        "int u = a[l]; a[l] = a[i]; a[i] = u; }\n}",
    ),
    (
        "hard",
        "two_sum_nested",
        "void twoSum(int a[], int n, int target) {\n"
        "    for (int i = 0; i < n; i++)\n"
        "        for (int j = i + 1; j < n; j++)\n"
        "            if (a[i] + a[j] == target) { printf(\"%d %d\\n\", i, j); return; }\n}",
    ),
    (
        "hard",
        "palindrome_check",
        "bool isPalindrome(char s[], int n) {\n"
        "    int l = 0, r = n - 1;\n"
        "    while (l < r) {\n"
        "        if (s[l] != s[r]) return false;\n"
        "        l++; r--;\n"
        "    }\n"
        "    return true;\n}",
    ),
    (
        "hard",
        "fibonacci_recursive",
        "int fibRec(int n) {\n"
        "    if (n <= 1) return n;\n"
        "    return fibRec(n - 1) + fibRec(n - 2);\n}",
    ),
]

# Same binary-search logic written with three different variable-naming styles.
NAMING_VARIANTS: list[tuple[str, str]] = [
    (
        "descriptive",
        "int binarySearch(int arr[], int n, int target) {\n"
        "    int left = 0, right = n - 1;\n"
        "    while (left <= right) {\n"
        "        int mid = left + (right - left) / 2;\n"
        "        if (arr[mid] == target) return mid;\n"
        "        else if (arr[mid] < target) left = mid + 1;\n"
        "        else right = mid - 1;\n"
        "    }\n"
        "    return -1;\n}",
    ),
    (
        "short",
        "int bs(int a[], int sz, int key) {\n"
        "    int lo = 0, hi = sz - 1;\n"
        "    while (lo <= hi) {\n"
        "        int m = lo + (hi - lo) / 2;\n"
        "        if (a[m] == key) return m;\n"
        "        else if (a[m] < key) lo = m + 1;\n"
        "        else hi = m - 1;\n"
        "    }\n"
        "    return -1;\n}",
    ),
    (
        "obfuscated",
        "int f(int x[], int c, int z) {\n"
        "    int p = 0, q = c - 1;\n"
        "    while (p <= q) {\n"
        "        int w = p + (q - p) / 2;\n"
        "        if (x[w] == z) return w;\n"
        "        else if (x[w] < z) p = w + 1;\n"
        "        else q = w - 1;\n"
        "    }\n"
        "    return -1;\n}",
    ),
]


def _time_block(label: str, fn: Callable[[], object]) -> tuple[object, float]:
    """Run ``fn`` and return ``(result, seconds)``; print the elapsed time.

    :param label: human-readable stage name for the timing log.
    :param fn: zero-argument callable to time.
    :return: a tuple of the callable's return value and elapsed seconds.
    """
    start = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - start
    print(f"    [{label}] {elapsed * 1000:.1f} ms")
    return result, elapsed


def inspect_one(label: str, code: str, raw_only: bool = False) -> dict[str, object]:
    """Run the full pipeline for one snippet and print output + timings.

    Problem solved: returns the per-example metrics so the caller can render a
    summary table after the run. Why return instead of only printing: the
    user asked for an at-a-glance comparison (label x latency x length).

    :param label: a name/label for the snippet (printed as a header).
    :param code: the C++ source to analyse.
    :param raw_only: when True, print only the raw ``model.generate()`` text
        with zero post-processing (Phase-1 raw-quality verification).
    :return: a metrics dict (label, analysis_ms, model_ms, total_ms,
        commented_len, explanation_len).
    """
    print("\n" + "=" * 78)
    print(f"EXAMPLE: {label}")
    print("=" * 78)

    analysis, t_analysis = _time_block("static analysis", lambda: analyze_code(code))
    raw, t_model = _time_block(
        "model inference", lambda: model_service.run_model(code, analysis=analysis)
    )

    if raw_only:
        print("-" * 78)
        print("RAW model.generate() OUTPUT (zero post-processing):\n")
        print(raw.raw_text.strip())
        return {
            "label": label,
            "analysis_ms": t_analysis * 1000,
            "model_ms": t_model * 1000,
            "total_ms": (t_analysis + t_model) * 1000,
            "commented_len": 0,
            "explanation_len": 0,
        }

    commented, _ = _time_block(
        "comment select", lambda: comment_service.generate(code, raw.commented_code)
    )
    explanation, _ = _time_block(
        "explanation select", lambda: explanation_service.generate(code, raw.explanation)
    )

    total_ms = (t_analysis + t_model) * 1000
    print(f"    [total] {total_ms:.1f} ms "
          f"(analysis {t_analysis * 1000:.1f} + model {t_model * 1000:.1f})")

    if DEBUG_MODEL:
        print("-" * 78)
        print("RAW model.generate() OUTPUT:\n")
        print(raw.raw_text.strip())

    print("-" * 78)
    comment_flag = "  [GENERIC COMMENT]" if is_generic_comment(commented) else ""
    explain_flag = "  [GENERIC EXPLANATION]" if is_generic_explanation(explanation) else ""
    print(f"commented_code:{comment_flag}\n")
    print(commented)
    print("-" * 78)
    print(f"explanation:{explain_flag}\n")
    print(explanation)

    return {
        "label": label,
        "analysis_ms": t_analysis * 1000,
        "model_ms": t_model * 1000,
        "total_ms": total_ms,
        "commented_len": len(commented),
        "explanation_len": len(explanation),
    }


def run_naming_comparison() -> list[dict[str, object]]:
    """Run the same logic under different variable names and compare output.

    :return: the list of per-variant metrics dicts for the summary table.
    """
    print("\n" + "#" * 78)
    print("# NAMING ROBUSTNESS: same logic, different variable names")
    print("#" * 78)
    rows: list[dict[str, object]] = []
    for name, code in NAMING_VARIANTS:
        rows.append(inspect_one(f"binarySearch :: {name}", code))
    return rows


def print_summary(rows: list[dict[str, object]]) -> None:
    """Print a comparison table of all inspected examples.

    Problem solved: lets the user compare latency and output size across all
    samples at a glance after a (slow) run. Why a fixed-width table: readable
    in a terminal without extra dependencies.

    :param rows: metrics dicts returned by ``inspect_one``.
    """
    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    header = f"{'example':<28} {'analysis':>9} {'model':>9} {'total':>9} {'cmmt':>6} {'expl':>6}"
    print(header)
    print("-" * 78)
    for row in rows:
        print(
            f"{str(row['label']):<28} "
            f"{row['analysis_ms']:>8.1f}ms "
            f"{row['model_ms']:>8.1f}ms "
            f"{row['total_ms']:>8.1f}ms "
            f"{row['commented_len']:>6} "
            f"{row['explanation_len']:>6}"
        )


def main() -> None:
    print(f"[model] checkpoint='{MODEL_CHECKPOINT}'  path={MODEL_PATH}")
    print(f"[device] {model_service.active_device()}")
    category_filter: str | None = None
    file_arg: str | None = None
    raw_only = False
    args = sys.argv[1:]
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--raw":
            raw_only = True
        elif arg.startswith("--category"):
            if "=" in arg:
                category_filter = arg.split("=", 1)[1]
            else:
                index += 1
                category_filter = args[index]
        elif not arg.startswith("-"):
            file_arg = arg
        index += 1

    rows: list[dict[str, object]] = []

    if file_arg:
        with open(file_arg, encoding="utf-8") as handle:
            rows.append(inspect_one(f"file:{file_arg}", handle.read(), raw_only=raw_only))
        print_summary(rows)
        return

    for category, label, code in SAMPLES:
        if category_filter and category != category_filter:
            continue
        rows.append(inspect_one(f"{category} :: {label}", code, raw_only=raw_only))

    if (not category_filter or category_filter == "medium") and not raw_only:
        rows.extend(run_naming_comparison())

    print_summary(rows)


if __name__ == "__main__":
    main()
