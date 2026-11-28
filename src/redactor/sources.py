"""Where idle mode finds something to erase.

MetaFilter is the source, but not the front page. Its posts run 30 to 70
words, which is far too thin: a page needs roughly 250 before the candidate
pool is big enough to choose from rather than settle for. What the site is
*pointing at* is the real material, and letting the community pick means the
agent reads a Guardian piece one day and a music blog the next.

Reaching it takes a detour. metafilter.com and its own rss.xml both answer 403
behind a Cloudflare challenge, while the FeedBurner mirror answers 200. That is
the only reason the feed URL looks like it does.

Linked pages are arbitrary, so plenty will be video, paywalled, or JavaScript
with no extractable text. Wikipedia's featured article is the fallback for
exactly that: always long, always prose, never challenged.
"""

from __future__ import annotations

import html
import json
import random
import re
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime

FEED = "https://feeds.feedburner.com/Metafilter"
WIKI = "https://en.wikipedia.org/api/rest_v1/feed/featured"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")

# Pages that never yield prose worth erasing.
BARREN = re.compile(
    r"(youtube\.com|youtu\.be|vimeo\.com|twitter\.com|x\.com|bsky\.app|"
    r"instagram\.com|tiktok\.com|soundcloud\.com|spotify\.com|"
    r"\.(pdf|jpg|jpeg|png|gif|mp3|mp4|zip)$)", re.IGNORECASE)


@dataclass(frozen=True)
class Candidate:
    url: str
    via: str          # the MetaFilter post that pointed here
    origin: str       # "metafilter" or "wikipedia"


def _get(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def metafilter_links(limit: int = 40) -> list[Candidate]:
    """Outbound links from the current MetaFilter feed, best first."""
    try:
        raw = _get(FEED)
    except OSError:
        return []
    out: list[Candidate] = []
    for item in re.findall(r"<item>(.*?)</item>", raw, re.DOTALL):
        title = re.search(r"<title>(.*?)</title>", item, re.DOTALL)
        body = re.search(r"<description>(.*?)</description>", item, re.DOTALL)
        if not body:
            continue
        via = html.unescape(title.group(1)).strip() if title else "MetaFilter"
        for link in re.findall(r'href="(https?://[^"]+)"',
                               html.unescape(body.group(1))):
            if "metafilter.com" in link or BARREN.search(link):
                continue
            out.append(Candidate(link, via, "metafilter"))
            if len(out) >= limit:
                return out
    return out


def wikipedia_featured(day: datetime | None = None) -> Candidate | None:
    """Today's featured article. The fallback that never fails."""
    day = day or datetime.now(UTC)
    try:
        payload = json.loads(_get(f"{WIKI}/{day.strftime('%Y/%m/%d')}"))
    except (OSError, ValueError):
        return None
    tfa = payload.get("tfa") or {}
    page = (tfa.get("content_urls") or {}).get("desktop", {}).get("page")
    if not page:
        return None
    title = (tfa.get("titles") or {}).get("normalized", "today's featured article")
    return Candidate(page, title, "wikipedia")


def shortlist(already: set[str], limit: int = 6,
              rng: random.Random | None = None) -> list[Candidate]:
    """Several things worth trying, best-guess order, Wikipedia last.

    More than one, because the filters here are only a guess from the URL. A
    download page, a photo essay or a login wall all look like ordinary links
    and only reveal themselves once fetched, and a run that gives up after the
    first miss does nothing at all that cycle.

    The order within MetaFilter's links is arbitrary on purpose. Ranking pages
    before erasing them would spend inference deciding what to spend inference
    on, and the community already chose these by posting them.
    """
    rng = rng or random.Random()
    fresh = [c for c in metafilter_links() if c.url not in already]
    rng.shuffle(fresh)
    out = fresh[:limit]
    wiki = wikipedia_featured()
    if wiki and wiki.url not in already:
        out.append(wiki)
    return out


def choose(already: set[str], rng: random.Random | None = None) -> Candidate | None:
    picks = shortlist(already, rng=rng)
    return picks[0] if picks else None
