# Implementation Plan — Hybrid C++ Code Review Backend

**Role:** Senior FastAPI engineer
**Goal:** Evolve the current single-model FastAPI backend into the hybrid
architecture defined in `project.md` (deterministic static analysis + AI
generation), **without breaking the existing mobile app**.

---

## 0. Code Standards (enforced via `pyproject.toml` tooling)

Every module must follow these rules (checked by `uv run ruff check app` and
`uv run mypy app` under `--strict`):

- **Strict typing everywhere.** No untyped/`Any`/dynamic params or returns.
  Tree-sitter nodes are typed `tree_sitter.Node`; AST helpers use a
  `TYPE_CHECKING` guard for the import. `dict`/`list`/`tuple` carry type args.
- **Document every function.** Each function docstring states the *problem it
  solves* and *why it is written this way*, plus a `:return:` type.
- **Clean & reusable.** One responsibility per module/service; shared helpers
  live in `app/utils` and `app/model_processing`; per-task logic lives in its
  own `app/services/*_service.py`.
- **Backward compatibility** (see §2) is non-negotiable.

Dev tooling (`ruff`, `mypy`, `pytest`) is declared under `[dependency-groups].dev`
in `pyproject.toml`; mypy runs with `strict = true` and `tree_sitter`/`torch`/
`transformers` are stubbed via overrides.

---

## 1. Current State (audited)

| Area | Status |
|---|---|
| FastAPI app | `app/main.py` — health, CORS, startup DB init |
| Endpoints | `/auth/*`, `POST /analyze`, `GET /analyze/history` |
| AI model | CodeT5 seq2seq at `codet5_commenst_expla/checkpoint_best` (comments + explanation) |
| `/analyze` I/O | in: `code`, `source`; out: `input_code`, `commented_code`, `explanation` |
| Auth + history | SQLite, token sessions, working |
| Rule fallbacks | `app/model_processing/*` (comments, explanation) |
| Missing | static analyzer, diff analyzer, suggestions, documentation, translation |
| Deps | fastapi 0.135, transformers 4.40.2, torch 2.0.1, py3.11; **no tree-sitter** |

### Golden Rule (from project.md)
> Only use AI where reasoning or natural-language generation is needed.
> Everything structural/deterministic is plain Python.

---

## 2. Backward-Compatibility Contract (non-negotiable)

The mobile app already consumes `POST /analyze`. Therefore:

1. **Never remove/rename** `input_code`, `commented_code`, `explanation`.
2. New request fields are **optional with defaults** (`language="cpp"`,
   `output_language="english"`, `old_code=None`).
3. New response fields are **additive** (`analysis`, `suggestions`,
   `documentation`, `translation`, `change_analysis`).
4. Auth scheme (`Authorization: Bearer <token>`) unchanged.
5. Old client sending only `{code}` still gets a valid, unchanged core response.

**Strategy chosen: extend `/analyze` additively** (not a `/v2`).

---

## 3. Target Architecture

Each NLP task is its own service. A service internally decides whether to use
the **rule engine** (now) or an **AI model** (later) — one task, one seam.

```
                 Mobile / Frontend
                        │
                        ▼
                  FastAPI Router (analyze.py)  ── orchestrates
                        │
     ┌──────────────────┼───────────────────────────┐
     ▼                  ▼                             ▼
 parsers/cpp_parser  services/analyzer      services/diff_service
 (tree-sitter AST)   (static facts JSON)    (old vs new, optional)
     └──────────────────┼───────────────────────────┘
                        ▼
        services/model_service  (shared CodeT5 inference → raw sections)
                        ▼
   ┌───────────────┬────┴───────────┬───────────────────┐
   ▼               ▼                ▼                    ▼
comment_service  explanation_    review_service     documentation_
(Phase 7)        service (P9)    (P6, suggestions)  service (P8)
   │               │                │                    │
   └───────────────┴────────────────┴────────────────────┘
                        ▼
        translation_service  (English → Roman Urdu, optional, Phase 10)
                        ▼
                 Combined JSON Response
```

