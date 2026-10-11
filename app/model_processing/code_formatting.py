"""Post-processing helpers for model-generated comments.

Problem solved: the CodeT5 output sometimes contains duplicated ``### COMMENTED
CODE`` blocks or inconsistent ``//`` placement. These helpers clean and reformat
that text into something the mobile editor can display reliably.
"""

from __future__ import annotations


def clean_duplicate_code(output: str) -> str:
    """Strip duplicated ``### COMMENTED CODE`` blocks from model output.

    Problem solved: certain checkpoints echo the section header twice, so we
    keep only the final (canonical) block. Why split on the header: it cleanly
    separates the duplicate preamble from the real content.

    :param output: the raw model output text.
    :return: the output with only the last comment block retained.
    """
    parts = output.split("### COMMENTED CODE")
    if len(parts) > 2:
        return "### COMMENTED CODE" + parts[-1]
    return output


def format_commented_code_for_editor(code: str) -> str:
    """Normalise ``//`` comment placement so each comment sits on its own line.

    Problem solved: the editor expects a comment directly above the code it
    describes, but model output may append ``//`` inline. Why move the comment
    to a separate line above: keeps code columns clean and readable on mobile.

    :param code: commented C++ source (any ``//`` placement).
    :return: source with each inline comment moved to its own line above the
        code it annotates.
    """
    formatted_lines: list[str] = []

    for line in code.splitlines():
        if "//" not in line:
            formatted_lines.append(line)
            continue

        code_part, comment_part = line.split("//", 1)
        code_part = code_part.rstrip()
        comment_part = comment_part.strip()
        indent = code_part[: len(code_part) - len(code_part.lstrip())]

        if code_part.strip() and comment_part:
            formatted_lines.append(f"{indent}// {comment_part}")
            formatted_lines.append(code_part)
        else:
            formatted_lines.append(line)

    return "\n".join(formatted_lines)
