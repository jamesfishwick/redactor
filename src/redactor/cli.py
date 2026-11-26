"""redactor — find an erasure poem in a web page and black out the rest."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import candidates as cand
from . import compare, rank, render, source, tagging
from .prosody import FORMS


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="redactor", description=__doc__)
    p.add_argument("url")
    p.add_argument("-f", "--form", default="haiku", choices=sorted(FORMS))
    p.add_argument("-r", "--runs", type=int, default=2,
                   help="maximum contiguous spans of kept words (default 2)")
    p.add_argument("-o", "--out", type=Path, default=Path("out"))
    p.add_argument("--no-image", action="store_true",
                   help="read the page as text; skip screenshot and rendering")
    p.add_argument("--no-pos", action="store_true", help="skip part-of-speech pruning")
    p.add_argument("--no-llm", action="store_true", help="never call a model")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--show", type=int, default=5, help="how many candidates to print")
    p.add_argument("--compare", action="store_true",
                   help="print one poem per method with its candidate count")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    form = FORMS[args.form]

    if args.no_image:
        words = source.from_html(args.url)
        shot = None
    else:
        shot = source.screenshot(args.url, args.out / "page.png")
        words = source.from_image(shot)
    print(f"source: {len(words)} words from {args.url}", file=sys.stderr)
    if len(words) < 20:
        print("too little text to erase", file=sys.stderr)
        return 1

    tags = tri = None
    if not args.no_pos:
        nlp = tagging.load()
        if nlp is not None:
            tags = tagging.tag(nlp, words)
            tri = tagging.trigrams(nlp, " ".join(w.text for w in words))
            print(f"pos: {len(tri)} trigrams learned from the source", file=sys.stderr)

    e = cand.Enumerator(words, form, max_runs=args.runs,
                        pos_tags=tags, allowed_trigrams=tri)
    found = e.all()
    print(f"candidates: {len(found)} ({args.form}, <={args.runs} runs)", file=sys.stderr)
    if not found:
        print("no erasure of this page satisfies that form; try --runs 3",
              file=sys.stderr)
        return 1

    if args.compare:
        attempts = compare.run(words, form, max_runs=args.runs, pos_tags=tags,
                               trigrams=tri, seed=args.seed, url=args.url,
                               use_model=not args.no_llm)
        print(compare.report(attempts, words))
        best = next((a.poem for a in reversed(attempts) if a.poem), None)
        if shot is not None and best is not None:
            dest = render.erase(shot, words, best.indices(), args.out / "erasure.png")
            print(f"\nwrote {dest}", file=sys.stderr)
        return 0

    note = ""
    chosen = None
    if not args.no_llm:
        picked = rank.by_model(found, words, args.url)
        if picked:
            chosen, note = picked
            print("ranked by model", file=sys.stderr)
    if chosen is None:
        chosen = rank.arbitrary(found, args.seed)
        print("no model available; chose arbitrarily", file=sys.stderr)

    for c in found[: args.show]:
        print("\n" + c.render(words))
    print("\n--- chosen ---\n" + chosen.render(words))
    if note:
        print("\n" + note)

    if shot is not None:
        dest = render.erase(shot, words, chosen.indices(), args.out / "erasure.png")
        print(f"\nwrote {dest}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
