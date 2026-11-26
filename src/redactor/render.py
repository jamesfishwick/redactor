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


def erase(png: Path, words, keep: list[int], dest: Path,
          pad: int = 3, magick: str = "magick") -> Path:
    placed = [w for w in words if w.placed]
    if not placed:
        raise ValueError("render needs positioned words; OCR the screenshot first")

    x0 = min(w.left for w in placed) - 14
    x1 = max(w.left + w.width for w in placed) + 14
    y0 = min(w.top for w in placed) - 14
    y1 = max(w.top + w.height for w in placed) + 14

    work = dest.parent
    base = work / "_base.png"
    subprocess.run([magick, str(png), "-fill", "black",
                    "-draw", f"rectangle {x0},{y0} {x1},{y1}", str(base)], check=True)

    cmd = [magick, str(base)]
    for n, span in enumerate(_runs(sorted(keep), words)):
        left = min(words[j].left for j in span) - pad
        right = max(words[j].left + words[j].width for j in span) + pad
        top = min(words[j].top for j in span) - pad
        bottom = max(words[j].top + words[j].height for j in span) + pad
        chip = work / f"_chip{n}.png"
        subprocess.run([magick, str(png), "-crop",
                        f"{right - left}x{bottom - top}+{left}+{top}",
                        "+repage", str(chip)], check=True)
        cmd += [str(chip), "-geometry", f"+{left}+{top}", "-composite"]
    cmd.append(str(dest))
    subprocess.run(cmd, check=True)

    for f in work.glob("_chip*.png"):
        f.unlink()
    base.unlink(missing_ok=True)
    return dest
