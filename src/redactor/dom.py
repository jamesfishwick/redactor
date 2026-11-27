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
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walk.nextNode())) {
    const parent = node.parentElement;
    if (!parent || SKIP.has(parent.tagName)) continue;
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
        chrome: furniture, tag: parent.tagName,
      });
    }
  }
  return out;
}"""


@dataclass(frozen=True)
class Read:
    words: list        # redactor.source.Word
    png: str           # full-page screenshot the boxes refer to
    title: str


def read(url: str, png, *, width: int = 1100, height: int = 1400,
         timeout: int = 60000, body_only: bool = True) -> Read | None:
    """Screenshot the page and return its words with exact boxes.

    The screenshot is full-page so that every box the DOM reports falls inside
    the image. A viewport-sized one would leave most words pointing off the
    bottom of it.
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
            page.goto(url, wait_until="networkidle", timeout=timeout)
            raw = page.evaluate(EXTRACT)
            title = page.title()
            page.screenshot(path=str(png), full_page=True)
        except Exception:
            browser.close()
            return None
        browser.close()

    words = []
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
    return Read(words, str(png), title) if words else None
