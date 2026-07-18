"""Integration tests for ``POST /analyze`` (the core endpoint).

Problem solved: verifies the full pipeline (auth -> static analysis -> model ->
per-task services -> response) end-to-end and that the mobile-app contract is
preserved. One test also *prints* the model output so a human can eyeball
comment/explanation quality (run with ``pytest -s``).
"""

from __future__ import annotations

from app.schemas.analyze import AnalyzeResponse

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


def test_analyze_returns_core_and_additive_fields(
    client, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        "/analyze", json={"code": SAMPLE_CODE}, headers=auth_headers
    )
    assert response.status_code == 200, response.text

    data = AnalyzeResponse(**response.json())
    # Backward-compatible core contract for the mobile app.
    assert data.input_code.strip()
    assert isinstance(data.commented_code, str)
    assert isinstance(data.explanation, str)
    # Additive fields are produced.
    assert data.analysis is not None
    assert data.analysis.recursive is False
    assert isinstance(data.suggestions, list)
    assert isinstance(data.documentation, list)


def test_analyze_requires_auth(client) -> None:
    response = client.post("/analyze", json={"code": SAMPLE_CODE})
    assert response.status_code == 401


def test_analyze_with_old_code_triggers_change_analysis(
    client, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        "/analyze",
        json={"code": SAMPLE_CODE, "old_code": "int binarySearch(int a[], int n, int t){ return -1; }"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["change_analysis"] is not None


def test_analyze_roman_urdu_translation(
    client, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        "/analyze",
        json={"code": SAMPLE_CODE, "output_language": "roman_urdu"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["translation"] is not None


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
