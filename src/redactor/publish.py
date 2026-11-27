"""Publish a finished erasure through the GitHub Sprites connector.

The connector is what makes this durable rather than a file in /tmp on a
machine that is explicitly disposable. It is also the only credential path
here that holds nothing: the gateway identifies the calling Sprite by Fly's
request signature, so a token is never read, stored or passed, and the Sprite
could be destroyed mid-run without leaking one.

Each erasure lands as a dated directory holding the poem, the rendered page
and the provenance needed to check the work: the source URL, the form it
satisfies, and how many erasures of that page also satisfied it.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

GATEWAY = "https://api.sprites.dev/v1/gateway/github"


def _call(connection: str, path: str, method: str = "GET", body=None):
    req = urllib.request.Request(
        f"{GATEWAY}/{connection}/{path.lstrip('/')}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def whoami(connection: str) -> str | None:
    me = _call(connection, "user")
    return me.get("login") if me else None


def put_file(connection: str, repo: str, path: str, content: bytes,
             message: str) -> str | None:
    """Create or replace one file. Returns its URL."""
    existing = _call(connection, f"repos/{repo}/contents/{path}")
    body = {
        "message": message,
        "content": base64.b64encode(content).decode(),
    }
    if existing and "sha" in existing:
        body["sha"] = existing["sha"]
    out = _call(connection, f"repos/{repo}/contents/{path}", "PUT", body)
    if not out:
        return None
    return (out.get("content") or {}).get("html_url")


def publish(connection: str, repo: str, *, url: str, poem: str, form: str,
            pool: int, note: str = "", image: Path | None = None,
            stamp: str | None = None) -> dict[str, str]:
    """Write one erasure to the repo. Returns the URLs written."""
    stamp = stamp or datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    folder = f"erasures/{stamp}"
    written: dict[str, str] = {}

    lines = [
        f"# {form}", "",
        "```", poem, "```", "",
        f"Source: {url}", "",
        f"Form: {form}. {pool:,} erasures of this page satisfy it.",
    ]
    if note:
        lines += ["", f"Chosen because: {note}"]
    readme = ("\n".join(lines) + "\n").encode()

    got = put_file(connection, repo, f"{folder}/poem.md", readme,
                   f"erasure: {form} from {url}")
    if got:
        written["poem"] = got

    if image and image.exists():
        got = put_file(connection, repo, f"{folder}/erasure.png",
                       image.read_bytes(), f"erasure: render for {stamp}")
        if got:
            written["image"] = got
    return written
