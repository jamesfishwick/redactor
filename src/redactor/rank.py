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


def _why(err) -> str:
    """The gateway's own account of a refusal, which carries the remedy.

    A connector out of prepaid credit answers 403 with the dashboard URL that
    tops it up. Discarding the body leaves the caller unable to tell that from
    having no connector at all.
    """
    try:
        payload = json.loads(err.read().decode())
    except (ValueError, OSError):
        return str(getattr(err, "reason", "")) or "no reason given"
    message = (payload.get("error") or {}).get("message")
    return message or str(payload)[:300]


def by_gateway(candidates, words, url: str, connection: str | None = None,
               model: str | None = None, shortlist: int = 60,
               timeout: int = 120, log=None):
    """Rank through a Sprites connector. Returns (candidate, note) or None."""
    connection = connection or discover()
    if not connection:
        if log:
            log("no openrouter connector is attached to this Sprite")
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
    except urllib.error.HTTPError as err:
        # Checked before URLError, which it subclasses, so the body survives.
        if log:
            log(f"the openrouter connector answered {err.code}: {_why(err)}")
        return None
    except (urllib.error.URLError, OSError, ValueError) as err:
        if log:
            log(f"the openrouter connector could not be reached: {err}")
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


def by_claude_code(candidates, words, url: str, shortlist: int = 60,
                   timeout: int = 180, log=None):
    """Rank with the Claude Code binary a Sprite already carries.

    This bills a Claude subscription rather than an API key, which is the
    difference between a hackathon costing nothing and costing per run. It is
    not a Sprites connector, so it cannot be the thing that satisfies that
    requirement on its own.
    """
    import shutil
    import subprocess

    exe = shutil.which("claude")
    if not exe:
        if log:
            log("the claude binary is not on PATH")
        return None
    pool = candidates[:shortlist]
    listing = "\n\n".join(f"{n + 1}.\n{c.render(words)}" for n, c in enumerate(pool))
    try:
        proc = subprocess.run(
            [exe, "-p", PROMPT.format(url=url, listing=listing)],
            capture_output=True, text=True, errors="replace",
            timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = proc.stdout.strip()
    if not text or "Not logged in" in text:
        if log:
            log("the claude binary is present but not logged in")
        return None
    head, _, note = text.partition("\n")
    digits = "".join(ch for ch in head if ch.isdigit())
    if not digits:
        return None
    idx = int(digits) - 1
    if not 0 <= idx < len(pool):
        return None
    return pool[idx], note.strip()


def by_model(candidates, words, url: str, *, log=None, **kw):
    """Try each ranker in turn; fall through to None so the caller can choose
    arbitrarily rather than fail.

    Each one says why it passed, because the three ways of getting no poem
    ranked are a missing connector, a connector that refused, and a missing
    binary, and they are worth telling apart.

    `kw` reaches the gateway alone, since a connection id and a model name
    mean nothing to the other. It used to be accepted here and dropped, so a
    caller naming a connection quietly got whichever one discovery found.
    """
    for ranker in (by_gateway, by_claude_code):
        got = ranker(candidates, words, url, log=log,
                     **(kw if ranker is by_gateway else {}))
        if got:
            if log:
                log(f"ranked by {ranker.__name__.removeprefix('by_')}")
            return got
    return None
