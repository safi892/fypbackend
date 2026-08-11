# Context brief for a new AI session

Paste the block below when starting a session scoped to this backend. It covers
what a fresh session would otherwise spend its first ten tool calls
rediscovering, and the handful of decisions that look wrong until you know why
they were made.

Keep it updated when those decisions change — a stale brief is worse than none,
because it is believed.

---

```
I'm working on a FastAPI backend that serves an AI C++ code-review model to a
mobile app. Project root: /Volumes/Data/saffi/fyp_backend

WHAT IT DOES
POST /analyze takes C++ and returns commented code, an explanation, and
deterministic static analysis (tree-sitter). POST /optimize returns a faster
rewrite. There is auth, history in SQLite, and a Roman Urdu translation path.
An Android app is the main client, so the response contract matters.

THE MODEL
Recently switched from a fine-tuned CodeT5 to a fine-tuned Qwen2.5-Coder-1.5B
(QLoRA), merged and quantised to GGUF, served by llama.cpp. MODEL_BACKEND in
.env picks the engine: "codet5" (legacy, in-process, no longer installed on my
machine) or "qwen_gguf" (current). The API talks to llama-server over HTTP on
port 8081; the API itself owns 8080.

  ./run_model_server.sh --bg    # llama.cpp, loads models/gguf/*.gguf
  ./runserver.sh                # the API
  curl localhost:8080/ready     # says what is missing if anything is

THE DESIGN DECISION THAT EXPLAINS MOST OF THE CODE
The model returns comments as {line, code, comment} records rather than a
rewritten copy of the source. Each record quotes the line it describes, so it
can be checked against the submission and dropped when it refers to a line the
user never wrote. commented_code is then the user's own source with comments
appended - never a model reconstruction of it.

This matters because the model's line NUMBERS are unreliable (~25% correct)
while its QUOTES are not (~100%), so anchors are relocated by their quoted text
before use. Measured on a real 138-line file: 42 comments proposed, 39 kept, 3
hallucinations dropped, 29 line numbers silently corrected.

Known limitation: this proves a comment is attached to a line that exists and is
quoted correctly. It does NOT prove the comment is true of that line. Roughly
9% of comments on real code are still factually wrong.

OTHER THINGS THAT LOOK ODD BUT ARE DELIBERATE
- Files are split on syntax boundaries before being sent. The checkpoint was
  trained on ~15-line functions; a whole file neither fits its context nor
  matches anything it has seen. Chunks are line ranges so the mapping back to
  file coordinates is exact.
- /optimize compiles the proposed rewrite next to the original, runs both on
  generated inputs and compares. A rewrite that disagrees is discarded and the
  user's own code is returned. `verified` says which happened. The C++ compiler
  is optional; without it rewrites come back with verified=false.
- ~150 lines of anchoring/chunking are duplicated from the training repo rather
  than imported: this project pins transformers 4.46 / torch 2.0.1 and that one
  needs 4.57, and this backend must stay independently deployable.
- /health is a cheap liveness probe the load balancer polls. /ready is the one
  that talks to the model server. Do not merge them.
- torch and transformers (~2 GB) are only needed by the legacy CodeT5 path.
  They are still required because model_service imports torch at module level.

CONSTRAINTS
- Python 3.11 (torch 2.0.1 has no 3.13 wheels), numpy<2 (torch 2.0.1 ABI)
- ruff with ANN rules: type annotations are enforced, line length 100
- mypy strict
- 63 tests, all passing: .venv/bin/python -m pytest -q
  (four of them exercise the model end to end, so llama-server must be
   running or they fail with a 503)
- models/ is gitignored; the 940 MB GGUF is shared out of band
- The response contract is additive only. input_code, commented_code and
  explanation come first and must not change shape - an Android client depends
  on them.

The training repo is a separate project at /Volumes/Data/fyp8th_clean (dataset
building, QLoRA training, evaluation, GGUF conversion). Only touch it if the
work is about training or the model itself.

Please read docs/SETUP.md and docs/API.md before changing anything.
```

---

## Keeping the two projects apart

| Work | Project |
| --- | --- |
| endpoints, schemas, auth, history, serving | `fyp_backend` (this one) |
| dataset, training, evaluation, GGUF builds | `fyp8th_clean` |

The split is worth preserving in sessions too. A session that holds both ends up
proposing training changes to fix serving bugs, and serving changes to fix
training ones.

## What to add when you start a session

Say what you actually want. The brief above says what the project is; it does
not say what today's task is, and a session given only background tends to
start refactoring.
