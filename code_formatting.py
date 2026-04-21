def clean_duplicate_code(output: str) -> str:
    parts = output.split("### COMMENTED CODE")
    if len(parts) > 2:
        return "### COMMENTED CODE" + parts[-1]
    return output


def format_commented_code_for_editor(code: str) -> str:
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
