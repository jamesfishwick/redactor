"""Publish a finished erasure through the GitHub Sprites connector.

The connector is what makes this durable rather than a file in /tmp on a
machine that is explicitly disposable. It is also the only credential path
here that holds nothing: the gateway identifies the calling Sprite by Fly's
request signature, so a token is never read, stored or passed, and the Sprite
could be destroyed mid-run without leaking one.

Each erasure lands as a dated directory holding the poem, the rendered page
and the provenance needed to check the work: the source URL, the form it
satisfies, and how many erasures of that page also satisfied it. The file is
named README.md so that browsing into the directory renders it as a page.

The agent writes only under `erasures/` and to `GALLERY.md`, and never touches
a file a person edits. That boundary is not tidiness: this repo already cost
one merge conflict when a human README met a machine one, and the agent
commits far more often than anybody reviews.
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


def raw_url(repo: str, path: str, branch: str = "main") -> str:
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"


def page(*, url: str, poem: str, form: str, pool: int, note: str = "",
         image_url: str | None = None, via: str = "") -> str:
    """The markdown for one erasure."""
    lines = [f"# {form}", "", "```", poem, "```", ""]
    if image_url:
        lines += [f"![erasure]({image_url})", ""]
    lines += [f"Source: {url}"]
    if via:
        lines += ["", f"Found via: {via}"]
    lines += ["", f"{pool:,} erasures of this page satisfy {form}."]
    if note:
        lines += ["", f"Chosen because: {note}"]
    return "\n".join(lines) + "\n"


def publish(connection: str, repo: str, *, url: str, poem: str, form: str,
            pool: int, note: str = "", image: Path | None = None,
            stamp: str | None = None, via: str = "") -> dict[str, str]:
    """Write one erasure to the repo. Returns the URLs written."""
    stamp = stamp or datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    folder = f"erasures/{stamp}"
    written: dict[str, str] = {}

    # The image goes first so the page can point at it.
    image_url = None
    if image and image.exists():
        got = put_file(connection, repo, f"{folder}/erasure.png",
                       image.read_bytes(), f"erasure: render for {stamp}")
        if got:
            written["image"] = got
            image_url = raw_url(repo, f"{folder}/erasure.png")
            written["image_raw"] = image_url

    body = page(url=url, poem=poem, form=form, pool=pool, note=note,
                image_url=image_url, via=via)
    got = put_file(connection, repo, f"{folder}/README.md", body.encode(),
                   f"erasure: {form} from {url}")
    if got:
        written["page"] = got
        written["folder"] = f"https://github.com/{repo}/tree/main/{folder}"

    _prepend_gallery(connection, repo, stamp=stamp, url=url, poem=poem,
                     form=form, image_url=image_url, folder=folder)
    return written


GALLERY_HEAD = """# Gallery

Every erasure this agent has published, newest first. Each one deletes words
from a single page and keeps the rest in their original order.

This file is written by the agent. Nothing here is hand-edited.

"""


def _inline_text(payload) -> str | None:
    """The file's text, or None when the API would not inline it.

    Contents returns the base64 body only below 1MB. Above that it answers with
    an empty string and `encoding: none`, which is indistinguishable from an
    empty file unless the encoding is checked. Treating it as empty rewrote the
    gallery from scratch over the existing sha, losing every earlier entry in a
    commit nobody was watching.
    """
    if not payload:
        return ""
    if payload.get("encoding") != "base64":
        return None
    return base64.b64decode(payload.get("content") or "").decode("utf-8", "replace")


def _prepend_gallery(connection: str, repo: str, *, stamp: str, url: str,
                     poem: str, form: str, image_url: str | None,
                     folder: str) -> None:
    existing = _call(connection, f"repos/{repo}/contents/GALLERY.md")
    body = _inline_text(existing)
    if body is None:
        raise RuntimeError(
            "GALLERY.md is too large for the contents API to return inline; "
            "refusing to rewrite it from scratch")
    if body.startswith(GALLERY_HEAD):
        body = body[len(GALLERY_HEAD):]

    entry = [f"## {stamp}", "", "```", poem, "```", ""]
    if image_url:
        entry += [f"![erasure]({image_url})", ""]
    entry += [f"{form}, from <{url}>. "
              f"[Full entry](https://github.com/{repo}/tree/main/{folder})", "", "---", ""]

    put_file(connection, repo, "GALLERY.md",
             (GALLERY_HEAD + "\n".join(entry) + body).encode(),
             f"gallery: {stamp}")
