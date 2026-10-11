"""Shared text/code helpers used across analyzer and generator services.

Problem solved: several independent modules needed the same small string
operations (whitespace normalization, comment stripping, line counting).
Centralising them avoids copy-paste and keeps behaviour consistent.

Why these helpers: the diff service compares function bodies, and that
comparison must ignore comment-only edits to avoid false "modified" reports.
"""

from __future__ import annotations

import re

_WHITESPACE = re.compile(r"\s+")


def normalize_whitespace(text: str) -> str:
    """Collapse all runs of whitespace into single spaces and trim ends.

    Problem solved: when normalising source for comparison or display we want
    one canonical form. Why ``\\s+``: handles tabs/newlines/carriage returns.

    :param text: the raw string to normalize.
    :return: the whitespace-collapsed, trimmed string.
    """
    return _WHITESPACE.sub(" ", text).strip()


def strip_comments_cpp(code: str) -> str:
    """Remove C/C++ comments so body comparison ignores comment-only edits.

    Problem solved: the diff service compares *normalized* function bodies. If
    comments stayed, adding a comment would wrongly count as a "modified"
    function. Why block-then-line order: line comments after a block would
    otherwise capture the trailing ``*/``.

    :param code: the C++ source whose comments to strip.
    :return: the source with block and line comments removed and whitespace
        normalized.
    """
    without_block = re.sub(r"/\*.*?\*/", "", code, flags=re.DOTALL)
    without_line = re.sub(r"//[^\n]*", "", without_block)
    return normalize_whitespace(without_line)


def count_lines(code: str) -> int:
    """Count non-blank source lines.

    Problem solved: a quick, cheap size metric for logging and thresholds.
    Why skip blank lines: they carry no signal about code volume.

    :param code: the source to measure.
    :return: number of non-empty lines.
    """
    return len([line for line in code.splitlines() if line.strip()])
