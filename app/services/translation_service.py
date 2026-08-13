"""Translation task (Phase 10) — English -> Roman Urdu.

Problem solved: when a client requests Roman Urdu, the generated English text
must be translated. This service owns that single NLP task, and a trained
model can later replace ``to_roman_urdu`` without changing callers.

Why sentence frames rather than the phrase dictionary this started as: Urdu
puts the verb last and English puts it in the middle, so replacing words where
they stand yields Urdu vocabulary in English order — "ye function calculate
karta hai the sum" — which is a sentence in neither language. Adding more
words makes it worse, not better. A frame matches a whole English pattern and
emits a whole Urdu sentence, so the order comes from the Urdu side.

Why untranslated lines are returned in English: measured on the corpus, a
frame carries 29.9% of ``Purpose:`` lines and about half the rest are
multi-clause prose no single frame can hold. Half-translated output is harder
to read than English, so a line either translates properly or not at all —
the same choice made for unverifiable optimisations and unanchored comments.
"""

from __future__ import annotations

from app.model_processing.frames import translate_block
from app.model_processing.masking import translate_protecting_code

ROMAN_URDU = "roman_urdu"
ENGLISH = "english"

def is_roman_urdu(output_language: str | None) -> bool:
    """Determine whether a request asks for Roman Urdu output.

    Problem solved: the router only wants to run translation when explicitly
    requested, so this is the single source of truth for that check.

    :param output_language: the client-requested output language (may be None).
    :return: ``True`` when the language is ``roman_urdu`` (case-insensitive).
    """
    return (output_language or ENGLISH).strip().lower() == ROMAN_URDU


def to_roman_urdu(text: str) -> str:
    """Translate English text to Roman Urdu, protecting the code inside it.

    Problem solved: provide an offline Roman Urdu rendering of generated text.

    Why the masking: these explanations are *about* code and therefore contain
    code. ``arr[j]`` is not English and has to survive verbatim, but anything
    that rewrites text will eventually rewrite it, and a comment that no longer
    names the variable it describes is worse than untranslated English. Code
    fragments are hidden before translation and checked back in afterwards; if
    any did not return intact, the English is kept.

    :param text: the English text to translate.
    :return: the Roman Urdu translation, or the input when code did not survive.
    """
    if not text:
        return text

    def frame(masked: str) -> str:
        translated, _matched, _total = translate_block(masked)
        return translated

    return translate_protecting_code(text, frame).text


def coverage(text: str) -> tuple[int, int]:
    """How many of ``text``'s lines a frame could carry.

    Exposed because "translated" and "partly translated" are different things
    to be told, and because this is the number that says when a trained model
    has become worth the corpus it needs.

    :param text: the English text.
    :return: ``(lines translated, lines attempted)``.
    """
    _translated, matched, total = translate_block(text)
    return matched, total


def translate(text: str, output_language: str | None) -> str | None:
    """Translate ``text`` only when Roman Urdu is requested.

    Problem solved: one convenience call used by the router. Why return
    ``None`` for other languages: the response field is nullable and the router
    simply leaves it unset.

    :param text: the English text to translate.
    :param output_language: the requested output language.
    :return: the Roman Urdu string, or ``None`` when translation is not wanted.
    """
    if not is_roman_urdu(output_language):
        return None
    return to_roman_urdu(text)
