# Implementing code optimisation: recursion to loops, and the rest

How to make `/optimize` reliably turn recursion into loops, remove duplicate
scans, and apply the other transformations a reviewer expects — in this repo,
against the code that is already here.

Everything below is measured. The numbers come from running the shipped 1.5B
GGUF on this machine on 2026-10-02, and the two defects in §3 were found by
running this backend's own verifier against two real student submissions.

## 1. The number that decides the design

Asked **once** at `temperature: 0`, the model gets these rewrites wrong most of
the time. Two submissions, four answers:

| | removed the recursion | output identical | compiles |
| --- | --- | --- | --- |
| recursive max, `iterate` | yes | **no** — wrong on 3 of 5 inputs | **no** — missing `#include <stack>` |
| recursive max, `optimize` | correctly declined to change it | yes | yes |
| row-difference sum, `iterate` | **no** — left `return s + f(a, n, x+1)` | — | yes |
| row-difference sum, `optimize` | **no** | **no** — dropped the `abs`, and changed the signature | yes |

One of four was right, and it was right by changing nothing. This matches the
training repo's measurement over 60 real submissions: the shipped wording
removes recursion in **3/60**, naming the container explicitly gets **10/60**.

**So the model is not the deliverable. The gate is.** Asked **eight** times at
`temperature: 0.8`, with every candidate compiled and run against the original:

| | servable | why the rest were rejected |
| --- | ---: | --- |
| recursive max | **1 / 8** | 4 ran correctly but **left the recursion in**; 2 wrong output; 1 **looped forever** |
| row-difference sum | **2 / 8** | 3 wrong output, 3 compile errors |

A 1-in-8 generator plus a perfect filter is a usable product. A 1-in-8
generator with no filter is not.

## 2. What already works here

`optimization_service.optimize_checked` has the right shape already. It
proposes a rewrite, calls `equivalence.check`, and returns the **user's own
code** on any doubt, with `changed` and `verified` saying which happened. Keep
that contract: a wrong optimisation is worse than none.

`equivalence._build_and_run` already handles the hang:

```python
except subprocess.TimeoutExpired:
    return None, f"ran longer than {timeout:g}s", timeout
```

That matters — one of the eight samples above ran forever. A rewrite that does
not terminate must be a rejection, not an exception that reaches the client.

## 3. Four defects in the verifier, found by running it — all now fixed

These are the important part of this document. A verifier that reports the
wrong thing is worse than no verifier: it turns "we do not know" into a verdict.

Three of the four made `check` blame **the user's code** for a limitation of the
driver. One let a rewrite through that is wrong for every argument except the
single value it was tested with.

### 3a. The driver's result variable collided with the function's own name

```
auto r = r(a0_0.data(), a0_1, a0_2);
         ^ error: use of 'r' before deduction of 'auto'
```

Single-letter names are the norm in these submissions, so a function called `r`
could **never** be checked — and `check` returned `not verified: original
compile failed`, which reads as a claim about the submission. Fixed by naming
the result `a{index}_ret`, sharing the per-case prefix the argument locals
already use.

**This was why the correct loop rewrite of the recursive max was rejected.** It
now reports `equivalent on 5 inputs`.

### 3b. A multidimensional array was driven as a flat one

```
error: cannot convert 'int*' to 'int (*)[5]'
```

The driver backs every sequence with a `std::vector` and passes `.data()`, an
`int*`. A parameter declared `int a[][5]` wants `int (*)[5]`. Fixed by making
such a parameter **not drivable**, so the verdict names the real limit:

```
cannot check f(...): it takes a multidimensional array (a); the driver can
only supply a flat sequence
```

Failing closed with an actionable reason is the correct behaviour. Supporting
2-D arrays properly is a separate piece of work.

### 3c. Defaulted parameters were dropped, so they were never varied

Tree-sitter labels a parameter with a default `optional_parameter_declaration`,
and the parser matched only `parameter_declaration`. So
`int f(int a[][5], int n, int x = 0)` parsed as **two** parameters and every
generated case ran with `x = 0`.