**Model separation (key refactor):** `model_service.py` is now a *pure CodeT5
inference engine* (loads model, runs generation, splits raw sections). It
applies no fallbacks/formatting. Each downstream NLP task is a dedicated
service that owns its rule-engine-vs-AI choice:

| Task | Service | Backend now | Backend later |
|---|---|---|---|
| Comments | `comment_service` | rule engine + CodeT5 raw | dedicated model |
| Explanation | `explanation_service` | rule engine + CodeT5 raw | dedicated model |
| Suggestions | `review_service` | rule engine (facts) | review model |
| Documentation | `documentation_service` | rule engine (facts) | doc model |
| Translation | `translation_service` | dictionary | translation model |

---

## 4. Target Folder Structure (additive)

```
app/
├── main.py
├── core/                 (config, database — extend)
├── routers/
│     analyze.py          (orchestrate full pipeline)
│     auth.py             (unchanged)
├── schemas/
│     analyze.py          (extend: request + response, new sub-models)
│     history.py          (unchanged public shape)
│     auth.py             (unchanged)
├── parsers/              NEW
│     __init__.py
│     cpp_parser.py       (tree-sitter wrapper, safe/lazy load)
├── services/
│     analyzer.py               NEW  static analysis (Phase 3)
│     diff_service.py           NEW  code change analysis (Phase 4)
│     model_service.py          shared CodeT5 inference engine (raw output)
│     comment_service.py        NEW  comments task (Phase 7)
│     explanation_service.py    NEW  explanation task (Phase 9)
│     review_service.py         NEW  suggestions task (Phase 6)
│     documentation_service.py  NEW  documentation task (Phase 8)
│     translation_service.py    NEW  English→Roman Urdu (Phase 10)
│     history_service.py        (unchanged public shape)
│     auth_service.py           (unchanged)
├── utils/                NEW
│     __init__.py
│     text.py             (shared helpers)
└── model_processing/     (existing rule fallbacks — reused)
```

---

## 5. Static Analyzer — facts to extract (Phase 3)

Deterministic, no AI. Output JSON:

```json
{
  "language": "cpp",
  "functions": [
    {"name": "factorial", "start_line": 3, "end_line": 9,
     "length": 7, "params": 1, "recursive": true,
     "max_loop_depth": 0, "has_comment": false, "has_doc": false}
  ],
  "function_count": 1,
  "recursive": true,
  "max_nested_loops": 2,
  "long_functions": ["calculateSalary"],
  "missing_comments": 4,
  "missing_docs": 2,
  "duplicate_functions": [],
  "loops": 3,
  "conditionals": 5,
  "cyclomatic_complexity": 6
}
```

**Detections:** function detection, params count, function length,
recursion (self-call), nested-loop depth, missing inline comment,
missing doc block (`/** ... */` above), duplicate function signatures,
long-function threshold (default 40 lines), cyclomatic complexity
(decision points + 1).

**Tech:** `tree-sitter` + `tree-sitter-cpp`. Manual node traversal
(`node.type`, `node.children`, `child_by_field_name`, `start_point`) —
version-robust vs. the churny Query API. Parser loaded lazily + cached;
if tree-sitter unavailable, a regex fallback keeps the endpoint alive.

---

## 6. Code Change Analyzer (Phase 4)

Input: `code` (new) + `old_code`. Deterministic diff of function sets:
`added_functions`, `removed_functions`, `modified_functions` (body
changed), `complexity_delta`, `complexity_increased`. Only runs when
`old_code` is provided.

---

## 7. Hybrid Prompt (Phase 5)

`model_service.build_prompt(code, analysis)` injects explicit facts
(recursive, nested loops, long functions, missing comments) + source into the
model input so the AI reasons over facts, not raw code. Lowers inference cost,
improves accuracy, easier to debug. (Kept inside `model_service` — no separate
`prompt_builder` module.)

