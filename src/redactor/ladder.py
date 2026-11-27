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

from dataclasses import dataclass

from .candidates import Enumerator, Space
from .prosody import FORMS, METERS, scans

# hardest first
RUNGS: tuple[str, ...] = (
    "ballad", "pentameter", "tetrameter",
    "fib", "cinquain", "tanka", "lune", "haiku",
)

FALLBACK_SHAPES: tuple[str, ...] = ("snowball", "abecedarian", "univocalic:a")


@dataclass
class Rung:
    form: str
    metered: bool
    pool: int
    candidates: list


def climb(words, *, max_runs=2, pos_tags=None, trigrams=None,
          want=1, limit=20000, sample=60, max_draws=40000,
          rng=None) -> Rung | None:
    """Return the hardest form this page admits, with candidates to choose from.

    The candidates are drawn uniformly from the whole space rather than taken
    from the front of an enumeration. A short form is only good when the choice
    behind it is wide, and one page measured here admits 182,040 ballads in its
    first 600 words alone; handing a ranker the first sixty of those gives it
    sixty poems from one corner of the page.
    """
    for name in RUNGS:
        meter = METERS.get(name)
        space = Space(words, FORMS[name], max_runs=max_runs)
        pool = space.count()
        if pool < want:
            continue
        if not meter:
            drawn = space.sample(sample, rng)
        else:
            # Scansion is checked after a line exists, not while it is built,
            # so metered forms are sampled until enough survive. On one page
            # fewer than one draw in a hundred scans, which is the whole
            # reason the ranker was being handed two poems out of 26 million.
            patterns = meter.split("/")
            drawn, tries = [], 0
            while len(drawn) < sample and tries < max_draws:
                batch = space.sample(min(2000, max_draws - tries), rng)
                tries += len(batch)
                drawn += [c for c in batch
                          if len(c.lines) == len(patterns)
                          and all(scans([words[i].text for i in line], pat)
                                  for line, pat in zip(c.lines, patterns))]
        drawn = drawn[:sample]
        if len(drawn) >= want:
            return Rung(name, meter is not None, pool, drawn)
    return None


def describe(rung: Rung) -> str:
    kind = "metrical" if rung.metered else "syllabic"
    return (f"{rung.form} ({kind}), {rung.pool:,} erasures of this page "
            f"satisfy it")
