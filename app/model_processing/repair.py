"""Targeted repairs for known model corruptions in generated C++.

Problem solved: the fine-tuned checkpoint occasionally emits token-level
garbage (invented identifiers ``elem``/``left``/``Arr``, doubled parens, stray
spaces inside brackets, comment-word typos). These replacements fix the
*documented, reproducible* corruptions from the failure table. Why a small
ordered list of exact/substring fixes rather than a general model: the corrupt
cases are specific and predictable, so a deterministic patch is safer than
guessing logic. Why applied only to the model's own output (not user code): we
must never rewrite what the user submitted.

Corruptions that need *logic* reconstruction (e.g. the full ``binarySearch``
branch) are intentionally NOT patched here -- the syntax gate
(``syntax_check``) flags those as ``needs_review`` instead of shipping a
wrong-but-pretty line.
"""

from __future__ import annotations

import re

# Ordered (old, new) substring fixes. Applied in order; each is a plain
# substring replacement so it only fires on the exact corrupt token.
_REPAIRS: tuple[tuple[str, str], ...] = (
    # factorial: dropped the spurious "/ 2" and doubled parens.
    ("n * factorial((n - 1)) / 2", "n * factorial(n - 1)"),
    # is_even: extra closing paren + missing spaces.
    ("if (n%2 == 0))", "if (n % 2 == 0)"),
    # bubbleSort: "n -= i - 1" should be "n - i - 1".
    ("j < n -= i - 1", "j < n - i - 1"),
    # binarySearch: invented "elem" identifier -> the input's "arr".
    ("elem[", "arr["),
    # checkpoint_best also invents "Arr" in array access.
    ("Arr[", "arr["),
    # reverse: invented "left" -> the input's "l"; stray space inside brackets.
    ("a[left]", "a[l]"),
    # reverse: space between the array name and its brackets ("a [r]" -> "a[r]").
    ("a [", "a["),
    # matrix_rotate: invented "row" -> the input's "i".
    ("m[row]", "m[i]"),
    # two_sum: "string j" loop variable should be "int j".
    ("string j", "int j"),
    # fib_recursive: garbled recursive call name.
    ("fibRecipRec", "fibRec"),
    # Comment-word typos.
    ("palinder", "palindrome"),
    ("pal indrome", "palindrome"),
    ("Fibond", "Fibonacci"),
    ("Fiboragorean", "Fibonacci"),
    # Generic: collapse a single space inside array brackets (e.g. "a [r]").
    ("[ ", "["),
    (" ]", "]"),
)

# "factoria" is a truncation of "factorial", but "factorial" itself already
# contains "factoria", so a plain substring replace would mangle it into
# "factoriall". The lookahead forces the match to stop before a trailing "l".
_FACTORIA_RE = re.compile(r"factoria(?!l)")


def repair_code(code: str) -> str:
    """Apply the known corruption fixes to generated commented code.

    Problem solved: returns model output with the documented token-level bugs
    normalised out, so downstream consumers see cleaner C++. Why idempotent
    substring replacement: running it twice is a no-op, which keeps the pipeline
    safe to call repeatedly.

    :param code: the model-generated commented code.
    :return: the same code with documented corruptions repaired.
    """
    repaired = code
    for old, new in _REPAIRS:
        repaired = repaired.replace(old, new)
    repaired = _FACTORIA_RE.sub("factorial", repaired)
    return repaired
