import os
import re
import threading
from typing import Optional, Tuple

import torch
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
    logic_analysis: str
    issues: str
    explanation: str
    raw_output: str
    received_chars: int
    source: Optional[str] = None


app = FastAPI(title="Code Analyzer API", version="0.1.0")

MODEL_PATH = os.getenv("MODEL_PATH", "/Volumes/Data/saffi/back/models")
TOKENIZER_PATH = os.getenv("TOKENIZER_PATH", MODEL_PATH)
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


def clean_duplicate_code(output: str) -> str:
    parts = output.split("### COMMENTED CODE")
    if len(parts) > 2:
        return "### COMMENTED CODE" + parts[-1]
    return output


def parse_model_output(output: str, input_code: str) -> AnalyzeResponse:
    cleaned_output = clean_duplicate_code(output).strip()
    normalized = cleaned_output.replace("\r\n", "\n")

    commented_code = ""
    logic_analysis = ""
    issues = ""
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
        logic_analysis = sections.get("LOGIC ANALYSIS", "")
        issues = sections.get("ISSUES", "")
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

    if not explanation:
        explanation = "None"

    if not issues:
        issues = "None"

    return AnalyzeResponse(
        input_code=input_code.strip(),
        commented_code=commented_code,
        logic_analysis=logic_analysis,
        issues=issues,
        explanation=explanation,
        raw_output=cleaned_output,
        received_chars=len(input_code),
        source=None,
    )


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

    prompt = build_prompt(payload.code)
    inputs = tokenizer(
        prompt,
        return_tensors="pt",
        max_length=512,
        truncation=True,
    ).to(device)

    with torch.no_grad():
        output_ids = model.generate(
            **inputs,
            max_length=900,
            num_beams=5,
            do_sample=True,
            temperature=0.7,
            no_repeat_ngram_size=3,
            early_stopping=True,
        )

    full_output = tokenizer.decode(output_ids[0], skip_special_tokens=True)
    response = parse_model_output(full_output, payload.code)
    response.source = payload.source
    return response
