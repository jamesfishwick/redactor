"""Get a page's words, with their positions on the rendered image when there is one.

Two paths, because they answer different questions. `from_html` is enough to
find a poem; `from_image` is required to black one out, since redaction needs
to know where each word physically sits.
"""

from __future__ import annotations

import csv
import io
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import requests

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
_TAGS = re.compile(r"(?is)<(script|style|svg|nav|footer|head)[^>]*>.*?</\1>")
_ANY = re.compile(r"(?s)<[^>]+>")


@dataclass(frozen=True)
class Word:
    text: str
    left: int = 0
    top: int = 0
    width: int = 0
    height: int = 0
    line: str = ""

    @property
    def placed(self) -> bool:
        return self.width > 0


def from_html(url: str, timeout: int = 30) -> list[Word]:
    import html as htmllib

    body = requests.get(url, headers={"User-Agent": UA}, timeout=timeout).text
    body = _TAGS.sub(" ", body)
    text = htmllib.unescape(_ANY.sub(" ", body))
    return [Word(w) for w in text.split() if normalize_ok(w)]


def normalize_ok(token: str) -> bool:
    return bool(re.search(r"[A-Za-z]", token))


def screenshot(url: str, png: Path, width: int = 1000, height: int = 1500,
               chrome: str | None = None, full_page: bool = False,
               scale: int = 2) -> Path:
    """Render the page. The explicit user-agent matters: a default headless
    string gets a bot challenge on a good fraction of real sites.

    `scale` is device pixels per CSS pixel, so the layout is unchanged and only
    the sampling gets finer. It pays twice. Tesseract reads small type more
    confidently with more pixels under it, and words it reports are words the
    erasure can both use and cover. The brush texture and the torn edges then
    have the resolution to read as marks rather than as stair steps.
    """
    exe = chrome or find_chrome()
    if exe is None:
        raise RuntimeError("no chrome/chromium binary found")
    args = [
        exe, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--no-sandbox", f"--window-size={width},{height}",
        f"--force-device-scale-factor={scale}",
        f"--user-agent={UA}", f"--screenshot={png}",
        "--virtual-time-budget=15000",
    ]
    if full_page:
        args.append("--screenshot-format=png")
    subprocess.run([*args, url], check=False, capture_output=True, timeout=180)
    if not png.exists():
        raise RuntimeError(f"screenshot failed for {url}")
    return png


def find_chrome() -> str | None:
    """Locate a usable browser binary.

    Playwright's download is checked before anything on PATH because Ubuntu
    ships `chromium-browser` as a snap stub, which refuses to run anywhere a
    snap daemon is absent, such as a container.
    """
    for pattern in ("chromium-*/chrome-linux*/chrome",
                    ("chromium_headless_shell-*/chrome-headless-shell-linux*"
                    "/chrome-headless-shell")):
        for hit in sorted(Path.home().glob(f".cache/ms-playwright/{pattern}")):
            if hit.exists():
                return str(hit)

    direct = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if Path(direct).exists():
        return direct
    for name in ("google-chrome", "google-chrome-stable", "chromium",
                 "chromium-browser"):
        found = shutil.which(name)
        if found and _runnable(found):
            return found
    return None


def _runnable(exe: str) -> bool:
    # A binary that cannot report a version is answer enough on its own.
    probe = subprocess.run([exe, "--version"], capture_output=True, text=True,
                           errors="replace", timeout=30, check=False)
    return "snap" not in (probe.stdout + probe.stderr).lower()


def article_bigrams(html: str) -> set[tuple[str, str]] | None:
    """Adjacent word pairs from the article body, as trafilatura sees it.

    OCR reports everything on the page: nav, logos, a judges list, a footer.
    Those fragments sit beside each other in reading order and yield erasures
    that hop between unrelated furniture.

    Pairs, not a vocabulary. A membership set is useless here, because `the`
    appears in any article and so every navigational `the` survives it. On one
    page that filter dropped 29 words out of 358 and changed no poem at all.
    A pair has to occur in the article in that order, so "Meet the Judges"
    only survives if the article itself says it.

    This guides OCR rather than replacing it: redaction needs coordinates and
    trafilatura has none.
    """
    try:
        import trafilatura
    except ImportError:
        return None
    text = trafilatura.extract(html, include_comments=False,
                               include_tables=False) or ""
    seq = [_bare(w) for w in text.split()]
    seq = [w for w in seq if w]
    pairs = {(seq[i], seq[i + 1]) for i in range(len(seq) - 1)}
    return pairs or None


def _bare(token: str) -> str:
    return re.sub(r"[^a-z0-9']", "", token.lower())


