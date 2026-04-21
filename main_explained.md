# main.py line-by-line function walkthrough

This file explains each function in main.py, step by step, line by line. Line numbers refer to main.py as it exists now.

## health (lines 39-41)
- Line 39: `@app.get("/health")` registers this function as a GET endpoint at `/health`.
- Line 40: `def health() -> dict:` defines the handler and states it returns a dict.
- Line 41: `return {"status": "ok"}` sends a simple JSON response.

## build_prompt (lines 44-73)
- Line 44: `def build_prompt(code: str) -> str:` defines a helper that builds a prompt string.
- Line 45: `return f"""` starts a multi-line f-string so `{code}` can be inserted later.
- Line 46: Adds the role line for the model (C++ code reviewer).
- Line 48: Adds the rule to analyze logic instead of names.
- Line 50: Adds the `INSTRUCTIONS:` section header.
- Line 51: Adds instruction 1 about explaining what conditions check.
- Line 52: Adds instruction 2 about describing what the function does.
- Line 53: Adds instruction 3 about name/logic mismatches.
- Line 54: Adds instruction 4 about inline comments.
- Line 55: Adds instruction 5 about precision.
- Line 57: Adds the `OUTPUT FORMAT:` section header.
- Line 59: Adds the `### COMMENTED CODE` header.
- Line 60: Adds placeholder text for commented code.
- Line 62: Adds the `### LOGIC ANALYSIS` header.
- Line 63: Adds placeholder text for step-by-step logic analysis.
- Line 65: Adds the `### ISSUES` header.
- Line 66: Adds placeholder text for issues.
- Line 68: Adds the `### EXPLANATION` header.
- Line 69: Adds placeholder text for a final summary.
- Line 71: Adds the `CODE:` label.
- Line 72: Inserts the `code` argument into the prompt.
- Line 73: Ends the multi-line f-string and returns it.

## clean_duplicate_code (lines 76-80)
- Line 76: `def clean_duplicate_code(output: str) -> str:` defines a cleanup helper.
- Line 77: Splits the output by the header `### COMMENTED CODE`.
- Line 78: Checks if there are more than two parts (meaning repeated headers).
- Line 79: If repeated, keeps only the last `### COMMENTED CODE` section.
- Line 80: Otherwise, returns the original output unchanged.

## _load_model (lines 83-114)
- Line 83: `def _load_model() -> Tuple[...]` defines a cached model loader.
- Line 84: `global _MODEL_CACHE` says the function will read/write the module cache.
- Line 85: If `_MODEL_CACHE` is already set, skip loading.
- Line 86: Returns the cached tokenizer, model, and device.
- Line 88: `with _MODEL_LOCK:` enters a lock to avoid multi-threaded double loads.
- Line 89: Checks the cache again inside the lock (another thread might have set it).
- Line 90: Returns the cache if it was set while waiting.
- Line 92: If the model path does not exist, raise a `FileNotFoundError`.
- Line 95: If the path is not a directory, raise a `FileNotFoundError`.
- Line 98: Start a try block for tokenizer loading.
- Line 99: Load the tokenizer from `TOKENIZER_PATH` using the fast tokenizer.
- Line 100: Catch any tokenizer load error.
- Line 101: Build a detailed error message string (part 1).
- Line 102: Continue the message (part 2) with tokenizer file hints.
- Line 103: Continue the message (part 3) with the error detail.
- Line 104: Close the message string.
- Line 106: Raise a `RuntimeError` with the message and the original exception.
- Line 108: Load the seq2seq model from `MODEL_PATH`.
- Line 109: Choose `cuda` if available, otherwise `cpu`.
- Line 110: Move the model to the chosen device.
- Line 111: Put the model in eval mode.
- Line 113: Store `(tokenizer, model, device)` in `_MODEL_CACHE`.
- Line 114: Return the cached tuple.

## analyze (lines 117-149)
- Line 117: `@app.post("/analyze", response_model=AnalyzeResponse)` registers the POST endpoint.
- Line 118: `def analyze(payload: AnalyzeRequest) -> AnalyzeResponse:` defines the handler.
- Line 119: Start a try block to load the model safely.
- Line 120: Call `_load_model()` and unpack tokenizer, model, and device.
- Line 121: Catch `FileNotFoundError` or `RuntimeError` from model loading.
- Line 122: Convert those into a 503 `HTTPException` response.
- Line 124: Build the full prompt using the request code.
- Line 125: Call the tokenizer to encode the prompt.
- Line 126: Pass the prompt text to the tokenizer.
- Line 127: Ask for PyTorch tensors (`pt`).
- Line 128: Limit input tokens to 512.
- Line 129: Enable truncation if the prompt is too long.
- Line 130: Move the resulting tensors to the selected device.
- Line 132: Disable gradients for inference.
- Line 133: Run `model.generate(...)` to create output tokens.
- Line 134: Pass the tokenized inputs into the model.
- Line 135: Limit output length to 900 tokens.
- Line 136: Use beam search with 5 beams.
- Line 137: Enable sampling alongside beams.
- Line 138: Set sampling temperature to 0.7.
- Line 139: Prevent repeating 3-gram sequences.
- Line 140: Stop early when beams finish.
- Line 141: Close the `generate` call.
- Line 143: Decode the first output sequence into text.
- Line 144: Remove duplicate `### COMMENTED CODE` sections if any.
- Line 145: Start building the response object.
- Line 146: Set the `analysis` field to the cleaned output.
- Line 147: Set `received_chars` to the length of the input code.
- Line 148: Pass through the optional `source` value.
- Line 149: Return the `AnalyzeResponse` model instance.
