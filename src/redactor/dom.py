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
  const CHROME = 'nav,header,footer,aside,form,[role=navigation],' +
                 '[role=banner],[role=contentinfo],[role=search]';
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
    const furniture = !!parent.closest(CHROME);
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


def read(url: str, png, *, width: int = 1100, height: int = 1400,
         timeout: int = 45000, settle: int = 2500,
         body_only: bool = True) -> Read | None:
    """Screenshot the page and return its words with exact boxes.

    The screenshot is full-page so that every box the DOM reports falls inside
    the image. A viewport-sized one would leave most words pointing off the
    bottom of it.

    Waits for `domcontentloaded` and then a fixed settle, not for
    `networkidle`. An ad-heavy page keeps connections open indefinitely, so
    networkidle never fires and the read times out on a page that rendered
    fine seconds earlier. The settle covers content that arrives late.
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
            raw = page.evaluate(EXTRACT)
            title = page.title()
            page.screenshot(path=str(png), full_page=True)
        except Exception:
            browser.close()
            return None
        browser.close()

    words, sections = [], []
    for w in raw:
        if body_only and w["chrome"]:
            continue
        words.append(Word(
            text=w["t"], left=w["x"], top=w["y"],
            width=w["w"], height=w["h"],
            # Words share a line when they share a parent element and a
            # baseline, which is what a visual run has to respect.
            line=f"{w['tag']}-{w['y']}",
        ))
        sections.append(w.get("sec", 0))
    return Read(words, str(png), title, sections) if words else None


def largest_section(read: "Read", floor: int = 150):
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
    for word, sec in zip(read.words, read.sections):
        runs.setdefault(sec, []).append(word)
    best = max(runs.values(), key=len)
    return best if len(best) >= floor else read.words
