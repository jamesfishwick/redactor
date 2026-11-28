"""Black out everything that isn't the poem.

Drawing bars over the erased words leaves anything OCR failed to read — UI
glyphs, emoji, illustration text — visible on the finished page. So the whole
text column goes black first and the surviving words are composited back from
the original. Nothing survives by accident.

Kept words are restored in contiguous runs rather than one at a time, because
word-sized windows leave black slivers inside a phrase and break the reading
order a reader relies on.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _runs(indices: list[int], words) -> list[list[int]]:
    """Group kept indices into spans that are adjacent in the source and share
    a line on the page."""
    out: list[list[int]] = []
    for i in indices:
        if out and i == out[-1][-1] + 1 and words[i].line == words[out[-1][-1]].line:
            out[-1].append(i)
        else:
            out.append([i])
    return out


# The DOM reader labels a line by the element that holds it, so a line id
# beginning with a tag name says the words were measured rather than read off
# a picture. OCR labels lines by block and paragraph number instead.
DOM_LINE_PREFIXES = tuple(f"{t}-" for t in (
    "P", "H1", "H2", "H3", "H4", "H5", "H6", "LI", "SPAN", "A", "DIV",
    "EM", "STRONG", "B", "I", "BLOCKQUOTE", "TD", "TH", "FIGCAPTION",
    "LABEL", "SMALL", "CODE", "PRE", "DD", "DT", "CAPTION"))


def _bands(kept, words, slack: int = 2):
    """Horizontal strips of the page that hold a surviving word.

    A poem taken from a long document lands in a few lines separated by
    thousands of pixels of nothing. Keeping that space is faithful to the page
    and unreadable: the two halves of one stanza ended up 2,000 pixels apart.
    The strips are stacked instead, so what remains is every line that still
    has words on it and none of the emptiness between.
    """
    rows = sorted({(w.top, w.top + w.height) for w in kept})
    merged = [list(rows[0])]
    for top, bottom in rows[1:]:
        if top <= merged[-1][1] + slack:
            merged[-1][1] = max(merged[-1][1], bottom)
        else:
            merged.append([top, bottom])
    return merged


def _height(png: Path, magick: str) -> int:
    out = subprocess.run([magick, "identify", "-format", "%h", str(png)],
                         capture_output=True, text=True, errors="replace")
    try:
        return int((out.stdout or "").strip().splitlines()[0])
    except (AttributeError, ValueError, IndexError):
        # Unknown height. The band clamp is a guard, not a requirement, so a
        # render still proceeds without it rather than failing on the probe.
        return 0


def erase(png: Path, words, keep: list[int], dest: Path,
          pad: int = 2, margin: int = 16, mode: str = "whiteout",
          magick: str = "magick") -> Path:
    """Black out the region these words occupy, keeping only `keep`.

    Two modes. `whiteout` is the canonical form and the default: the page as
    it was, with a bar over every word removed. It is only honest when every
    removed word is known, which means the words came from the DOM. OCR
    reports only what it managed to read, so a word it missed gets no bar and
    stays legible on a page that claims to be erased. `blackout` inverts it,
    blacking the field and letting the survivors show through, which is safe
    whatever the words came from and reads better when the poem is a few words
    in a long document.

    The frame is the span of the surviving words, not of the whole page or
    even the whole section. Everything above the first and below the last is
    black with nothing in it, so including it adds height and no reading. A
    full-page capture of a long document is also enormous on its own: one
    chapter of the Copyright Act renders 103,102 pixels tall, which ImageMagick
    refuses outright.

    Width stays at the text column so the erased lines keep their measure. A
    poem squeezed to the width of its own words would lose the blacked-out
    space it was taken out of.
    """
    placed = [w for w in words if w.placed]
    if not placed:
        raise ValueError("render needs positioned words; read the page first")
    kept = [words[i] for i in keep if words[i].placed]
    if not kept:
        raise ValueError("nothing to keep")
    if mode == "whiteout" and not all(w.line.startswith(DOM_LINE_PREFIXES)
                                      for w in placed):
        mode = "blackout"

    x0 = max(0, min(w.left for w in placed) - margin)
    x1 = max(w.left + w.width for w in placed) + margin
    cw = x1 - x0

    work = dest.parent
    keepset = set(keep)
    page_h = _height(png, magick)
    strips = []
    for n, (top, bottom) in enumerate(_bands(kept, words)):
        # A band below the capture crops to a 1x1 image, which ImageMagick
        # reports as success, so a whole line of the poem vanished from the
        # render with nothing raised anywhere.
        if page_h and top >= page_h:
            raise ValueError(
                f"a kept word sits at y={top}, below the {page_h}px capture")
        bottom = min(bottom, page_h) if page_h else bottom
        h = bottom - top
        if h <= 0:
            continue
        strip = work / f"_strip{n}.png"
        on_strip = [i for i, w in enumerate(words)
                    if w.placed and top <= w.top < bottom]

        if mode == "whiteout":
            # Keep the strip and bar over everything on it that went.
            draws = []
            for i in on_strip:
                if i in keepset:
                    continue
                w = words[i]
                draws += ["-draw", f"rectangle {w.left - x0 - pad},0 "
                                   f"{w.left + w.width - x0 + pad},{h}"]
            subprocess.run([magick, str(png), "-crop", f"{cw}x{h}+{x0}+{top}",
                            "+repage", "-fill", "black", *draws, str(strip)],
                           check=True)
        else:
            subprocess.run([magick, str(png), "-crop", f"{cw}x{h}+{x0}+{top}",
                            "+repage", "-fill", "black",
                            "-draw", f"rectangle 0,0 {cw},{h}", str(strip)],
                           check=True)
            cmd = [magick, str(strip)]
            survivors = [i for i in sorted(keepset) if i in set(on_strip)]
            for m, span in enumerate(_runs(survivors, words)):
                left = min(words[j].left for j in span) - pad
                right = max(words[j].left + words[j].width for j in span) + pad
                chip = work / f"_chip{n}_{m}.png"
                subprocess.run([magick, str(png), "-crop",
                                f"{right - left}x{h}+{left}+{top}",
                                "+repage", str(chip)], check=True)
                cmd += [str(chip), "-geometry", f"+{left - x0}+0", "-composite"]
            cmd.append(str(strip))
            subprocess.run(cmd, check=True)
        strips.append(str(strip))

    subprocess.run([magick] + strips + ["-append", str(dest)], check=True)
    for f in list(work.glob("_chip*.png")) + list(work.glob("_strip*.png")):
        f.unlink(missing_ok=True)
    return dest
