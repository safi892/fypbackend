"""Translate whole sentence patterns, because word-by-word cannot work.

Problem solved: Urdu puts the verb last and English puts it in the middle, so
substituting words in place produces Urdu vocabulary in English order — "ye
function calculate karta hai the sum" — which is not a sentence in either
language. A larger dictionary makes that worse, not better, because it replaces
more words while leaving the order alone.

Whole frames avoid the problem entirely. A frame matches an English sentence
pattern and emits a complete Urdu sentence, so the word order is decided by the
Urdu template rather than inherited from the English.

This is only affordable because the text is templated. Measured over the 18,942
explanations in the training corpus: 68.2% of sentences open with one of four
section labels, and within ``Purpose:`` lines the ten most common opening verbs
cover 60.3% of them, the top 25 cover 77.7%.

What happens when no frame matches: the English sentence is kept, untouched.
That is the same choice made everywhere else here — an unverifiable
optimisation returns the user's own code, an unanchored comment is dropped —
and it is much better than emitting a half-translated sentence the reader has
to decode.

The Roman Urdu here follows how developers in Pakistan actually speak, keeping
technical nouns in English ("function", "array", "pointer", "return"). It
needs review by a native speaker before it ships; the structure is right, the
phrasing is a first draft.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Section labels. `Input` and `Output` stay as they are: developers say them
#: in English, and translating them would be less natural rather than more.
LABELS = {
    "purpose": "Maqsad",
    "algorithm": "Tareeqa",
    "complexity": "Complexity",
    "input": "Input",
    "output": "Output",
    "note": "Note",
    "edge case": "Edge case",
    "edge cases": "Edge cases",
}

#: (English pattern, Roman Urdu template). Ordered: the first match wins, so
#: more specific patterns are listed before the general ones they would
#: otherwise be swallowed by. `{0}`, `{1}` carry matched groups across.
#:
#: Every verb here is among the most frequent openings measured in the corpus.
FRAMES: list[tuple[re.Pattern[str], str]] = [
    # --- whether/if questions, which take a different shape in Urdu --------------
    (re.compile(r"^(?:determines?|checks?|tests?)\s+(?:whether|if)\s+(.+)$", re.I),
     "Ye check karta hai ke {0}"),
    (re.compile(
        r"^returns?\s+true\s+(?:if|when)\s+(.+?)"
        r"(?:,\s*(?:and\s+)?false\s+otherwise)?$", re.I),
     "Agar {0} to true return karta hai, warna false"),

    # --- the common action verbs -------------------------------------------------
    (re.compile(r"^(?:computes?|calculates?)\s+(.+)$", re.I), "Ye {0} nikalta hai"),
    (re.compile(r"^counts?\s+(?:how many\s+)?(.+)$", re.I), "Ye ginta hai ke {0}"),
    (re.compile(r"^(?:finds?|locates?|searches? for)\s+(.+)$", re.I), "Ye {0} dhoondta hai"),
    (re.compile(r"^sorts?\s+(.+)$", re.I), "Ye {0} ko sort karta hai"),
    (re.compile(r"^reverses?\s+(.+)$", re.I), "Ye {0} ko ulta karta hai"),
    (re.compile(r"^prints?\s+(?:out\s+)?(.+)$", re.I), "Ye {0} print karta hai"),
    (re.compile(r"^removes?\s+(.+)$", re.I), "Ye {0} hata deta hai"),
    (re.compile(r"^adds?\s+(.+)$", re.I), "Ye {0} add karta hai"),
    (re.compile(r"^converts?\s+(.+?)\s+(?:to|into)\s+(.+)$", re.I),
     "Ye {0} ko {1} mein convert karta hai"),
    (re.compile(r"^(?:swaps?|exchanges?)\s+(.+)$", re.I), "Ye {0} ko swap karta hai"),
    (re.compile(r"^(?:merges?|combines?)\s+(.+)$", re.I), "Ye {0} ko merge karta hai"),
    (re.compile(r"^inserts?\s+(.+)$", re.I), "Ye {0} insert karta hai"),
    (re.compile(r"^updates?\s+(.+)$", re.I), "Ye {0} update karta hai"),
    (re.compile(r"^returns?\s+(.+)$", re.I), "Ye {0} return karta hai"),

    # --- "This function ..." openings, folded onto the same verbs -----------------
    (re.compile(r"^this\s+(?:function|method|code)\s+(.+)$", re.I), "Ye function {0}"),
    (re.compile(r"^the\s+function\s+(.+)$", re.I), "Ye function {0}"),
]


@dataclass
class Translation:
    """A translated sentence, and whether a frame was actually found for it."""

    text: str
    matched: bool = False


#: A frame wraps one clause. Applied to several, it moves the verb to the end
#: of the whole thing and strands the rest: "Computes the sum, then divides by
#: 10" became "Ye the sum, then divides by 10 nikalta hai", which is worse than
#: leaving it in English. Sentences with a second clause are left alone.
_MULTI_CLAUSE = re.compile(
    r",\s*(?:then|and|but|which|while|before|after|so)\b|;|\bthen\b.*\band\b", re.I
)

#: Beyond this a sentence is prose rather than a pattern, whatever its shape.
_MAX_FRAME_WORDS = 14


#: Placeholders left by the masking pass, which must survive framing too.
_PLACEHOLDER = re.compile(r"⟦\d+⟧")


def is_framable(body: str) -> bool:
    """Whether one frame can carry this sentence without mangling it."""
    return not _MULTI_CLAUSE.search(body) and len(body.split()) <= _MAX_FRAME_WORDS


def _keeps_everything(before: str, after: str) -> bool:
    """Whether framing preserved every masked fragment it was handed."""
    return sorted(_PLACEHOLDER.findall(before)) == sorted(_PLACEHOLDER.findall(after))


def translate_sentence(sentence: str) -> Translation:
    """Translate one sentence if a frame fits it, otherwise hand it back.

    :param sentence: one English sentence, already stripped of its label.
    :return: the Roman Urdu rendering, and whether a frame matched.
    """
    stripped = sentence.strip()
    if not stripped:
        return Translation(text=sentence)

    trailing = "." if stripped.endswith(".") else ""
    body = stripped.rstrip(".").strip()

    if not is_framable(body):
        return Translation(text=sentence)

    for pattern, template in FRAMES:
        match = pattern.match(body)
        if not match:
            continue
        filled = template.format(*[g or "" for g in match.groups()])
        # A frame that captures less than it matched silently deletes the rest
        # of the sentence. Measured on the corpus, this cost 28% of
        # explanations their code fragments before it was caught - the
        # "returns true if X, false otherwise" frame dropped the trailing
        # clause and everything in it. Any placeholder that went in must come
        # out, or the frame is not used.
        if _keeps_everything(body, filled):
            return Translation(text=filled + trailing, matched=True)

    return Translation(text=sentence)


def split_label(line: str) -> tuple[str | None, str]:
    """Separate a ``Purpose: ...`` style label from the sentence after it."""
    match = re.match(r"^\s*([A-Za-z][A-Za-z ]{2,12})\s*:\s*(.*)$", line, re.S)
    if not match:
        return None, line
    label = match.group(1).strip().lower()
    return (label, match.group(2)) if label in LABELS else (None, line)


def translate_block(text: str) -> tuple[str, int, int]:
    """Translate an explanation line by line, keeping what does not fit.

    Coverage is returned rather than hidden, because a reader is owed the
    difference between "translated" and "partly translated", and because it is
    the number that says whether a trained model is needed yet.

    :param text: an English explanation, possibly several labelled lines.
    :return: ``(translated, matched, total)`` over translatable sentences.
    """
    out: list[str] = []
    matched = total = 0

    for line in text.split("\n"):
        if not line.strip():
            out.append(line)
            continue

        label, body = split_label(line)
        total += 1
        result = translate_sentence(body)
        matched += result.matched
        out.append(f"{LABELS[label]}: {result.text}" if label else result.text)

    return "\n".join(out), matched, total
