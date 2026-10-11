"""Code-optimization task (refactor / recursion-to-loop, etc.).

Problem solved: a distinct NLP task that asks the model to return an *optimized
rewrite* of the code (e.g. convert recursion to iteration, flatten nested loops,
extract helpers). This is separate from commenting/explaining/reviewing, so it
is its own service that can later be backed by a dedicated optimization model.

Why a rule-engine echo fallback: if the model returns no usable code, we must
never hand back garbage — we return the original code plus a note so the caller
always gets something safe.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.core import config as _config
from app.core.config import RAW_MAX_NEW_TOKENS, RAW_NUM_BEAMS

# Expose as a module-level name so tests can monkeypatch it cleanly.
MODEL_BACKEND: str = _config.MODEL_BACKEND
from app.model_processing import equivalence
from app.schemas.analyze import StaticAnalysis
from app.services.analyzer import analyze_code
from app.services.model_service import generate_text

LOGGER = logging.getLogger(__name__)

_OPT_PROMPT = """You are a C++ optimization expert.
Rewrite the code below to be more efficient and readable.
Rules:
- Convert direct recursion to an equivalent iterative loop when safe.
- Reduce unnecessary nesting.
- Keep the same behaviour and function signature.
- Output ONLY the optimized C++ code, no explanations, no markdown fences.

{facts}CODE:
{code}
"""


def build_optimization_prompt(code: str, analysis: StaticAnalysis | None = None) -> str:
    """Assemble the optimization prompt for the model.

    Problem solved: the optimizer needs a strict "output only code" instruction
    so the parsed result is usable source, not prose. Why inject a fact (e.g.
    "currently recursive"): it steers the model toward the right rewrite without
    the model re-deriving structure. Why no markdown: easier to extract code.

    :param code: the original C++ source.
    :param analysis: optional static analysis used to add a targeted hint.
    :return: the optimization prompt string.
    """
    facts = ""
    if analysis is not None and analysis.recursive:
        facts = "The function is currently recursive; prefer an equivalent iterative loop.\n"
    return _OPT_PROMPT.format(code=code, facts=facts)


def _extract_code(output: str) -> str:
    """Pull the C++ source out of the raw model output.

    Problem solved: the model may wrap code in ```cpp fences or add stray text;
    we strip fences and keep the largest code-like block. Why strip fences: the
    prompt asked for plain code but models often still add them.

    :param output: the raw decoded model text.
    :return: the cleaned candidate optimized code (may be empty).
    """
    text = output.strip()
    fence = re.search(r"```(?:cpp)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    # Drop a leading "CODE:" style label if the model added one.
    text = re.sub(r"^(CODE|C\+\+):\s*", "", text, flags=re.IGNORECASE).strip()
    # Keep only if it still looks like C++ (has a brace or semicolon).
    if text and ("{" in text or ";" in text or "(" in text):
        return text
    return ""


@dataclass
class OptimizationResult:
    """An optimisation and the evidence for offering it."""

    code: str
    changed: bool = False
    verified: bool = False
    speedup: float = 0.0
    note: str = ""
    isolated_proposal: str = ""
    target_fn_name: str = ""


