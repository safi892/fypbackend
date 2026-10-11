## Code Analyzer Backend

FastAPI backend for C++ code review, static analysis, automated commenting, and verified recursion-to-loop optimization powered by a fine-tuned local LLM and Tree-Sitter.

---

### Browser Playground

Start the model and API server, then open **http://localhost:8000/**:

```bash
export LLAMA_MODEL_PATH=models/gguf/qwen-cpp-review-q4_k_m.gguf
./run_model_server.sh --bg
./runserver.sh start
```

Or run uvicorn directly with hot reload:

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

On Windows, open Command Prompt in the project directory and run:

```bat
setup.bat
```

---

### How to Test the APIs

You can test all backend APIs in four ways:

#### 1. Web Playground UI (`http://localhost:8000/`)
- Paste any C++ function or complete program (or click **Example**).
- Real-time syntax checking verifies C++ syntax as you type (`POST /validate-code`).
- Choose **English** or **Roman Urdu**.
- Toggle **Convert recursion to loop** to see verified iterative stack/loop code.
- Click **Analyze code** (or press <kbd>Ctrl/Cmd</kbd> + <kbd>Enter</kbd>).
- View the unified response card containing:
  - **Function-level Docstrings** (`Function`, `Summary`, `Inputs`, `Process`, `Returns`).
  - **Inline comments** explaining statements.
  - **Code explanation** and review diagnostics.

#### 2. Interactive OpenAPI / Swagger UI (`http://localhost:8000/docs`)
- Test all endpoints with live interactive requests and schema inspection.
- ReDoc alternative available at **http://localhost:8000/redoc**.

#### 3. Command Line (`curl`)

```bash
# Health probe
curl http://localhost:8000/health

# Readiness probe (compiler, llama-server, model)
curl http://localhost:8000/ready

# Fast syntax check
curl -X POST http://localhost:8000/validate-code \
  -H "Content-Type: application/json" \
  -d '{"code": "int add(int a, int b) { return a + b; }"}'

# Code analysis with function doc comments & line annotations
curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"code": "int f(int a[], int n) {\n    int x = a[0];\n    for (int i = 1; i < n; i++) if (a[i] > x) x = a[i];\n    return x;\n}"}'

# Recursion-to-loop conversion
curl -X POST http://localhost:8000/optimize \
  -H "Content-Type: application/json" \
  -d '{"code": "int sum(int n) { if (n <= 0) return 0; return n + sum(n - 1); }", "mode": "iterate", "source": "web"}'
```

#### 4. Programmatic Client Integration
See complete client integration examples (JavaScript, Python, Dart/Flutter) in the [API Reference](docs/API.md).

---

### Key Capabilities

- **Structured Function Docstrings**: Automatically prepends Javadoc/Doxygen block comments above every function:
  ```cpp
  /**
   * Function: f
   * Summary: Finds the maximum element.
   * Inputs: int a[], int n
   * Process: Iterates through elements in a loop, applying conditional updates.
   * Returns: int
   */
  ```
- **Syntax-Gated Comment Attachment**: AST line anchors ensure comments match user source code without regenerating or hallucinating lines.
- **Verified Optimizations**: Compiles original and proposed iterative code side-by-side on test inputs to prove semantic equivalence before returning.
- **Multilingual Support**: Supports English and Roman Urdu explanations and comments.

---

### Documentation

- [API Reference & Implementation Guide](docs/API.md) — Complete endpoint schemas, request/response models, and client code.
- [Setup & Prerequisites](docs/SETUP.md) — Python 3.11, llama.cpp, models, and compiler setup.
- [Authentication & Database](docs/AUTH.md) — User registration, sessions, and SQLite storage.
- [Optimization Pipeline](docs/OPTIMIZATION_PIPELINE.md) — Equivalence verification and performance benchmarking.
- [Android Integration](docs/ANDROID.md) — Retrofit/OkHttp guide for the mobile app.
