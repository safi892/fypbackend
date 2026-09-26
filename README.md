## Code Analyzer Backend

This service exposes a FastAPI endpoint that analyzes source code using a local model and a small SQLite auth layer.

### Browser playground

Start the model and API, then open **http://localhost:8000/**:

```bash
export LLAMA_MODEL_PATH=models/gguf/qwen-cpp-review-q4_k_m.gguf
./run_model_server.sh --bg
.venv/bin/python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Set `LLAMA_MODEL_PATH` to your installed GGUF filename if it differs.

Paste C++ code (or load an example), choose English or Roman Urdu, and click
**Analyze code**. No account is needed for testing. The page displays the
explanation, commented code, review warnings, and raw API response, with copy
buttons and a Ctrl/Cmd+Enter shortcut. It uses the existing API and requires no
frontend build or extra dependencies.
Only C++ input is accepted: the API checks C++ syntax before model inference
and rejects other `language` values, invalid syntax, and empty/comment-only input.
This is a syntax check, not compilation or a guarantee that the program is correct.
The browser checks syntax as you type (after a short pause), keeps Analyze disabled
until the current text passes, and offers a jump to the reported error line.
Live checks use `POST /validate-code` without sign-in or model inference; the
browser accepts snippets up to 100,000 characters. C++ is the fixed source
language; English/Roman Urdu selects only the explanation language.

`POST /analyze` supports `output_language: "english" | "roman_urdu"`.
English is the default. Roman Urdu requests translate generated prose
(`explanation` and inline comments) while keeping the submitted C++ unchanged.
The public response is intentionally small: `input_code`, `commented_code`,
`explanation`, and `needs_review`. The explanation omits time and space
complexity details.

Start here:

- [Setup](docs/SETUP.md)
- [API Reference](docs/API.md)
- [Auth and Database](docs/AUTH.md)
- [Android Integration](docs/ANDROID.md)

Project structure:

- `app/` contains the FastAPI package
- `app/main.py` is the FastAPI entrypoint
- `run_model_server.sh` starts llama.cpp with the model
- `runserver.sh` starts the API
- `uv sync` installs dependencies
