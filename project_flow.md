# Project Flow — Hybrid C++ Code-Review Backend

This document explains **how the whole system works end-to-end**: the architecture,
the API surface, and — most importantly — the exact step-by-step flow that runs
when the mobile app sends *raw C++ code* to the backend and gets a review back.

---

## 1. What this system is

A **FastAPI backend** that reviews C++ source code. It is a *hybrid* system:

- **Deterministic part (no AI):** a static analyzer parses the code with
  tree-sitter and extracts hard facts — functions, recursion, loop nesting,
  missing comments/docs, complexity, etc.
- **AI part:** a single trained **CodeT5** seq2seq model generates inline
  comments and a natural-language explanation.

The golden rule (from `project.md`): **AI is only used for reasoning / natural
language generation. Everything structural is plain deterministic Python.**

The original mobile app already consumes `POST /analyze` and expects three
fields (`input_code`, `commented_code`, `explanation`). This backend extends
that endpoint **additively** so the old app keeps working while new clients can
opt into analysis, suggestions, documentation, change-tracking and translation.

---

## 2. Tech stack

| Concern | Choice |
|---|---|
| Web framework | FastAPI 0.135 + Uvicorn |
| Language | Python 3.11 |
| C++ parsing | `tree-sitter` 0.25 + `tree-sitter-cpp` 0.23 (lazy-loaded, regex fallback) |
| AI model | `transformers` 4.40.2 + `torch` 2.0.1 (CodeT5 checkpoint) |
| Auth + history DB | SQLite (file `app.db`) |
| Validation / serialization | Pydantic v2 |
| Lint / types | `ruff` (lint+format), `mypy --strict` (enforced in `pyproject.toml`) |

---

## 3. Project structure (relevant pieces)

```
app/
├── main.py                  # FastAPI app, CORS, /health, startup DB init
├── core/
│   ├── config.py            # MODEL_PATH, tokenizer, generation knobs, DB_PATH
│   └── database.py          # SQLite connection + lock + schema init
├── routers/
│   ├── auth.py              # /auth/register, /login, /me, /logout
│   └── analyze.py           # POST /analyze, GET /analyze/history
├── schemas/
│   ├── analyze.py           # AnalyzeRequest / AnalyzeResponse + sub-models
│   ├── auth.py              # Register/Login/AuthResponse
│   └── history.py           # HistoryEntry / HistoryListResponse
├── parsers/
│   └── cpp_parser.py        # tree-sitter C++ wrapper (cached, fallback-safe)
├── services/
│   ├── analyzer.py          # STATIC ANALYSIS (facts) — Phase 3
│   ├── diff_service.py      # OLD vs NEW comparison — Phase 4
│   ├── model_service.py     # SHARED CodeT5 inference engine
│   ├── comment_service.py   # Comments task — Phase 7
│   ├── explanation_service.py # Explanation task — Phase 9
│   ├── review_service.py    # Suggestions task — Phase 6
│   ├── documentation_service.py # Documentation task — Phase 8
│   ├── translation_service.py   # EN -> Roman Urdu — Phase 10
│   ├── auth_service.py      # register/login/session
│   └── history_service.py   # SQLite history read/write
├── model_processing/        # deterministic rule fallbacks + formatting
│   ├── code_formatting.py
│   ├── comment_rules.py
│   └── explanation_rules.py
└── utils/text.py            # whitespace/comment/line helpers
```

Design principle: **one task = one service**. Each service internally decides
whether to use the AI model output or its deterministic rule engine, so a
trained per-task model can later replace one service without touching the rest.

---

## 4. The API surface

### 4.1 Auth (token session)

| Method | Path | Purpose | Auth header |
|---|---|---|---|
| POST | `/auth/register` | create account, auto-login | — |
| POST | `/auth/login` | get a session token | — |
| GET | `/auth/me` | current user info | Bearer `<token>` |
| POST | `/auth/logout` | delete session | Bearer `<token>` |

`RegisterRequest`: `name`, `email`, `password` (≥6), `confirm_password`.
`AuthResponse`: `{ message, token, user:{id,name,email} }`.

Passwords are hashed with PBKDF2-HMAC-SHA256 + per-user salt (`auth_service.py`).
The session token is a 32-byte URL-safe secret stored in the `sessions` table
with an expiry (`SESSION_TTL_HOURS`, default 720h). Every protected request must
send `Authorization: Bearer <token>`.

### 4.2 Analyze (the core endpoint)

| Method | Path | Purpose | Auth header |
|---|---|---|---|
| POST | `/analyze` | full review pipeline | Bearer `<token>` |
| GET | `/analyze/history?limit=&offset=` | paginated history | Bearer `<token>` |

### 4.3 Health

`GET /health` → `{ "status": "ok" }` (no auth; used by the app/tests/liveness probe).

---

## 5. The request & response contract (`/analyze`)

### 5.1 Request — `AnalyzeRequest`

