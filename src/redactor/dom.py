"""Read a page's words and their positions from the browser, not from a picture.

Erasure needs two things about every word: what it says and where it sits. OCR
of a screenshot supplies both badly. It misreads (`TypeSafeAl`, `ona`, `vy`),
it sees only as much of the page as the screenshot was tall, and it reports
nav, logos and footers as ordinary text, which then have to be guessed at
afterwards with an article extractor.

The browser already knows all of it exactly. A Range around each word gives a
precise box, and `closest('nav, footer, ...')` says whether the word is page
furniture rather than prose. On one page that read 605 words, split 487 body to
118 chrome, against 358 from OCR of the same page.

OCR still earns its place on an image of text, where there is no DOM to ask.
It does not earn it here.
"""

from __future__ import annotations

from dataclasses import dataclass

# Walks text nodes, measures each word, and marks the ones inside page
# furniture. Runs in the page, so it sees the laid-out result rather than the
# markup: text hidden by CSS is skipped because its box has no size.
EXTRACT = r"""() => {
  const SKIP = new Set(['SCRIPT','STYLE','NOSCRIPT','SVG','HEAD','TEXTAREA']);
  // Consent dialogs, newsletter overlays and cookie bars are ordinary divs,
  // so the landmark elements alone do not catch them. They read as body text
  // and then turn up in the poem: one page erased down to its own cookie
  // banner, which is the page's lawyers rather than the page.
  const CHROME = [
    'nav', 'header', 'footer', 'aside', 'form',
    '[role=navigation]', '[role=banner]', '[role=contentinfo]',
    '[role=search]', '[role=dialog]', '[role=alertdialog]',
    '[aria-modal=true]', 'dialog',
    '[id*=cookie i]', '[class*=cookie i]',
    '[id*=consent i]', '[class*=consent i]',
    '[id*=gdpr i]', '[class*=gdpr i]',
    '[class*=newsletter i]', '[class*=subscribe i]',
    '[class*=paywall i]', '[class*=modal i]', '[class*=popup i]',
    '[class*=banner i]', '[class*=notice i]',
  ].join(',');
  const out = [];
  const HEADING = new Set(['H1','H2','H3','H4','H5','H6']);
  let section = 0;
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walk.nextNode())) {
    const parent = node.parentElement;
    if (!parent || SKIP.has(parent.tagName)) continue;
    // A heading starts a new section, so a long document can be cut at its own
    // seams instead of at an arbitrary word count.
    if (HEADING.has(parent.tagName)) section++;
    const style = getComputedStyle(parent);
    if (style.visibility === 'hidden' || style.display === 'none') continue;
    const marked = document.querySelector('[data-redactor-article]');
    const outside = marked && !parent.closest('[data-redactor-article]');
    const furniture = outside || !!parent.closest(CHROME);
    const re = /\S+/g;
    let match;
    while ((match = re.exec(node.nodeValue))) {
      const range = document.createRange();
      range.setStart(node, match.index);
      range.setEnd(node, match.index + match[0].length);
      const box = range.getBoundingClientRect();
      if (box.width < 1 || box.height < 1) continue;
      out.push({
        t: match[0],
        x: Math.round(box.x + scrollX), y: Math.round(box.y + scrollY),
        w: Math.round(box.width), h: Math.round(box.height),
        chrome: furniture, tag: parent.tagName, sec: section,
      });
    }
  }
  return out;
}"""


