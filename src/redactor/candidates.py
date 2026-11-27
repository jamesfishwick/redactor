"""Enumerate every erasure of a source that satisfies a form.

An erasure may only delete, so every candidate is a subsequence of the source
in its original order. On its own that is far too permissive: a 43-word
paragraph holds about 1.6e10 valid haiku, essentially all of them word salad.

Three constraints cut it to something a reader can be shown, measured on the
opening of Moby-Dick:

    none                      15,829,992,033
    POS bigram                 6,858,150,007
    POS trigram                   75,156,809
    contiguity <= 3 runs              89,813
    contiguity <= 2 runs               1,643
    contiguity <= 2 + trigram            102

Contiguity does nearly all the work, and for a reason worth keeping in mind:
the source is already grammatical, so preserving its spans inherits its syntax
outright. Part-of-speech transitions only check tag pairs, which is a far
weaker proxy for the same thing.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from .prosody import METERS, scans, syllables


@dataclass(frozen=True)
class Candidate:
    lines: tuple[tuple[int, ...], ...]   # word indices, per line
    runs: int

    def indices(self) -> list[int]:
        return [i for line in self.lines for i in line]

    def render(self, words) -> str:
        return "\n".join(" ".join(words[i].text for i in line) for line in self.lines)


class Enumerator:
    """Walks the source once per form, pruning as it goes.

    `max_runs` counts contiguous spans across the whole poem rather than per
    line, because a phrase that wraps still reads as one run.

    A span must be adjacent in reading order *and* on the same line of the
    page. Those are not the same thing: OCR order walks a column, then jumps to
    a nav bar, a sidebar and a footer, so two words next to each other in the
    stream can sit a thousand pixels apart. Counting only reading order made
    the enumerator believe a candidate had two unbroken spans when the page
    showed five scattered chips, and contiguity is the one constraint carrying
    grammar here. A short screenshot hides this, since one column of prose has
    reading order and visual order mostly agreeing.
    """

    def __init__(self, words, form, max_runs: int = 2, pos_tags=None,
                 allowed_trigrams=None, limit: int = 5000, meter: str | None = None):
        self.w = words
        self.form = tuple(form)
        # Stress is a property of the assembled line, so it filters results
        # rather than pruning the walk.
        self.meter = tuple(meter.split("/")) if meter else None
        self.max_runs = max_runs
        self.pos = pos_tags
        self.tri = allowed_trigrams
        self.limit = limit
        self.syl = [syllables(x.text) for x in words]
        # Where a line of the page ends, so a run cannot silently cross it.
        self.line = [getattr(x, "line", "") for x in words]

    def _joins(self, prev_i: int, i: int) -> bool:
        """Does keeping word i extend the run that ended at prev_i?"""
        return prev_i == i - 1 and self.line[prev_i] == self.line[i]

    def _pos_ok(self, p1, p2, i) -> bool:
        if not self.tri or self.pos is None:
            return True
        if p1 is None or p2 is None:
            return True
        return (p1, p2, self.pos[i]) in self.tri

    def count(self) -> int:
        n, form, syl = len(self.w), self.form, self.syl

        @lru_cache(maxsize=None)
        def walk(i, line, used, p1, p2, runs, prev):
            if line == len(form):
                return 1 if used == 0 else 0
            if used == form[line]:
                return walk(i, line + 1, 0, p1, p2, runs, prev)
            if i == n:
                return 0
            total = walk(i + 1, line, used, p1, p2, runs, -1)
            s = syl[i]
            nr = runs + (0 if (prev >= 0 and self._joins(prev, i)) else 1)
            if used + s <= form[line] and nr <= self.max_runs and self._pos_ok(p1, p2, i):
                nxt = self.pos[i] if self.pos else None
                total += walk(i + 1, line, used + s, p2, nxt, nr, i)
            return total

        return walk(0, 0, 0, None, None, 0, -1)

    def all(self) -> list[Candidate]:
        n, form, syl = len(self.w), self.form, self.syl
        found: list[Candidate] = []

        def walk(i, line, used, p1, p2, runs, prev, acc):
            if len(found) >= self.limit:
                return
            if line == len(form):
                if used == 0:
                    found.append(Candidate(tuple(tuple(x) for x in acc), runs))
                return
            if used == form[line]:
                last = line + 1 == len(form)
                if not last:
                    acc.append([])
                walk(i, line + 1, 0, p1, p2, runs, prev, acc)
                if not last:
                    acc.pop()
                return
            if i == n:
                return
            walk(i + 1, line, used, p1, p2, runs, -1, acc)
            s = syl[i]
            nr = runs + (0 if (prev >= 0 and self._joins(prev, i)) else 1)
            if used + s <= form[line] and nr <= self.max_runs and self._pos_ok(p1, p2, i):
                nxt = self.pos[i] if self.pos else None
                acc[line].append(i)
                walk(i + 1, line, used + s, p2, nxt, nr, i, acc)
                acc[line].pop()

        walk(0, 0, 0, None, None, 0, -1, [[]])
        if self.meter:
            found = [c for c in found if self._scans(c)]
        return found

    def _scans(self, candidate) -> bool:
        if len(candidate.lines) != len(self.meter):
            return False
        return all(
            scans([self.w[i].text for i in line], pattern)
            for line, pattern in zip(candidate.lines, self.meter)
        )


def is_subsequence(poem_words, source_words) -> bool:
    """The one invariant an erasure must satisfy: delete only, never reorder."""
    it = iter(source_words)
    return all(w in it for w in poem_words)