```json
{
  "code": "int add(int a, int b) { return a + b; }",   // required, non-empty
  "source": "mobile",                                    // optional client tag
  "language": "cpp",                                     // optional, default "cpp"
  "output_language": "english",                          // optional: english | roman_urdu
  "old_code": null                                       // optional previous version (Phase 4)
}
```

Old mobile clients still send only `{ "code": "..." }`; every new field has a
default, so the request always validates.

### 5.2 Response — `AnalyzeResponse`

```json
{
  "input_code":    "int add(int a, int b) { return a + b; }",  // trimmed original (CORE)
  "commented_code":"// ... \nint add(int a, int b) { ... }",   // commented code (CORE)
  "explanation":   "This function adds two integers ...",      // NL summary (CORE)

  "analysis": { ... },          // StaticAnalysis (Phase 3)
  "suggestions": [ "..." ],     // review suggestions (Phase 6)
  "documentation": [ ... ],     // per-function docs (Phase 8)
  "change_analysis": null,      // ChangeAnalysis or null (Phase 4)
  "translation": null           // Roman Urdu string or null (Phase 10)
}
```

**Backward-compatibility guarantee:** the three CORE fields (`input_code`,
`commented_code`, `explanation`) are always present, in that order, with the
same meaning the old app expects. All other fields are additive and default to
`null`/`[]` when not produced, so serialization never breaks for old clients.

---

## 6. End-to-end flow: mobile app sends raw C++ code

This is the detailed walkthrough, annotated with the exact code locations.

### Step 0 — App has a session token
The mobile app authenticates once (register/login) and stores the `token`.
Every call to `/analyze` includes `Authorization: Bearer <token>`.

### Step 1 — HTTP request arrives
```
POST /analyze
Authorization: Bearer <token>
Content-Type: application/json

{ "code": "int add(int a, int b) { return a + b; }" }
```
FastAPI validates the body against `AnalyzeRequest` (pydantic). If `code` is
missing/empty → automatic `422`.

### Step 2 — Router entry (`app/routers/analyze.py::analyze`)
1. `require_user(authorization)` (`auth_service.py`) splits the Bearer token,
   looks up the `sessions` row joined to `users`, checks expiry, and returns the
   `AuthUser`. Any failure → `401`.
2. The pipeline then runs **in order**:

### Step 3 — Static analysis (deterministic) — Phase 3
`static_analyze(payload.code, language=...)` → `analyzer.py::analyze_code`
- `cpp_parser.parse(code)` builds a tree-sitter AST (parser is **lazily
  loaded + cached** behind a lock in `cpp_parser.py`).
- If tree-sitter is unavailable, it falls back to a **regex analyzer**
  (`_regex_analyze`) so the endpoint never hard-fails.
- The AST path walks `function_definition` nodes and computes, per function:
  name, start/end line, length, parameter count, **recursion** (self-call),
  max loop-nesting depth, whether it has a leading comment / doc block.
- Globally it computes: function count, total loops/conditionals,
  **cyclomatic complexity** (decision points + 1, including `&&`/`||`),
  long functions (>40 lines), duplicate definitions, missing-comment/doc counts.
- Returns a fully-typed `StaticAnalysis` pydantic model.

### Step 4 — Shared AI model (CodeT5) — `model_service.py`
`model_service.run_model(code, analysis=analysis)`
- Loads the tokenizer + model **once** (cached, thread-locked). Path:
  `codet5_commenst_expla/checkpoint_best`.
- First tries raw generation on the code. If no sections appear, it builds a
  **fact-augmented prompt** via `build_prompt(code, analysis)` that injects the
  ground-truth facts from Step 3 ("Recursive: true", "Cyclomatic complexity: N",
  …) so the model reasons over facts, not raw names.
- Decodes output and splits it into `RawModelOutput(commented_code, explanation)`
  using section headers (`### COMMENTED CODE`, `### EXPLANATION`). If the model
  merely echoed the prompt template, it returns empty sections so the fallback
  runs.
- **This engine applies NO rules/formatting** — that is delegated to the tasks.

### Step 5 — Per-task NLP services (each owns rule-vs-AI)
- `comment_service.generate(code, raw.commented_code)`
  prefers the model's commented code; if it has no meaningful `//` comments, it
  falls back to the deterministic `generate_rule_based_comments` (regex heuristics
  for declarations, arithmetic, loops, conditions) and finally formats it for the
  editor (`format_commented_code_for_editor`).
- `explanation_service.generate(code, raw.explanation)`
  prefers the model explanation; falls back to
  `generate_rule_based_explanation` (detects function name + behaviours).
- `review_service.generate_suggestions(analysis)`
  turns the **static facts** into ranked suggestions: recursion → memoization,
  deep nesting → flatten, long function → split, missing comments/docs, duplicate
  functions, high complexity, too many parameters → group into a struct.
  If nothing is wrong, returns a single "no issues" note.
- `documentation_service.generate(analysis)`
  emits one `DocEntry` per named function: description (derived from recursion /
  loop traits), parameter list, return note.

