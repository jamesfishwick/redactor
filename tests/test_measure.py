"""The README's measured tables must still agree with the code.

Only the rows that no model touches are pinned here. The POS row moves with
the spaCy model version, so asserting it would fail on an upgrade that broke
nothing, and the staleness this guards against is the kind where the code
changed and the prose did not.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
README = ROOT / "README.md"


def _measure():
    spec = importlib.util.spec_from_file_location(
        "measure", ROOT / "scripts" / "measure.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _region(name: str) -> str:
    text = README.read_text()
    found = re.search(
        re.escape(f"<!-- measured:{name} -->") + r"(.*?)"
        + re.escape(f"<!-- /measured:{name} -->"), text, re.S)
    assert found, f"README has no region marked measured:{name}"
    return found.group(1)


def _rows(body: str) -> dict[str, int]:
    out = {}
    for line in body.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 2 and cells[1].replace(",", "").isdigit():
            out[cells[0]] = int(cells[1].replace(",", ""))
    return out


class TestReadmeTables:
    def test_constraints_region_is_current(self):
        measure = _measure()
        from redactor.candidates import Enumerator
        from redactor.prosody import FORMS

        words = measure._words(measure.MOBY)
        published = _rows(_region("constraints"))
        assert published, "the constraints table has no rows"

        for label, runs in (("none", len(words)),
                            ("contiguity, 3 runs", 3),
                            ("contiguity, 2 runs", 2)):
            assert label in published, f"{label} row missing from README"
            fresh = Enumerator(words, FORMS["haiku"], max_runs=runs).count()
            assert published[label] == fresh, (
                f"README says {published[label]:,} for {label!r}, the code "
                f"gives {fresh:,}. Run scripts/measure.py constraints "
                f"--write README.md")

    def test_forms_region_names_its_basis(self):
        # The counts move with the page, so they cannot be pinned. What can be
        # pinned is that the table says which page and how many words, which
        # is the omission that made the first version of it unfalsifiable.
        body = _region("forms")
        assert re.search(r"https?://", body), "forms table names no page"
        assert re.search(r"[\d,]+ words of article", body), (
            "forms table does not say how many words it measured")


@pytest.mark.parametrize("name", ["constraints", "forms"])
def test_region_is_not_empty(name):
    assert _region(name).strip(), f"measured:{name} region is empty"