---

## 8. AI Layers (Phases 6/8/9/10)

Model files arrive later, so each task ships now with a **deterministic
rule-based generator**, behind a stable per-task service interface. Dropping in
a trained model later = swap that one service's impl only.

- **model_service.run_model(code, analysis)** — shared CodeT5 inference; returns
  `RawModelOutput(commented_code, explanation)` (raw, no fallback/formatting).
- **comment_service.generate(code, raw)** — finalize commented code; rule
  engine + editor formatting when the model output is not meaningful.
- **explanation_service.generate(code, raw)** — finalize explanation; rule
  engine fallback.
- **review_service.generate_suggestions(analysis)** — facts → suggestions
  (recursive → memoization; deep loops → reduce nesting; long function →
  split; missing docs → add documentation; many params → group into struct).
- **documentation_service.generate(analysis)** — per-function
  Description / Parameters / Returns from signatures.
- **translation_service.to_roman_urdu(text)** — dictionary/phrase fallback now,
  model-swappable later. Runs only if `output_language == "roman_urdu"`.

**Why split:** comments, explanation, suggestions, documentation and
translation are distinct NLP tasks. One service per task keeps each seam clean
and independently replaceable, instead of one god-module doing everything.

---

## 9. Combined Response (Phase 11)

```json
{
  "input_code": "...",
  "commented_code": "...",
  "explanation": "...",
  "analysis": { ... },
  "suggestions": ["..."],
  "documentation": [{"function": "factorial", "description": "...",
                     "parameters": ["..."], "returns": "..."}],
  "change_analysis": null,
  "translation": null
}
```

Old 3 fields first & unchanged → mobile keeps working.

---

## 10. Schema Changes

**AnalyzeRequest** (all new fields optional):
`code` (req), `source?`, `language="cpp"`, `output_language="english"`,
`old_code?`.

**AnalyzeResponse**: existing 3 fields + `analysis`, `suggestions`,
`documentation`, `change_analysis`, `translation` (all defaulted so
serialization never breaks).

New sub-models: `FunctionInfo`, `StaticAnalysis`, `DocEntry`,
`ChangeAnalysis`.

---

## 11. Persistence

Keep `analysis_history` public shape. Optional additive columns
(`analysis_json`, `suggestions_json`) via `ALTER TABLE ... IF NOT EXISTS`
guard (checked with PRAGMA) — non-breaking. History API response
unchanged for now.

---

## 12. Dependencies

Add to `pyproject.toml`:
- `tree-sitter>=0.23,<0.26`
- `tree-sitter-cpp>=0.23,<0.24`

Install into existing `.venv`.

---

## 13. Delivery Order (sprints)

1. **Deps + parser** — install tree-sitter, `parsers/cpp_parser.py`. ✅
2. **Static analyzer** — `services/analyzer.py` + schemas. ✅
3. **Diff analyzer** — `services/diff_service.py`. ✅
4. **Model engine + hybrid prompt** — `model_service.run_model` returns raw
   sections; facts injected into prompt. ✅
5. **Per-task services** — `comment_service`, `explanation_service`,
   `review_service`, `documentation_service` (split from one module). ✅
6. **Translation** — `translation_service`, Roman Urdu (optional). ✅
7. **Router orchestration** — wire pipeline into `POST /analyze` additively. ✅
8. **Verify** — health check, backward-compat smoke test, sample C++. ✅

---

## 14. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| tree-sitter wheel/ABI issue | lazy import + regex fallback analyzer |
| Model files absent | rule-based generators behind stable interfaces |
| Breaking mobile app | strictly additive schema, old fields preserved |
| Latency (multiple stages) | analyzer is fast; AI stages already cached model |
| Query API churn | manual node traversal, not tree-sitter queries |
```