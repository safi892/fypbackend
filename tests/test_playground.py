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
    assert 'id="code-heading"' in response.text
    assert 'id="commented-code"' in response.text
    assert 'id="optimized-code"' in response.text
    assert 'id="optimize-button"' in response.text
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


def test_validation_offers_a_previewable_fix_that_passes_the_same_gate(client):
    code = "int main() {\n    return 0\n}"
    data = client.post("/validate-code", json={"code": code}).json()
    assert data["valid"] is False
    assert data["line"] == 2
    fix = data["suggested_fix"]
    assert fix is not None
    assert "return 0;" in fix["code"]
    assert fix["edits"] == [{"line": 2, "before": "    return 0", "after": "    return 0;"}]
    # The client only ever shows a proposal that the validator itself accepts.
    assert client.post("/validate-code", json={"code": fix["code"]}).json()["valid"] is True


def test_validation_offers_no_fix_when_there_is_none_to_trust(client):
    # Valid code, non-C++, comment-only input, and ERROR-only shapes (where
    # the parser named no missing token) all come back without a proposal.
    for code in [
        "int main() { return 0; }",
        "def add(a, b):\n    return a + b",
        "// Just a comment",
        "int add(int a, int b) {\n    int c = a + b\n    return c;\n}",
    ]:
        data = client.post("/validate-code", json={"code": code}).json()
        assert data["suggested_fix"] is None, code


# --- the browser bug the Python suite cannot see ----------------------------- #

def test_optimize_only_variables_are_not_used_in_the_analyze_handler():
    """`optData` and `defects` exist only after the /optimize call.

    This guards a real regression: rendering code meant for the optimize handler
    was inserted before the first `$('raw-response')` write, which belongs to
    *analyze*. The Python suite stayed green while the Analyze button failed in
    the browser with "optData is not defined" — nothing here executes app.js, so
    a syntax-valid scope error is invisible to every other test.
    """
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "app" / "web" / "app.js"
    lines = source.read_text(encoding="utf-8").split("\n")
    optimize_call = next(
        index for index, line in enumerate(lines)
        if "await request('/optimize'" in line
    )
    early = [
        index + 1
        for index, line in enumerate(lines[:optimize_call])
        if "optData" in line or "defects" in line
    ]
    assert not early, f"optimize-only variables referenced at line(s) {early}"


def test_every_const_in_the_optimize_handler_is_declared_before_it_is_used():
    """A `const` used above its declaration throws at runtime, not at parse time.

    `node --check` passes it, the Python suite never executes it, and the page
    fails with a ReferenceError the moment the button is pressed. This has now
    happened twice while editing this handler.
    """
    import re
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app" / "web" / "app.js").read_text("utf-8")
    lines = source.split("\n")
    start = next(i for i, line in enumerate(lines) if "await request('/optimize'" in line)
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("}")), len(lines))
    block = lines[start:end]

    for index, line in enumerate(block):
        # Only the handler's own top-level consts: exactly one indent level.
        # A `const` inside a nested block has its own scope, and this flat scan
        # cannot model that - it would flag `const code` in a loop body against
        # an unrelated `optData.code` higher up.
        match = re.match(r"^    const\s+([A-Za-z_$][\w$]*)\s*=", line)
        if not match:
            continue
        name = match.group(1)
        # Not preceded by a dot, so `optData.code` is not a use of `code`.
        pattern = rf"(?<![.\w$]){re.escape(name)}\b"
        earlier = [
            start + i + 1
            for i, candidate in enumerate(block[:index])
            if re.search(pattern, candidate)
        ]
        assert not earlier, f"`{name}` used at line(s) {earlier} before line {start + index + 1}"
