"""`redactor-agent` — answer a request if one is waiting, else erase something new.

Polling and publishing are separate rates on purpose. MetaFilter posts about
every 90 minutes and the feed holds 18 hours, so a two-hour check never misses
one and costs 18KB. Publishing at that rate would put twelve entries a day in
the gallery, which is a log rather than something anybody scrolls, so a run
publishes at most one.

Choosing which link to erase is deliberately arbitrary. Ranking pages before
erasing them would spend inference to decide what to spend inference on, and
the community has already done the choosing by posting it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import agent, publish, rank, render, sources


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="redactor-agent", description=__doc__)
    p.add_argument("--repo", default="jamesfishwick/redactor")
    p.add_argument("--connection", help="GitHub connector id")
    p.add_argument("-o", "--out", type=Path, default=Path("/tmp/redactor"))
    p.add_argument("--runs", type=int, default=2)
    p.add_argument("--no-llm", action="store_true")
    p.add_argument("--style", default="whiteout", choices=sorted(render.STYLES),
                   help="how the erased words are covered: 'whiteout' brushes "
                        "correction fluid mixed from the page, 'black' lays "
                        "an opaque bar")
    p.add_argument("--fluid", metavar="COLOR",
                   help="override the whiteout color; by default it is mixed "
                        "from the page")
    p.add_argument("--dry-run", action="store_true",
                   help="say what it would do and publish nothing")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    conn = args.connection or rank.discover("github")
    if not conn:
        print("no GitHub connector reachable", file=sys.stderr)
        return 1

    try:
        kind, jobs = agent.next_job(conn, args.repo)
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 0

    if args.dry_run:
        for j in jobs:
            print(f"{kind}: {j.url}", file=sys.stderr)
        return 0

    got = job = None
    for candidate in jobs:
        print(f"{kind}: {candidate.url}", file=sys.stderr)
        got = agent.erase_page(candidate.url, out=args.out, runs=args.runs,
                               section=getattr(candidate, "section", ""))
        if got is not None:
            job = candidate
            break
        print("  no usable text; trying the next one", file=sys.stderr)

    if got is None:
        if kind == "request":
            agent.decline(conn, args.repo, jobs[0].number,
                          agent.why_not(jobs[0].url))
            print("declined; issue left open", file=sys.stderr)
        else:
            print(f"nothing usable in {len(jobs)} candidates", file=sys.stderr)
        return 0

    url = job.url
    via = getattr(job, "via", "")
    asker = getattr(job, "asker", "")
    words, rung, shot = got
    note = ""
    chosen = None
    if not args.no_llm:
        picked = rank.by_model(rung.candidates, words, url)
        if picked:
            chosen, note = picked
    if chosen is None:
        chosen = rank.arbitrary(rung.candidates)

    image = render.erase(shot, words, chosen.indices(),
                         args.out / "erasure.png", style=args.style,
                         seed=args.seed, color=args.fluid)
    poem = chosen.render(words)

    written = publish.publish(conn, args.repo, url=url, poem=poem,
                              form=rung.form, pool=rung.pool, note=note,
                              image=image, via=via)
    print("\n" + poem + "\n", file=sys.stderr)
    for what, link in written.items():
        print(f"{what}: {link}", file=sys.stderr)

    if kind == "request":
        # Use the URL publish actually wrote, not one rebuilt from the folder
        # name. A failed image upload otherwise sends the asker a broken image,
        # and a failed page upload sends them a path with nothing in it.
        body = publish.page(url=url, poem=poem, form=rung.form, pool=rung.pool,
                            note=note, via=via,
                            image_url=written.get("image_raw"))
        agent.answer(conn, args.repo, job.number,
                     f"@{asker} here you go.\n\n{body}")
        print(f"answered #{job.number}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
