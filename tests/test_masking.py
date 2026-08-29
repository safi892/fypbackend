"""Tests for hiding code fragments from a translator.

The property under test is the one that can be checked without knowing any
Urdu: whatever the translator does to the prose, every identifier comes back
present, once, and spelled the way the user wrote it — or the translation is
refused and the English is returned.

The failing translators below are not hypothetical. Dropping an unfamiliar
token, duplicating one while reordering a clause, and rewriting the digits
inside it are the three things general translation models do with text they
were never trained on.
"""

from __future__ import annotations

from app.model_processing.masking import (
    mask,
    restore,
    translate_protecting_code,
)

SENTENCE = "Divide `total` by 10 to drop the last digit of arr[j]"


# --- masking -------------------------------------------------------------------- #


def test_code_fragments_are_hidden_and_prose_is_not():
    hidden = mask(SENTENCE)

    assert "`total`" not in hidden.text and "arr[j]" not in hidden.text
    assert "Divide" in hidden.text and "last digit" in hidden.text
    assert hidden.spans == ["`total`", "arr[j]"]


def test_a_repeated_fragment_shares_one_placeholder():
    """Fewer placeholders is less for a translator to lose, and a stricter check."""
    hidden = mask("Set total to 0, then add each value to total")

    assert hidden.spans.count("total") <= 1


def test_the_shapes_that_appear_in_real_comments_are_all_protected():
    for fragment in (
        "`std::vector<int>`",   # backticked, with template brackets
        "fib(n - 1)",            # a call with arithmetic inside
        "data[i + 1]",           # an index expression
        "node->next",            # member access
        "std::cout",             # qualified name
        "sortValues",            # camelCase
        "sorted_list",           # snake_case
        "O(n log n)",            # complexity
    ):
        hidden = mask(f"The code uses {fragment} here")
        assert hidden.count == 1, f"{fragment} was not protected"
        assert fragment not in hidden.text


def test_ordinary_prose_needs_no_placeholders():
    hidden = mask("This function counts how many digits are in the sum")

    assert hidden.count == 0


# --- restoring, and refusing ---------------------------------------------------- #


def test_a_faithful_translation_gets_its_code_back_verbatim():
    hidden = mask(SENTENCE)
    translated = hidden.text.replace("Divide", "Taqseem karein")

    result = restore(translated, hidden)

    assert result.ok
    assert "`total`" in result.text and "arr[j]" in result.text


def test_a_dropped_identifier_is_caught_and_named():
    """The failure that matters: a comment about a variable, minus the variable."""
    hidden = mask(SENTENCE)
    lost = hidden.text.replace("⟦1⟧", "")

    result = restore(lost, hidden)

    assert not result.ok
    assert "arr[j]" in result.reason


def test_a_duplicated_identifier_is_caught():
    hidden = mask(SENTENCE)
    doubled = hidden.text + " ⟦0⟧"

    result = restore(doubled, hidden)

    assert not result.ok
    assert "total" in result.reason


def test_a_fragment_the_author_repeated_is_allowed_to_come_back_repeated():
    """Repeats share a placeholder, so the count is what must match, not one.

    Found on the corpus: 836 explanations in 3,000 failed an identity
    round-trip because a legitimately repeated identifier looked like a
    translator duplicating one.
    """
    hidden = mask("Add each value to `total`, then return `total`")

    assert hidden.count == 1, "the repeat shares a placeholder"
    assert hidden.occurrences == [2], "and is recorded as occurring twice"

    result = restore(hidden.text, hidden)

    assert result.ok, result.reason
    assert result.text.count("`total`") == 2


def test_losing_one_of_two_mentions_is_still_caught():
    hidden = mask("Add each value to `total`, then return `total`")
    lost_one = hidden.text.replace("⟦0⟧", "", 1)

    result = restore(lost_one, hidden)

    assert not result.ok
    assert "total" in result.reason


def test_an_invented_placeholder_is_caught():
    """Translators hallucinate structure they have seen in training."""
    hidden = mask(SENTENCE)

    result = restore(hidden.text + " ⟦7⟧", hidden)

    assert not result.ok
    assert "invented" in result.reason


# --- the whole pass ------------------------------------------------------------- #


def test_a_translator_that_mangles_code_returns_english_instead():
    """A translation missing what it was about is worse than no translation."""

    def drops_placeholders(text: str) -> str:
        return text.replace("⟦0⟧", "kuch").replace("⟦1⟧", "kuch")

    result = translate_protecting_code(SENTENCE, drops_placeholders)

    assert not result.ok
    assert result.text == SENTENCE, "the user gets readable English, not mangled Urdu"


def test_a_working_translator_produces_roman_urdu_with_the_code_intact():
    def to_roman_urdu(text: str) -> str:
        return text.replace("Divide", "").replace(
            "by 10 to drop the last digit of", "ko 10 se divide karein taake"
        ).strip() + " ka aakhri digit hat jaye"

    result = translate_protecting_code(SENTENCE, to_roman_urdu)

    assert result.ok
    assert "`total`" in result.text
    assert "arr[j]" in result.text
    assert "karein" in result.text


def test_text_without_code_is_translated_normally():
    result = translate_protecting_code("This function adds two numbers", str.upper)

    assert result.ok
    assert result.text == "THIS FUNCTION ADDS TWO NUMBERS"


def test_empty_text_is_left_alone():
    result = translate_protecting_code("   ", str.upper)

    assert result.ok and result.text == "   "
