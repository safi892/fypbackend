import re


def has_meaningful_explanation(explanation: str) -> bool:
    normalized = explanation.strip()
    if not normalized:
        return False

    weak_values = {"none", "n/a", "no explanation", "null"}
    return normalized.lower() not in weak_values


def _detect_function_name(code: str) -> str | None:
    for line in code.splitlines():
        stripped = line.strip()
        match = re.match(
            r"^(?!if\b|for\b|while\b|switch\b|catch\b)(?:[\w:&*<>\[\]\s]+)\s+([A-Za-z_]\w*)\s*\([^;]*\)\s*\{?$",
            stripped,
        )
        if match:
            return match.group(1)
    return None


def _collect_behaviors(code: str) -> list[str]:
    behaviors: list[str] = []

    if re.search(r"\bfor\s*\(|\bwhile\s*\(|\bdo\s*\{?", code):
        behaviors.append("uses loops to repeat work")
    if re.search(r"\bif\s*\(|\belse\b|\bswitch\s*\(", code):
        behaviors.append("checks conditions to control the flow")
    if re.search(r"\breturn\b", code):
        behaviors.append("returns a result")
    if re.search(r"\bcout\s*<<|\bprintf\s*\(", code):
        behaviors.append("prints output")
    if re.search(r"\bcin\s*>>|\bscanf\s*\(", code):
        behaviors.append("reads input")
    if re.search(r"\bswap\s*\(|\btemp\b|\btmp\b", code):
        behaviors.append("reorders values by swapping them")
    if re.search(r"\b(push_back|emplace_back)\s*\(", code):
        behaviors.append("adds values into a container")
    if re.search(r"\b(accumulate|sort|reverse|find|max|min)\s*\(", code):
        behaviors.append("uses a standard library helper")
    if re.search(r"\+\+|--|\+=|-=|\*=|/=|%=|=.+[+\-*/%].+;", code):
        behaviors.append("performs arithmetic operations")
    if re.search(r"\b(sum|total)\b", code):
        behaviors.append("tracks a running total")
    if re.search(r"\b(count|cnt)\b", code):
        behaviors.append("tracks a counter")
    if re.search(r"\b(avg|average)\b", code):
        behaviors.append("computes an average")
    if re.search(r"\b(maximum|max)\b", code):
        behaviors.append("looks for a maximum value")
    if re.search(r"\b(minimum|min)\b", code):
        behaviors.append("looks for a minimum value")
    if re.search(r"\b(arr|array|vector)\b|\[[^\]]+\]", code):
        behaviors.append("works with a collection of values")
    if re.search(r"\b(fib|factorial|gcd|lcm|prime|binarySearch|bubbleSort|linearSearch)\b", code):
        behaviors.append("implements a common student algorithm")

    deduped: list[str] = []
    for behavior in behaviors:
        if behavior not in deduped:
            deduped.append(behavior)
    return deduped


def generate_rule_based_explanation(code: str) -> str:
    function_name = _detect_function_name(code)
    behaviors = _collect_behaviors(code)

    if function_name:
        opening = f"The function {function_name} processes the given code."
    else:
        opening = "This code processes the given input step by step."

    if not behaviors:
        return f"{opening} It updates values and follows the written statements in order."

    if len(behaviors) == 1:
        detail = behaviors[0]
    elif len(behaviors) == 2:
        detail = f"{behaviors[0]} and {behaviors[1]}"
    else:
        detail = ", ".join(behaviors[:-1]) + f", and {behaviors[-1]}"

    return f"{opening} It {detail}."
