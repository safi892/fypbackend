"""``/ready`` — say whether this machine can actually answer requests.

Problem solved: the API depends on things that live outside it — a separate
inference server, a model file of nearly a gigabyte, a C++ compiler for
verifying optimisations. On a fresh machine any of them can be missing, and
without this the first symptom is a failed request with an error that describes
the symptom rather than the cause.

Why it never fails the request: a monitoring probe wants a body it can read,
and a developer wants the whole list of what is wrong, not the first item.
``ready`` is the single field to check; ``checks`` says why.

Why not ``/health``: that already exists and answers whether the process is
up, which a load balancer polls constantly and must stay cheap. This one talks
to the inference server and touches the disk, so it is a readiness check and
belongs at its own path.
"""

from __future__ import annotations

import json
import shutil
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import APIRouter

from app.core.config import (
    LLAMA_MODEL_PATH,
    LLAMA_SERVER_URL,
    MODEL_BACKEND,
)

router = APIRouter()


def _check_llama_server() -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(f"{LLAMA_SERVER_URL}/health", timeout=5) as response:
            status = json.load(response).get("status")
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return False, (
            f"not answering at {LLAMA_SERVER_URL} ({exc}). "
            f"Start it with ./run_model_server.sh --bg"
        )
    if status != "ok":
        return False, f"reachable but still loading the model (status: {status})"
    return True, f"ready at {LLAMA_SERVER_URL}"


def _check_model_file() -> tuple[bool, str]:
    path = Path(LLAMA_MODEL_PATH)
    if not path.is_file():
        return False, (
            f"missing: {path}. The GGUF is not in the repository; copy it into "
            f"models/gguf/ or set LLAMA_MODEL_PATH."
        )
    return True, f"{path.name} ({path.stat().st_size / 1024**3:.2f} GB)"


def _check_compiler() -> tuple[bool, str]:
    compiler = shutil.which("c++")
    if compiler is None:
        return False, (
            "no c++ on PATH. Comments and explanations still work; optimisations "
            "cannot be verified and will be returned unchecked."
        )
    return True, compiler


@router.get("/ready")
def ready() -> dict:
    """Report whether every dependency this backend needs is present.

    :return: ``ready`` plus a per-dependency breakdown, always HTTP 200.
    """
    checks: dict[str, dict] = {}

    if MODEL_BACKEND == "qwen_gguf":
        for name, probe in (
            ("model_file", _check_model_file),
            ("llama_server", _check_llama_server),
        ):
            ok, detail = probe()
            checks[name] = {"ok": ok, "detail": detail}
    else:
        checks["model_backend"] = {
            "ok": True,
            "detail": "codet5 (in-process); llama-server not required",
        }

    # The compiler is optional: without it optimisation is unverified rather
    # than unavailable, so it must not hold `ready` down.
    ok, detail = _check_compiler()
    checks["cpp_compiler"] = {"ok": ok, "detail": detail, "required": False}

    required = [name for name, check in checks.items() if check.get("required", True)]
    ready = all(checks[name]["ok"] for name in required)

    return {
        "ready": ready,
        "backend": MODEL_BACKEND,
        "checks": checks,
        "next_step": None
        if ready
        else [checks[name]["detail"] for name in required if not checks[name]["ok"]][0],
    }
