# Setup

Everything needed to run this backend, in order. Three of the four steps are
ordinary Python; the fourth is the inference server, which is a native binary
and the model weights, neither of which pip can install.

Check your work at any point with:

```bash
curl -s localhost:8080/ready | python3 -m json.tool
```

It names what is missing rather than leaving you to infer it from a failed
request.

---

## What you need

| Component | Version | Why | Required |
| --- | --- | --- | --- |
| Python | **3.11** | 3.13 is excluded: torch 2.0.1 has no wheels for it | yes |
| llama.cpp | any recent | serves the Qwen model over HTTP | for `qwen_gguf` |
| GGUF weights | 0.92 GB | not in git, shared separately | for `qwen_gguf` |
| C++ compiler | any C++17 | verifies optimisations by running them | optional |

The C++ compiler is genuinely optional: without it `/analyze` works normally
and `/optimize` returns rewrites marked `verified: false`.

---

## 1. Python 3.11

```bash
python3 --version        # want 3.11.x
```

If it is not 3.11:

```bash
# macOS
brew install python@3.11

# Ubuntu / Debian
sudo apt install python3.11 python3.11-venv

# Windows — install from python.org, then use Git Bash or WSL for the scripts
```

`.python-version` pins 3.11 for tools that read it (uv, pyenv).

## 2. Python dependencies

```bash
# recommended
python3 -m pip install --upgrade uv
uv sync

# or plain pip
python3 -m venv .venv && source .venv/bin/activate
pip install -e . && pip install pytest httpx ruff mypy
```

Pinned versions and the reason for each pin are in `pyproject.toml`. Two are
load-bearing:

- **`torch==2.0.1`** — newer versions change seq2seq beam search, which alters
  the CodeT5 output.
- **`numpy<2`** — torch 2.0.1 was built against the NumPy 1.x ABI. NumPy 2
  installs cleanly and then fails at runtime when converting tensors, which is
  a slow way to find out.

If you use the notebooks under `notebooks/`, add their kernel — `uv sync`
removes anything not declared, so without this Jupyter stops working:

```bash
uv sync --extra notebooks
```

Verify:

```bash
.venv/bin/python -m pytest -q
```

## 3. llama.cpp

The API does not load the Qwen model itself. It talks to `llama-server`, which
loads the weights once and keeps them in memory — a gigabyte is not something to
load per request, or per worker.

```bash
# macOS
brew install llama.cpp

# Ubuntu / Debian — build from source
sudo apt install build-essential cmake git
git clone https://github.com/ggml-org/llama.cpp
cd llama.cpp && cmake -B build && cmake --build build --config Release -j
sudo cp build/bin/llama-server /usr/local/bin/

# Windows — download a release binary from
# https://github.com/ggml-org/llama.cpp/releases and put it on PATH
```

Verify:

```bash
llama-server --version
```

## 4. The model weights

**Not in git.** `models/` is ignored because the file is 940 MB. Get it from
whoever set the project up and put it here:

```
models/gguf/qwen-cpp-review-q4_k_m.gguf
```

Verify:

```bash
ls -lh models/gguf/
```

Three builds exist; all produce the same answers, and all keep 100% anchor
validity. The smallest loses one concept in sixteen against the unquantised
build, which is why it is the default.

| file | size | speed (CPU) |
| --- | ---: | ---: |
| `qwen-cpp-review-q4_k_m.gguf` | 0.92 GB | ~18 tok/s |
| `qwen-cpp-review-q8_0.gguf` | 1.5 GB | ~13 tok/s |
| `qwen-cpp-review-f16.gguf` | 2.9 GB | ~8 tok/s |

Set `LLAMA_MODEL_PATH` to choose a different one.

## 5. C++ compiler (optional)

Used only by `/optimize`, to compile a proposed rewrite alongside the original
and check they still agree.

```bash
# macOS — comes with the Xcode command line tools
xcode-select --install

# Ubuntu / Debian
sudo apt install build-essential
```

Verify:

```bash
c++ --version
```

## 6. Configuration

Create `.env` in the project root:

```ini
MODEL_BACKEND=qwen_gguf
LLAMA_SERVER_URL=http://127.0.0.1:8081
```

`MODEL_BACKEND` defaults to `codet5`, so an existing deployment keeps its old
behaviour until it opts in. Every other setting has a working default; the ones
worth knowing:

| Variable | Default | Meaning |
| --- | --- | --- |
| `MODEL_BACKEND` | `codet5` | `codet5` or `qwen_gguf` |
| `LLAMA_SERVER_URL` | `http://127.0.0.1:8081` | where llama-server listens |
| `LLAMA_MODEL_PATH` | `models/gguf/qwen-cpp-review-q4_k_m.gguf` | which build to serve |
| `LLAMA_THREADS` | `8` | set to your CPU core count |
| `LLAMA_CHUNK_TOKENS` | `300` | how large a piece of a file the model sees at once |
| `LLAMA_MAX_NEW_TOKENS` | `900` | answer budget; too small truncates the JSON |

---

## Running

Two processes. Start the model server first — the API falls back to CodeT5
without it.

```bash
./run_model_server.sh --bg     # llama.cpp on 8081
./runserver.sh                 # the API on 8080
```

Port 8081 is deliberate: the API owns 8080, and the two competing for the
socket is a confusing way to discover the clash.

Stop the model server with `./run_model_server.sh --stop`.

## Confirming it works

```bash
curl -s localhost:8080/ready | python3 -m json.tool
```

```json
{
  "ready": true,
  "backend": "qwen_gguf",
  "checks": {
    "model_file":   { "ok": true, "detail": "qwen-cpp-review-q4_k_m.gguf (0.92 GB)" },
    "llama_server": { "ok": true, "detail": "ready at http://127.0.0.1:8081" },
    "cpp_compiler": { "ok": true, "detail": "/usr/bin/c++", "required": false }
  },
  "next_step": null
}
```

Then a real request:

```bash
TOKEN=$(curl -s localhost:8080/auth/register -H 'Content-Type: application/json' \
  -d '{"name":"Dev","email":"dev@example.com","password":"password123","confirm_password":"password123"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin).get("token",""))')

curl -s localhost:8080/analyze -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"code":"int fib(int n){ if(n<=1) return n; return fib(n-1)+fib(n-2); }"}' \
  | python3 -m json.tool
```

---

## Troubleshooting

**`llama-server ... is not answering`**
The model server is not running. `./run_model_server.sh --bg`. The API falls
back to CodeT5 rather than failing, so a mobile client gets a degraded answer
instead of an error.

**`Model path not found: .../checkpoint-9604`**
The CodeT5 backend is selected but its checkpoint is not on this machine. Set
`MODEL_BACKEND=qwen_gguf` in `.env`, or restore the checkpoint.

**`Numpy is not available` / `_ARRAY_API not found`**
NumPy 2 was installed over torch 2.0.1. `pip install "numpy<2"`.

**First request is slow**
The model loads when the server starts, not per request.
`run_model_server.sh --bg` waits for it before returning.

**Long files take a while**
A file is split into function-sized pieces and each is a separate request.
Roughly a minute per 120 lines on a laptop CPU.

**Port already in use**
Something else holds 8081. Set `LLAMA_PORT` and `LLAMA_SERVER_URL` to match.

**Tests fail on `test_analyze_endpoint`**
Those exercise the model end to end. Start the model server first, or set
`MODEL_BACKEND` to a backend this machine actually has.
