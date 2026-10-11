# Known issues

Found in a full read of `app/` on 2026-08-11, at commit `db678e0` on
`semantic-comment-validation`. None is a regression and none blocks anything
today; several would embarrass the project in front of someone reading it
closely, which is the reason to write them down rather than fix them silently
later.

**How these were established.** Every entry was verified by reading the code
and tracing the call path. Where an entry says *reproduced*, it was also
triggered at runtime. Where it does not, the failure is argued from the source
and has not been observed — treat those as high-confidence, not as measured.

The one *deliberate* oddity in this list is none of them: for things that look
wrong and are not, see the section of that name in `CLAUDE.md`. Do not "fix"
those.

| # | Issue | Where | Severity |
| --- | --- | --- | --- |
| 1 | `/ready` cannot fail on the CodeT5 backend | `routers/health.py` | Medium |
| 2 | Every database call leaks its connection | `core/database.py` | Medium |
| 3 | Foreign keys are declared but never enforced | `core/database.py` | Medium |
| 4 | The optimizer accepts a rewrite that prints extra output | `model_processing/equivalence.py` | Medium |
| 5 | Two different compiler names for the same job | `syntax_check.py` vs `equivalence.py` | Low |
| 6 | Login is user-enumerable by response time | `services/auth_service.py` | Low |
| 7 | A timed-out original produces a fabricated speedup | `model_processing/equivalence.py` | Low |
| 8 | Four modules have no docstring | `auth_service`, `history_service`, `database`, `config` | Low |
| 9 | `@app.on_event` is deprecated | `main.py` | Low |
| 10 | Six mypy errors, one pre-existing long line | various | Accepted |

---

## 1. `/ready` cannot fail on the CodeT5 backend

`app/routers/health.py:87-91`

When `MODEL_BACKEND` is anything but `qwen_gguf`, the readiness check writes a
single entry and hard-codes it:

```python
checks["model_backend"] = {"ok": True, "detail": "codet5 (in-process); llama-server not required"}
```

It never checks that `MODEL_PATH` exists. `required` defaults to `True` for
that entry, but `ok` is `True` unconditionally, so `ready` is `True` on a
machine where the checkpoint is absent — and `/analyze` then returns 503 from
`_load_model`'s `FileNotFoundError`. That is precisely the failure `/ready`
exists to catch, described in its own module docstring: *"without this the
first symptom is a failed request with an error that describes the symptom
rather than the cause."*

`runserver.sh` already prints the warning that `/ready` will not
(`Warning: model directory not found: .../checkpoint_best`), which is how this
was noticed.

**Fix.** Give the CodeT5 branch a real probe — `os.path.isdir(MODEL_PATH)` —
mirroring `_check_model_file`. Cheap, and it makes the two backends answer the
same question.

**Note.** The current machine runs `qwen_gguf`, where `/ready` is correct and
was reproduced answering `ready: true` with all three real probes passing. This
issue is reachable only by switching the backend.

## 2. Every database call leaks its connection

`app/core/database.py:14-21`

```python
def get_db_connection() -> sqlite3.Connection:
    ...
    return sqlite3.connect(DB_PATH, check_same_thread=False)
```

Every caller uses it as `with get_db_connection() as connection:`. A
`sqlite3.Connection` used as a context manager **commits or rolls back the
transaction — it does not close the connection**. Nothing in the codebase ever
calls `.close()`. A new connection is opened for every register, login, session
lookup, history write and history read.

CPython's refcounting collects each one when it falls out of scope, so this
does not exhaust file descriptors in practice and has not been observed to
fail. It is still an anti-pattern that depends on an implementation detail of
the interpreter, and it is the first thing a reviewer familiar with `sqlite3`
will point at.

**Fix.** Either `contextlib.closing` around each use, or make
`get_db_connection` a `@contextmanager` that closes in a `finally`, or hold one
module-level connection (the `_DB_LOCK` that already guards every call means
concurrency is serialised anyway).

## 3. Foreign keys are declared but never enforced

`app/core/database.py:47,61`

Both `sessions` and `analysis_history` declare
`FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE`. SQLite ignores
foreign-key constraints entirely unless `PRAGMA foreign_keys = ON` is issued
**per connection**, and it never is. The cascade is decorative: deleting a user
would orphan every session and history row.

Latent today because nothing deletes a user. It becomes a live data-integrity
bug the moment an account-deletion endpoint is added, which is the sort of
thing that gets added late.

**Fix.** `connection.execute("PRAGMA foreign_keys = ON")` in
`get_db_connection`, before returning. Note this must be repeated per
connection, which interacts with issue 2 — fixing 2 first makes this one line.

## 4. The optimizer accepts a rewrite that prints extra output

`app/model_processing/equivalence.py:199-206`

```python
result.agreed = sum(
    1
    for index, line in enumerate(expected_lines)
    if index < len(actual_lines) and actual_lines[index] == line
)
result.equivalent = result.agreed == result.cases
```

The comparison iterates over `expected_lines` only. Lines the rewrite prints
*beyond* the expected count are never examined. A rewrite that produces every
correct answer and then prints anything else — debug output, a trailing
diagnostic, a second pass over the data — is accepted as equivalent and
returned to the user with `verified: true`.

This matters more than the other entries because `verified` is the field the
whole `/optimize` design rests on: the module docstring promises *"Nothing here
is offered to a client until it has been run"*, and the response schema tells
the client to trust `verified` specifically.

