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
               chrome: str | None = None, full_page: bool = False) -> Path:
    """Render the page. The explicit user-agent matters: a default headless
    string gets a bot challenge on a good fraction of real sites."""
    exe = chrome or find_chrome()
    if exe is None:
        raise RuntimeError("no chrome/chromium binary found")
    args = [
        exe, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--no-sandbox", f"--window-size={width},{height}",
        f"--user-agent={UA}", f"--screenshot={png}",
        "--virtual-time-budget=15000",
    ]
    if full_page:
        args.append("--screenshot-format=png")
    subprocess.run(args + [url], check=False, capture_output=True, timeout=180)
    if not png.exists():
        raise RuntimeError(f"screenshot failed for {url}")
    return png


def find_chrome() -> str | None:
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "chromium", "chromium-browser", "google-chrome", "google-chrome-stable",
    ]
    for c in candidates:
        if c.startswith("/") and Path(c).exists():
            return c
        found = shutil.which(c)
        if found:
            return found
    return None


def from_image(png: Path, min_conf: float = 55.0) -> list[Word]:
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
        capture_output=True, text=True, errors="replace",
    )
    out = proc.stdout
    if out.count("\n") < 2:
        raise RuntimeError(f"tesseract produced no rows for {png}: {proc.stderr[:200]}")
    words = []
    for row in csv.DictReader(io.StringIO(out), delimiter="\t"):
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
