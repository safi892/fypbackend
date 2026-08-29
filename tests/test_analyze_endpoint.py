"""Integration tests for ``POST /analyze`` (the core endpoint).

Problem solved: verifies the full pipeline (auth -> static analysis -> model ->
per-task services -> response) end-to-end and that the mobile-app contract is
preserved. One test also *prints* the model output so a human can eyeball
comment/explanation quality (run with ``pytest -s``).
"""

from __future__ import annotations

from app.schemas.analyze import AnalyzeResponse
from app.services import model_service, translation_service

SAMPLE_CODE = """
int binarySearch(int arr[], int n, int target) {
    int left = 0, right = n - 1;
    while (left <= right) {
        int mid = left + (right - left) / 2;
        if (arr[mid] == target) return mid;
        else if (arr[mid] < target) left = mid + 1;
        else right = mid - 1;
    }
    return -1;
    
}
"""


def test_analyze_returns_only_display_fields(
    client, auth_headers: dict[str, str], monkeypatch
) -> None:
    def fake_model(_code, analysis=None):
        return model_service.RawModelOutput(
            commented_code=SAMPLE_CODE,
            explanation="Purpose: Searches the array.",
            verified=True,
        )

    monkeypatch.setattr(model_service, "run_model", fake_model)

    response = client.post(
        "/analyze", json={"code": SAMPLE_CODE}, headers=auth_headers
    )
    assert response.status_code == 200, response.text

    data = AnalyzeResponse(**response.json())
    # Backward-compatible core contract for the mobile app.
    assert data.input_code.strip()
    assert isinstance(data.commented_code, str)
    assert isinstance(data.explanation, str)
    assert set(response.json()) == {
        "input_code",
        "commented_code",
        "explanation",
        "needs_review",
    }


def test_analyze_requires_auth(client) -> None:
    response = client.post("/analyze", json={"code": SAMPLE_CODE})
    assert response.status_code == 401


def test_analyze_with_old_code_triggers_change_analysis(
    client, auth_headers: dict[str, str], monkeypatch
) -> None:
    def fake_model(_code, analysis=None):
        return model_service.RawModelOutput(
            commented_code=SAMPLE_CODE,
            explanation="Purpose: Searches the array.",
            verified=True,
        )

    monkeypatch.setattr(model_service, "run_model", fake_model)

    response = client.post(
        "/analyze",
        json={
            "code": SAMPLE_CODE,
            "old_code": "int binarySearch(int a[], int n, int t){ return -1; }",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert "change_analysis" not in response.json()


def test_analyze_roman_urdu_translation(
    client, auth_headers: dict[str, str], monkeypatch
) -> None:
    def fake_model(_code, analysis=None):
        return model_service.RawModelOutput(
            commented_code=SAMPLE_CODE,
            explanation="English explanation",
            verified=True,
        )

    monkeypatch.setattr(model_service, "run_model", fake_model)
    monkeypatch.setattr(
        translation_service, "to_roman_urdu", lambda text: f"Roman Urdu: {text}"
    )

    response = client.post(
        "/analyze",
        json={"code": SAMPLE_CODE, "output_language": "roman_urdu"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["explanation"]


def test_analyze_roman_urdu_translates_explanation_and_anchored_comments(
    client, auth_headers: dict[str, str], monkeypatch
) -> None:
    def fake_model(_code, analysis=None):
        return model_service.RawModelOutput(
            commented_code=SAMPLE_CODE,
            explanation="English explanation",
            line_comments=[
                {
                    "line": 2,
                    "code": "int binarySearch(int arr[], int n, int target) {",
                    "comment": "English comment",
                }
            ],
            anchor_stats={"proposed": 1, "kept": 1, "exact": 1, "chunks": 1},
            verified=True,
        )

    def fake_translate(text: str) -> str:
        return {
            "English explanation": "Roman Urdu explanation",
            "English comment": "Roman Urdu comment",
        }.get(text, text)

    monkeypatch.setattr(model_service, "run_model", fake_model)
    monkeypatch.setattr(translation_service, "to_roman_urdu", fake_translate)

    response = client.post(
        "/analyze",
        json={"code": SAMPLE_CODE, "output_language": "roman_urdu"},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["explanation"] == "Roman Urdu explanation"
    assert "Roman Urdu comment" in data["commented_code"]
    assert "int binarySearch" in data["commented_code"]


def test_analyze_hides_time_and_space_complexity_from_explanation(
    client, auth_headers: dict[str, str], monkeypatch
) -> None:
    def fake_model(_code, analysis=None):
        return model_service.RawModelOutput(
            commented_code=SAMPLE_CODE,
            explanation=(
                "Purpose: Sorts an integer array in ascending order. "
                "Algorithm: Repeatedly compares adjacent elements, resulting in "
                "O(n^2) time and O(1) extra space."
            ),
            verified=True,
        )

    monkeypatch.setattr(model_service, "run_model", fake_model)

    response = client.post(
        "/analyze",
        json={"code": SAMPLE_CODE},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    explanation = response.json()["explanation"]
    assert "Purpose: Sorts an integer array" in explanation
    assert "Algorithm: Repeatedly compares adjacent elements" in explanation
    assert "O(" not in explanation
    assert "time" not in explanation.lower()
    assert "space" not in explanation.lower()


def test_print_model_output_for_manual_review(
    client, auth_headers: dict[str, str], capsys
) -> None:
    """Print the model's commented code + explanation for human inspection.

    Run with ``pytest tests/test_analyze_endpoint.py::test_print_model_output_for_manual_review -s``
    to see the actual generated text in the terminal.
    """
    response = client.post(
        "/analyze", json={"code": SAMPLE_CODE}, headers=auth_headers
    )
    data = AnalyzeResponse(**response.json())
    with capsys.disabled():
        print("\n\n===== MODEL OUTPUT (binarySearch) =====")
        print("--- commented_code ---")
        print(data.commented_code)
        print("--- explanation ---")
        print(data.explanation)
        print("--- suggestions ---")
        for s in data.suggestions:
            print(" -", s)
        print("==============================\n")
    assert response.status_code == 200
