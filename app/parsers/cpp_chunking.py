"""Split a C++ file into pieces small enough for the model to answer about.

Problem solved: the Qwen checkpoint was trained on functions of roughly fifteen
lines. A whole file is neither a shape it has seen nor one that fits its
context, so a single request over a long file produces a truncated answer.
Splitting at syntax boundaries keeps every request the shape the model handles,
and no comment is ever written about half a function.

Why chunks are line ranges rather than extracted text: a chunk's first line
number is its offset into the file, so mapping an answer back to file
coordinates is exact rather than reconstructed. That is what lets an anchor
still be checked against the original file after stitching.

Why it reuses ``cpp_parser``: that module already owns the cached tree-sitter
parser, and building a second one costs the same construction the cache exists
to avoid. When tree-sitter is unavailable the file becomes one chunk, which
degrades the answer rather than failing the request.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.parsers import cpp_parser

if TYPE_CHECKING:  # pragma: no cover - only for static type checkers
    from tree_sitter import Node

#: Node types that stand alone and must never be split across chunks.
UNIT_TYPES = {
    "function_definition",
    "class_specifier",
    "struct_specifier",
    "namespace_definition",
    "template_declaration",
    "enum_specifier",
    "union_specifier",
}

#: Roughly the ratio the Qwen tokenizer achieves on C++. An estimate is enough
#: here: the budget only decides where to split, and being a little out moves a
#: boundary rather than breaking one.
CHARS_PER_TOKEN = 3.2


@dataclass(frozen=True)
class Chunk:
    """A contiguous run of lines, 1-based and inclusive at both ends."""

    start_line: int
    end_line: int
    text: str
    kind: str
    #: A single indivisible unit already over budget. Splitting it would cut a
    #: function in half, so it is passed through whole.
    oversized: bool = False

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1


def estimate_tokens(text: str) -> int:
    """Approximate the token count of ``text``."""
    return max(1, int(len(text) / CHARS_PER_TOKEN))


def _select_units(node: Node, lines: list[str], max_tokens: int) -> Iterator[tuple[int, int, str]]:
    """Yield the outermost units that fit the budget, descending when they do not.

    A class that fits is one unit; a class that does not is descended into so
    its methods become units of their own.
    """
    for child in node.children:
        start, end = child.start_point[0] + 1, child.end_point[0] + 1
        if child.type in UNIT_TYPES:
            body = "\n".join(lines[start - 1 : end])
            if estimate_tokens(body) <= max_tokens:
                yield start, end, child.type
                continue
            inner = list(_select_units(child, lines, max_tokens))
            if inner:
                yield from inner
            else:
                yield start, end, child.type
        else:
            yield from _select_units(child, lines, max_tokens)


def chunk_code(code: str, *, max_tokens: int = 300, merge_below: int | None = None) -> list[Chunk]:
    """Split ``code`` on syntax boundaries into chunks of at most ``max_tokens``.

    ``merge_below`` is the much smaller size under which neighbours are
    combined, defaulting to a third of the ceiling. The two thresholds are
    separate deliberately: merging everything up to the ceiling produces
    hundred-line chunks, which is the size the model answers worst, so merging
    only rescues scraps — includes, a stray comment, a one-line accessor — from
    becoming requests of their own.

    :param code: the source to split.
    :param max_tokens: ceiling a chunk may not cross.
    :param merge_below: size under which neighbours are combined.
    :return: chunks covering every non-blank line exactly once.
    """
    if not code.strip():
        return []
    if merge_below is None:
        merge_below = max(1, max_tokens // 3)

    lines = code.split("\n")

    def text_of(start: int, end: int) -> str:
        return "\n".join(lines[start - 1 : end])

    root = cpp_parser.parse(code)
    if root is None:
        # No parser: one chunk is a worse answer than several, but a correct
        # one, and the anchors are still checked against the file.
        return [Chunk(1, len(lines), code, "whole_file", estimate_tokens(code) > max_tokens)]

    units = sorted(_select_units(root, lines, max_tokens))
    ranges: list[tuple[int, int, str]] = []
    cursor = 1
    for start, end, kind in units:
        if start > cursor:
            ranges.append((cursor, start - 1, "filler"))
        start = max(start, cursor)
        if end >= start:
            ranges.append((start, end, kind))
            cursor = end + 1
    if cursor <= len(lines):
        ranges.append((cursor, len(lines), "filler"))

    chunks: list[Chunk] = []
    pending: list[tuple[int, int, str]] = []

    def flush() -> None:
        if not pending:
            return
        start, end = pending[0][0], pending[-1][1]
        kinds = [kind for _, _, kind in pending if kind != "filler"]
        chunks.append(
            Chunk(
                start_line=start,
                end_line=end,
                text=text_of(start, end),
                kind=kinds[0] if len(set(kinds)) == 1 else ("mixed" if kinds else "filler"),
            )
        )
        pending.clear()

    for start, end, kind in ranges:
        size = estimate_tokens(text_of(start, end))
        if size > max_tokens:
            flush()
            chunks.append(Chunk(start, end, text_of(start, end), kind, oversized=True))
            continue
        if pending:
            combined = estimate_tokens(text_of(pending[0][0], end))
            if combined > merge_below or combined > max_tokens:
                flush()
        pending.append((start, end, kind))

    flush()
    return [chunk for chunk in chunks if chunk.text.strip()]
