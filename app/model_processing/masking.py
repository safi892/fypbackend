"""Hide code fragments from a translator, and prove they came back intact.

Problem solved: translating an explanation means handing it to something that
rewrites text, and the text contains identifiers. ``arr[j]`` is not English and
must survive verbatim, but a translator sees a token it does not recognise and
does what it was trained to do — guesses, transliterates, or drops it. Renaming
a variable inside a comment about that variable is the one failure that makes
the translation worse than no translation at all.

So the code fragments are masked out before translation and restored after,
and the restoration is *checked* rather than assumed. Every placeholder must
return present, exactly once, unchanged. That is decidable without a fluent
reader, which matters because Roman Urdu has no standardised spelling and there
is no automatic way to judge whether the prose itself came back right.

This is the same discipline as anchor repair, applied to a different failure:
a mechanically checkable property that catches the mistake that would actually
reach a user, leaving the rest to human judgement rather than pretending to
measure it.

It also improves the output on its own. Masking removes exactly the tokens a
general translation model handles worst, so the check is worth having even if
the translator is never replaced.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

#: Anything that maps one string to another: a dictionary pass, a trained
#: model, a remote service. The masking does not care which.
Translator = Callable[[str], str]

#: Placeholder form. Mathematical white square brackets are used because they
#: survive tokenisers that would split ``<<0>>`` or ``{0}`` into pieces, and
#: because no C++ identifier and no Urdu text contains them - so a placeholder
#: can never collide with the text it is protecting.
_OPEN, _CLOSE = "⟦", "⟧"
_PLACEHOLDER = re.compile(rf"{_OPEN}(\d+){_CLOSE}")

#: What must survive translation untouched, in the order it is searched for.
#: Backticked spans come first: the model emits them around identifiers, and
#: matching the whole span keeps `arr[j] + 1` together rather than protecting
#: three fragments and translating the arithmetic between them.
_PROTECTED = re.compile(
    r"`[^`\n]+`"                       # `arr[j]`, `total`, `std::vector<int>`
    r"|\b[A-Za-z_]\w*\s*\([^()\n]*\)"  # fib(n - 1), push_back(v)
    r"|\b[A-Za-z_]\w*\s*\[[^\[\]\n]*\]"  # arr[j], data[i + 1]
    r"|\b[A-Za-z_]\w*(?:::|->|\.)\w+"  # std::cout, node->next, obj.size
    r"|\b[a-z]+[A-Z]\w*"               # camelCase: sortValues, maxDepth
    r"|\b\w+_\w+\b"                    # snake_case: sorted_list, max_depth
    r"|\bO\([^()\n]*\)"                # O(n log n)
)


@dataclass
class Masked:
    """Text with its code fragments replaced, and the originals to put back."""

    text: str
    spans: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.spans)


@dataclass
class Restoration:
    """The result of putting the fragments back, and whether it was sound."""

    text: str
    ok: bool = True
    reason: str = ""


def mask(text: str) -> Masked:
    """Replace code fragments with numbered placeholders.

    Repeats share a placeholder: a sentence mentioning ``total`` three times
    protects one span and reuses it, which gives the translator less to lose
    track of and makes the integrity check stricter, since a dropped mention is
    still a dropped placeholder.

    :param text: an English comment or explanation.
    :return: the masked text and the spans removed from it.
    """
    spans: list[str] = []
    index: dict[str, int] = {}

    def swap(match: re.Match[str]) -> str:
        span = match.group(0)
        if span not in index:
            index[span] = len(spans)
            spans.append(span)
        return f"{_OPEN}{index[span]}{_CLOSE}"

    return Masked(text=_PROTECTED.sub(swap, text), spans=spans)


def restore(translated: str, masked: Masked) -> Restoration:
    """Put the original fragments back, and refuse the result if they moved.

    Three ways a translator can break this, all seen in practice with general
    models: it drops a placeholder it did not recognise, it duplicates one while
    reordering a clause, or it "translates" the digits inside it. Each leaves
    evidence, and each is a reason to return the English instead.

    :param translated: the translator's output, still containing placeholders.
    :param masked: what :func:`mask` produced for the source text.
    :return: the restored text, and whether it can be trusted.
    """
    found = _PLACEHOLDER.findall(translated)
    numbers = [int(n) for n in found]

    unknown = [n for n in numbers if n >= masked.count]
    if unknown:
        return Restoration(
            text=masked.text,
            ok=False,
            reason=f"translation invented placeholder {unknown[0]}",
        )

    missing = [n for n in range(masked.count) if n not in numbers]
    if missing:
        dropped = masked.spans[missing[0]]
        return Restoration(
            text=masked.text,
            ok=False,
            reason=f"translation dropped {dropped!r}",
        )

    duplicated = [n for n in set(numbers) if numbers.count(n) > 1]
    if duplicated:
        repeated = masked.spans[duplicated[0]]
        return Restoration(
            text=masked.text,
            ok=False,
            reason=f"translation repeated {repeated!r}",
        )

    restored = _PLACEHOLDER.sub(lambda m: masked.spans[int(m.group(1))], translated)
    return Restoration(text=restored)


def translate_protecting_code(text: str, translate: Translator) -> Restoration:
    """Mask, translate, restore, and report whether the code survived.

    The whole point is the last step. ``translate`` may be a dictionary, a
    trained model or a remote service; whichever it is, its output is checked
    against what went in rather than trusted, and a failure returns the English
    rather than a mangled translation.

    :param text: the English comment or explanation.
    :param translate: anything that maps one string to another.
    :return: the translation if the code survived, otherwise the input.
    """
    if not text.strip():
        return Restoration(text=text)

    hidden = mask(text)
    if hidden.count == 0:
        return Restoration(text=translate(hidden.text))

    result = restore(translate(hidden.text), hidden)
    if not result.ok:
        # Returning English is the honest failure. A translation missing the
        # identifier it was about is worse than not translating at all.
        return Restoration(text=text, ok=False, reason=result.reason)
    return result
