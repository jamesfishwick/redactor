"""Erase everything that isn't the poem.

Two looks, one invariant: the whole text column is covered first and the
surviving words are composited back from the original. Covering only the words
OCR reported would leave everything it missed -- UI glyphs, emoji, illustration
text -- sitting on the finished page.

`black` lays an opaque bar, which destroys the erased pixels outright.
`whiteout` imitates correction fluid on paper, after Mary Ruefle's *A Little
White Shadow*: strokes dragged along the line of type in a tone mixed from the
page's own background, ragged at their edges, thin enough in places that the
covered type ghosts through. That ghosting is the look rather than a flaw in
it, so the fluid is deliberately not fully opaque. GHOST_FLOOR bounds how far
it thins.

Kept words are restored in contiguous runs rather than one at a time, because
word-sized windows leave slivers inside a phrase and break the reading order a
reader relies on.
"""

from __future__ import annotations

import colorsys
import re
import subprocess
from pathlib import Path

STYLES = ("black", "whiteout")

GHOST_FLOOR = 0.90
"""Thinnest the fluid is allowed to get, as alpha.

Set by what stays unreadable rather than by taste. Fluid at 0.82 over white
leaves roughly a fifth of the original ink, which is light grey text and reads
fine; by 0.90, against the blurred ground below, what shows is a smudge with a
word's shape and none of its letters."""

MARGIN = 14
"""Paper included when sampling the background, so the sample is not starved
on a page whose text runs to the edge of its column."""

FLUID_PAD = 20
"""How far past the text the fluid is laid before its edge is torn.

The tear pulls the edge back by at most its own amplitude, so this bounds how
far it can retreat: as long as the pad exceeds the amplitude, no word the poem
does not keep can be uncovered by a stroke that happened to end short."""

TEAR = 16
"""Amplitude of the torn edge, in pixels. Must stay under FLUID_PAD."""

SAFETY = 4
"""Pixels held back from the gap between a kept run and its neighbour, to
absorb the difference between an OCR box and the ink it reports."""

BASELINE_TEXT = 12.0
"""Median word height, in pixels, of body type in a screenshot taken at one
device pixel per CSS pixel.

Every constant above is a pixel count tuned against that. Screenshot the same
page at twice the scale and they would all describe half as much of it, so the
brushwork would thin and the paper around a kept word would close up while the
type stayed the same size on screen. `text_unit` measures what the page
actually came out at, and the geometry scales by it."""


def text_unit(words, baseline: float = BASELINE_TEXT) -> float:
    """How big this page's type is against the size the constants assume."""
    placed = [w for w in words if w.placed]
    if not placed:
        return 1.0
    median = sorted(w.height for w in placed)[len(placed) // 2]
    return max(0.25, median / baseline)


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


def column(words, margin: int = MARGIN) -> tuple[int, int, int, int]:
    placed = [w for w in words if w.placed]
    if not placed:
        raise ValueError("render needs positioned words; OCR the screenshot first")
    return (min(w.left for w in placed) - margin,
            min(w.top for w in placed) - margin,
            max(w.left + w.width for w in placed) + margin,
            max(w.top + w.height for w in placed) + margin)


_HIST = re.compile(r"^\s*(\d+):\s*\((\d+),(\d+),(\d+)")


def page_background(png: Path, box, magick: str = "magick") -> tuple[int, int, int]:
    """The paper color, taken as the most common pixel in the text column.

    Type covers a small share of a column's area even on a dense page, so the
    mode is the background. A mean would be dragged toward grey by the very
    text about to be erased.
    """
    x0, y0, x1, y1 = box
    out = subprocess.run(
        [magick, str(png), "-crop", f"{x1 - x0}x{y1 - y0}+{x0}+{y0}", "+repage",
         "-depth", "8", "-format", "%c", "histogram:info:-"],
        capture_output=True, text=True, check=True).stdout
    best, top = (255, 255, 255), -1
    for line in out.splitlines():
        m = _HIST.match(line)
        if m and int(m.group(1)) > top:
            top = int(m.group(1))
            best = (int(m.group(2)), int(m.group(3)), int(m.group(4)))
    return best


def fluid_color(bg, desaturate: float = 0.25, lighten: float = 0.12) -> str:
    """Mix correction fluid for a given paper.

    Measured off Ruefle's page: paper is a saturated warm tan (237,212,188),
    the fluid over it near-neutral and lighter (244,240,242). So the fluid is
    the background with most of its color removed and its lightness raised,
    which keeps the two in one family on any page rather than dropping a
    foreign white onto it.

    The fluid is never darker than the paper, which is why the lightness
    clamps instead of falling back. Correction fluid sits on top of a page and
    catches more light than the page does, so a darker cover reverses what the
    eye reads: the covered column turns into a wash, the untouched paper
    around each kept word turns into the brightest thing on the page, and the
    erasure looks applied to the words that survived rather than to the ones
    that went.

    Paper already at white therefore gets fluid at white, and the stroke reads
    by its edges and its texture rather than by its color. A page can look
    blank where its words were taken out. It cannot look painted over the
    words that stayed.
    """
    h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in bg))
    s *= desaturate
    l = min(1.0, l + lighten)
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return "#%02x%02x%02x" % tuple(round(c * 255) for c in (r, g, b))


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def _seed(seed: int | None, bump: int = 0) -> list[str]:
    return [] if seed is None else ["-seed", str(seed + bump)]


