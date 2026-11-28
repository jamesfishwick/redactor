"""Try the hardest form a page can satisfy, and say which rung it reached.

Difficulty is measured, not asserted: it is how rarely a page admits the form
at all. On 260 words of one page, out of the erasures that fit each shape by
syllable count, these fractions also scan:

    ballad          0.01%        9 of 118,302
    pentameter     12.54%   16,297 of 129,965
    tetrameter     20.34%   20,533 of 100,928
    haiku         100%     (no stress requirement to fail)

The ordering is worth more than a difficulty badge. A tight metrical form can
only be satisfied by long contiguous spans, so its output inherits the source's
grammar wholesale and reads better than a loose form's. Harder is not a
trade against sense here; it buys sense.

Word-level shapes sit at the bottom. A snowball is legible as a rule and
almost never as a sentence, which makes it a last resort rather than a goal.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .candidates import Enumerator, Space
from .prosody import (FORMS, METERS, SCHEMES, normalize,
                      rhyme_classes, scans)

# hardest first
RUNGS: tuple[str, ...] = (
    "quatrain", "couplet", "ballad", "pentameter", "tetrameter",
    "fib", "cinquain", "tanka", "lune", "haiku",
)

FALLBACK_SHAPES: tuple[str, ...] = ("snowball", "abecedarian", "univocalic:a")


def _distinct(candidate, words, scheme: str) -> bool:
    """Do the lines sharing a scheme letter end on different words?

    A word rhymes with itself, so the table cannot tell `know` from `know`,
    and a couplet closing twice on the same word turns out to be the most
    common poem in the space. Identity is a property of the finished poem
    rather than of any one line, so it filters the sample the way the stress
    evidence check does. The pool reported alongside the survivors is the
    table's own count and so includes the poems this rejects.
    """
    seen: dict[str, set[str]] = {}
    for letter, line in zip(scheme, candidate.lines):
        if letter == "." or not line:
            continue
        word = normalize(words[line[-1]].text)
        if word in seen.setdefault(letter, set()):
            return False
        seen[letter].add(word)
    return True


@dataclass
class Rung:
    form: str
    metered: bool
    pool: int
    candidates: list


def climb(words, *, max_runs=2, want=1, sample=60, max_draws=40000,
          rhyme_tries: int = 25, budget_s: float = 90.0,
          rng=None) -> Rung | None:
    """Return the hardest form this page admits, with candidates to choose from.

    The candidates are drawn uniformly from the whole space rather than taken
    from the front of an enumeration. A short form is only good when the choice
    behind it is wide, and one page measured here admits 182,040 ballads in its
    first 600 words alone; handing a ranker the first sixty of those gives it
    sixty poems from one corner of the page.

    `budget_s` bounds each rung in wall-clock, because this runs on a Sprite
    billed by the second. It is per rung rather than for the whole climb: one
    deadline for all of them meant a hard form could spend the entire budget
    and every easier one after it then entered already expired, drew nothing
    and was skipped. The climb returned nothing at all on a page where a haiku
    would have succeeded instantly, which is the opposite of dropping to an
    easier form.
    """
    classes = None
    for name in RUNGS:
        deadline = time.monotonic() + budget_s
        meter = METERS.get(name)
        scheme = SCHEMES.get(name)
        patterns = meter.split("/") if meter else None

        def draw(space, cap=None):
            """Sample this space and keep the poems the table cannot vet.

            Stress is enforced while the table is built, so every draw already
            scans and none are thrown away. What the table cannot see is
            whether a line offers any evidence that it scans: a line of ten
            monosyllables matches any pattern. Nor can it see that two rhymed
            lines closed on the same word. Both are properties of the finished
            poem, so they filter the sample, which is small and costs nothing
            to walk again.
            """
            def usable(c):
                if patterns and not all(
                        scans([words[i].text for i in line], pat)
                        for line, pat in zip(c.lines, patterns)):
                    return False
                return not scheme or _distinct(c, words, scheme)

            if not patterns and not scheme:
                # Every draw is usable, so there is nothing for a budget to
                # bound. Gating this too meant a spent budget skipped the easy
                # rungs as well, and the climb returned nothing from a page
                # that would have given a haiku at once.
                return space.sample(sample, rng)
            kept, tries = [], 0
            limit = min(cap, max_draws) if cap else max_draws
            while (len(kept) < sample and tries < limit
                   and time.monotonic() < deadline):
                batch = space.sample(min(sample * 2, limit - tries), rng)
                if not batch:
                    break
                tries += len(batch)
                kept += [c for c in batch if usable(c)]
            return kept

        if scheme:
            # One table per candidate rhyme class, biggest first. A class with
            # more distinct words offers more ways to close a line, so it is
            # likelier to admit anything at all, and most classes admit none.
            # A class is only spent once its poems have been drawn and vetted,
            # because a table that counts in the thousands can still hold
            # nothing but a word rhymed against itself.
            if classes is None:
                classes = sorted(rhyme_classes(words).items(),
                                 key=lambda kv: -len(kv[1]))[:rhyme_tries]
            # Score every class before drawing from any of them. How many
            # distinct words a class holds says little about how many poems it
            # admits: on one 1,975-word page the class with the most words
            # admitted 34 couplets and the richest admitted 9,213. Taking the
            # first class that worked therefore settled for an arbitrary
            # corner of the form. Each table is dropped once counted, because
            # twenty-five of them resident at once is the memory this avoids,
            # and rebuilding the winner costs one build.
            scored = []
            for part, _members in classes:
                trial = Space(words, FORMS[name], max_runs=max_runs,
                              meter=meter, scheme=scheme, parts={"A": part})
                count = trial.count()
                del trial
                if count >= want:
                    scored.append((count, part))
                if time.monotonic() >= deadline:
                    break
            scored.sort(reverse=True)

            space = drawn = None
            for _count, part in scored:
                trial = Space(words, FORMS[name], max_runs=max_runs,
                              meter=meter, scheme=scheme, parts={"A": part})
                # A class giving nothing usable in twenty batches is not worth
                # the time the next class needs.
                got = draw(trial, cap=sample * 20)
                if len(got) >= want:
                    space, drawn = trial, got
                    break
                if time.monotonic() >= deadline:
                    break
            if space is None:
                continue
            pool = space.count()
        else:
            space = Space(words, FORMS[name], max_runs=max_runs, meter=meter)
            pool = space.count()
            if pool < want:
                continue
            drawn = draw(space)

        drawn = drawn[:sample]
        if len(drawn) >= want:
            return Rung(name, meter is not None, pool, drawn)
    return None


def describe(rung: Rung) -> str:
    kind = "rhymed" if SCHEMES.get(rung.form) else (
        "metrical" if rung.metered else "syllabic")
    return (f"{rung.form} ({kind}), {rung.pool:,} erasures of this page "
            f"satisfy it")
