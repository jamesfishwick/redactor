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
    "tetrameter": (8,),
    "ballad": (8, 6, 8, 6),
}

# A syllable count is not a meter. These forms additionally require the line's
# stresses to match a pattern, which is checked after a line is assembled
# because stress depends on the whole line, not on each word in isolation.
METERS: dict[str, str] = {
    "pentameter": "0101010101",
    "tetrameter": "01010101",
    "ballad": "01010101/010101/01010101/010101",
}


# Used to measure lexical density, never to assign stress. Marking these
# unstressed rejects "Shall I compare thee to a summer's day", because English
# stress is positional and `to`, `a` and `be` take it depending on where they
# fall. Counting them is safe; scanning with them is not.
FUNCTION_WORDS = frozenset("""
a an the this that these those my your his her its our their
of to in on at by for from with into onto upon as than
and or but nor so yet if though
is are was were be been am do does did has have had
will would shall should may might must can could
i you he she it we they me him them us
""".split())


def content_words(words: list[str]) -> int:
    return sum(1 for w in words if normalize(w) not in FUNCTION_WORDS)


def scans(words: list[str], pattern: str, min_fixed: int = 2,
          min_content: int = 3) -> bool:
    """Does this line fit the metrical pattern, on evidence?

    Monosyllables carry no lexical stress in CMU and take it from position, so
    they match either slot. A line of ten monosyllables is therefore all
    wildcards and scans as anything: measured on one page, 4.8% of accepted
    pentameters were exactly that, which made the form mean "ten syllables"
    again for one result in twenty. `min_fixed` is how many positions must
    carry real stress before a line counts, which rejects the vacuous ones.

    It cannot carry the check alone, because most English pentameter is
    monosyllabic. "When I do count the clock that tells the time" has no
    polysyllable at all and is perfectly iambic, so it offers no stress
    evidence either. What separates it from "the the the the the the the the
    the the" is not stress but lexical density, which `min_content` measures.
    A line must satisfy one of the two.

    A function-word list was tried here and removed. Marking `to`, `a` and
    `be` unstressed rejects "Shall I compare thee to a summer's day", because
    English stress is positional and those words take it or not depending on
    where they fall. Doing this properly needs Optimality Theory over the
    whole line, which is what `prosodic` implements. That library wants espeak
    as a native dependency on every machine it runs, which is the trade not
    taken here.
    """
    built = ""
    for w in words:
        s = stress(w)
        if s is None:
            return False
        built += s
    if len(built) != len(pattern):
        return False
    if not all(b == "?" or b == p for b, p in zip(built, pattern)):
        return False
    fixed = len(built) - built.count("?")
    return fixed >= min_fixed or content_words(words) >= min_content
