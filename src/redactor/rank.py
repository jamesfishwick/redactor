"""Choose among candidates that are already correct.

Every candidate reaching this point satisfies the form and is grammatical, so
nothing here can fix a broken poem and nothing needs to. The model only ranks,
which removes the failure modes that come with asking it to generate: invented
words, miscounted syllables, reordered lines.

Without a model, `arbitrary` keeps the pipeline whole. Its output is still
form-correct and still readable; it just isn't chosen.
"""

from __future__ import annotations

import os
import random

PROMPT = """You are judging erasure poems. Each was made by deleting words from a \
single source page, keeping the rest in their original order. All of them are \
already correct: the form scans and the grammar holds. Judge only what a reader \
would feel.

Prefer poems that say something the source did not set out to say. Prefer \
concrete images over abstraction. Distrust a poem that merely quotes the source \
intact.

Source page: {url}

{listing}

Reply with the number of the best poem, then a blank line, then one sentence \
saying what it does. Nothing else."""


def arbitrary(candidates, seed: int | None = None):
    return random.Random(seed).choice(candidates)


def by_model(candidates, words, url: str, model: str = "claude-sonnet-5",
             shortlist: int = 60):
    """Rank with Claude. Returns (candidate, note) or None when unavailable."""
    try:
        import anthropic
    except ImportError:
        return None
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None

    pool = candidates[:shortlist]
    listing = "\n\n".join(
        f"{n + 1}.\n{c.render(words)}" for n, c in enumerate(pool)
    )
    client = anthropic.Anthropic()
    reply = client.messages.create(
        model=model,
        max_tokens=300,
        messages=[{"role": "user",
                   "content": PROMPT.format(url=url, listing=listing)}],
    )
    text = "".join(b.text for b in reply.content if b.type == "text").strip()
    head, _, note = text.partition("\n")
    digits = "".join(ch for ch in head if ch.isdigit())
    if not digits:
        return None
    idx = int(digits) - 1
    if not 0 <= idx < len(pool):
        return None
    return pool[idx], note.strip()
