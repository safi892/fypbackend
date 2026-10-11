from __future__ import annotations

from app.services import translation_service


def test_roman_urdu_uses_trained_model_when_available(monkeypatch) -> None:
    def fake_model(text: str) -> str | None:
        assert "⟦0⟧" in text
        return "⟦0⟧ ko 10 se divide karta hai."

    monkeypatch.setattr(translation_service, "_translate_with_model", fake_model)

    result = translation_service.to_roman_urdu("Divide `total` by 10.")

    assert result == "`total` ko 10 se divide karta hai."


def test_roman_urdu_falls_back_to_frames_when_model_missing(monkeypatch) -> None:
    monkeypatch.setattr(translation_service, "_translate_with_model", lambda _text: None)

    result = translation_service.to_roman_urdu("Purpose: Compute the sum.")

    assert result != ""
    assert result != "Purpose: Compute the sum."


def test_roman_urdu_returns_english_when_model_drops_code(monkeypatch) -> None:
    monkeypatch.setattr(translation_service, "_translate_with_model", lambda _text: "galat")

    text = "Divide `total` by 10."

    assert translation_service.to_roman_urdu(text) == text


def test_one_unsafe_explanation_line_does_not_revert_the_whole_block(monkeypatch) -> None:
    def fake_model(text: str) -> str | None:
        if "⟦0⟧" in text:
            return "galat"
        return "Roman Urdu line"

    monkeypatch.setattr(translation_service, "_translate_with_model", fake_model)

    result = translation_service.to_roman_urdu("Purpose: Sorts the array.\nInput: `arr` array.")

    assert result == "Roman Urdu line\nInput: `arr` array."


def test_bubblesort_explanation_lines_translate_independently(monkeypatch) -> None:
    def fake_model(text: str) -> str | None:
        return {
            "Purpose: Sorts an integer array.": "Purpose: Integer array sort karta hai.",
            "Input: ⟦0⟧ – the array.": "Input: ⟦0⟧ – array.",
            "Output: The array ⟦0⟧ is reordered.": "Output: Array ⟦0⟧ reorder hota hai.",
        }[text]

    monkeypatch.setattr(translation_service, "_translate_with_model", fake_model)

    result = translation_service.to_roman_urdu(
        "Purpose: Sorts an integer array.\n"
        "Input: `int arr[]` – the array.\n"
        "Output: The array `arr` is reordered."
    )

    assert result == (
        "Purpose: Integer array sort karta hai.\n"
        "Input: `int arr[]` – array.\n"
        "Output: Array `arr` reorder hota hai."
    )


def test_model_placeholders_do_not_stick_to_words():
    result = translation_service._space_placeholders("Input:⟦0⟧array;⟦1⟧ jisse⟦2⟧time")

    assert result == "Input: ⟦0⟧ array; ⟦1⟧ jisse ⟦2⟧ time"
