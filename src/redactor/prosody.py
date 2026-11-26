"""Syllable counting for form constraints.

CMU gives phoneme-derived counts, which is what a metrical form needs. A
hyphenator answers a different question (where a line may break) and is wrong
often enough to matter: it reports "about" and "ago" as one syllable.
"""

from __future__ import annotations

import re
from functools import lru_cache

import pronouncing

_WORD = re.compile(r"[^a-zA-Z']")


def normalize(word: str) -> str:
    return _WORD.sub("", word).lower()


@lru_cache(maxsize=None)
def syllables(word: str) -> int:
    """Syllable count, or a vowel-group estimate for words CMU doesn't know."""
    w = normalize(word)
    if not w:
        return 0
    phones = pronouncing.phones_for_word(w)
    if phones:
        return pronouncing.syllable_count(phones[0])
    return max(1, len(re.findall(r"[aeiouy]+", w)))


@lru_cache(maxsize=None)
def stress(word: str) -> str | None:
    """CMU stress digits. Monosyllables return '?' because meter decides them."""
    w = normalize(word)
    phones = pronouncing.phones_for_word(w)
    if not phones:
        return None
    s = pronouncing.stresses(phones[0])
    return "?" if len(s) == 1 else s.replace("2", "?")


FORMS: dict[str, tuple[int, ...]] = {
    "haiku": (5, 7, 5),
    "tanka": (5, 7, 5, 7, 7),
    "lune": (5, 3, 5),
    "cinquain": (2, 4, 6, 8, 2),
    "fib": (1, 1, 2, 3, 5, 8),
    "pentameter": (10,),
}