def page_html(url: str, chrome: str | None = None, timeout: int = 60) -> str | None:
    """The rendered DOM, via the same browser that takes the screenshot.

    trafilatura ships a fetcher, but it collects blocks on sites that serve
    headless clients differently, and the Guardian is one. The browser is
    already running for the screenshot, so reuse what it saw.
    """
    exe = chrome or find_chrome()
    if exe is None:
        return None
    try:
        out = subprocess.run(
            [exe, "--headless=new", "--disable-gpu", "--no-sandbox",
             f"--user-agent={UA}", "--virtual-time-budget=15000",
             "--dump-dom", url],
            capture_output=True, text=True, errors="replace",
            timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout or None


REQUIRED_COLUMNS = frozenset({
    "text", "conf", "left", "top", "width", "height",
    "block_num", "par_num", "line_num",
})
"""Every column `words_from_tsv` reads. Kept beside the reader that needs it."""

MIN_CONF = 55.0
"""Confidence below which a reported word is treated as noise, not text."""


def from_image(png: Path, min_conf: float = MIN_CONF,
               pairs: set[tuple[str, str]] | None = None) -> list[Word]:
    """OCR the rendered page into positioned words.

    Confidence filtering is not cosmetic. Below it, Tesseract reports text in
    illustrations and UI glyphs, and anything it fails to report survives the
    redaction as a stray mark.
    """
    # Tesseract exits non-zero on Leptonica warnings it has already recovered
    # from, so the exit code says nothing about whether the TSV is usable.
    # Judge it by whether rows came back, and decode leniently: stderr carries
    # raw bytes on some inputs.
    proc = subprocess.run(
        ["tesseract", str(png), "stdout", "tsv"],
        capture_output=True, text=True, errors="replace", check=False,
    )
    out = proc.stdout
    if out.count("\n") < 2:
        raise RuntimeError(f"tesseract produced no rows for {png}: {proc.stderr[:200]}")
    words = words_from_tsv(out, min_conf)
    if pairs is None:
        return words
    return _in_article(words, pairs)


def _in_article(words: list[Word], pairs: set[tuple[str, str]]) -> list[Word]:
    """Keep a word only where it joins a neighbour the article also joins.

    A word on its own proves nothing. A word that continues a pair the article
    contains is almost certainly body text, and chrome rarely reproduces the
    article's own phrasing.
    """
    bare = [_bare(w.text) for w in words]
    keep = [False] * len(words)
    for i in range(len(words) - 1):
        if (bare[i], bare[i + 1]) in pairs:
            keep[i] = keep[i + 1] = True
    return [w for w, k in zip(words, keep, strict=False) if k]


def words_from_tsv(tsv: str, min_conf: float = MIN_CONF) -> list[Word]:
    """Parse Tesseract's TSV into positioned words.

    Confidence filtering is not cosmetic. Below `min_conf`, Tesseract reports
    text in illustrations and UI glyphs, and a word it reports is a word the
    erasure can both use and cover.

    Tesseract never quotes its fields, but the words inside them are whatever
    was on the page. Under the default dialect a field beginning with a double
    quote opens a quoted field, and the rows after it are swallowed into that
    field until a closing quote or the end of input. They are not dropped. They
    arrive as one Word holding a blob of raw TSV at the opening word's
    position, and the words they contained never arrive at all.

    That matters downstream, since `render.erase` sizes its cover from the
    words it is handed, so anything past the last survivor stays legible on the
    finished page.

    QUOTE_NONE is what prevents it. quotechar=None changes nothing while
    QUOTE_NONE is there, and is set as a tripwire: remove QUOTE_NONE and
    DictReader raises at construction, where it would otherwise go on parsing
    with quoting restored.

    Malformed input is handled unevenly, by column. A row short of its columns
    loses its text and is dropped, as is a row whose conf will not parse.
    Unparseable geometry raises instead.
    """
    reader = csv.DictReader(io.StringIO(tsv), delimiter="\t",
                            quoting=csv.QUOTE_NONE, quotechar=None)
    # DictReader takes the first line as the header whatever it holds, so a
    # caller that strips Tesseract's header loses its first word and gets a
    # list one short with no error. Every column the loop dereferences is
    # checked, not just one: a missing conf is swallowed by the except below
    # and empties the list just as quietly, and a missing geometry column
    # would raise KeyError where this contract promises ValueError.
    missing = REQUIRED_COLUMNS - set(reader.fieldnames or ())
    if missing:
        raise ValueError(f"not a Tesseract TSV header, missing "
                         f"{sorted(missing)}: {reader.fieldnames}")

    words = []
    for row in reader:
        text = (row.get("text") or "").strip()
        if not text or not normalize_ok(text):
            continue
        try:
            conf = float(row["conf"])
        except (KeyError, ValueError):
            continue
        if conf < min_conf:
            continue
        words.append(Word(
            text=text,
            left=int(row["left"]), top=int(row["top"]),
            width=int(row["width"]), height=int(row["height"]),
            line=f"{row['block_num']}-{row['par_num']}-{row['line_num']}",
        ))
    return words