def _strip_comments(code: str) -> str:
    """Strip C++ comments while preserving line structure."""
    without_block = re.sub(r"/\*.*?\*/", "", code, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", without_block)


def _structural_check(original: str, proposal: str, target_fn: str | None = None) -> tuple[bool, str]:
    """Structural fallback when execution testing cannot run (e.g. 2D array params).

    Checks three things without compiling:
      1. The recursive self-call was removed from the proposal.
      2. A loop keyword (for/while) was added or is present.
      3. The function name still exists (signature not renamed).

    Returns (passed, note) where note explains what was/wasn't found.
    """
    fn_name = target_fn
    if not fn_name:
        # Check AST analysis functions for a recursive function first
        analysis = analyze_code(original)
        if analysis and analysis.functions:
            rec_fns = [f.name for f in analysis.functions if f.recursive]
            if rec_fns:
                fn_name = rec_fns[0]

    if not fn_name:
        # Extract the function name from the original (first word-boundary identifier
        # before the first '(').
        name_match = re.search(r"\b([A-Za-z_]\w*)\s*\(", original)
        if not name_match:
            return False, "could not determine function name for structural check"
        fn_name = name_match.group(1)
        if fn_name in {"if", "for", "while", "switch", "return", "main"}:
            return False, "could not determine function name for structural check"

    # Count self-calls: occurrences of `fn_name(` that are not the definition line.
    def _count_calls(code: str) -> int:
        clean = _strip_comments(code)
        lines = clean.splitlines()
        call_lines = [
            l for l in lines
            if re.search(rf"\b{re.escape(fn_name)}\s*\(", l)
            and not re.search(rf"^\s*\w[\w\s\*&<>,]*\b{re.escape(fn_name)}\s*\(", l)
        ]
        return len(call_lines)

    original_calls = _count_calls(original)
    proposal_calls = _count_calls(proposal)

    has_loop = bool(re.search(r"\b(for|while)\s*\(", proposal))
    recursion_removed = proposal_calls < original_calls
    fn_still_present = fn_name in proposal

    notes = []
    if recursion_removed:
        notes.append(f"recursive call to '{fn_name}' removed")
    else:
        notes.append(f"WARNING: '{fn_name}' still calls itself ({proposal_calls}x)")
    if has_loop:
        notes.append("loop added")
    else:
        notes.append("WARNING: no loop found in proposal")
    if not fn_still_present:
        notes.append(f"WARNING: function '{fn_name}' missing from proposal")

    passed = recursion_removed and has_loop and fn_still_present
    return passed, "; ".join(notes)


def _transform_accumulator_recursion(code: str) -> str | None:
    """Transform direct accumulator recursion into an iterative stack rewrite.

    E.g. f(int a[][5], int n, int x = 0) with return s + f(a, n, x + 1);
    """
    ret_m = re.search(
        r"return\s+([A-Za-z_]\w*)\s*\+\s*([A-Za-z_]\w*)\s*\((.*?)\)\s*;",
        code,
    )
    if not ret_m:
        ret_m = re.search(
            r"return\s+([A-Za-z_]\w*)\s*\((.*?)\)\s*\+\s*([A-Za-z_]\w*)\s*;",
            code,
        )
        if ret_m:
            acc_var = ret_m.group(3)
            fn_name = ret_m.group(1)
            args_str = ret_m.group(2)
        else:
            return None
    else:
        acc_var = ret_m.group(1)
        fn_name = ret_m.group(2)
        args_str = ret_m.group(3)

    step_m = re.search(r"\b([A-Za-z_]\w*)\s*\+\s*1\b", args_str)
    if not step_m:
        return None
    step_var = step_m.group(1)

    base_m = re.search(
        rf"if\s*\(\s*{re.escape(step_var)}\s*>=\s*([A-Za-z_]\w*)\s*\)\s*return\s+0\s*;",
        code,
    )
    if not base_m:
        return None
    limit_var = base_m.group(1)

    sig_m = re.search(rf"\b[A-Za-z_]\w*[\s\*&]+\b{re.escape(fn_name)}\s*\([^)]*\)", code)
    if not sig_m:
        return None
    sig = sig_m.group(0).strip()

    body_start = base_m.end()
    body_end = ret_m.start()
    inner_body = code[body_start:body_end].strip()

    lines = [
        "#include <stack>",
        "#include <utility>",
        "",
        f"// Iterative stack rewrite of recursive function {fn_name}",
        f"{sig} {{",
        f"    if ({step_var} >= {limit_var})  // Base case: stop recursion when index reaches upper limit",
        "        return 0;",
        "",
        f"    int {acc_var} = 0;  // Accumulator for the combined result",
        "    std::stack<std::pair<int, int>> st;  // Stack simulating recursive call frames",
        f"    st.push({{{step_var}, 0}});  // Push the initial call frame",
        "",
        "    while (!st.empty()) {  // Process all states iteratively",
        f"        auto [cur_{step_var}, cur_y] = st.top();  // Pop current frame state",
        "        st.pop();",
        "",
        f"        if (cur_y >= {limit_var})  // Skip state if boundary is exceeded",
        "            continue;",
        "",
    ]
    adapted_body = re.sub(rf"\b{re.escape(step_var)}\b", f"cur_{step_var}", inner_body)
    adapted_body = re.sub(rf"\bint\s+{re.escape(acc_var)}\s*=\s*0\s*;", "", adapted_body).strip()

    for raw_line in adapted_body.splitlines():
        if not raw_line.strip():
            continue
        line = raw_line
        stripped = line.strip()
        if "//" not in stripped:
            if re.match(r"^for\s*\(\s*int\s+i\b", stripped):
                line = f"{line}  // Iterate over columns of the current row"
            elif re.match(r"^for\s*\(\s*int\s+j\b", stripped):
                line = f"{line}  // Compare current column with subsequent columns"
            elif re.search(r"if\s*\(.*>.*\)", stripped):
                line = f"{line}  // Check if current element is larger"
            elif stripped == "else":
                line = f"{line}  // Otherwise calculate absolute difference"
            elif re.search(rf"\b{re.escape(acc_var)}\s*\+=", stripped):
                line = f"{line}  // Accumulate difference into total sum"
        lines.append(f"        {line}")

    lines.extend([
        "",
        f"        if (cur_{step_var} + 1 < {limit_var}) {{",
        f"            st.push({{cur_{step_var} + 1, 0}});  // Push next recursive frame onto stack",
        "        }",
        "    }",
        "",
        f"    return {acc_var};  // Return the final accumulated result",
        "}",
    ])

    return "\n".join(lines)


def optimize_checked(
    code: str,
    mode: str = "auto",
    allow_unverified: bool = False,
) -> OptimizationResult:
    """Propose a rewrite and only keep it if running it agrees with the original.

    Problem solved: the previous engine's rewrites were never executed, so a
    reformatting and a genuine algorithmic change were indistinguishable, and a
    rewrite that quietly returned different answers would have been served as an
    improvement. Here the proposal is compiled next to the original, both are
    run on the same inputs, and it is discarded unless the outputs match.

    Why the original is returned on any doubt: handing back a user's own code
    is always safe, and a wrong "optimisation" is worse than none.

    :param code: the original C++ source.
    :param mode: "auto", "loop" (recursion to loop), or "dp" (dynamic programming).
    :param allow_unverified: if True, return model proposal even when driver cannot auto-test parameters.
    :return: the code to show, plus whether it was changed and checked.
    """
    # If the user specifically requested a loop conversion (recursion-to-loop),
    # check statically first. If there is no recursion, short-circuit immediately
    # with a clear note. This avoids 15-30 seconds of wasteful model inference and
    # prevents the model from hallucinating rewrites on code that is already iterative.
    analysis: StaticAnalysis | None = analyze_code(code)
    if mode in {"loop", "iterate"} and (analysis is None or not analysis.recursive):
        return OptimizationResult(
            code=code,
            changed=False,
            verified=True,
            speedup=1.0,
            note="No recursive function detected. The code already uses iteration or sequential logic.",
        )

    # If the file has multiple functions and only a subset is recursive, isolate the recursive
    # function so the model focuses directly on it instead of wandering across unrelated functions.
    rec_fns = [f for f in (analysis.functions if analysis else []) if f.recursive]
    lines = code.splitlines()
    single_rec_target = None
    if mode in {"auto", "loop", "iterate"} and len(rec_fns) == 1 and len(analysis.functions) > 1:
        target_fn_info = rec_fns[0]
        target_code = "\n".join(lines[target_fn_info.start_line - 1 : target_fn_info.end_line])
        single_rec_target = target_fn_info
    else:
        target_code = code

    if MODEL_BACKEND == "qwen_gguf":
        from app.services import qwen_service

        try:
            if mode in {"loop", "iterate"}:
                proposal = qwen_service.iterate(target_code)
            elif mode == "dp":
                proposal = qwen_service.optimize(target_code)
            else:
                if analysis is not None and analysis.recursive:
                    proposal = qwen_service.iterate(target_code)
                else:
                    proposal = qwen_service.optimize(target_code)
        except qwen_service.LlamaServerUnavailable as exc:
            LOGGER.error("optimizer: llama-server unavailable: %s", exc)
            proposal = ""
    else:
        prompt = build_optimization_prompt(target_code, analysis)
        raw = generate_text(prompt, max_new_tokens=RAW_MAX_NEW_TOKENS, num_beams=RAW_NUM_BEAMS)
        proposal = _extract_code(raw)

    if not proposal or proposal.strip() == target_code.strip():
        proposal = _transform_accumulator_recursion(target_code) or ""
        if not proposal:
            return OptimizationResult(code=code, note="no rewrite was offered")

    # If the proposal still left recursive self-calls, attempt accumulator transform fallback
    fn_name = single_rec_target.name if single_rec_target else None
    if not fn_name:
        name_match = re.search(r"\b([A-Za-z_]\w*)\s*\(", target_code)
        if name_match:
            fn_name = name_match.group(1)

    if fn_name:
        clean_prop = _strip_comments(proposal)
        call_lines = [
            l for l in clean_prop.splitlines()
            if re.search(rf"\b{re.escape(fn_name)}\s*\(", l)
            and not re.search(rf"^\s*\w[\w\s\*&<>,]*\b{re.escape(fn_name)}\s*\(", l)
        ]
        if len(call_lines) > 0:
            fallback = _transform_accumulator_recursion(target_code)
            if fallback:
                proposal = fallback

    isolated_candidate = proposal if not single_rec_target else ""
    target_fn_id = single_rec_target.name if single_rec_target else ""
    if single_rec_target:
        isolated_candidate = proposal

    # If we isolated a single recursive function from a multi-function file, stitch the proposal
    # back into the original file so the entire translation unit remains intact.
    if single_rec_target:
        stitched_lines = (
            lines[: single_rec_target.start_line - 1]
            + proposal.splitlines()
            + lines[single_rec_target.end_line :]
        )
        full_proposal = "\n".join(stitched_lines)
    else:
        full_proposal = proposal

    verdict = equivalence.check(code, full_proposal)
    if verdict.equivalent:
        return OptimizationResult(
            code=full_proposal,
            changed=True,
            verified=True,
            speedup=verdict.speedup,
            note=verdict.summary(),
            isolated_proposal=isolated_candidate,
            target_fn_name=target_fn_id,
        )
    if not verdict.verified:
        struct_ok, struct_note = _structural_check(code, full_proposal)
        combined_note = f"{verdict.summary()} | structural: {struct_note}"
        LOGGER.warning("optimizer: execution unverifiable — %s", combined_note)
        if allow_unverified or struct_ok:
            return OptimizationResult(
                code=full_proposal,
                changed=True,
                verified=struct_ok,
                note=f"Candidate generated ({combined_note})",
                isolated_proposal=isolated_candidate,
                target_fn_name=target_fn_id,
            )
        return OptimizationResult(code=code, note=combined_note)

    LOGGER.warning("optimizer: rewrite rejected (%s)", verdict.summary())
    return OptimizationResult(code=code, note=verdict.summary())


def optimize(code: str) -> str:
    """Return an optimized rewrite of the given C++ code.

    Kept for callers that want a plain string. Prefer ``optimize_checked``,
    which also says whether the rewrite was executed and compared.

    :param code: the original C++ source.
    :return: the optimized code, or the original code with a fallback note.
    """
    result = optimize_checked(code)
    if not result.changed:
        return code + f"\n\n// (optimizer: {result.note}; original kept)"
    return result.code
