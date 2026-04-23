import os
import re
import threading
from typing import Optional, Tuple

import torch
from code_formatting import clean_duplicate_code, format_commented_code_for_editor
from comment_rules import generate_rule_based_comments, has_meaningful_comments
from explanation_rules import generate_rule_based_explanation, has_meaningful_explanation
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer


class AnalyzeRequest(BaseModel):
    code: str = Field(..., min_length=1, description="Source code to analyze")
    source: Optional[str] = Field(None, description="Client identifier, e.g. mobile")


class AnalyzeResponse(BaseModel):
    input_code: str
    commented_code: str
    explanation: str


app = FastAPI(title="Code Analyzer API", version="0.1.0")

MODEL_PATH = os.getenv(
    "MODEL_PATH",
    "/Volumes/Data/saffi/back/codet5_commenst_expla/checkpoint_best",
)
TOKENIZER_PATH = os.getenv("TOKENIZER_PATH", MODEL_PATH)
RAW_MAX_LENGTH = int(os.getenv("RAW_MAX_LENGTH", "768"))
RAW_NUM_BEAMS = int(os.getenv("RAW_NUM_BEAMS", "4"))
PROMPT_MAX_LENGTH = int(os.getenv("PROMPT_MAX_LENGTH", "900"))
PROMPT_NUM_BEAMS = int(os.getenv("PROMPT_NUM_BEAMS", "5"))
_MODEL_LOCK = threading.Lock()
_MODEL_CACHE: Optional[Tuple[AutoTokenizer, AutoModelForSeq2SeqLM, torch.device]] = None

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


def build_prompt(code: str) -> str:
    return f"""
You are an expert C++ code reviewer.

Analyze the following code strictly based on LOGIC, not function or variable names.

INSTRUCTIONS:
1. First, explain what each condition or expression actually checks.
2. Then describe what the function really does.
3. If the logic contradicts the function name, report it as an issue.
4. Add clear inline comments to the code.
5. Be precise and avoid generic explanations.

COMMENT RULES:
- Comment important declarations and initializations, not just loops and if statements.
- Use context-aware comments that explain why a value is stored or checked.
- Cover common edge cases such as empty input, null pointers, first/last index setup, and early returns.
- Keep comments short and natural. Avoid repeating the code word-for-word.

COMMENT EXAMPLES:
- `int n = arr.size();` -> `// Store the array size for loop bounds or later checks`
- `int left = 0;` -> `// Start the left pointer at the first position`
- `int right = arr.size() - 1;` -> `// Start the right pointer at the last valid index`
- `if (arr.empty()) return 0;` -> `// Handle the empty-input case early`
- `Node* temp = head;` -> `// Start traversing from the head node`
- `int mx = arr[0];` -> `// Use the first element as the initial maximum`
- `bool found = false;` -> `// Track whether a matching value is found`
- `return (double)sum / arr.size();` -> `// Return the average value`

OUTPUT FORMAT:

### COMMENTED CODE
<code with inline comments>

### LOGIC ANALYSIS
<step-by-step explanation of conditions and operations>

### ISSUES
<list any bugs, mismatches, or problems. If none, write "None">

### EXPLANATION
<final clean summary>

CODE:
{code}
"""

def _looks_like_prompt_echo(output: str) -> bool:
    markers = (
        "<code with inline comments>",
        "<step-by-step explanation",
        "<final clean summary>",
        "OUTPUT FORMAT",
    )
    return any(marker in output for marker in markers)


def parse_model_output(output: str, input_code: str) -> AnalyzeResponse:
    cleaned_output = clean_duplicate_code(output).strip()
    normalized = cleaned_output.replace("\r\n", "\n")

    commented_code = ""
    explanation = ""

    section_pattern = re.compile(
        r"###\s*(COMMENTED CODE|LOGIC ANALYSIS|ISSUES|EXPLANATION)\s*\n",
        re.IGNORECASE,
    )
    matches = list(section_pattern.finditer(normalized))

    if matches:
        sections: dict[str, str] = {}
        for index, match in enumerate(matches):
            title = match.group(1).upper()
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
            sections[title] = normalized[start:end].strip()

        commented_code = sections.get("COMMENTED CODE", "")
        explanation = sections.get("EXPLANATION", "")
    elif "===EXPLANATION===" in normalized:
        commented_code, explanation = normalized.split("===EXPLANATION===", 1)
        commented_code = commented_code.strip()
        explanation = explanation.strip()
    else:
        explanation_match = re.search(r"\bEXPLANATION\s*:\s*", normalized, re.IGNORECASE)
        if explanation_match:
            commented_code = normalized[: explanation_match.start()].strip()
            explanation = normalized[explanation_match.end() :].strip()
        else:
            commented_code = normalized

    if not commented_code:
        commented_code = input_code.strip()

    if not has_meaningful_comments(commented_code):
        commented_code = generate_rule_based_comments(input_code.strip())

    commented_code = format_commented_code_for_editor(commented_code)

    if not has_meaningful_explanation(explanation):
        explanation = generate_rule_based_explanation(input_code.strip())

    return AnalyzeResponse(
        input_code=input_code.strip(),
        commented_code=commented_code,
        explanation=explanation,
    )


