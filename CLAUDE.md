# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

`docs/AI_CONTEXT.md` is the human-maintained version of this brief — keep the two in agreement when either changes.

## What this is

A FastAPI backend that reviews C++ for an Android client. `POST /analyze` returns commented code, an explanation and deterministic static analysis; `POST /optimize` returns a faster rewrite that has been compiled and executed against the original. Auth and history live in SQLite.

Model training lives in a **separate project** at `/Volumes/Data/fyp8th_clean` (dataset, QLoRA training, evaluation, GGUF conversion). Only go there if the task is about training or the model itself — this repo is endpoints, schemas, auth, history and serving.

## Commands

```bash
uv sync                                    # deps (or: pip install -e .)
uv sync --extra notebooks                  # add the Jupyter kernel; uv prunes it otherwise

./run_model_server.sh --bg                 # llama.cpp on 8081; --status / --stop
./runserver.sh                             # the API; start|stop|restart|status|logs
curl -s localhost:8080/ready | python3 -m json.tool   # names what is missing

.venv/bin/python -m pytest -q              # 63 tests, ~2 min with the model server up
.venv/bin/python -m pytest tests/test_qwen_backend.py::test_a_miscounted_anchor_is_moved_to_the_line_it_quotes
.venv/bin/python -m pytest -p no:warnings  # the deprecation noise buries the summary line
.venv/bin/python -m ruff check app         # clean
.venv/bin/python -m mypy app               # 6 pre-existing errors (see below)
```

`./runserver.sh test|lint|typecheck` wraps the same tools through `uv run`.

Two things to know before believing a command failed:

- **Port.** `runserver.sh` defaults to `PORT=8000`, but every doc and curl example uses 8080. Set `PORT=8080` or adjust the URL; do not assume the server failed to start.
- **mypy is not clean.** Six strict-mode errors predate any current work, in `equivalence.py:143`, `qwen_service.py:134`, `health.py:73,78`, `model_service.py:64,66`. Fix them if you touch those lines; don't treat them as regressions you caused.

Tests need no model — the HTTP call is stubbed everywhere except `test_analyze_endpoint.py`, which exercises the real pipeline and needs `run_model_server.sh --bg` (or a `MODEL_BACKEND` this machine actually has). Compiler-dependent tests skip themselves when `c++` is absent.

## Architecture

**Two processes.** The API (`app.main:app`) owns 8080; `llama-server` owns 8081 and holds the ~1 GB GGUF in memory. The API never loads the Qwen weights — it POSTs to `/completion` over `urllib`, so the Qwen path pulls in no Python dependencies at all.

**One switch, two engines.** `MODEL_BACKEND` in `.env` picks which engine answers `model_service.run_model()`:

- `qwen_gguf` — current. `qwen_service` → llama-server → line-anchored comments.
- `codet5` — legacy, in-process seq2seq, **the code default** so existing deployments keep their behaviour. The checkpoint is no longer on this machine.

When llama-server is down the Qwen path falls back to CodeT5 rather than erroring, so a mobile client gets a degraded answer. If the fallback also fails, the *llama-server* error is what surfaces — "checkpoint not found" would name something the operator never chose.

**The `/analyze` pipeline** ([app/routers/analyze.py](app/routers/analyze.py)) is the orchestrator; services stay single-purpose:

```
static_analyze (tree-sitter, cheap, ground truth)
  → model_service.run_model  → qwen_service | codet5
  → comment_service / explanation_service / review_service / documentation_service
  → syntax gate → needs_review
  → diff_service (only with old_code) → translation_service (only for roman_urdu)
  → record_history
```

`app/services/` owns tasks (each can later swap its rule engine for a model); `app/model_processing/` owns the deterministic text/code machinery (anchoring, equivalence, repair, syntax check); `app/parsers/` owns tree-sitter.

## The invariant that explains most of the code

The model returns comments as `{line, code, comment}` records, **not** a rewritten copy of the source. Each record quotes the line it describes, so it can be checked against the submission.

Line **numbers** are unreliable (~25–43% correct); the **quotes** are not (~100%). So [anchors.py](app/model_processing/anchors.py) relocates each comment by its quoted text, drops anything quoting a line the user never wrote, and `render_commented_code` appends comments to the user's own lines. `commented_code` is therefore always the submitted source verbatim plus `// comment` — never a model reconstruction. Measured on a 138-line file: 42 proposed, 39 kept, 3 dropped, 29 line numbers silently corrected.

This proves a comment is *attached correctly*. It does not prove the comment is *true* — roughly 9% are still factually wrong. Don't describe the output as verified-correct.

When `verified=True` reaches `comment_service`, repair and rule-based fallbacks are bypassed on purpose; they could only move the text away from what the user sent.

## Things that look wrong and are not

Sessions reliably try to tidy these away. Don't.

- **~150 lines duplicated from the training repo** (anchoring, chunking). That repo pins `transformers` 4.57, this one pins 4.46, and this backend must stay independently deployable.
- **`/health` and `/ready` are both present.** `/health` is the cheap liveness probe a load balancer polls; `/ready` touches disk and the inference server. Merging them makes the probe expensive.
- **torch + transformers (~2 GB) with nothing in the current path using them.** Only the legacy CodeT5 engine needs them, and they stay required because `model_service` imports torch at module level. Making them optional means making that import lazy first.
- **Files are chunked before being sent.** The checkpoint saw ~15-line functions; a whole file fits neither its context nor its training distribution. Chunks are line ranges so mapping answers back to file coordinates is exact, and anchors are repaired *inside the chunk* before being shifted — a bare `return 0;` searched file-wide would attach to the wrong function.
- **`/optimize` returns the user's original code on failure.** A rewrite is compiled beside the original, both are run on generated inputs, and it is discarded unless outputs agree. `changed` and `verified` say which case happened; a `verified: false` rewrite is one the driver could not call, not one that failed.

## Constraints

- **The response contract is additive only.** `input_code`, `commented_code`, `explanation` come first and must not change shape — an Android client depends on them. New fields are optional.
- Python 3.11 (torch 2.0.1 has no 3.12/3.13 wheels), `numpy<2` (torch 2.0.1 ABI). Both pins are load-bearing and documented in `pyproject.toml`.
- ruff enforces `ANN` (annotations required) at line length 100; mypy runs strict.
- Not in git: `models/` (the GGUF is shared out of band), `.env`, `app.db`, `logs/`.

## Docstring convention

Modules and non-trivial functions state **what problem this solves** and **why this design over the obvious alternative**, then `:param:` / `:return:` / `:raises:`. Roughly two-thirds of `app/` follows it. Match it — the "why" lines are how the deliberate oddities above stay defensible, and a session that strips them removes the only record of the measurement behind a decision.