This one is latent rather than observed on the submission above — that function
is refused by §3b anyway — so it is demonstrated on a shape the driver can
call. `tally(int a[], int n, int from = 0)` against a rewrite that ignores
`from`: identical whenever `from` is 0, wrong everywhere else. Before the fix
that was every case. `tests/test_optimization_verified.py` pins it.

### 3d. Index scalars were filled as though they were lengths

```
correctness inputs: ((), 0, 2), ((7,), 1, 2), ((1,2,3,4), 4, 2), ...
```

The rule was "an integer following a sequence is that sequence's length", which
is right for `f(arr, n)` and wrong for `r(arr, l, h)`. The third case is
`l = 4, h = 2` on a four-element array, so the function returns `a[4]`; the
first indexes an **empty** sequence. Both versions then read out of bounds and
the comparison is between two undefined behaviours, which can agree and mean
nothing.

Fixed by reading the name: length-ish names still take the sequence length,
low-index names start inside it, high-index names take the last valid
subscript, and the empty case is dropped for signatures that index. Now:

```
((7,), 0, 0)   ((1,2,3,4), 1, 3)   ((4,3,2,1), 0, 3)   ((5,1,5,1,5), 2, 4)
```

**The fix had the same shape as the bug on the first attempt.** Pinning low
indices to `0` would mean a parameter named `from` or `start` takes one value in
every case — untested for exactly the reason §3c was untested. Low indices now
vary across the case list, and a test asserts they do.

Two limits worth stating. The name heuristic is a heuristic: a parameter called
`l` that is not an index gets a small in-range value, which is harmless, but an
index called something unexpected still gets the length. Reading which
parameters appear inside a subscript expression via `cpp_parser` would settle
it. And verification proves equivalence **on the inputs tried**, never in
general — which is the whole reason every parameter has to vary.

## 4. The pipeline to build

```
code ─▶ 1 route by shape ─▶ 2 sample N ─▶ 3 repair ─▶ 4 verify ─▶ 5 did it do the task? ─▶ serve or decline
```

### Step 1 — route on the shape of the recursion

Port `optimization_routing.classify_recursion` from the training repo
(~120 lines, tree-sitter with a regex fallback; this repo already has
`app/parsers/cpp_parser`). It picks the right question:

- two or more self-calls **in the return expression** → `optimize`, the
  memoisation wording. `fib(n-1) + fib(n-2)` is overlapping work.
- otherwise → `iterate`, the loop wording.

It got both submissions above right, including declining to memoise the
divide-and-conquer max, which has no overlapping subproblems. Routing is free
accuracy: asking for a table where a loop is wanted guarantees a rejection.

### Step 2 — sample N, not 1

`optimize_checked` currently calls `qwen_service.optimize(code)` once. Sample
**8 at `temperature: 0.8`, `top_p: 0.95`** with different seeds, and verify each.
Keep the first that passes. Cost is 8 llama-server calls, and on this CPU the
1.5B runs at ~7.5 tok/s, so budget a few minutes per request or make the
endpoint asynchronous.

The scoring rule matters, and the training repo's `best_of` already encodes it:
do **not** rank on "fewest objections", because the empty answer objects to
nothing and would win every time. Discard answers that said nothing *first*,
then prefer answers with no objections, then prefer the one that said the most.

### Step 3 — repair what is mechanically repairable

Before compiling, add missing standard headers. A rewrite that uses
`std::stack` without `#include <stack>` is a forgotten header, not wrong logic,
and repairing it rescued **5 of 16** candidates in the run above.

```python
HEADERS = {"stack": "<stack>", "queue": "<queue>", "pair": "<utility>",
           "vector": "<vector>", "deque": "<deque>", "map": "<map>",
           "unordered_map": "<unordered_map>", "unordered_set": "<unordered_set>",
           "set": "<set>", "swap": "<algorithm>", "max": "<algorithm>",
           "min": "<algorithm>", "sort": "<algorithm>"}

def repair_includes(code: str) -> str:
    need = {h for name, h in HEADERS.items() if re.search(rf"std::{name}\b", code)}
    need -= set(re.findall(r"#include\s*(<[^>]+>)", code))
    return "".join(f"#include {h}\n" for h in sorted(need)) + code
```

