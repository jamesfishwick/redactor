"""Enumerate every erasure of a source that satisfies a form.

An erasure may only delete, so every candidate is a subsequence of the source
in its original order. On its own that is far too permissive: a 43-word
paragraph holds about 1.6e10 valid haiku, essentially all of them word salad.

Two constraints cut that to a set a reader can be shown, contiguity and a
part-of-speech trigram filter. The counts live in README.md and are produced
by scripts/measure.py, not copied here, because the copy that used to sit in
this docstring was four orders of magnitude out and nothing could tell.

Contiguity does the work worth having, for a reason that outlasts any count:
the source is already grammatical, so preserving its spans inherits its syntax
outright. Part-of-speech transitions only check tag triples, a weaker proxy
for the same thing, and one whose strength depends on how much text the
triples were learned from.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from .prosody import METERS, rhyme_part, scans, stress, syllables


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

    # One recursion frame per word, so the cap has to sit under Python's own
    # limit of 1000. Capped rather than raising that limit, which trades a
    # clean error for a deeper C stack and would have to be raised for the
    # whole process to serve one caller. `Space` has no such ceiling and is
    # what the agent uses; this walk remains for comparing against it.
    MAX_WORDS = 800

    def __init__(self, words, form, max_runs: int = 2, pos_tags=None,
                 allowed_trigrams=None, limit: int = 5000, meter: str | None = None):
        if len(words) > self.MAX_WORDS:
            words = words[:self.MAX_WORDS]
            if pos_tags is not None:
                pos_tags = pos_tags[:self.MAX_WORDS]
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


class Space:
    """The whole candidate space of one page, counted bottom-up and sampled.

    Two things the recursive walk could not do. It recursed once per word, so
    a 7,487-word article overflowed the stack and the page had to be truncated
    to 600 words; and enumerating "the first N" returns N poems from one region
    of the page rather than a sample of the space. Both matter, because a short
    form drawn from a large page is only good if the choice is wide: that page
    admits 182,040 ballads in its first 600 words and millions across all of it.

    `prev` collapses to a boolean. A run continues only when the previous word
    was kept *and* was the immediately preceding one, so the table needs to know
    whether word i-1 survived, not which word it was.
    """

    # Table size is words x lines x syllables x runs x 2. Chapter 1 of the
    # Copyright Act is 72,731 words in one page, which is roughly 20 million
    # cells before a single sample is drawn, and each sample then walks every
    # word. A cap is a real limit on what a page can be, so it is set where
    # choice stops mattering rather than where memory runs out: 15,000 words
    # already admit erasures in the hundreds of millions.
    MAX_WORDS = 15000

    def __init__(self, words, form, max_runs: int = 2, meter: str | None = None,
                 scheme: str | None = None, parts: dict | None = None):
        if len(words) > self.MAX_WORDS:
            words = words[:self.MAX_WORDS]
        self.w = words
        self.form = tuple(form)
        self.max_runs = max_runs
        self.syl = [syllables(x.text) for x in words]
        self.line = [getattr(x, "line", "") for x in words]
        # Stress is checked as each word is placed rather than after a line
        # exists, which is what made metered forms expensive: fewer than one
        # draw in five hundred scanned, so sixty usable poems cost thirty
        # thousand draws and each one walked the whole page.
        #
        # No extra state is needed for it. `used` is the count of syllables
        # already in the line, so it is also the offset into the line's
        # pattern, and a word's own stress has to match the slice starting
        # there. A word CMU does not know contributes wildcards.
        # Rhyme is a constraint on the last word of a line, so the state does
        # not grow for it: the class each line must end on is fixed before the
        # table is built, and checked when a line completes. Enumerating one
        # table per candidate class is what makes that affordable.
        self.scheme = scheme
        self.parts = parts or {}
        if scheme:
            self.ends = [rhyme_part(w.text) for w in words]
        self.pattern = tuple(meter.split("/")) if meter else None
        if self.pattern:
            self.stress = []
            for word, n in zip(words, self.syl):
                st = stress(word.text)
                self.stress.append(st if st and len(st) == n else "?" * n)
        self._table = None

    def _closes(self, i, l, u, s) -> bool:
        """May word i end line l, given what that line has to rhyme with?"""
        if not self.scheme or u + s != self.form[l]:
            return True
        letter = self.scheme[l] if l < len(self.scheme) else "."
        if letter == ".":
            return True
        want = self.parts.get(letter)
        return want is not None and self.ends[i] == want

    def _fits(self, i, l, u) -> bool:
        """Does word i's stress match the pattern at this offset?"""
        if self.pattern is None:
            return True
        pat = self.pattern[l]
        st = self.stress[i]
        if u + len(st) > len(pat):
            return False
        return all(a == "?" or a == b for a, b in zip(st, pat[u:u + len(st)]))

    def _idx(self, i, l, u, r, p):
        return ((((i * (len(self.form) + 1) + l) * self._U + u)
                 * self._R + r) * 2 + p)

    def _build(self):
        """One flat list, filled from the last word backwards.

        Nested lists cost an object header per cell, which a page of this size
        cannot afford. Walking i downwards works because a cell only ever reads
        cells at i+1.
        """
        n, form, syl, line = len(self.w), self.form, self.syl, self.line
        L = len(form)
        self._U = U = max(form) + 1
        self._R = R = self.max_runs + 1
        table = [0] * ((n + 1) * (L + 1) * U * R * 2)

        for i in range(n, -1, -1):
            for l in range(L, -1, -1):
                for u in range(U - 1, -1, -1):
                    for r in range(R):
                        for p in (0, 1):
                            at = self._idx(i, l, u, r, p)
                            if l == L:
                                table[at] = 1 if u == 0 else 0
                                continue
                            if u == form[l]:
                                table[at] = table[self._idx(i, l + 1, 0, r, p)]
                                continue
                            if i == n:
                                table[at] = 0
                                continue
                            total = table[self._idx(i + 1, l, u, r, 0)]
                            s = syl[i]
                            joins = p == 1 and i > 0 and line[i - 1] == line[i]
                            nr = r + (0 if joins else 1)
                            if (u + s <= form[l] and nr <= self.max_runs
                                    and self._fits(i, l, u)
                                    and self._closes(i, l, u, s)):
                                total += table[self._idx(i + 1, l, u + s, nr, 1)]
                            table[at] = total
        self._table = table

    def count(self) -> int:
        if self._table is None:
            self._build()
        return self._table[self._idx(0, 0, 0, 0, 0)]

    def sample(self, k: int, rng=None) -> list[Candidate]:
        """Draw k poems uniformly at random from the whole space.

        Uniform because each branch is taken in proportion to how many whole
        poems lie down it, which is what the table already holds. Without this
        a ranker sees only whichever corner of the page the walk reached first.
        """
        import random
        rng = rng or random.Random()
        if self._table is None:
            self._build()
        if not self.count():
            return []
        n, form, syl, line = len(self.w), self.form, self.syl, self.line
        t, out = self._table, []
        for _ in range(k):
            i, l, u, r, p = 0, 0, 0, 0, 0
            lines, cur = [], []
            while l < len(form):
                if u == form[l]:
                    lines.append(tuple(cur)); cur = []
                    l, u = l + 1, 0
                    continue
                skip = t[self._idx(i + 1, l, u, r, 0)] if i < n else 0
                s = syl[i] if i < n else 0
                joins = p == 1 and i > 0 and line[i - 1] == line[i]
                nr = r + (0 if joins else 1)
                keep = (t[self._idx(i + 1, l, u + s, nr, 1)]
                        if (i < n and u + s <= form[l] and nr <= self.max_runs
                            and self._fits(i, l, u)
                            and self._closes(i, l, u, s)) else 0)
                if keep and rng.random() < keep / (keep + skip):
                    cur.append(i); u += s; r, p = nr, 1
                else:
                    p = 0
                i += 1
            out.append(Candidate(tuple(lines), r))
        return out


def is_subsequence(poem_words, source_words) -> bool:
    """The one invariant an erasure must satisfy: delete only, never reorder."""
    it = iter(source_words)
    return all(w in it for w in poem_words)
