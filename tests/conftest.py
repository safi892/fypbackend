"""Pytest fixtures for the code-review backend.

Problem solved: the ``/analyze`` endpoint requires a Bearer session token, so
every integration test needs a registered, logged-in user. This fixture
registers a fresh user (unique email) and returns ready-to-use auth headers.

Why a unique email each session: the SQLite DB persists between runs, so a
fixed email would collide with a previous run's registration (409).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Provide a FastAPI test client backed by an in-process app.

    :return: a ``TestClient`` instance for the app under test.
    """
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers(client: TestClient) -> dict[str, str]:
    """Register a fresh user and return ``Authorization`` headers for requests.

    :param client: the test client fixture.
    :return: a dict with the ``Authorization: Bearer <token>`` header.
    """
    email = f"test_{uuid.uuid4().hex[:10]}@example.com"
    password = "password123"
    response = client.post(
        "/auth/register",
        json={
            "name": "Tester",
            "email": email,
            "password": password,
            "confirm_password": password,
        },
    )
    assert response.status_code == 200, response.text
    token = response.json()["token"]
    return {"Authorization": f"Bearer {token}"}