### Step 6 — Optional: change analysis (Phase 4)
Only if `payload.old_code` was provided:
`diff_service.compare(old_code, new_code)` parses both versions, maps function
name → normalized body (comments stripped via `utils/text.py`), and reports
`added_functions`, `removed_functions`, `modified_functions`, plus
`complexity_delta` / `complexity_increased`.

### Step 7 — Optional: translation (Phase 10)
Only if `payload.output_language == "roman_urdu"`:
`translation_service.to_roman_urdu(explanation)` substitutes a phrase dictionary
(offline, fast). Otherwise `translation` stays `null`.

### Step 8 — Assemble response
The router builds `AnalyzeResponse` with the 3 core fields first (trimmed input,
commented code, explanation), then the additive fields.

### Step 9 — Persist history
`record_history(user_id, input_code, commented_code, explanation, source)` writes
a row to `analysis_history` (SQLite). The public history shape is unchanged for
the old app.

### Step 10 — JSON returned to mobile
```
HTTP/1.1 200 OK
{
  "input_code": "...",
  "commented_code": "...",
  "explanation": "...",
  "analysis": { ... },
  "suggestions": [ ... ],
  "documentation": [ ... ],
  "change_analysis": null,
  "translation": null
}
```

### Step 11 — Mobile renders
The old app reads the 3 core fields and shows commented code + explanation. A new
app additionally renders `analysis`, `suggestions`, `documentation`, etc.

---

## 7. Worked example (real shape)

Request:
```json
POST /analyze
{ "code": "int factorial(int n){ if(n<=1) return 1; return n*factorial(n-1); }",
  "output_language": "english" }
```

Produces (abbreviated):
```json
{
  "input_code": "int factorial(int n){ if(n<=1) return 1; return n*factorial(n-1); }",
  "commented_code": "// ...commented variant...",
  "explanation": "This function computes factorial recursively ...",
  "analysis": {
    "language": "cpp",
    "functions": [{ "name": "factorial", "recursive": true, "params": 1,
                    "max_loop_depth": 0, "has_comment": false, "has_doc": false }],
    "function_count": 1,
    "recursive": true,
    "max_nested_loops": 0,
    "missing_comments": 1,
    "missing_docs": 1,
    "cyclomatic_complexity": 2,
    "parser": "tree-sitter"
  },
  "suggestions": [
    "Recursive logic detected (factorial). Consider memoization or an iterative version ...",
    "1 function(s) lack inline comments. Add short comments ...",
    "1 function(s) lack documentation blocks. Add a description ..."
  ],
  "documentation": [
    { "function": "factorial", "description": "Function 'factorial' uses recursion.",
      "parameters": ["param1"], "returns": "See function signature for the return type." }
  ],
  "change_analysis": null,
  "translation": null
}
```

---

## 8. How the system decides "rule engine vs AI"

| Task | Primary source | Fallback |
|---|---|---|
| Comments | CodeT5 raw output | deterministic regex commenter |
| Explanation | CodeT5 raw output | deterministic behaviour summariser |
| Suggestions | static-analysis facts (rules) | — (no model yet) |
| Documentation | static-analysis facts (rules) | — (no model yet) |
| Translation | Roman-Urdu phrase dict | — (no model yet) |
| Static / diff analysis | tree-sitter AST | regex analyzer |

The model is **shared** (one load, one inference) and only produces the two raw
sections; every task service post-processes locally. Swapping in a trained
per-task model later means editing only that one service.

---

## 9. Error & status-code behaviour

| Situation | Status | Body |
|---|---|---|
| Missing/invalid Bearer token | 401 | `{detail: "Missing/Invalid authorization token"}` |
| Expired session | 401 | `{detail: "Session expired"}` |
| Model path missing / tokenizer load fails | 503 | error string from `model_service` |
| Invalid request body | 422 | pydantic validation errors |
| Success | 200 | `AnalyzeResponse` |
| Health probe | 200 | `{status:"ok"}` |

---

## 10. Configuration (`app/core/config.py`, env-overridable)

| Setting | Default | Meaning |
|---|---|---|
| `MODEL_PATH` | `codet5_commenst_expla/checkpoint_best` | model directory |
| `TOKENIZER_PATH` | = `MODEL_PATH` | tokenizer directory |
| `DB_PATH` | `app.db` | SQLite file |
| `RAW_MAX_LENGTH` / `RAW_NUM_BEAMS` | 768 / 4 | 1st-stage generation |
| `PROMPT_MAX_LENGTH` / `PROMPT_NUM_BEAMS` | 900 / 5 | fact-augmented generation |
| `PASSWORD_HASH_ITERATIONS` | 200000 | PBKDF2 cost |
| `SESSION_TTL_HOURS` | 720 | session lifetime |

---

## 11. How to run / verify

```bash
uv sync                       # install deps (incl. dev: ruff, mypy, pytest)
uv run ruff check app         # lint — must be clean
uv run mypy app               # strict types — must pass
uv run uvicorn app.main:app --reload
```

The backend is intentionally **additive and deterministic-first**: the mobile
app never breaks, the AI is used only where it adds value, and every structural
decision is plain, testable Python.
