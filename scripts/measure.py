#!/usr/bin/env python
"""Regenerate the measured tables in README.md.

Every count in the README comes from here, so a claim about this code is
checked against this code rather than typed next to it. The tables were hand
measured once and went stale silently: the difficulty table named a page it
no longer matched, and nothing could have caught that, because a number in
prose has no basis attached and nothing re-derives it.

Two tables, with different reach. `constraints` is deterministic and offline,
so a test can assert the README still agrees with it. `forms` reads a live
page, so its basis (the URL and the word count it saw) is printed into the
table itself and the numbers move when the page does.

    scripts/measure.py constraints --write README.md
    scripts/measure.py forms https://example.com/page
    scripts/measure.py forms <url> | scripts/measure.py splice forms README.md
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from redactor.candidates import Enumerator, Space  # noqa: E402
from redactor.prosody import FORMS, METERS, SCHEMES, rhyme_classes  # noqa: E402
from redactor.source import Word  # noqa: E402

# The opening of Moby-Dick, stripped of punctuation. Short enough that the
# unconstrained count is reachable and long enough that it runs to eleven
# figures, which is the whole point of the table it feeds.
MOBY = """Call me Ishmael Some years ago never mind how long precisely having
little or no money in my purse and nothing particular to interest me on shore
I thought I would sail about a little and see the watery part of the world"""

# How many rhyme classes a rhymed form tries before giving up, matching the
# ladder's own default so the table reports what the tool would find.
RHYME_TRIES = 25


def _words(text: str) -> list[Word]:
    return [Word(t) for t in text.split()]


def constraints_table() -> str:
    """What each constraint leaves of one paragraph's haiku."""
    from redactor import tagging

    words = _words(MOBY)
    form = FORMS["haiku"]
    loose = len(words)

    rows = [("none", Enumerator(words, form, max_runs=loose).count())]

    nlp = tagging.load()
    if nlp is None:
        print("warning: spaCy or en_core_web_sm missing, skipping the POS row",
              file=sys.stderr)
        tags = tri = None
    else:
        tags = tagging.tag(nlp, words)
        tri = tagging.trigrams(nlp, " ".join(w.text for w in words))
        rows.append(("POS trigram",
                     Enumerator(words, form, max_runs=loose, pos_tags=tags,
                                allowed_trigrams=tri).count()))

    rows.append(("contiguity, 3 runs",
                 Enumerator(words, form, max_runs=3).count()))
    rows.append(("contiguity, 2 runs",
                 Enumerator(words, form, max_runs=2).count()))
    if tri is not None:
        rows.append(("contiguity 2 + POS trigram",
                     Enumerator(words, form, max_runs=2, pos_tags=tags,
                                allowed_trigrams=tri).count()))

    width = max(len(name) for name, _ in rows)
    # The trigram vocabulary is the parameter the first version of this table
    # left unstated, and it is the whole difference between a filter that
    # cuts to thousands and one that cuts to millions. The tool learns it
    # from whatever it is erasing, so a short source makes a harsh filter.
    learned = (f" Trigrams are learned from the paragraph itself, as the tool "
               f"does, giving a vocabulary of {len(tri)}." if tri else "")
    out = [f"Measured on the {len(words)}-word opening of _Moby-Dick_, "
           f"counting 5/7/5 erasures.{learned}",
           "",
           f"| {'constraint':<{width}} | candidates     |",
           f"| {'-' * width} | -------------- |"]
    out += [f"| {name:<{width}} | {count:>14,} |" for name, count in rows]
    return "\n".join(out)


def forms_table(url: str) -> str:
    """How rarely a page admits each form, which is what ranks the ladder."""
    import tempfile

    from redactor import dom

    with tempfile.TemporaryDirectory() as tmp:
        got = dom.read(url, pathlib.Path(tmp) / "page.png")
    words = got.words

    rows = []
    for name in ("quatrain", "couplet", "ballad", "pentameter", "tetrameter",
                 "fib", "cinquain", "tanka", "lune", "haiku"):
        form = FORMS[name]
        # The denominator is every erasure fitting the form by syllable count,
        # so the fraction isolates what the stress and rhyme add.
        fits = Space(words, form, max_runs=2).count()
        scheme = SCHEMES.get(name)
        if scheme:
            classes = sorted(rhyme_classes(words).items(),
                             key=lambda kv: -len(kv[1]))[:RHYME_TRIES]
            # Summing is exact rather than an estimate: a poem's last word has
            # exactly one rhyming part, so the classes partition the space.
            admits = sum(
                Space(words, form, max_runs=2, meter=METERS.get(name),
                      scheme=scheme, parts={"A": part}).count()
                for part, _ in classes)
            kind = f"{'/'.join(str(n) for n in form)}, rhymed {scheme}"
        else:
            admits = Space(words, form, max_runs=2,
                           meter=METERS.get(name)).count()
            kind = ("%s, alternating stress" % "/".join(str(n) for n in form)
                    if METERS.get(name)
                    else "/".join(str(n) for n in form))
        pct = 100.0 * admits / fits if fits else 0.0
        rows.append((name, admits, fits, pct, kind))

    kw = max(len(k) for _, _, _, _, k in rows)
    nw = max(len(n) for n, _, _, _, _ in rows) + 2
    out = [f"Measured on [{url}]({url}), {len(words):,} words of article.",
           "",
           f"| {'form':<{nw}} | admits  | of             | {'shape':<{kw}} |",
           f"| {'-' * nw} | ------- | -------------- | {'-' * kw} |"]
    for name, admits, fits, pct, kind in rows:
        shown = f"{pct:.2f}%" if pct >= 0.01 or pct == 0 else "<0.01%"
        out.append(f"| {'`' + name + '`':<{nw}} | {shown:>7} | "
                   f"{fits:>14,} | {kind:<{kw}} |")
    out.append("")
    out.append(f"Regenerate with `scripts/measure.py forms {url}`.")
    return "\n".join(out)


def splice(readme: pathlib.Path, name: str, body: str) -> None:
    """Replace one marked region, leaving the rest of the file alone."""
    begin, end = f"<!-- measured:{name} -->", f"<!-- /measured:{name} -->"
    text = readme.read_text()
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.S)
    if not pattern.search(text):
        raise SystemExit(f"{readme}: no region marked {begin} ... {end}")
    readme.write_text(pattern.sub(f"{begin}\n\n{body}\n\n{end}", text))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("constraints", help="what each constraint leaves")
    c.add_argument("--write", type=pathlib.Path)

    f = sub.add_parser("forms", help="how rarely a page admits each form")
    f.add_argument("url")
    f.add_argument("--write", type=pathlib.Path)

    s = sub.add_parser("splice", help="write a table read from stdin")
    s.add_argument("name")
    s.add_argument("readme", type=pathlib.Path)

    args = ap.parse_args()
    if args.cmd == "splice":
        splice(args.readme, args.name, sys.stdin.read().strip())
        return

    body = (constraints_table() if args.cmd == "constraints"
            else forms_table(args.url))
    if args.write:
        splice(args.write, args.cmd, body)
    else:
        print(body)


if __name__ == "__main__":
    main()
