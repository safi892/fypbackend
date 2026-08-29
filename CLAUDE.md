# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

`docs/AI_CONTEXT.md` is the human-maintained version of this brief — keep the two in agreement when either changes.

`docs/KNOWN_ISSUES.md` lists the defects found by review and not yet fixed, with the reasoning for each. Check it before reporting something as new, and delete an entry when you fix it rather than leaving it to rot.

## What this is

A FastAPI backend that reviews C++ for an Android client. `POST /analyze` publicly returns only the submitted code, commented code, explanation and `needs_review`; `POST /optimize` returns a faster rewrite that has been compiled and executed against the original. Auth and history live in SQLite.

Model training lives in a **separate project** at `/Volumes/Data/fyp8th_clean` (dataset, QLoRA training, evaluation, GGUF conversion). Only go there if the task is about training or the model itself — this repo is endpoints, schemas, auth, history and serving.

## Commands

```bash
uv sync                                    # deps (or: pip install -e .)
uv sync --extra notebooks                  # add the Jupyter kernel; uv prunes it otherwise

./run_model_server.sh --bg                 # llama.cpp on 8081; --status / --stop
./runserver.sh                             # the API; start|stop|restart|status|logs
curl -s localhost:8080/ready | python3 -m json.tool   # names what is missing

.venv/bin/python -m pytest -q              # 90 tests, ~2 min with the model server up
.venv/bin/python scripts/eval_comment_validator.py    # what the comment rules catch
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

**Roman Urdu is backend-local now.** `translation_service.to_roman_urdu` first
loads `models/roman-model/t5-stage2-c` (override with `ROMAN_URDU_MODEL_PATH`),
the trained 61M-param T5 from the training repo. If it is missing or errors, the
old frame translator still answers. Code placeholders are masked and restored
around the model; if a placeholder is dropped, the English is returned rather
than unsafe Roman Urdu. For `/analyze`, `output_language=roman_urdu` translates
the main `explanation` and the comments appended in `commented_code`; code
fields stay as submitted. The public response is trimmed to `input_code`,
`commented_code`, `explanation`, and `needs_review`; internal analysis,
line comments and anchor stats are still computed but not returned. Time and
space complexity are stripped from the public explanation.

**The `/analyze` pipeline** ([app/routers/analyze.py](app/routers/analyze.py)) is the orchestrator; services stay single-purpose:

```
static_analyze (tree-sitter, cheap, ground truth)
  → model_service.run_model  → qwen_service | codet5
       qwen only: repair_anchors → whole-file gate → comment_validation
  → comment_service / explanation_service / review_service / documentation_service
  → syntax gate (skipped when the backend anchored) → needs_review
  → diff_service (only with old_code) → translation_service (only for roman_urdu)
  → record_history
```

The static facts feed the response and the rule-based services. On this path
they reach no model prompt on either backend — both checkpoints are fine-tuned
on fixed wording and drift on anything prepended to it, `run_model`'s `analysis`
argument is accepted and ignored, and the dead `_facts_block` that tried it has
been deleted. `/optimize` is the exception: `build_optimization_prompt` puts one
recursion hint in the prompt, on the CodeT5 path only.

`app/services/` owns tasks (each can later swap its rule engine for a model); `app/model_processing/` owns the deterministic text/code machinery (anchoring, equivalence, repair, syntax check); `app/parsers/` owns tree-sitter.

## The invariant that explains most of the code

The model returns comments as `{line, code, comment}` records, **not** a rewritten copy of the source. Each record quotes the line it describes, so it can be checked against the submission.

Line **numbers** are unreliable (~25–43% correct); the **quotes** are not (~100%). So [anchors.py](app/model_processing/anchors.py) relocates each comment by its quoted text, drops anything quoting a line the user never wrote, and `render_commented_code` appends comments to the user's own lines. `commented_code` is therefore always the submitted source verbatim plus `// comment` — never a model reconstruction. Measured on a 138-line file: 42 proposed, 39 kept, 3 dropped, 29 line numbers silently corrected.

This proves a comment is *attached correctly*. It does not prove the comment is *true* — on 46 hand-labelled comments, 5 were wrong while perfectly anchored. Don't describe the output as verified-correct.

Three rules close part of that gap by discarding comments the code refutes — `_is_punctuation_only` and `_contradicts_its_line` in `anchors.py`, then [comment_validation.py](app/model_processing/comment_validation.py) on the AST (claims of iteration or recursion the tree denies; names cited as code the enclosing function never mentions). Measured by `scripts/eval_comment_validator.py`: **3 of the 5 rejected, 0 correct comments lost** — precision 1.00, recall 0.60. `anchor_stats.rejected_semantic` and `dropped_*` report every rejection; the fixture is 46 comments over two programs, enough to tune precision and not enough for a tight interval on the error rate.

Two things about those rules resist tidying. Each is scoped to the enclosing **function**, not the anchored line: "iterates over the array" on a signature line is true of the function and false of the line, and the line-scoped version throws it away. And rule 3 only checks tokens the comment *writes as code* (underscore, camelCase, `name(`/`name[`), never comment words that merely match an identifier — real programs are full of variables called `path` and `next`, and matching on those rejects correct English. Precision is the constraint: a lost correct comment is visible, a missed wrong one only leaves the status quo.

When `verified=True` reaches `comment_service`, repair and rule-based fallbacks are bypassed on purpose; they could only move the text away from what the user sent.

## Things that look wrong and are not

Sessions reliably try to tidy these away. Don't.

- **~150 lines duplicated from the training repo** (anchoring, chunking). That repo pins `transformers` 4.57, this one pins 4.46, and this backend must stay independently deployable.
- **`/health` and `/ready` are both present.** `/health` is the cheap liveness probe a load balancer polls; `/ready` touches disk and the inference server. Merging them makes the probe expensive.
- **torch + transformers (~2 GB) with nothing in the current path using them.** Only the legacy CodeT5 engine needs them, and they stay required because `model_service` imports torch at module level. Making them optional means making that import lazy first.
- **Files are chunked before being sent.** The checkpoint saw ~15-line functions; a whole file fits neither its context nor its training distribution. Chunks are line ranges so mapping answers back to file coordinates is exact, and anchors are repaired *inside the chunk* before being shifted — a bare `return 0;` searched file-wide would attach to the wrong function.
- **`/optimize` returns the user's original code on failure.** A rewrite is compiled beside the original, both are run on generated inputs, and it is discarded unless outputs agree. `changed` and `verified` say which case happened; a `verified: false` rewrite is one the driver could not call, not one that failed.

## Constraints

- **The `/analyze` public response is intentionally small.** It returns only `input_code`, `commented_code`, `explanation`, and `needs_review`. Keep internal/debug fields out of that response unless the Android client is updated with the change.
- Python 3.11 (torch 2.0.1 has no 3.12/3.13 wheels), `numpy<2` (torch 2.0.1 ABI). Both pins are load-bearing and documented in `pyproject.toml`.
- ruff enforces `ANN` (annotations required) at line length 100; mypy runs strict.
- Not in git: `models/` (the GGUF is shared out of band), `.env`, `app.db`, `logs/`.

## Docstring convention

Modules and non-trivial functions state **what problem this solves** and **why this design over the obvious alternative**, then `:param:` / `:return:` / `:raises:`. Roughly two-thirds of `app/` follows it. Match it — the "why" lines are how the deliberate oddities above stay defensible, and a session that strips them removes the only record of the measurement behind a decision.
