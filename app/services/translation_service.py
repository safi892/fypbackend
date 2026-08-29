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

import re
from collections.abc import Callable, Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.core.config import (
    ROMAN_URDU_MAX_NEW_TOKENS,
    ROMAN_URDU_MODEL_PATH,
    ROMAN_URDU_NUM_BEAMS,
)
from app.model_processing.frames import translate_block
from app.model_processing.masking import translate_protecting_code

ROMAN_URDU = "roman_urdu"
ENGLISH = "english"
PREFIX = "translate English to Roman Urdu: "
_SERVING = re.compile(r"⟦(\d+)⟧")
_SENTINEL = re.compile(r"<extra_id_(\d+)>")
_SERVING_PLACEHOLDER = re.compile(r"⟦\d+⟧")


class _ModelUnavailable(RuntimeError):
    """Raised when Roman Urdu falls back to the frame translator."""


class _Tokenizer(Protocol):
    def __call__(self, text: str, **kwargs: object) -> Mapping[str, object]: ...

    def decode(self, token_ids: object, **kwargs: object) -> str: ...


class _Seq2SeqModel(Protocol):
    def eval(self) -> object: ...

    def generate(self, *args: object, **kwargs: object) -> Sequence[object]: ...


def _to_sentinel(text: str) -> str:
    return _SERVING.sub(lambda match: f"<extra_id_{int(match.group(1))}>", text)


def _to_serving(text: str) -> str:
    return _SENTINEL.sub(lambda match: f"⟦{int(match.group(1))}⟧", text)


def _space_placeholders(text: str) -> str:
    """Keep restored code from sticking to translated words."""
    text = re.sub(rf"(?<=[A-Za-z0-9:;,.])(?={_SERVING_PLACEHOLDER.pattern})", " ", text)
    return re.sub(rf"({_SERVING_PLACEHOLDER.pattern})(?=[A-Za-z])", r"\1 ", text)


def is_roman_urdu(output_language: str | None) -> bool:
    """Determine whether a request asks for Roman Urdu output.

    Problem solved: the router only wants to run translation when explicitly
    requested, so this is the single source of truth for that check.

    :param output_language: the client-requested output language (may be None).
    :return: ``True`` when the language is ``roman_urdu`` (case-insensitive).
    """
    return (output_language or ENGLISH).strip().lower() == ROMAN_URDU


@lru_cache(maxsize=1)
def _load_model() -> tuple[_Tokenizer, _Seq2SeqModel] | None:
    """Load the backend-local Roman Urdu model, if it exists.

    Problem solved: the backend should be self-contained. Why lazy loading:
    most requests ask for English, and loading a 231 MB T5 on startup would
    slow every deployment for an optional response field.

    :return: tokenizer/model pair, or ``None`` when the local model is absent.
    """
    path = Path(ROMAN_URDU_MODEL_PATH)
    if not path.is_dir():
        return None

    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(str(path))
    model = AutoModelForSeq2SeqLM.from_pretrained(str(path))
    model.eval()
    return tokenizer, model


def _translate_line_with_model(tokenizer: _Tokenizer, model: _Seq2SeqModel, line: str) -> str:
    """Translate one masked line with the T5 model."""
    import torch

    encoded = tokenizer(PREFIX + _to_sentinel(line), return_tensors="pt", truncation=True)
    with torch.no_grad():
        output = model.generate(
            **encoded,
            max_new_tokens=ROMAN_URDU_MAX_NEW_TOKENS,
            num_beams=ROMAN_URDU_NUM_BEAMS,
        )
    raw = tokenizer.decode(output[0], skip_special_tokens=False)
    for token in ("<pad>", "</s>"):
        raw = raw.replace(token, "")
    return _space_placeholders(_to_serving(raw.strip()))


def _translate_with_model(text: str) -> str | None:
    """Translate text with the trained model, preserving line boundaries."""
    loaded = _load_model()
    if loaded is None:
        return None
    tokenizer, model = loaded
    return "\n".join(
        _translate_line_with_model(tokenizer, model, line) if line.strip() else line
        for line in text.splitlines()
    )


def _translate_lines_protecting_code(text: str, translate: Callable[[str], str]) -> str:
    """Translate each line separately so one unsafe line cannot poison a block."""
    pieces = []
    for segment in text.splitlines(keepends=True):
        body = segment.rstrip("\r\n")
        line_ending = segment[len(body):]
        if not body.strip():
            pieces.append(segment)
            continue
        pieces.append(translate_protecting_code(body, translate).text + line_ending)
    return "".join(pieces)


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

    try:
        def model_translate(masked: str) -> str:
            translated = _translate_with_model(masked)
            if translated is None:
                raise _ModelUnavailable
            return translated

        return _translate_lines_protecting_code(text, model_translate)
    except _ModelUnavailable:
        pass
    except Exception:
        pass

    def frame(masked: str) -> str:
        translated, _matched, _total = translate_block(masked)
        return translated

    return _translate_lines_protecting_code(text, frame)


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
