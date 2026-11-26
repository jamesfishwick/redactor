"""Produce one poem per method, so the cost of each constraint is visible.

The three are not alternatives to fall back through. They are the same walk
over the source with successively more pruning, and the only honest way to
show what a constraint buys is to print what the page yields without it.

    form only      every erasure that scans; mostly word salad
    + grammar      contiguous runs, and optionally POS trigrams
    + judgement    a model ranks what survived

Counts come from the same enumerator, so the three numbers are comparable.
"""

from __future__ import annotations

from dataclasses import dataclass

from .candidates import Candidate, Enumerator
from . import rank


@dataclass
class Attempt:
    method: str
    note: str
    pool: int
    poem: Candidate | None
    comment: str = ""


def run(words, form, *, max_runs=2, pos_tags=None, trigrams=None,
        seed=None, url="", use_model=True, limit=4000) -> list[Attempt]:
    out: list[Attempt] = []

    # The pool size has to be the uncapped count. `all()` stops at `limit`, so
    # reporting its length makes two stages that both overflow look identical
    # and hides exactly the difference this mode exists to show.
    loose = Enumerator(words, form, max_runs=len(words), limit=limit)
    found = loose.all()
    out.append(Attempt(
        "form only", "syllables scan; nothing else is checked",
        loose.count(), rank.arbitrary(found, seed) if found else None))

    tight = Enumerator(words, form, max_runs=max_runs,
                       pos_tags=pos_tags, allowed_trigrams=trigrams, limit=limit)
    kept = tight.all()
    pool = tight.count()
    note = f"at most {max_runs} unbroken runs"
    if trigrams:
        note += ", part-of-speech trigrams from the source"
    out.append(Attempt("form + grammar", note, pool,
                       rank.arbitrary(kept, seed) if kept else None))

    if not kept:
        out.append(Attempt("form + grammar + judgement",
                           "nothing survived the previous stage", 0, None))
        return out

    picked = rank.by_model(kept, words, url) if use_model else None
    if picked:
        poem, comment = picked
        out.append(Attempt("form + grammar + judgement",
                           "a model ranked the survivors", pool, poem, comment))
    else:
        out.append(Attempt("form + grammar + judgement",
                           "no model available; same pool, unranked",
                           pool, None))
    return out


def report(attempts, words) -> str:
    blocks = []
    for a in attempts:
        head = f"{a.method}  [{a.pool:,} candidates]"
        body = a.poem.render(words) if a.poem else "(none)"
        chunk = f"{head}\n{a.note}\n\n{body}"
        if a.comment:
            chunk += f"\n\n{a.comment}"
        blocks.append(chunk)
    return ("\n\n" + "-" * 58 + "\n\n").join(blocks)