def parse_basic_output(output: str, input_code: str) -> AnalyzeResponse:
    cleaned_output = clean_duplicate_code(output).strip()
    if "===EXPLANATION===" in cleaned_output:
        commented_code, explanation = cleaned_output.split("===EXPLANATION===", 1)
        commented_code = commented_code.strip()
        explanation = explanation.strip()
    else:
        commented_code = cleaned_output
        explanation = "None"

    if not commented_code:
        commented_code = input_code.strip()

    if not has_meaningful_comments(commented_code):
        commented_code = generate_rule_based_comments(input_code.strip())

    commented_code = format_commented_code_for_editor(commented_code)

    if not has_meaningful_explanation(explanation):
        explanation = generate_rule_based_explanation(input_code.strip())

    return AnalyzeResponse(
        input_code=input_code.strip(),
        commented_code=commented_code,
        explanation=explanation,
    )


def _generate_output(
    tokenizer: AutoTokenizer,
    model: AutoModelForSeq2SeqLM,
    device: torch.device,
    text: str,
    generation_kwargs: dict[str, object],
) -> str:
    inputs = tokenizer(
        text,
        return_tensors="pt",
        max_length=512,
        truncation=True,
    ).to(device)

    with torch.no_grad():
        output_ids = model.generate(
            **inputs,
            **generation_kwargs,
        )

    return tokenizer.decode(output_ids[0], skip_special_tokens=True)


def _load_model() -> Tuple[AutoTokenizer, AutoModelForSeq2SeqLM, torch.device]:
    global _MODEL_CACHE
    if _MODEL_CACHE is not None:
        return _MODEL_CACHE

    with _MODEL_LOCK:
        if _MODEL_CACHE is not None:
            return _MODEL_CACHE

        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(f"Model path not found: {MODEL_PATH}")

        if not os.path.isdir(MODEL_PATH):
            raise FileNotFoundError(f"Model directory not found: {MODEL_PATH}")

        try:
            tokenizer = AutoTokenizer.from_pretrained(TOKENIZER_PATH, use_fast=True)
        except Exception as exc:
            message = (
                "Tokenizer load failed. Ensure tokenizer.json (or vocab.json + merges.txt, "
                "or spiece.model) matches the model and is not corrupted. "
                f"Tokenizer source: {TOKENIZER_PATH}. Error: {exc}"
            )
            raise RuntimeError(message) from exc

        model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_PATH)
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model.to(device)
        model.eval()

        _MODEL_CACHE = (tokenizer, model, device)
        return _MODEL_CACHE


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(payload: AnalyzeRequest) -> AnalyzeResponse:
    try:
        tokenizer, model, device = _load_model()
    except (FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # This checkpoint behaves best when it receives raw code, which matches the
    # successful Kaggle notebook inference path.
    full_output = _generate_output(
        tokenizer,
        model,
        device,
        payload.code,
        generation_kwargs={
            "max_length": RAW_MAX_LENGTH,
            "num_beams": RAW_NUM_BEAMS,
        },
    )

    if "###" in full_output:
        response = parse_model_output(full_output, payload.code)
    elif "===EXPLANATION===" in full_output or full_output.strip() != payload.code.strip():
        response = parse_basic_output(full_output, payload.code)
    else:
        prompt = build_prompt(payload.code)
        full_output = _generate_output(
            tokenizer,
            model,
            device,
            prompt,
            generation_kwargs={
                "max_length": PROMPT_MAX_LENGTH,
                "num_beams": PROMPT_NUM_BEAMS,
                "no_repeat_ngram_size": 3,
                "early_stopping": True,
            },
        )
        if _looks_like_prompt_echo(full_output):
            response = parse_basic_output(payload.code, payload.code)
        else:
            response = parse_model_output(full_output, payload.code)

    return response
