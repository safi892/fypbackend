import re
from typing import Optional


def has_meaningful_comments(code: str) -> bool:
    return any("//" in line for line in code.splitlines())


def _normalize_code_for_rules(code: str) -> str:
    normalized = code.replace("{", "{\n").replace("}", "\n}")
    normalized = re.sub(r";\s*", ";\n", normalized)
    normalized = re.sub(r"\n{2,}", "\n", normalized)
    return normalized.strip()


def _match_arithmetic_comment(stripped_line: str) -> Optional[str]:
    if re.search(r"\w+\s*=\s*.+\s*\+\s*.+;", stripped_line):
        return "Add values and store the result"
    if re.search(r"\w+\s*=\s*.+\s*-\s*.+;", stripped_line):
        return "Subtract one value from another and store the result"
    if re.search(r"\w+\s*=\s*.+\s*\*\s*.+;", stripped_line):
        return "Multiply values and store the result"
    if re.search(r"\w+\s*=\s*.+\s*/\s*.+;", stripped_line):
        return "Divide values and store the result"
    if re.search(r"\w+\s*=\s*.+\s*%\s*.+;", stripped_line):
        return "Compute the remainder after division"
    if re.search(r"^\+\+\w+;|^\w+\+\+;$", stripped_line):
        return "Increase the value by 1"
    if re.search(r"^--\w+;|^\w+--;?$", stripped_line):
        return "Decrease the value by 1"
    if re.search(r"\w+\s*\+=\s*.+;", stripped_line):
        return "Add to the current value"
    if re.search(r"\w+\s*-=\s*.+;", stripped_line):
        return "Subtract from the current value"
    if re.search(r"\w+\s*\*=\s*.+;", stripped_line):
        return "Multiply and update the current value"
    if re.search(r"\w+\s*/=\s*.+;", stripped_line):
        return "Divide and update the current value"
    return None


def _match_student_friendly_comment(stripped_line: str) -> Optional[str]:
    declaration_match = re.match(
        r"^(int|float|double|char|bool|string|long|short)\s+([A-Za-z_]\w*)\s*(=\s*.+)?;$",
        stripped_line,
    )
    if declaration_match:
        variable_name = declaration_match.group(2)
        if declaration_match.group(3):
            return f"Declare {variable_name} and set its starting value"
        return f"Declare the variable {variable_name}"

    if re.search(r"\b(sum|total)\s*\+?=", stripped_line):
        return "Add the current value to the running sum"
    if re.search(r"\b(count|cnt)\s*\+\+|\b(count|cnt)\s*\+=\s*1", stripped_line):
        return "Increase the counter"
    if re.search(r"\b(avg|average)\b", stripped_line) and "/" in stripped_line:
        return "Calculate the average value"
    if re.search(r"\b(minimum|min)\b", stripped_line):
        return "Track or compare the smallest value"
    if re.search(r"\b(maximum|max)\b", stripped_line):
        return "Track or compare the largest value"
    if "[" in stripped_line and "]" in stripped_line and "=" in stripped_line:
        return "Update a value at a specific array position"
    if ".size()" in stripped_line:
        return "Use the container size in this step"
    if "vector<" in stripped_line or "array<" in stripped_line:
        return "Create a container to store multiple values"
    return None


def rule_based_comment_for_line(stripped_line: str) -> Optional[str]:
    if not stripped_line or stripped_line in {"{", "}", "};"}:
        return None

    if stripped_line.startswith(("//", "/*", "*", "*/", "#include", "using ", "namespace ")):
        return None

    function_match = re.match(
        r"^(?!if\b|for\b|while\b|switch\b|catch\b)(?:[\w:&*<>\[\]\s]+)\s+([A-Za-z_]\w*)\s*\([^;]*\)\s*\{?$",
        stripped_line,
    )
    if function_match:
        function_name = function_match.group(1)
        return f"Define the function {function_name}"

    if re.match(r"^(if|else if)\s*\(", stripped_line):
        return "Check whether the condition is true before running this block"
    if stripped_line.startswith("else"):
        return "Run this block when earlier conditions do not match"
    if re.match(r"^for\s*\(", stripped_line):
        return "Iterate through values using a loop"
    if re.match(r"^while\s*\(", stripped_line):
        return "Repeat this block while the condition remains true"
    if re.match(r"^do\s*\{?$", stripped_line):
        return "Start a loop that runs at least once"
    if re.match(r"^switch\s*\(", stripped_line):
        return "Branch to a case based on the expression value"
    if stripped_line.startswith("case "):
        return "Handle this specific switch case"
    if stripped_line.startswith("default:"):
        return "Handle values that do not match any explicit case"
    if stripped_line.startswith("break;"):
        return "Exit the current loop or switch block"
    if stripped_line.startswith("continue;"):
        return "Skip to the next loop iteration"
    if stripped_line.startswith("return "):
        return "Return the computed value to the caller"
    if stripped_line == "return;":
        return "Exit the function early"
    if "swap(" in stripped_line:
        return "Swap the two values"
    if "cout <<" in stripped_line or "printf(" in stripped_line or stripped_line.startswith("print("):
        return "Display output to the user"
    if "cin >>" in stripped_line or "scanf(" in stripped_line or stripped_line.startswith("input("):
        return "Read input into a variable"
    if ".push_back(" in stripped_line or ".emplace_back(" in stripped_line:
        return "Append a new element to the container"
    if re.search(r"\b(sort|reverse|accumulate|max|min|find)\s*\(", stripped_line):
        return "Apply a standard library operation"
    if re.search(r"\b(temp|tmp)\b\s*=", stripped_line):
        return "Store a temporary value for later use"

    arithmetic_comment = _match_arithmetic_comment(stripped_line)
    if arithmetic_comment:
        return arithmetic_comment

    student_comment = _match_student_friendly_comment(stripped_line)
    if student_comment:
        return student_comment

    if re.search(r"\w+\s*=\s*.+;", stripped_line):
        return "Update the variable with a new value"

    return None


def generate_rule_based_comments(code: str) -> str:
    commented_lines: list[str] = []

    for line in _normalize_code_for_rules(code).splitlines():
        stripped_line = line.strip()
        indent = line[: len(line) - len(line.lstrip())]
        comment = rule_based_comment_for_line(stripped_line)

        if comment:
            commented_lines.append(f"{indent}// {comment}")
        commented_lines.append(line.rstrip())

    return "\n".join(commented_lines)