**Fix.** One line: compare the lists outright,
`result.equivalent = actual_lines == expected_lines`, and derive `agreed` for
the message. Length equality is part of behavioural agreement.

## 5. Two different compiler names for the same job

`app/model_processing/syntax_check.py:75` runs `gcc -fsyntax-only -x c++`.
`app/model_processing/equivalence.py:127` runs `c++`. `app/routers/health.py:63`
probes for `c++`.

On a host with one binary and not the other, `/ready` reports the compiler
present while the syntax gate silently fails open — `check_cpp_syntax` catches
`FileNotFoundError` and returns `(True, None)`, which is deliberate and
documented, but it means the gate can be permanently disabled without any
signal saying so. Both binaries exist on macOS and on most Linux images, so
this is unlikely to bite here.

**Fix.** Use `c++` in `syntax_check.py` too, so one probe answers for both.

## 6. Login is user-enumerable by response time

`app/services/auth_service.py:153-157`

The error message is correctly identical for both cases
(`"Invalid email or password"`). The timing is not: an unknown email returns
immediately, while a known one runs `_hash_password` through
`PASSWORD_HASH_ITERATIONS` rounds of PBKDF2 first. The difference is the whole
point of the iteration count, so it is large and easy to measure remotely.

An attacker learns which addresses are registered. That is the entire severity
— passwords remain safe, the hashing itself is sound (PBKDF2-HMAC-SHA256, a
per-user 16-byte salt, `secrets.compare_digest` for the comparison).

**Fix.** On the miss path, verify against a fixed dummy salt and hash and
discard the result, so both paths pay the same cost.

## 7. A timed-out original produces a fabricated speedup

`app/model_processing/equivalence.py:139,214-221`

`_build_and_run` returns `timeout` as its elapsed time when the run times out.
The timing runs at lines 214-215 discard the stdout and the error, keeping only
that number. If the original times out on the large timing input — which is
exactly what an exponential implementation does, and exactly the case the
optimizer targets — `slow` becomes the 20-second ceiling and the reported
speedup is computed from it.

The user is then shown a specific figure ("equivalent on 8 inputs, 400.0x
faster") that is a lower bound wearing the clothes of a measurement. Correctness
is unaffected: the equivalence check ran earlier on the small inputs and passed
on its own terms.

**Fix.** Have `_build_and_run` signal a timeout distinctly, and set
`timing_reliable = False` with a note saying the original did not finish, rather
than quoting a ratio derived from the ceiling.

## 8. Four modules have no docstring

`app/services/auth_service.py`, `app/services/history_service.py`,
`app/core/database.py`, `app/core/config.py` begin with an import, not a
docstring, and their functions carry none either.

`CLAUDE.md` states the convention — *"Modules and non-trivial functions state
what problem this solves and why this design over the obvious alternative"* —
and notes that roughly two-thirds of `app/` follows it. These four are most of
the missing third, and they are the ones a reader reaches for first when asking
how auth and persistence work.

**Fix.** Write them. `auth_service` in particular has real decisions worth
recording: why sessions in a table rather than JWTs, why PBKDF2 at this
iteration count, why the lock wraps every call.

## 9. `@app.on_event` is deprecated

`app/main.py:42`

FastAPI deprecated `on_event` in favour of a `lifespan` context manager. This is
very likely most of the deprecation noise that `CLAUDE.md` warns *"buries the
summary line"*, which is why the documented test command is
`pytest -p no:warnings`.

**Fix.** Move `initialize_database()` into an `asynccontextmanager` lifespan
handler passed to `FastAPI(lifespan=...)`. Worth doing mainly so the warning
suppression can be dropped and real warnings become visible again.

## 10. Accepted: six mypy errors and one long line

Six strict-mode errors predate all current work and are documented in
`CLAUDE.md` as expected:

```
equivalence.py:143   Item "None" of "CompletedProcess[str] | None" has no attribute "stdout"
qwen_service.py:135  Returning Any from function declared to return "str"
model_service.py:64  Missing type arguments for generic type "dict"
model_service.py:66  Missing type arguments for generic type "dict"
health.py:73         Missing type arguments for generic type "dict"
health.py:78         Missing type arguments for generic type "dict"
```

The first is genuinely unreachable — `_build_and_run`'s `runs` parameter
defaults to 3 and no caller passes 0, so `result` cannot be `None` at line 143 —
but mypy cannot see that. The other five are one-line annotations.

`ruff check tests` also reports one pre-existing `E501` at
`tests/test_analyze_endpoint.py:58`. `ruff check app scripts`, which is the
command the project documents, is clean.

---

## Not issues

Recorded here because each has been proposed as a fix at least once.

- **The comment validator's two AST rules fire on nothing in the current
  fixture.** Verified, expected, and stated in `CLAUDE.md`. The measured catch
  (3 of 5 wrong comments, 0 correct comments lost) comes from the two
  anchor-stage rules. The AST rules are unit-tested guardrails against drift,
  not a measured improvement — describe them that way in any write-up.
- **`comment_validation.py` imports from `app.services.analyzer`,** pointing
  from `model_processing` up into `services`. Deliberate: the analyzer already
  answers "is this a loop" and "does this call itself" for the response the user
  reads, and two answers that could disagree is worse than one import that looks
  upside down.
- **Anything in the "Things that look wrong and are not" section of
  `CLAUDE.md`** — the duplicated anchoring code, both `/health` and `/ready`,
  torch present but unused on the current path, chunking before sending,
  `/optimize` returning the original on failure.
