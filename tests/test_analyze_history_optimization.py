"""Tests for optimization persistence and optimization fields in /analyze/history.

Validates the Android client requirements:
1. GET /analyze/history after POST /analyze returns null for all 4 optimization fields.
2. GET /analyze/history after POST /analyze + POST /optimize returns matching optimization fields.
3. GET /analyze/history/{id} returns the detailed entry with optimization fields.
4. Existing legacy rows without optimization data return null for all 4 fields.
5. Pagination (total, limit, offset) remains valid JSON.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db_connection, get_db_lock, initialize_database
from app.main import app
from app.schemas.auth import RegisterRequest
from app.services import auth_service, model_service

CODE_SAMPLE = """int compute(int n)
{
    if (n <= 0) return 0;
    return n + compute(n - 1);
}"""


@pytest.fixture(autouse=True)
def mock_run_model(monkeypatch):
    """Stub model_service.run_model so unit tests do not require a running llama-server."""
    def fake_model(code, analysis=None):
        return model_service.RawModelOutput(
            commented_code=code,
            explanation="Calculates sum recursively.",
            verified=True,
        )

    monkeypatch.setattr(model_service, "run_model", fake_model)


@pytest.fixture
def auth_client() -> tuple[TestClient, dict[str, str], int]:
    """Provide a TestClient with an authenticated user and auth headers."""
    initialize_database()
    client = TestClient(app)

    unique_email = f"test_hist_{auth_service._utc_now().timestamp()}@example.com"
    payload = RegisterRequest(
        name="History User",
        email=unique_email,
        password="Password123!",
        confirm_password="Password123!",
    )
    auth_resp = auth_service.register_user(payload)
    headers = {"Authorization": f"Bearer {auth_resp.token}"}

    return client, headers, auth_resp.user.id


def test_analyze_history_returns_null_optimization_fields_after_analyze(auth_client):
    client, headers, user_id = auth_client

    # 1. Post to analyze
    res_analyze = client.post(
        "/analyze",
        headers=headers,
        json={"code": CODE_SAMPLE, "source": "android"},
    )
    assert res_analyze.status_code == 200

    # 2. Get history
    res_history = client.get("/analyze/history", headers=headers)
    assert res_history.status_code == 200
    data = res_history.json()

    assert data["total"] >= 1
    assert "items" in data
    item = data["items"][0]

    assert item["input_code"] == CODE_SAMPLE
    assert "optimized_code" in item
    assert item["optimized_code"] is None
    assert "optimization_verified" in item
    assert item["optimization_verified"] is None
    assert "speedup" in item
    assert item["speedup"] is None
    assert "optimization_note" in item
    assert item["optimization_note"] is None


def test_analyze_history_returns_populated_optimization_fields_after_optimize(
    auth_client, monkeypatch
):
    client, headers, user_id = auth_client

    # 1. Post to analyze first
    res_analyze = client.post(
        "/analyze",
        headers=headers,
        json={"code": CODE_SAMPLE, "source": "android"},
    )
    assert res_analyze.status_code == 200

    # Mock optimization_service so it doesn't need C++ compiler or model server
    from app.services import optimization_service

    mock_optimized_code = (
        "int compute(int n) {\n"
        "    int total = 0;\n"
        "    while (n > 0) { total += n; n--; }\n"
        "    return total;\n"
        "}"
    )
    mock_note = "Converted recursion to while loop with verified equivalence."
    mock_result = optimization_service.OptimizationResult(
        code=mock_optimized_code,
        changed=True,
        verified=True,
        speedup=2.5,
        note=mock_note,
    )
    monkeypatch.setattr(
        optimization_service, "optimize_checked", lambda *args, **kwargs: mock_result
    )

    # 2. Post to optimize with same code
    res_opt = client.post(
        "/optimize",
        headers=headers,
        json={"code": CODE_SAMPLE, "source": "android", "mode": "loop"},
    )
    assert res_opt.status_code == 200
    opt_data = res_opt.json()
    assert opt_data["verified"] is True
    assert opt_data["speedup"] == 2.5

    # 3. Check history list endpoint
    res_history = client.get("/analyze/history", headers=headers)
    assert res_history.status_code == 200
    history_data = res_history.json()

    item = history_data["items"][0]
    assert item["input_code"] == CODE_SAMPLE
    assert item["optimized_code"] == opt_data["code"]
    assert item["optimization_verified"] is True
    assert item["speedup"] == 2.5
    assert item["optimization_note"] == mock_note

    # 4. Check history detail endpoint
    entry_id = item["id"]
    res_detail = client.get(f"/analyze/history/{entry_id}", headers=headers)
    assert res_detail.status_code == 200
    detail_data = res_detail.json()
    assert detail_data["id"] == entry_id
    assert detail_data["optimized_code"] == opt_data["code"]
    assert detail_data["optimization_verified"] is True
    assert detail_data["speedup"] == 2.5
    assert detail_data["optimization_note"] == mock_note


def test_history_detail_returns_404_when_not_found(auth_client):
    client, headers, _ = auth_client
    res = client.get("/analyze/history/999999", headers=headers)
    assert res.status_code == 404
    assert res.json()["detail"] == "History entry not found"


def test_legacy_rows_return_all_four_optimization_fields_as_null(auth_client):
    """Ensure older records created before this feature degrade cleanly with null fields."""
    client, headers, user_id = auth_client

    # Direct DB insertion simulating a row created before the migration
    with get_db_lock():
        with get_db_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO analysis_history
                (user_id, input_code, commented_code, explanation, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    "int legacy();",
                    "int legacy(); // comm",
                    "legacy exp",
                    "android",
                    "2026-01-01T00:00:00Z",
                ),
            )
            conn.commit()
            legacy_id = cursor.lastrowid

    res_history = client.get("/analyze/history", headers=headers)
    assert res_history.status_code == 200
    items = res_history.json()["items"]
    legacy_item = next(it for it in items if it["id"] == legacy_id)

    assert legacy_item["optimized_code"] is None
    assert legacy_item["optimization_verified"] is None
    assert legacy_item["speedup"] is None
    assert legacy_item["optimization_note"] is None


def test_standalone_optimize_creates_history_record_with_optimization_fields(
    auth_client, monkeypatch
):
    client, headers, user_id = auth_client

    from app.services import optimization_service

    standalone_code = "int square(int x) { return x * x; }"
    mock_result = optimization_service.OptimizationResult(
        code=standalone_code,
        changed=False,
        verified=False,
        speedup=1.0,
        note="Already optimal.",
    )
    monkeypatch.setattr(
        optimization_service, "optimize_checked", lambda *args, **kwargs: mock_result
    )

    res_opt = client.post(
        "/optimize",
        headers=headers,
        json={"code": standalone_code, "source": "android", "mode": "loop"},
    )
    assert res_opt.status_code == 200

    res_history = client.get("/analyze/history", headers=headers)
    assert res_history.status_code == 200
    item = res_history.json()["items"][0]

    assert item["input_code"] == standalone_code
    assert item["optimized_code"] == standalone_code
    assert item["optimization_verified"] is False
    assert item["speedup"] == 1.0
    assert item["optimization_note"] == "Already optimal."


def test_analyze_history_unauthenticated_returns_401():
    client = TestClient(app)
    res = client.get("/analyze/history")
    assert res.status_code == 401
