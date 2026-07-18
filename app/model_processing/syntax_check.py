"""Best-effort C++ syntax gate for model output.

Problem solved: the fine-tuned model sometimes emits syntactically invalid C++
(``elem[mid>target)``, ``if (n%2 == 0))``, ``a[left] = a[r]``, ``string j``). We
run ``gcc -fsyntax-only`` on the generated code so the router can flag clearly
broken output as ``needs_review`` instead of shipping it as if correct. Why
``-fsyntax-only``: it parses + type-checks without emitting an object file, so it
is fast and side-effect free. Why wrap with standard includes + ``using
namespace std;``: the model emits bare function bodies that rely on ``vector`` /
``string`` / ``cout`` etc., which need those headers to compile standalone.

The model also appends prose blocks (``### VERIFICATION``, ``# EXPLANATION``);
we strip those before compiling so the prose never causes a false failure.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

# Prose separators the model inserts after the code. A line that starts with '#'
# but is NOT a preprocessor directive (i.e. '# ' or '###') marks prose.
_PROSE_RE = re.compile(r"^\s*#(\s|#)")

_STD_PREAMBLE = (
    "#include <iostream>\n"
    "#include <vector>\n"
    "#include <string>\n"
    "#include <algorithm>\n"
    "using namespace std;\n"
)

_GCC_TIMEOUT_SECONDS = 20


def _extract_code_region(text: str) -> str:
    """Return only the C++ code portion, dropping trailing prose blocks.

    :param text: raw model output (code possibly followed by VERIFICATION prose).
    :return: the candidate C++ source, or "" when no code is found.
    """
    code_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            code_lines.append(line)
            continue
        if _PROSE_RE.match(stripped):
            break
        code_lines.append(line)
    return "\n".join(code_lines).strip()


def check_cpp_syntax(code: str) -> tuple[bool, str | None]:
    """Type-check C++ source with ``gcc -fsyntax-only``.

    Problem solved: a single boolean gate the router can use to mark output that
    the compiler rejects as needing human review. Why return the error snippet:
    the caller may log it for debugging. Why tolerate a missing compiler: if gcc
    is unavailable we refuse to fail-closed (we do not block valid output).

    :param code: the C++ source to check (may contain prose -- it is stripped).
    :return: ``(ok, error)`` where ``ok`` is True when it compiles and ``error``
        is the first compiler message (or None) when it does not.
    """
    region = _extract_code_region(code)
    if not region:
        # No extractable code (e.g. pure prose) -- nothing to verify.
        return True, None

    source = _STD_PREAMBLE + region

    gcc = "gcc"
    try:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".cpp", delete=False
        ) as handle:
            handle.write(source)
            path = handle.name
        try:
            result = subprocess.run(
                [gcc, "-fsyntax-only", "-x", "c++", path],
                capture_output=True,
                text=True,
                timeout=_GCC_TIMEOUT_SECONDS,
            )
        finally:
            Path(path).unlink(missing_ok=True)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return True, None

    if result.returncode == 0:
        return True, None

    error = (result.stderr or result.stdout).strip().splitlines()
    snippet = " ".join(error)[:500] if error else "syntax error"
    return False, snippet
