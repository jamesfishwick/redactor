"""Choose among candidates that are already correct.

Everything reaching here satisfies the form and holds together
grammatically, so nothing in this module can fix a broken poem and nothing
needs to. The model ranks. It never generates, which removes invented words,
miscounted syllables and reordered lines as possibilities rather than leaving
them as bugs to catch downstream.

Inference goes through a Sprites connector. Inside a Sprite the gateway
identifies the caller by Fly's request signature, so no key is read, stored
or passed, and a probe that goes wrong cannot leak a credential the machine
never held.

Without a reachable gateway, `arbitrary` keeps the pipeline whole. Its output
is still form-correct and still readable. It just isn't chosen.
"""

from __future__ import annotations

import json
import os
import random
import urllib.error
import urllib.request

GATEWAY = "https://api.sprites.dev/v1/gateway"
DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"

PROMPT = """You are judging erasure poems. Each was made by deleting words from \
one web page and keeping the rest in their original order. They are all already \
correct: the syllable count scans and the grammar holds. Judge only what a reader \
would feel.

Prefer a poem that says something the page did not set out to say. Prefer concrete \
images over abstraction. Distrust one that merely quotes the page intact.

Page: {url}

{listing}

Reply with the number of the best poem, then a newline, then one sentence on what \
it does. Nothing else."""


def arbitrary(candidates, seed: int | None = None):
    return random.Random(seed).choice(candidates) if candidates else None


def discover(provider: str = "openrouter") -> str | None:
    """Ask the gateway which connectors this Sprite can reach."""
    override = os.environ.get("REDACTOR_CONNECTION")
    if override:
        return override
    try:
        with urllib.request.urlopen(f"{GATEWAY}/list", timeout=20) as r:
            payload = json.load(r)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    entries = payload.get("connections") or payload.get("gateways") or []
    for entry in entries:
        if entry.get("provider") == provider:
            return entry.get("id") or entry.get("connection_id")
    return None


def by_gateway(candidates, words, url: str, connection: str | None = None,
               model: str | None = None, shortlist: int = 60, timeout: int = 120):
    """Rank through a Sprites connector. Returns (candidate, note) or None."""
    connection = connection or discover()
    if not connection:
        return None
    model = model or os.environ.get("REDACTOR_MODEL", DEFAULT_MODEL)

    pool = candidates[:shortlist]
    listing = "\n\n".join(f"{n + 1}.\n{c.render(words)}" for n, c in enumerate(pool))
    body = json.dumps({
        "model": model,
        "max_tokens": 300,
        "messages": [{"role": "user",
                      "content": PROMPT.format(url=url, listing=listing)}],
    }).encode()

    req = urllib.request.Request(
        f"{GATEWAY}/openrouter/{connection}/v1/chat/completions",
        data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            reply = json.load(r)
    except (urllib.error.URLError, OSError, ValueError):
        return None

    try:
        text = reply["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        return None

    head, _, note = text.partition("\n")
    digits = "".join(ch for ch in head if ch.isdigit())
    if not digits:
        return None
    idx = int(digits) - 1
    if not 0 <= idx < len(pool):
        return None
    return pool[idx], note.strip()


# kept under the old name so the CLI and compare module need no branching
by_model = by_gateway
