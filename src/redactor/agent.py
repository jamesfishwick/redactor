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

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from . import publish, sources

URL_IN_TITLE = re.compile(r"erase:\s*(https?://\S+)", re.IGNORECASE)
# `erase: <url> section: § 107` asks for one part of a long document. Without
# it a long page is reduced to its longest section, which on Title 17 chapter 1
# is 17,754 words of royalty provisions rather than the 184 about fair use.
SECTION_IN_TITLE = re.compile(r"section:\s*(.+?)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Request:
    number: int
    url: str
    asker: str
    section: str = ""


def open_requests(connection: str, repo: str) -> list[Request]:
    """Issues asking for a page, oldest first so nobody is starved."""
    # Oldest first from the server. The default is newest first, so sorting
    # one page of results ordered that page and not the queue: past thirty
    # open issues the genuinely oldest requests were never in the response.
    issues = publish._call(
        connection,
        f"repos/{repo}/issues?state=open&per_page=30&sort=created&direction=asc")
    out: list[Request] = []
    for issue in issues or []:
        if "pull_request" in issue:
            continue
        found = URL_IN_TITLE.search(issue.get("title") or "")
        if not found:
            continue
        if any(lab.get("name") == DECLINED for lab in issue.get("labels") or []):
            continue
        title = issue.get("title") or ""
        named = SECTION_IN_TITLE.search(title)
        out.append(Request(issue["number"], found.group(1).rstrip(".,)"),
                           (issue.get("user") or {}).get("login", "someone"),
                           named.group(1) if named else ""))
    return sorted(out, key=lambda r: r.number)


def already_erased(connection: str, repo: str) -> set[str]:
    """Source URLs the gallery already records, so idle mode never repeats."""
    page = publish._call(connection, f"repos/{repo}/contents/GALLERY.md")
    body = publish._inline_text(page)
    if body is None:
        # Too large to inline. An empty set here would mean re-erasing every
        # page already done, so say so rather than quietly repeating work.
        raise RuntimeError("GALLERY.md is too large to read inline")
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


DECLINED = "declined"


def decline(connection: str, repo: str, number: int, why: str) -> None:
    """Say why a page yielded nothing, and stop picking it up.

    The issue stays open, because a page too short or behind a paywall is not
    the asker's mistake and closing it silently would make the agent look
    broken rather than honest. It gets a label instead.

    Without one it is picked up forever: requests are served lowest number
    first, so a single page that cannot be read starves every later request
    and all idle work, and posts the same comment on every cycle.
    """
    answer(connection, repo, number,
           f"Could not erase that page. {why}\n\n"
           f"Leaving this open in case the page changes. Remove the "
           f"`{DECLINED}` label to have it tried again.", close=False)
    publish._call(connection, f"repos/{repo}/issues/{number}/labels",
                  "POST", {"labels": [DECLINED]})


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

# No cap. A cap was here while the enumerator recursed once per word, and it
# cost exactly what matters: a 7,487-word article was read down to 600, and the
# ballad finally chosen came from 182,040 candidates when millions were on the
# page. More source is not more poem, since the form is a fixed size either way.
# It is a wider choice of which fixed-size poem to keep.

# Width sets the layout the page is measured in, so it decides where words
# wrap and therefore what counts as a line. Height is only the OCR fallback's
# viewport, since the DOM path clips its own capture to the words it kept.
SHOT = (1100, 5000)


def erase_page(url: str, *, out: Path, runs: int = 2,
               shot_size: tuple[int, int] = SHOT, section: str = ""):
    """Read the page, enumerate its erasures. Returns (words, rung, shot) or None.

    The DOM is asked first and OCR is the fallback, not the other way round.
    A browser knows each word exactly and knows whether it sits in a nav or a
    footer; OCR guesses at both. OCR stays for the case the DOM cannot answer,
    such as a page that is an image of text.
    """
    from . import dom, ladder, source

    shot_path = out / "page.png"
    words = None
    # The section is chosen inside the read, not after it. The capture is
    # clipped to whatever was chosen, so asking afterwards would clip to the
    # wrong part of the page and then look for the section in it.
    got = dom.read(url, shot_path, width=shot_size[0], section=section)
    if got is not None:
        shot, words = Path(got.png), got.words
        if section and len(words) < MIN_WORDS:
            print(f"  section {section!r} gave {len(words)} words",
                  file=sys.stderr)

    if words is None or len(words) < MIN_WORDS:
        try:
            shot = source.screenshot(url, shot_path,
                                     width=shot_size[0], height=shot_size[1])
            html = source.page_html(url)
            pairs = source.article_bigrams(html) if html else None
            ocr = source.from_image(shot, pairs=pairs)
            if len(ocr) < MIN_WORDS and pairs is not None:
                ocr = source.from_image(shot)
            # The DOM path rejects a page that only answered with a bot
            # challenge. Reading the same page again with a different tool
            # would erase the challenge, which is what this guards against.
            if dom.is_challenge([w.text for w in ocr]):
                return None
            if words is None or len(ocr) > len(words):
                words = ocr
        except Exception:  # noqa: BLE001 - OCR is already the fallback
            if words is None:
                return None
    if words is None or len(words) < MIN_WORDS:
        return None

    # Part-of-speech pruning is not wired into the sampler, so tagging here
    # would load spaCy and change nothing. Contiguity carries the grammar.
    rung = ladder.climb(words, max_runs=runs)
    if rung is None:
        return None
    return words, rung, shot


def why_not(url: str) -> str:
    """A reason a reader can act on, rather than a stack trace."""
    return (f"<{url}> gave too little readable text, or no erasure of it fits "
            f"any form. Pages that are mostly video, images or script tend to "
            f"land here.")
