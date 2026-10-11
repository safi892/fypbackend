"""Code change analysis (Phase 4) — deterministic old vs new comparison.

Problem solved: when a user submits a previous version of the code, we must
report what changed at the function level (added / removed / modified) and
whether complexity went up. This is pure comparison — no AI.

Why compare normalized bodies: stripping comments before comparing means a
comment-only edit does not count as a "modified" function. Why recompute
cyclomatic complexity on each side: it gives a single ``complexity_delta``
signal the frontend can show directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.parsers import cpp_parser
from app.schemas.analyze import ChangeAnalysis
from app.services.analyzer import _function_name, analyze_code
from app.utils.text import strip_comments_cpp

if TYPE_CHECKING:  # pragma: no cover - typing only
    from tree_sitter import Node


def _function_bodies(code: str) -> dict[str, str]:
    """Map each function name to its normalized body (comments stripped).

    Problem solved: we need a name -> body view of one version to diff against
    another. Why strip comments: avoids false "modified" on comment edits.
    Why skip when parser is unavailable: without a parser we cannot reliably
    map names to bodies, so we return empty and the caller reports no changes.

    :param code: the C++ source for one version (old or new).
    :return: mapping of function name to its whitespace-normalized body.
    """
    root: Node | None = cpp_parser.parse(code)
    bodies: dict[str, str] = {}
    if root is None:
        return bodies

    for fn in cpp_parser.iter_descendants(root, {"function_definition"}):
        name = _function_name(fn)
        body: Node | None = fn.child_by_field_name("body")
        body_text = cpp_parser.node_text(body) if body is not None else ""
        if name:
            bodies[name] = strip_comments_cpp(body_text)
    return bodies


def compare(old_code: str, new_code: str) -> ChangeAnalysis:
    """Compare two versions of C++ code and summarize the function-level delta.

    Problem solved: produce the ``ChangeAnalysis`` consumed by the router.
    Why set difference for added/removed and body compare for modified: that is
    exactly the three states a function can be in between versions.

    :param old_code: the previous version of the source.
    :param new_code: the new version of the source.
    :return: a ``ChangeAnalysis`` with added/removed/modified names and the
        cyclomatic-complexity delta.
    """
    old_bodies = _function_bodies(old_code)
    new_bodies = _function_bodies(new_code)

    old_names = set(old_bodies)
    new_names = set(new_bodies)

    added = sorted(new_names - old_names)
    removed = sorted(old_names - new_names)
    modified = sorted(
        name for name in (old_names & new_names) if old_bodies[name] != new_bodies[name]
    )

    old_complexity = analyze_code(old_code).cyclomatic_complexity
    new_complexity = analyze_code(new_code).cyclomatic_complexity
    delta = new_complexity - old_complexity

    return ChangeAnalysis(
        added_functions=added,
        removed_functions=removed,
        modified_functions=modified,
        complexity_delta=delta,
        complexity_increased=delta > 0,
    )
