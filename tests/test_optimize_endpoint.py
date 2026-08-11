"""Tests for ``POST /optimize`` and ``GET /ready``.

The optimizer is stubbed: what is under test is the contract the mobile client
sees, not what the model happens to propose.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.services import optimization_service
from app.services.optimization_service import OptimizationResult

NAIVE = "int fib(int n)\n{\n  if (n <= 1)\n    return n;\n  return fib(n - 1) + fib(n - 2);\n}"
FASTER = (
    "int fib(int n)\n{\n  int a = 0, b = 1;\n"
    "  for (int i = 0; i < n; ++i) { int t = a + b; a = b; b = t; }\n  return a;\n}"
)


def test_optimize_requires_authentication(client: TestClient):
    response = client.post("/optimize", json={"code": NAIVE})

    assert response.status_code == 401


def test_a_verified_rewrite_is_returned_with_its_evidence(
    client: TestClient, auth_headers: dict[str, str], monkeypatch
):
    monkeypatch.setattr(
        optimization_service,
        "optimize_checked",
        lambda code: OptimizationResult(
            code=FASTER, changed=True, verified=True, speedup=12.5,
            note="equivalent on 8 inputs, 12.5x faster",
        ),
    )

    response = client.post("/optimize", json={"code": NAIVE}, headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == FASTER
    assert body["changed"] is True and body["verified"] is True
    assert body["speedup"] == 12.5
    assert body["input_code"] == NAIVE


def test_a_rejected_rewrite_returns_the_users_own_code(
    client: TestClient, auth_headers: dict[str, str], monkeypatch
):
    """The failure that matters: never hand back code that computes something else."""
    monkeypatch.setattr(
        optimization_service,
        "optimize_checked",
        lambda code: OptimizationResult(
            code=code,
            changed=False,
            verified=False,
            note="rejected: output differs on 6 of 8 inputs",
        ),
    )

    body = client.post("/optimize", json={"code": NAIVE}, headers=auth_headers).json()

    assert body["code"] == NAIVE
    assert body["changed"] is False and body["verified"] is False
    assert "rejected" in body["note"]


def test_an_unverifiable_rewrite_is_marked_rather_than_claimed(
    client: TestClient, auth_headers: dict[str, str], monkeypatch
):
    """Some shapes cannot be driven automatically; say so instead of implying proof."""
    monkeypatch.setattr(
        optimization_service,
        "optimize_checked",
        lambda code: OptimizationResult(
            code=FASTER, changed=True, verified=False,
            note="not verified: cannot generate a caller for fib(...) automatically",
        ),
    )

    body = client.post("/optimize", json={"code": NAIVE}, headers=auth_headers).json()

    assert body["changed"] is True
    assert body["verified"] is False, "an unchecked rewrite must not look checked"


def test_empty_code_is_rejected_by_validation(client: TestClient, auth_headers: dict[str, str]):
    response = client.post("/optimize", json={"code": ""}, headers=auth_headers)

    assert response.status_code == 422


# --- readiness ------------------------------------------------------------------ #


def test_ready_reports_each_dependency(client: TestClient):
    response = client.get("/ready")

    assert response.status_code == 200, "a probe must answer even when unhealthy"
    body = response.json()
    assert "ready" in body and "checks" in body
    assert "cpp_compiler" in body["checks"]


def test_the_cheap_liveness_probe_still_works(client: TestClient):
    """`/health` predates this and the load balancer polls it; it must stay cheap."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_names_the_next_step_when_something_is_missing(client: TestClient, monkeypatch):
    from app.routers import health as health_router

    monkeypatch.setattr(health_router, "MODEL_BACKEND", "qwen_gguf")
    monkeypatch.setattr(
        health_router, "_check_llama_server", lambda: (False, "not answering at http://x")
    )
    monkeypatch.setattr(health_router, "_check_model_file", lambda: (True, "present"))

    body = client.get("/ready").json()

    assert body["ready"] is False
    assert body["next_step"], "an unready service should say what to do about it"
