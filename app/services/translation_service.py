"""Translation task (Phase 10) — English -> Roman Urdu.

Problem solved: when a client requests Roman Urdu, the generated English text
must be translated. This service owns that single NLP task. The current
implementation is a dictionary/phrase fallback; a trained translation model can
later replace ``to_roman_urdu`` without changing callers.

Why a phrase dictionary (not a full MT model): the generated suggestions use a
small, predictable vocabulary, so a targeted substitution is fast, offline and
good enough until a real model is trained.
"""

from __future__ import annotations

import re

ROMAN_URDU = "roman_urdu"
ENGLISH = "english"

_PHRASES = {
    "this function": "ye function",
    "the function": "ye function",
    "calculates": "calculate karta hai",
    "returns": "return karta hai",
    "recursively": "recursive tareeqe se",
    "the code": "ye code",
    "consider": "ghaur karein",
    "detected": "detect hua hai",
    "found": "mila hai",
    "add": "add karein",
    "comments": "comments",
    "documentation": "documentation",
    "function": "function",
    "loops": "loops",
    "nested": "nested",
    "complexity": "complexity",
    "reduce": "kam karein",
    "split": "todein",
    "into smaller": "chote hisson mein",
}


def is_roman_urdu(output_language: str | None) -> bool:
    """Determine whether a request asks for Roman Urdu output.

    Problem solved: the router only wants to run translation when explicitly
    requested, so this is the single source of truth for that check.

    :param output_language: the client-requested output language (may be None).
    :return: ``True`` when the language is ``roman_urdu`` (case-insensitive).
    """
    return (output_language or ENGLISH).strip().lower() == ROMAN_URDU


def to_roman_urdu(text: str) -> str:
    """Translate English text to Roman Urdu via phrase substitution.

    Problem solved: provide an offline Roman Urdu rendering of generated text.
    Why sort phrases by length (longest first): longer phrases ("into smaller")
    must be matched before their shorter sub-phrases ("smaller") to avoid
    partial, wrong replacements.

    :param text: the English text to translate.
    :return: the best-effort Roman Urdu translation.
    """
    if not text:
        return text

    result = text
    for english, roman in sorted(_PHRASES.items(), key=lambda kv: len(kv[0]), reverse=True):
        result = re.sub(rf"\b{re.escape(english)}\b", roman, result, flags=re.IGNORECASE)
    return result


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