def _ragged(size: tuple[int, int], jitter: int, dest: Path, magick: str,
            seed: int | None, bump: int = 0, sigma: float | None = None) -> Path:
    """A white field with a brushed edge, for use as an alpha mask.

    The boundary is pushed around by a displacement map of blurred noise,
    which wanders at the scale of the blur. Scattering the edge pixels instead
    -- `-spread` -- only frays it by a pixel or two, which disappears at any
    size worth looking at.

    The blur has to be scaled to the shape. Noise blurred wider than the shape
    is short is near enough constant across it, and a constant displacement
    map slides the whole rectangle sideways instead of disturbing its edge.

    The masks must carry no alpha of their own. A grayscale image with an
    alpha channel composites as transparency rather than as a mask, and
    CopyOpacity then silently reproduces the untouched rectangle.
    """
    w, h = size
    pad = jitter + 2
    sigma = max(1.5, sigma if sigma is not None else min(w, h) / 7)
    _run([magick, "-size", f"{w + 2 * pad}x{h + 2 * pad}", "xc:black",
          "-fill", "white",
          "-draw", f"rectangle {pad},{pad} {pad + w - 1},{pad + h - 1}",
          "(", "-size", f"{w + 2 * pad}x{h + 2 * pad}", *_seed(seed, bump),
          "xc:gray(50%)", "+noise", "Random",
          "-channel", "R", "-separate", "+channel", "-blur", f"0x{sigma:.1f}",
          "-auto-level", ")",
          "-compose", "Displace", "-define", f"compose:args={jitter}x{jitter}",
          "-composite", "-alpha", "off", "-colorspace", "Gray",
          "-blur", "0x0.6", "-threshold", "50%",
          "-crop", f"{w}x{h}+{pad}+{pad}", "+repage", str(dest)])
    return dest


def _brush(size: tuple[int, int], passes: int, dest: Path, magick: str,
           seed: int | None, unit: float = 1.0) -> Path:
    """Streaks along the line of type, full contrast, for the caller to level.

    Three scales of noise, because a brush leaves all three: whole passes that
    differ in how much fluid they carried, long thin places within a pass
    where it ran out, and a fine grain across everything. Motion blur orients
    the latter two. The gamma weights the field toward white, so thin places
    stay occasional instead of becoming the texture of the page.

    Returned at full contrast because the same field drives two things at very
    different amplitudes -- the fluid's opacity and its tone -- and levelling
    it here would flatten one of them.
    """
    w, h = size
    long_, fine = dest.with_name("_long.png"), dest.with_name("_fine.png")
    band = dest.with_name("_band.png")
    # One random value per pass, stretched to full width with no interpolation
    # so the passes stay flat and their boundaries stay hard, then displaced so
    # those boundaries wander the way the edge of a stroke does.
    _run([magick, "-size", f"1x{max(passes, 2)}", *_seed(seed, 331),
          "xc:gray(50%)", "+noise", "Random",
          "-channel", "R", "-separate", "+channel", "-auto-level",
          "-filter", "point", "-resize", f"{w}x{h}!",
          "(", "-size", f"{w}x{h}", *_seed(seed, 449), "xc:gray(50%)",
          "+noise", "Random", "-channel", "R", "-separate", "+channel",
          "-blur", f"0x{max(2.0, h / max(passes, 2) / 3):.1f}", "-auto-level", ")",
          "-compose", "Displace",
          "-define", f"compose:args=0x{max(2, h // max(passes, 2) // 2)}",
          "-composite", "-alpha", "off", "-colorspace", "Gray",
          "+level", "62%,100%", str(band)])
    _run([magick, "-size", f"{w}x{h}", *_seed(seed, 977), "xc:gray(50%)",
          "+noise", "Random", "-channel", "R", "-separate", "+channel",
          "-motion-blur", f"0x{60 * unit:.0f}+0", "-auto-level",
          "-gamma", "2.2", str(long_)])
    _run([magick, "-size", f"{w}x{h}", *_seed(seed, 613), "xc:gray(50%)",
          "+noise", "Random", "-channel", "R", "-separate", "+channel",
          "-motion-blur", f"0x{max(3.0, 9 * unit):.0f}+0", "-auto-level",
          "-gamma", "3.0", str(fine)])
    _run([magick, str(long_), str(fine), "-compose", "Multiply", "-composite",
          str(band), "-compose", "Multiply", "-composite",
          "-alpha", "off", "-colorspace", "Gray", "-auto-level", str(dest)])
    for tmp in (long_, fine, band):
        tmp.unlink(missing_ok=True)
    return dest


