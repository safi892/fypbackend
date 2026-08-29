# Running the backend on a new machine

Everything the API needs lives in this project except the ignored model weights
and `llama.cpp` (a native binary). This page covers both, and the readiness
probe tells you if the Qwen server is missing rather than leaving you to guess
from a failed request.

## 1. Python environment

```bash
uv sync                     # or: pip install -e .
```

## 2. llama.cpp

The API does not load the model itself. It talks to `llama-server`, which loads
the weights once and keeps them in memory — a gigabyte is not something to load
per request or per worker.

```bash
# macOS
brew install llama.cpp

# Linux / Windows
# build from https://github.com/ggml-org/llama.cpp
```

Check it: `llama-server --version`

## 3. The model file

Not in git — `models/` is ignored, so a clone will not have it. Get
the Qwen GGUF and Roman Urdu T5 model from whoever set the project up and put
them here:

```
models/gguf/qwen-cpp-review-q4_k_m.gguf
models/roman-model/t5-stage2-c/
```

Three builds exist, all producing the same answers:

| file | size | speed | when to use |
| --- | ---: | ---: | --- |
| `qwen-cpp-review-q4_k_m.gguf` | 0.92 GB | ~18 tok/s | **default** |
| `qwen-cpp-review-q8_0.gguf` | 1.5 GB | ~13 tok/s | if you have RAM to spare |
| `qwen-cpp-review-f16.gguf` | 2.9 GB | ~8 tok/s | reference, unquantised |

Measured on CPU. Anchor validity is 100% on all three; the smallest loses one
concept out of sixteen against the unquantised build, which is why it is the
default. Set `LLAMA_MODEL_PATH` to use a different one.

The Roman Urdu model is used when `/analyze` receives
`"output_language": "roman_urdu"`. The default path is
`models/roman-model/t5-stage2-c`, overrideable with `ROMAN_URDU_MODEL_PATH`.
If it is missing, the backend falls back to the older frame translator.
Only the final inference files are needed there; do not copy `checkpoint-*` or
trainer state into the backend.

## 4. Configuration

`.env` in the project root:

```ini
MODEL_BACKEND=qwen_gguf
LLAMA_SERVER_URL=http://127.0.0.1:8081
```

`MODEL_BACKEND` defaults to `codet5`, the original engine, so an existing
deployment keeps working until it opts in. `qwen_gguf` selects the new one.

## 5. Start both processes

```bash
./run_model_server.sh --bg     # llama.cpp on 8081, loads the weights
./runserver.sh                 # the API on 8080
```

Port 8081 is deliberate: this API owns 8080, and the two competing for the
socket is a confusing way to discover the clash.

## 6. Confirm it works

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

When something is missing, `ready` is `false` and `next_step` names the fix.
`/health` stays a cheap liveness probe for the load balancer and does not touch
the model.

## The C++ compiler

Optional, and only used by `/optimize`. Without it, comments and explanations
work normally; a proposed optimisation comes back with `verified: false`
because it could not be compiled and run. With it, a rewrite is executed
alongside the original and discarded unless the outputs agree.

## Troubleshooting

**`llama-server ... is not answering`** — the model server is not running.
`./run_model_server.sh --bg`. The API falls back to CodeT5 rather than failing,
so a mobile client sees a degraded answer instead of an error.

**First request is slow** — the model loads on the server's first start, not
per request. `run_model_server.sh --bg` waits for it before returning.

**Long files take a while** — a file is split into function-sized pieces and
each is a separate request. Roughly a minute per 120 lines on a laptop CPU.

**Port already in use** — something else holds 8081. Set `LLAMA_PORT` and
`LLAMA_SERVER_URL` to match.