def slice_between(words, start: str, end: str | None = None):
    """Keep the words from the first `start` up to the next `end`.

    Some pages are a whole document rather than an article. Chapter 1 of the
    Copyright Act is 72,731 words in one URL, and erasing "the chapter" is not
    a thing anyone means: the unit is a section. This takes one out by its own
    heading text, so a fragment like #107 becomes a source.

    Matching is on the joined text, so a heading split across elements still
    matches, and the comparison ignores case and runs of whitespace.
    """
    import re as _re

    def norm(t: str) -> str:
        return _re.sub(r"\s+", " ", t).strip().lower()

    joined, spans = "", []
    for i, w in enumerate(words):
        spans.append((len(joined), i))
        joined += norm(w.text) + " "

    begin = joined.find(norm(start))
    if begin < 0:
        return []
    stop = joined.find(norm(end), begin + 1) if end else -1
    if stop < 0:
        stop = len(joined)

    first = next((i for off, i in spans if off >= begin), 0)
    last = next((i for off, i in reversed(spans) if off < stop), len(words) - 1)
    return words[first:last + 1]


@dataclass(frozen=True)
class Read:
    words: list        # redactor.source.Word
    png: str           # full-page screenshot the boxes refer to
    title: str
    sections: list     # heading index per word, parallel to `words`


MAX_CAPTURE = 30000   # ImageMagick refuses an image taller than 32,000px

# A site that declines automated access still answers with a page, and that
# page has words on it. One of them was published as an erasure of a Pulitzer
# finalist, having actually been made from the interstitial. A challenge is not
# a short page to be skipped for thinness, it is the wrong page entirely.
CHALLENGE = (
    "performing security verification",
    "checking your browser",
    "enable javascript and cookies",
    "verify you are human",
    "just a moment",
    "access denied",
    "request blocked",
    "unusual traffic",
    "are you a robot",
)


def is_challenge(words) -> bool:
    text = " ".join(getattr(w, "text", w) for w in words[:80]).lower()
    return any(phrase in text for phrase in CHALLENGE)


