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

from .candidates import Enumerator
from .prosody import FORMS, METERS

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
          want=1, limit=20000) -> Rung | None:
    """Return the hardest form this page admits, with its candidates."""
    for name in RUNGS:
        meter = METERS.get(name)
        e = Enumerator(words, FORMS[name], max_runs=max_runs, pos_tags=pos_tags,
                       allowed_trigrams=trigrams, limit=limit, meter=meter)
        found = e.all()
        if len(found) >= want:
            return Rung(name, meter is not None, len(found), found)
    return None


def describe(rung: Rung) -> str:
    kind = "metrical" if rung.metered else "syllabic"
    return (f"{rung.form} ({kind}), {rung.pool:,} erasures of this page "
            f"satisfy it")
