"""Forms that constrain which words survive, with no line structure at all.

These are a second mechanism, not more entries in the syllabic table. A haiku
partitions lines by syllable sums; a snowball says nothing about lines and
everything about the words, so the page supplies the layout.

That difference is also what makes them erasure-compatible. A form that
dictates where a word sits cannot be an erasure, because an erasure inherits
the source's layout and may only delete. A mesostic needs its spine stacked at
one x position and no page will supply that by accident; measured on 506 words
of a real page, a strict Cage mesostic with any descent requirement has zero
solutions. These forms ask nothing about position, so they always compose.

Snowball is the one worth reaching for first. Most constraints are invisible
unless announced, and a reader sees this one without being told.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

VOWELS = frozenset("aeiou")
_CLEAN = re.compile(r"[^A-Za-z']")

# A one-letter token is usually a bullet, a chevron or an OCR artifact rather
# than a word, so forms that start at length one say which ones are real.
REAL_SINGLES = frozenset({"a", "i"})


def clean(text: str) -> str:
    return _CLEAN.sub("", text)


@dataclass(frozen=True)
class Shape:
    name: str
    rule: str
    visible: bool
    allows: Callable[[str], bool] = lambda w: True
    follows: Callable[[str, str], bool] | None = None
    starts: Callable[[str], bool] | None = None


def _vowels(word: str) -> frozenset[str]:
    return frozenset(word.lower()) & VOWELS


def snowball() -> Shape:
    return Shape(
        name="snowball", rule="each word one letter longer than the last",
        visible=True,
        allows=lambda w: len(w) > 1 or w.lower() in REAL_SINGLES,
        follows=lambda prev, w: len(w) == len(prev) + 1,
        starts=lambda w: len(w) == 1,
    )


def univocalic(vowel: str) -> Shape:
    v = vowel.lower()
    return Shape(
        name=f"univocalic-{v}", rule=f"every word uses {v!r} and no other vowel",
        visible=False,
        allows=lambda w: _vowels(w) == {v},
    )


def lipogram(letter: str) -> Shape:
    c = letter.lower()
    return Shape(
        name=f"lipogram-{c}", rule=f"no word contains {c!r}",
        visible=False,
        allows=lambda w: c not in w.lower(),
    )


def abecedarian() -> Shape:
    return Shape(
        name="abecedarian", rule="initials advance through the alphabet",
        visible=True,
        allows=lambda w: bool(w),
        follows=lambda prev, w: w[:1].lower() == chr(ord(prev[:1].lower()) + 1),
        starts=lambda w: w[:1].lower() == "a",
    )


def chain() -> Shape:
    return Shape(
        name="chain", rule="each word starts with the last letter of the last",
        visible=False,
        allows=lambda w: bool(w),
        follows=lambda prev, w: w[:1].lower() == prev[-1:].lower(),
    )


def build(spec: str) -> Shape:
    """Parse a shape name, with an argument after a colon where one applies."""
    name, _, arg = spec.partition(":")
    name = name.strip().lower()
    if name == "snowball":
        return snowball()
    if name == "abecedarian":
        return abecedarian()
    if name == "chain":
        return chain()
    if name == "univocalic":
        return univocalic(arg or "a")
    if name == "lipogram":
        return lipogram(arg or "e")
    raise ValueError(f"unknown shape: {spec}")


NAMES = ("snowball", "univocalic", "lipogram", "abecedarian", "chain")


def longest(words, shape: Shape) -> list[int]:
    """The longest surviving subsequence under this shape.

    Longest rather than any, because a short one reads as scattered debris
    rather than as a poem. Below roughly ten words the render stops holding
    together, which is the practical limit on stacking two shapes at once.
    """
    toks = [clean(w.text) for w in words]
    n = len(toks)
    best = [0] * n
    prev = [-1] * n

    for i, t in enumerate(toks):
        if not t or not shape.allows(t):
            continue
        if shape.follows is None:
            best[i] = 1 if not shape.starts or shape.starts(t) else 0
        elif shape.starts is None or shape.starts(t):
            best[i] = 1
        for j in range(i):
            if not best[j]:
                continue
            if shape.follows and not shape.follows(toks[j], t):
                continue
            if best[j] + 1 > best[i]:
                best[i] = best[j] + 1
                prev[i] = j

    if not any(best):
        return []
    end = max(range(n), key=lambda i: best[i])
    out = []
    while end >= 0:
        out.append(end)
        end = prev[end]
    return out[::-1]