def read(url: str, png, *, width: int = 1100, height: int = 1400,
         timeout: int = 45000, settle: int = 2500, section: str = "",
         body_only: bool = True) -> Read | None:
    """Screenshot the page and return its words with exact boxes.

    The screenshot is full-page so that every box the DOM reports falls inside
    the image. A viewport-sized one would leave most words pointing off the
    bottom of it.

    Waits for `domcontentloaded` and then a fixed settle, not for
    `networkidle`. An ad-heavy page keeps connections open indefinitely, so
    networkidle never fires and the read times out on a page that rendered
    fine seconds earlier. The settle covers content that arrives late.

    The capture is clipped to the words that will actually be used, chosen
    before the browser closes. A whole statute rendered full-page is 103,102
    pixels tall and no image tool will open it, and the rest of it is not the
    poem's page in any case.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    from .source import Word

    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox"])
        try:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            page.wait_for_timeout(settle)
            try:
                page.add_script_tag(url=READABILITY_CDN)
                page.evaluate(MARK_ARTICLE)
            except Exception:  # noqa: BLE001 - any CDN failure reads on
                pass             # a page that blocks the CDN still gets read
            raw = page.evaluate(EXTRACT)
            title = page.title()
            kept = _choose(raw, body_only, section)
            if not kept or is_challenge([w["t"] for w in kept]):
                browser.close()
                return None
            clip = _clip(kept, width)
            page.screenshot(path=str(png), full_page=True, clip=clip)
        except Exception:  # noqa: BLE001 - a browser fails unpredictably
            browser.close()
            return None
        browser.close()

    words, sections = [], []
    for w in kept:
        words.append(Word(
            text=w["t"],
            # Boxes are reported against the page, the capture starts at the
            # clip, so positions move with it.
            left=w["x"] - clip["x"], top=w["y"] - clip["y"],
            width=w["w"], height=w["h"],
            # Words share a line when they share a parent element and a
            # baseline, which is what a visual run has to respect.
            line=f"{w['tag']}-{w['y']}",
        ))
        sections.append(w.get("sec", 0))
    return Read(words, str(png), title, sections) if words else None


# Mozilla's Readability, the algorithm behind Firefox Reader Mode. Run in the
# page rather than over fetched HTML, because the boxes have to come from the
# same DOM the words do and an extractor working on a copy has no coordinates
# to hand back.
READABILITY_CDN = "https://cdn.jsdelivr.net/npm/@mozilla/readability@0.5.0/Readability.js"

# Readability parses a clone, so its result cannot be matched back by node.
# Matching it back by text does not work either: a forward walk over tokens
# loses alignment on the first common word and keeps a soup of "the" and "to".
#
# So take the ends instead. Find the live elements holding the article's first
# and last distinctive phrases, walk up to their common ancestor, and mark it.
# The extractor then keeps what is inside, which is a question about node
# identity rather than about text.
MARK_ARTICLE = r"""() => {
  if (typeof Readability === 'undefined') return false;
  let parsed;
  try {
    parsed = new Readability(document.cloneNode(true), {charThreshold: 200}).parse();
  } catch (e) { return false; }
  if (!parsed || !parsed.textContent) return false;

  const text = parsed.textContent.replace(/\s+/g, ' ').trim();
  if (text.length < 400) return false;
  const words = text.split(' ');
  const head = words.slice(0, 8).join(' ');
  const tail = words.slice(-8).join(' ');

  const find = (phrase) => {
    const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node, best = null;
    const want = phrase.toLowerCase().slice(0, 60);
    while ((node = walk.nextNode())) {
      const t = node.nodeValue.replace(/\s+/g, ' ').trim().toLowerCase();
      if (t.length > 8 && want.startsWith(t.slice(0, 30))) { best = node; break; }
      if (t.includes(want.slice(0, 30))) { best = node; break; }
    }
    return best ? best.parentElement : null;
  };

  let a = find(head), b = find(tail);
  if (!a && !b) return false;
  let box = a || b;
  if (a && b) {
    box = a;
    while (box && !box.contains(b)) box = box.parentElement;
  }
  // Never let it climb to the whole document, which would mark everything.
  if (!box || box === document.body || box === document.documentElement) return false;
  box.setAttribute('data-redactor-article', '1');
  return true;
}"""


def _choose(raw, body_only: bool, section: str):
    """The words to work with, decided before the browser closes."""
    pool = [w for w in raw if not (body_only and w["chrome"])]
    if not pool:
        return []
    if section:
        named = _named_raw(pool, section)
        if named:
            return named
    return _largest_raw(pool)


def _named_raw(pool, start: str):
    import re as _re
    want = _re.sub(r"\s+", " ", start).strip().lower()
    joined, offsets = "", []
    for i, w in enumerate(pool):
        offsets.append((len(joined), i))
        joined += _re.sub(r"\s+", " ", w["t"]).strip().lower() + " "
    at = joined.find(want)
    if at < 0:
        return []
    begin = next((i for off, i in offsets if off >= at), 0)
    seen, end = [], begin
    while end < len(pool):
        sec = pool[end].get("sec", 0)
        if sec not in seen:
            if len(seen) == 2:
                break
            seen.append(sec)
        end += 1
    return pool[begin:end]


def _largest_raw(pool, floor: int = 150):
    if len(pool) < floor * 2:
        return pool
    runs: dict[int, list] = {}
    for w in pool:
        runs.setdefault(w.get("sec", 0), []).append(w)
    best = max(runs.values(), key=len)
    return best if len(best) >= floor else pool


def _clip(kept, width: int) -> dict:
    top = max(0, min(w["y"] for w in kept) - 60)
    bottom = max(w["y"] + w["h"] for w in kept) + 60
    return {"x": 0, "y": top, "width": width,
            "height": min(bottom - top, MAX_CAPTURE)}


def named_section(read: Read, start: str, cap: int = 4000):
    """The part of a page that begins at `start` and ends where it does.

    `slice_between` with no end marker runs to the end of the document, which
    on a page holding a whole statute is tens of thousands of words: asking for
    section 107 that way returns everything after it. The heading index already
    records where each part stops, so the end comes from the page's own
    structure rather than from a second marker the asker has to supply.
    """
    chosen = slice_between(read.words, start)
    if not chosen:
        return []
    begin = len(read.words) - len(chosen)
    if read.sections:
        # A heading is its own element, so it gets its own index and the body
        # it introduces gets the next one. Stopping at the first change
        # therefore returns the heading alone: on section 107 that was eight
        # words, the title and nothing under it. Run on until a third index
        # appears, which is the following heading.
        seen, end = [], begin
        while end < len(read.words):
            sec = read.sections[end]
            if sec not in seen:
                if len(seen) == 2:
                    break
                seen.append(sec)
            end += 1
        chosen = read.words[begin:end]
    return chosen[:cap]


def largest_section(read: Read, floor: int = 150):
    """The longest run of words under one heading.

    Preferred over truncating a long page, which cuts wherever the count runs
    out. Chapter 1 of the Copyright Act is 60,280 words in one URL and reading
    it costs 29 seconds before anything is enumerated, while the section that
    is actually about this project is 184 words and costs 8 seconds end to end.
    Cheaper and a better unit at the same time.
    """
    if not read.sections or len(read.words) < floor * 2:
        return read.words
    runs: dict[int, list] = {}
    for word, sec in zip(read.words, read.sections, strict=False):
        runs.setdefault(sec, []).append(word)
    best = max(runs.values(), key=len)
    return best if len(best) >= floor else read.words


def read_page(url: str, png, *, width: int = 1100, height: int = 5000,
              section: str = "", least: int = 120, log=None):
    """Words for a page, from the DOM where it answers and OCR where it does not.

    The DOM is asked first and OCR is the fallback, not the other way round.
    A browser knows each word exactly and knows whether it sits in a nav or a
    footer; OCR guesses at both. OCR stays for the case the DOM cannot answer,
    such as a page that is an image of text.

    `least` is how many words make a page worth erasing, and it does two jobs:
    a DOM read thinner than this is treated as a failure worth falling back
    from, and a page still thinner than it after both readers is refused. A
    caller erasing one page on request can set it low; one publishing
    unattended should not.

    Returns `(words, screenshot path)`, or None when neither reader found
    enough. Both callers went through here rather than keeping a copy, because
    the copy that lived in the CLI stayed on OCR through every improvement the
    DOM path gained and quietly read a different page from the agent.
    """
    from pathlib import Path

    from . import source

    words = shot = None
    # The section is chosen inside the read, not after it. The capture is
    # clipped to whatever was chosen, so asking afterwards would clip to the
    # wrong part of the page and then look for the section in it.
    got = read(url, png, width=width, section=section)
    if got is not None:
        shot, words = Path(got.png), got.words
        if section and len(words) < least and log:
            log(f"section {section!r} gave {len(words)} words")

    if words is None or len(words) < least:
        if log:
            log(f"the DOM gave {0 if words is None else len(words)} words, "
                f"reading the page again with OCR")
        try:
            shot = source.screenshot(url, png, width=width, height=height)
            html = source.page_html(url)
            pairs = source.article_bigrams(html) if html else None
            ocr = source.from_image(shot, pairs=pairs)
            if len(ocr) < least and pairs is not None:
                ocr = source.from_image(shot)
            # The DOM path rejects a page that only answered with a bot
            # challenge. Reading the same page again with a different tool
            # would erase the challenge, which is what this guards against.
            if is_challenge([w.text for w in ocr]):
                return None
            if words is None or len(ocr) > len(words):
                words = ocr
        except Exception:  # noqa: BLE001 - OCR is already the fallback
            if words is None:
                return None

    # This check is what keeps the words and the image a matched pair, so it
    # cannot be relaxed on its own. OCR writes its screenshot over the DOM's
    # capture and at a different scale, while the words are only replaced when
    # OCR returns more of them, so "DOM words, OCR image" is a reachable
    # assignment and its boxes would land nowhere near the text. Every path
    # that reaches it is under `least` and refused here.
    if words is None or len(words) < least:
        return None
    return words, shot
