"""redactor — find an erasure poem in a web page and black out the rest."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import candidates as cand
from . import agent, compare, ladder, publish, rank, render, shapes, source, tagging
from .prosody import FORMS, METERS


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="redactor", description=__doc__)
    p.add_argument("url")
    p.add_argument("-f", "--form", default="auto",
                   choices=["auto"] + sorted(FORMS),
                   help="'auto' climbs to the hardest form the page admits")
    p.add_argument("-s", "--shape",
                   help="word-level form instead of a syllabic one: "
                        + ", ".join(shapes.NAMES)
                        + " (univocalic and lipogram take a letter, e.g. univocalic:o)")
    p.add_argument("-r", "--runs", type=int, default=2,
                   help="maximum contiguous spans of kept words (default 2)")
    p.add_argument("-o", "--out", type=Path, default=Path("out"))
    p.add_argument("--no-image", action="store_true",
                   help="read the page as text; skip screenshot and rendering")
    p.add_argument("--no-pos", action="store_true", help="skip part-of-speech pruning")
    p.add_argument("--no-llm", action="store_true", help="never call a model")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--publish", metavar="OWNER/REPO",
                   help="write the result to a repo through the GitHub connector")
    p.add_argument("--connection", metavar="ID",
                   help="GitHub connector id (discovered from the gateway if omitted)")
    p.add_argument("--show", type=int, default=5, help="how many candidates to print")
    p.add_argument("--compare", action="store_true",
                   help="print one poem per method with its candidate count")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    form = FORMS.get(args.form) if args.form != "auto" else None

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

    if args.shape:
        shape = shapes.build(args.shape)
        keep = shapes.longest(words, shape)
        print(f"shape: {shape.name} ({shape.rule})", file=sys.stderr)
        if len(keep) < 3:
            print(f"only {len(keep)} words survive that shape on this page",
                  file=sys.stderr)
            return 1
        print(f"kept: {len(keep)} of {len(words)} words", file=sys.stderr)
        print()
        for i in keep:
            print(words[i].text)
        if shot is not None:
            dest = render.erase(shot, words, keep, args.out / "erasure.png")
            print(f"\nwrote {dest}", file=sys.stderr)
        return 0

    tags = tri = None
    if not args.no_pos:
        nlp = tagging.load()
        if nlp is not None:
            tags = tagging.tag(nlp, words)
            tri = tagging.trigrams(nlp, " ".join(w.text for w in words))
            print(f"pos: {len(tri)} trigrams learned from the source", file=sys.stderr)

    if args.form == "auto":
        rung = ladder.climb(words, max_runs=args.runs, pos_tags=tags,
                            trigrams=tri)
        if rung is None:
            shape_used = next(
                (sh for sh in ladder.FALLBACK_SHAPES
                 if len(shapes.longest(words, shapes.build(sh))) >= 6), None)
            if shape_used is None:
                print("no form or shape fits this page", file=sys.stderr)
                return 1
            sh = shapes.build(shape_used)
            keep = shapes.longest(words, sh)
            print(f"no metrical or syllabic form fits; fell back to "
                  f"{sh.name} ({sh.rule})", file=sys.stderr)
            print()
            for i in keep:
                print(words[i].text)
            if shot is not None:
                dest = render.erase(shot, words, keep, args.out / "erasure.png")
                print(f"\nwrote {dest}", file=sys.stderr)
            return 0
        found = rung.candidates
        form_label = rung.form
        print(f"form: {ladder.describe(rung)}", file=sys.stderr)
    else:
        e = cand.Enumerator(words, form, max_runs=args.runs, pos_tags=tags,
                            allowed_trigrams=tri, meter=METERS.get(args.form))
        found = e.all()
        form_label = args.form
        print(f"candidates: {len(found)} ({args.form}, <={args.runs} runs)",
              file=sys.stderr)
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

    dest = None
    if shot is not None:
        dest = render.erase(shot, words, chosen.indices(), args.out / "erasure.png")
        print(f"\nwrote {dest}", file=sys.stderr)

    if args.publish:
        conn = args.connection or rank.discover("github")
        if not conn:
            print("no GitHub connector reachable; nothing published",
                  file=sys.stderr)
            return 0
        written = publish.publish(
            conn, args.publish, url=args.url, poem=chosen.render(words),
            form=form_label, pool=len(found), note=note, image=dest)
        for kind, link in written.items():
            print(f"published {kind}: {link}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
