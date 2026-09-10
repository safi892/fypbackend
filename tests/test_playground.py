"""The browser workspace is public, including test analysis."""

import pytest

from app.parsers import cpp_parser
from app.services import model_service


def test_playground_serves_assets_and_allows_guest_analysis(client, monkeypatch):
    def fake_model(_code, analysis=None):
        return model_service.RawModelOutput(
            commented_code="int main() { return 0; }",
            explanation="Purpose: Returns success.",
            verified=True,
        )

    monkeypatch.setattr(model_service, "run_model", fake_model)

    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'id="analyze-form"' in response.text
    assert "No account needed" in response.text
    assert "auth-dialog" not in response.text
    for path, content_type in [("/static/app.js", "javascript"), ("/static/style.css", "text/css")]:
        asset = client.get(path)
        assert asset.status_code == 200
        assert content_type in asset.headers["content-type"]
    assert client.get("/static/../core/config.py").status_code == 404
    assert client.get("/health").json() == {"status": "ok"}
    assert client.post("/analyze", json={"code": "int main() { return 0; }"}).status_code == 200


@pytest.mark.parametrize(
    ("code", "valid"),
    [
        ("int add(int a, int b) { return a + b; }", True),
        ('#include <iostream>\nint main() { std::cout << "Hi"; return 0; }', True),
        ("def add(a, b):\n    return a + b", False),
        ("const add = (a, b) => a + b;", False),
        ("int main() {\n    return 0\n}", False),
        ("", False),
        ("// Just a comment", False),
    ],
)
def test_editor_validation_needs_no_login_or_model(client, monkeypatch, code, valid):
    def unexpected_model(*args, **kwargs):
        pytest.fail("Live syntax checking must not invoke the model")

    monkeypatch.setattr(model_service, "run_model", unexpected_model)
    response = client.post("/validate-code", json={"code": code})
    assert response.status_code == 200
    assert response.json()["valid"] is valid
    if code == "int main() {\n    return 0\n}":
        assert response.json()["line"] == 2


def test_editor_validation_unavailable_and_size_limit(client, monkeypatch):
    monkeypatch.setattr(cpp_parser, "parse", lambda code: None)
    assert client.post("/validate-code", json={"code": "int x;"}).status_code == 503
    assert client.post("/validate-code", json={"code": "x" * 100001}).status_code == 422