def _halo(span: list[int], words, pad: int,
          safety: int = SAFETY) -> tuple[int, int, int, int]:
    """The box restored for one kept run: the run, plus paper around it.

    The halo is what makes a run look brushed around rather than cut out, but
    it is bounded by the gap it has to stop in. Pad a run too far toward its
    neighbour and the neighbour shows -- a letter or two of a word the poem
    never kept, which reads as a mistake in the erasure rather than as a mark
    on it. So each side is clamped independently against the nearest word that
    could be exposed on that side.

    `safety` comes off the gap before it is halved, because the boxes being
    measured are OCR's and OCR's boxes are not the ink. A box that sits a few
    pixels inside its own glyphs makes an apparently safe half-gap reach them
    anyway, which is how a stray first letter gets left standing beside a kept
    run.
    """
    line = words[span[0]].line
    left = min(words[j].left for j in span)
    right = max(words[j].left + words[j].width for j in span)
    top = min(words[j].top for j in span)
    bottom = max(words[j].top + words[j].height for j in span)

    # Excluded by position, not by value: Word is a frozen dataclass, so a
    # word repeated on the page equals the one in the run and `index` would
    # find the wrong occurrence.
    held = set(span)
    placed = [w for i, w in enumerate(words) if w.placed and i not in held]
    row = [w for w in placed if w.line == line]
    before = [w.left + w.width for w in row if w.left + w.width <= left]
    after = [w.left for w in row if w.left >= right]
    # Only words that actually sit above or below this run can be uncovered by
    # a vertical pad; one further along an adjacent line cannot.
    over = [w for w in placed
            if w.line != line and w.left < right and w.left + w.width > left]
    above = [w.top + w.height for w in over if w.top + w.height <= top]
    below = [w.top for w in over if w.top >= bottom]

    def share(gap):
        return max(0, min(pad, (gap - safety) // 2))

    lp = pad if not before else share(left - max(before))
    rp = pad if not after else share(min(after) - right)
    tp = pad if not above else share(top - max(above))
    bp = pad if not below else share(min(below) - bottom)
    return left - lp, top - tp, right + rp, bottom + bp


def _black(png: Path, words, keep, dest: Path, box, pad: int, magick: str) -> Path:
    safety = round(SAFETY * text_unit(words))
    x0, y0, x1, y1 = box
    work = dest.parent
    base = work / "_base.png"
    _run([magick, str(png), "-fill", "black",
          "-draw", f"rectangle {x0},{y0} {x1},{y1}", str(base)])

    cmd = [magick, str(base)]
    for n, span in enumerate(_runs(sorted(keep), words)):
        left, top, right, bottom = _halo(span, words, pad, safety)
        chip = work / f"_chip{n}.png"
        _run([magick, str(png), "-crop",
              f"{right - left}x{bottom - top}+{left}+{top}", "+repage", str(chip)])
        cmd += [str(chip), "-geometry", f"+{left}+{top}", "-composite"]
    cmd.append(str(dest))
    _run(cmd)
    _cleanup(work)
    base.unlink(missing_ok=True)
    return dest


def _whiteout(png: Path, words, keep, dest: Path, box, pad: int, magick: str,
              seed: int | None, color: str | None) -> Path:
    # Two boxes, because they answer different questions. The paper is sampled
    # from the wider one, so a page whose text runs to the edge of its column
    # still offers enough background to find a mode in. The fluid is laid over
    # the tighter one, so that what is left unpainted around it reads as the
    # edge of the brushwork rather than as a crop.
    work = dest.parent
    fluid = color or fluid_color(page_background(png, box, magick))
    unit = text_unit(words)
    x0, y0, x1, y1 = column(words, round(FLUID_PAD * unit))
    w, h = x1 - x0, y1 - y0

    # One pass per line of type: the fluid was dragged along the lines, so
    # that is the scale its passes vary at, and the scale its edges wander at.
    placed = [w_ for w_ in words if w_.placed]
    passes = max(2, len({w_.line for w_ in placed}))
    line_h = max(6.0, sorted(w_.height for w_ in placed)[len(placed) // 2] * 1.4)
    streaks = _brush((w, h), passes, work / "_brush.png", magick, seed, unit)

    alpha = work / "_alpha.png"
    _run([magick, str(streaks), "+level", f"{GHOST_FLOOR * 100:.0f}%,100%",
          str(_ragged((w, h), round(TEAR * unit), work / "_edge.png", magick,
                      seed, sigma=line_h)),
          "-compose", "Multiply", "-composite",
          "-alpha", "off", "-colorspace", "Gray", str(alpha)])

    # Vary the fluid's own tone as well as its opacity. Opacity alone cannot
    # show a brush mark on a page whose background is already near the fluid's
    # color: there is nothing underneath for a thin place to reveal. The
    # overlay is centred on mid grey, so it lightens and darkens the fluid by
    # a few values either way and leaves its color alone.
    layer = work / "_fluid.png"
    _run([magick, "-size", f"{w}x{h}", f"xc:{fluid}",
          "(", str(streaks), "+level", "32%,68%", ")",
          "-compose", "Overlay", "-composite",
          str(alpha), "-alpha", "off", "-compose", "CopyOpacity", "-composite",
          str(layer)])

    # Blur the column before covering it. Fluid scatters what is under it, so
    # where the stroke runs thin the ghost should have a word's shape and not
    # its letters. Without this the thin places read as legible grey text.
    ghost = work / "_ghost.png"
    _run([magick, str(png), "-crop", f"{w}x{h}+{x0}+{y0}", "+repage",
          "-blur", f"0x{3 * unit:.1f}", str(ghost)])

    base = work / "_base.png"
    _run([magick, str(png),
          str(ghost), "-geometry", f"+{x0}+{y0}", "-composite",
          str(layer), "-geometry", f"+{x0}+{y0}", "-composite", str(base)])

    cmd = [magick, str(base)]
    for n, span in enumerate(_runs(sorted(keep), words)):
        left, top, right, bottom = _halo(span, words, pad, round(SAFETY * unit))
        cw, ch = right - left, bottom - top
        chip = work / f"_chip{n}.png"
        _run([magick, str(png), "-crop", f"{cw}x{ch}+{left}+{top}", "+repage",
              str(_ragged((cw, ch), round(5 * unit),
                          work / f"_cmask{n}.png", magick, seed, n + 1)),
              "-alpha", "off", "-compose", "CopyOpacity", "-composite", str(chip)])
        cmd += [str(chip), "-geometry", f"+{left}+{top}", "-composite"]
    cmd.append(str(dest))
    _run(cmd)
    _cleanup(work)
    return dest


def _cleanup(work: Path) -> None:
    for pattern in ("_chip*.png", "_cmask*.png"):
        for f in work.glob(pattern):
            f.unlink()
    for name in ("_alpha.png", "_brush.png", "_band.png", "_edge.png",
                 "_fluid.png", "_ghost.png", "_base.png"):
        (work / name).unlink(missing_ok=True)


def erase(png: Path, words, keep: list[int], dest: Path,
          pad: int = 3, magick: str = "magick", style: str = "whiteout",
          seed: int | None = None, color: str | None = None) -> Path:
    if style not in STYLES:
        raise ValueError(f"unknown style {style!r}; expected one of {STYLES}")
    unit = text_unit(words)
    box = column(words, round(MARGIN * unit))
    if style == "whiteout":
        return _whiteout(png, words, keep, dest, box,
                         round(max(pad, 7) * unit), magick, seed, color)
    return _black(png, words, keep, dest, box, round(pad * unit), magick)
