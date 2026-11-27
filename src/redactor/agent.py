"""The loop: answer a request if one is waiting, otherwise find your own page.

A Sprite is free while idle and wakes instantly on a request, so the platform's
billing shape and the agent's behaviour are the same shape. Idle work is the
default rather than filler, and a request preempts it.

Requests arrive as GitHub issues titled `erase: <url>`, which is a deliberate
choice over an HTTP endpoint. A Sprite's URL is authenticated by default, so
opening one up is a real decision, whereas an issue needs no client, no token
and no link to a machine: anyone with a GitHub account can file one from a
phone. The thread then holds the whole exchange, which makes the request log
and the display the same artifact.
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import publish, sources

URL_IN_TITLE = re.compile(r"erase:\s*(https?://\S+)", re.I)


@dataclass(frozen=True)
class Request:
    number: int
    url: str
    asker: str


def open_requests(connection: str, repo: str) -> list[Request]:
    """Issues asking for a page, oldest first so nobody is starved."""
    issues = publish._call(connection, f"repos/{repo}/issues?state=open&per_page=30")
    out: list[Request] = []
    for issue in issues or []:
        if "pull_request" in issue:
            continue
        found = URL_IN_TITLE.search(issue.get("title") or "")
        if not found:
            continue
        out.append(Request(issue["number"], found.group(1).rstrip(".,)"),
                           (issue.get("user") or {}).get("login", "someone")))
    return sorted(out, key=lambda r: r.number)


def already_erased(connection: str, repo: str) -> set[str]:
    """Source URLs the gallery already records, so idle mode never repeats."""
    page = publish._call(connection, f"repos/{repo}/contents/GALLERY.md")
    if not page or not page.get("content"):
        return set()
    import base64
    body = base64.b64decode(page["content"]).decode("utf-8", "replace")
    return set(re.findall(r"from <(https?://[^>]+)>", body))


def answer(connection: str, repo: str, number: int, body: str,
           close: bool = True) -> str | None:
    """Reply on the issue, and close it once the work is published."""
    out = publish._call(connection, f"repos/{repo}/issues/{number}/comments",
                        "POST", {"body": body})
    if close:
        publish._call(connection, f"repos/{repo}/issues/{number}", "PATCH",
                      {"state": "closed"})
    return (out or {}).get("html_url")


def decline(connection: str, repo: str, number: int, why: str) -> None:
    """Say why a page yielded nothing, and leave the issue open.

    A page that is too short or behind a paywall is not the asker's mistake and
    not a failure to hide. Closing it silently would make the agent look broken
    rather than honest.
    """
    answer(connection, repo, number,
           f"Could not erase that page. {why}\n\n"
           f"Leaving this open in case the page changes.", close=False)


def next_job(connection: str, repo: str,
             tries: int = 6) -> tuple[str, list]:
    """What to work on now: a waiting request, else several things to try."""
    waiting = open_requests(connection, repo)
    if waiting:
        return "request", [waiting[0]]
    picks = sources.shortlist(already_erased(connection, repo), limit=tries)
    if not picks:
        raise RuntimeError("nothing to erase: no requests and no fresh sources")
    return "idle", picks


# --- the run itself -------------------------------------------------------

MIN_WORDS = 120     # below this a page yields a pool too small to choose from

# A viewport-sized shot catches only the top of a page. The Hacksgiving rules
# gave 92 words at 1000x1500 against 504 in its HTML, which is the difference
# between declining a page and erasing it. Taller is also a better picture:
# more of the page goes black around what survives.
SHOT = (1100, 5000)


def erase_page(url: str, *, out: Path, runs: int = 2, use_pos: bool = False,
               shot_size: tuple[int, int] = SHOT):
    """Screenshot, read, enumerate. Returns (words, rung, shot) or None."""
    from . import ladder, source, tagging

    try:
        shot = source.screenshot(url, out / "page.png",
                                 width=shot_size[0], height=shot_size[1])
        html = source.page_html(url)
        pairs = source.article_bigrams(html) if html else None
        words = source.from_image(shot, pairs=pairs)
        if len(words) < MIN_WORDS and pairs is not None:
            # The extractor found little or nothing it recognised as an
            # article. Better a page with chrome in it than no page at all.
            words = source.from_image(shot)
    except Exception:
        return None
    if len(words) < MIN_WORDS:
        return None

    tags = tri = None
    if use_pos:
        nlp = tagging.load()
        if nlp is not None:
            tags = tagging.tag(nlp, words)
            tri = tagging.trigrams(nlp, " ".join(w.text for w in words))

    rung = ladder.climb(words, max_runs=runs, pos_tags=tags, trigrams=tri)
    if rung is None:
        return None
    return words, rung, shot


def why_not(url: str) -> str:
    """A reason a reader can act on, rather than a stack trace."""
    return (f"<{url}> gave too little readable text, or no erasure of it fits "
            f"any form. Pages that are mostly video, images or script tend to "
            f"land here.")