Do not repair anything else. Rewriting the model's logic to make it compile
means serving code nobody checked.

### Step 4 — verify by execution

`equivalence.check` already does this. Fix §3a and §3b first, and add the
out-of-bounds guard, or the gate will pass rewrites that are wrong off the
cases it happened to try.

### Step 5 — check it actually did the task

This is the gap that surprises people. Four of the eight `iterate` samples
compiled, ran, and agreed with the original on every input — while still
containing `return s + f(a, n, x + 1)`. They are equivalent *and useless*, and
without this check the endpoint reports them as optimisations.

```python
from app.model_processing.recursion import recursive_functions  # port from claim_checks

if task == "iterate" and recursive_functions(strip_comments(candidate)):
    reject("the rewrite still calls itself")
```

Add the same idea per transformation: for `optimize`, require that the rewrite
introduced storage the original did not have, comparing **introduced** tokens
against the original rather than scanning the rewrite alone. The training repo
learned this the hard way — `binary_search` takes a parameter named `table`, so
scanning the rewrite for `table` scored a textbook loop as memoised.

## 5. The deterministic catalogue — do this part first

Most of what a beginner-facing reviewer should suggest needs no model at all.
Rule-based rewrites are 100% reliable instead of 1-in-8, and they still go
through Step 4 because a rule can be written wrong.

| transformation | detect | safe |
| --- | --- | --- |
| tail / accumulator recursion → `while` | single self-call in a return | yes |
| recursive linear search → `for` | single self-call, no accumulation | yes |
| `std::endl` → `'\n'` | token | yes |
| `push_back` in a counted loop → `reserve()` first | loop bound known | yes |
| repeated `.size()` / `strlen` in a loop condition → hoist | loop condition | yes |
| pass large object by value → `const&` | parameter type | yes |
| O(n²) membership scan → `unordered_set` as a **seen** marker | nested loop whose inner body only compares and breaks | yes — measured **20× faster, byte-identical output** |
| `int t=a; a=b; b=t;` → `std::swap` | three-statement swap | yes — measured **2.3× faster** |
| recursion needing a hand-built stack | model + gate | **1 in 8** |

### Two transformations to refuse, with the measurement

**Swap via XOR.** Not an optimisation and not safe:

```
40,000,000 swaps:  temp 23.2 ms   xor 30.0 ms   std::swap 13.1 ms
xor swap, both indices the same: the element becomes 0
```

It is 29% *slower* than a temp variable, and `eval_hard.py` in the training repo
already uses this exact pattern as a **defect the model is supposed to catch**.
Never suggest it.

**Replacing the array with a set to deduplicate.** Changes the answer:

```
input            : 30 10 30 20 10 40
loop (original)  : 30 10 20 40      <- first-occurrence order
std::set         : 10 20 30 40      <- sorted
unordered_set    : 40 20 10 30      <- arbitrary
```

The transformation users mean is the *seen marker* in the table above, which
keeps the order. Step 4 catches the difference automatically, which is the
argument for never skipping it.

## 6. Order of work

1. ~~Fix the verifier.~~ **Done** — all four defects in §3, with tests.
2. **Add Step 5**, the did-it-do-the-task check. Cheap, and it removes the
   largest class of useless "optimisations": four of eight samples ran
   correctly while still containing the self-call.
3. **Add Step 3**, include repair. One function, rescued a third of candidates.
4. **Add Step 2**, best-of-8. This is what turns the feature on.
5. **Add Step 1**, routing, and the two measured wordings from the training
   repo's `prompt.py`.
6. **Then** the deterministic catalogue in §5, largest win first.

## 7. How to know whether it worked

Write down which number should move **before** running anything. The training
repo lost a month to an evaluation that never prompted the task it had changed.

For this feature the numbers are: share of requests where a rewrite is served
at all, share of served rewrites that pass the gate, and — the one that matters
— share where the requested transformation actually happened. Measure the last
one separately, because §5 of the run above is the proof that the first two can
look fine while nothing was optimised.

Report "no detectable change" rather than "no change" when `n` is small, and
test paired differences with McNemar exact rather than comparing two
percentages.
