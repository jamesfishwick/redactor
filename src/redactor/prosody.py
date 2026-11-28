"""Syllable counting for form constraints.

CMU gives phoneme-derived counts, which is what a metrical form needs. A
hyphenator answers a different question (where a line may break) and is wrong
often enough to matter: it reports "about" and "ago" as one syllable.
"""

from __future__ import annotations

import re
from functools import cache

import pronouncing

_WORD = re.compile(r"[^a-zA-Z']")


def normalize(word: str) -> str:
    return _WORD.sub("", word).lower()


# Initialisms an ordinary word is spelled the same as. CMU reads most
# initialisms correctly on its own, because it holds them under their own
# entries: FBI is three syllables there, HTML four, URL three. It only fails
# where a word collides with one, and then it answers for the word. `ai` is
# the sloth, one syllable, so a line ending "help you" scanned as ten when a
# reader says eleven.
#
# Listed here is the arbitrary part, which is that these are read letter by
# letter at all. How long that takes is still counted from the letters, so
# nothing here has to be revised if one of them grows.
SPELLED = frozenset({"AI"})


@cache
def syllables(word: str) -> int:
    """Syllable count, or a vowel-group estimate for words CMU doesn't know."""
    letters = _WORD.sub("", word)
    # Capitalisation is the evidence, so lowercase `ai` stays the animal.
    if len(letters) > 1 and letters in SPELLED:
        return sum(syllables(c) for c in letters)
    w = normalize(word)
    if not w:
        return 0
    phones = pronouncing.phones_for_word(w)
    if phones:
        return pronouncing.syllable_count(phones[0])
    return max(1, len(re.findall(r"[aeiouy]+", w)))


@cache
def stress(word: str) -> str | None:
    """CMU stress digits. Monosyllables return '?' because meter decides them."""
    w = normalize(word)
    phones = pronouncing.phones_for_word(w)
    if not phones:
        return None
    s = pronouncing.stresses(phones[0])
    return "?" if len(s) == 1 else s.replace("2", "?")


@cache
def rhyme_part(word: str) -> str | None:
    """What a word rhymes on: everything from its last stressed vowel.

    Exact equality is the test, so `home` and `roam` agree on OW1 M while
    `rations` and `nations` do not, their stressed vowels differing.
    """
    w = normalize(word)
    phones = pronouncing.phones_for_word(w)
    return pronouncing.rhyming_part(phones[0]) if phones else None


def rhyme_classes(words, least: int = 3) -> dict[str, set[str]]:
    """Rhyme classes on this page, keyed by part, with their distinct words.

    Function words are dropped first. The largest classes on any English page
    are `the`, `to`, `and` and `a`, and a couplet closing on `the` and `the`
    rhymes with itself rather than rhyming.
    """
    found: dict[str, set[str]] = {}
    for w in words:
        text = normalize(getattr(w, "text", w))
        if not text or text in FUNCTION_WORDS:
            continue
        part = rhyme_part(text)
        if part:
            found.setdefault(part, set()).add(text)
    return {k: v for k, v in found.items() if len(v) >= least}


FORMS: dict[str, tuple[int, ...]] = {
    "haiku": (5, 7, 5),
    "tanka": (5, 7, 5, 7, 7),
    "lune": (5, 3, 5),
    "cinquain": (2, 4, 6, 8, 2),
    "fib": (1, 1, 2, 3, 5, 8),
    "pentameter": (10,),
    "tetrameter": (8,),
    "ballad": (8, 6, 8, 6),
    "couplet": (10, 10),
    "quatrain": (8, 6, 8, 6),
}

# Which lines have to rhyme with which. A letter repeated is a rhyme, a dot
# is a line free to end anywhere. The hardest thing the ladder can ask for,
# since it constrains syllables, stress and the last word all at once.
SCHEMES: dict[str, str] = {
    "couplet": "AA",
    "quatrain": ".A.A",
}

# A syllable count is not a meter. These forms additionally require the line's
# stresses to match a pattern, which is checked after a line is assembled
# because stress depends on the whole line, not on each word in isolation.
METERS: dict[str, str] = {
    "pentameter": "0101010101",
    "tetrameter": "01010101",
    "ballad": "01010101/010101/01010101/010101",
    "couplet": "0101010101/0101010101",
    "quatrain": "01010101/010101/01010101/010101",
}


# Used to measure lexical density, never to assign stress. Marking these
# unstressed rejects "Shall I compare thee to a summer's day", because English
# stress is positional and `to`, `a` and `be` take it depending on where they
# fall. Counting them is safe; scanning with them is not.
FUNCTION_WORDS = frozenset(["a", "an", "the", "this", "that", "these", "those", "my", "your", "his", "her", "its", "our", "their", "of", "to", "in", "on", "at", "by", "for", "from", "with", "into", "onto", "upon", "as", "than", "and", "or", "but", "nor", "so", "yet", "if", "though", "is", "are", "was", "were", "be", "been", "am", "do", "does", "did", "has", "have", "had", "will", "would", "shall", "should", "may", "might", "must", "can", "could", "i", "you", "he", "she", "it", "we", "they", "me", "him", "them", "us"])


@cache
def _parser():
    """prosodic, if it is installed. Imported late: it pulls in pandas."""
    import contextlib
    import io

    # It prints thirty lines about installing espeak the moment it loads.
    # Nothing here reaches the path that wants espeak, so the notice is only
    # noise in front of a poem.
    try:
        with contextlib.redirect_stderr(io.StringIO()), \
                contextlib.redirect_stdout(io.StringIO()):
            import prosodic
    except ImportError:
        return None
    return prosodic


def violations(words: list[str]) -> float | None:
    """How badly a line breaks the metre, by Optimality Theory, or None.

    Scansion is a solved problem and `prosodic` solves it, parsing a line
    against the constraints metrists actually argue about rather than
    matching a string of stress digits. `scans` cannot tell a line of ten
    content monosyllables from iambic pentameter, because CMU gives a
    monosyllable no stress and every position becomes a wildcard. Asked the
    same two lines, this returns 0 for "When I do count the clock that tells
    the time" and 5 for "cat dog bird hawk fish owl wren finch crow jay".

    A hand-rolled rule was tried first and measured before it was believed.
    Marking every content monosyllable stressed rejected 87% of the lines
    this page already accepts, "an ugly question in your own way" among them,
    because English demotes stress in a clash and that is a property of the
    line rather than of any word in it. Which is the argument for the
    library.

    prosodic wants espeak for a word CMU does not know, and nothing here
    installs it. That path is unreachable from where this is called: `scans`
    already refuses a line holding a word CMU cannot pronounce, so every line
    that gets this far is covered. The guard stays anyway, since an exception
    here should cost a candidate rather than the run.
    """
    parser = _parser()
    if parser is None:
        return None
    try:
        return float(parser.Text(" ".join(words)).parse().best[0].score)
    except Exception:  # noqa: BLE001 - any parse failure is one lost candidate
        return None


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
    if not all(b == "?" or b == p for b, p in zip(built, pattern, strict=False)):
        return False
    fixed = len(built) - built.count("?")
    return fixed >= min_fixed or content_words(words) >= min_content
