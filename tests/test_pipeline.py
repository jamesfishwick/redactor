import shutil
import subprocess
from pathlib import Path

import pytest

from redactor import render
from redactor.candidates import Candidate, Enumerator, is_subsequence
from redactor.prosody import syllables
from redactor.source import Word

MOBY = """Call me Ishmael Some years ago never mind how long precisely having
little or no money in my purse and nothing particular to interest me on shore
I thought I would sail about a little and see the watery part of the world""".split()


def words(tokens):
    return [Word(t) for t in tokens]


class TestSyllables:
    @pytest.mark.parametrize("word,n", [
        ("about", 2), ("ago", 2), ("money", 2), ("watery", 3),
        ("interest", 2), ("particular", 4), ("I", 1),
    ])
    def test_cmu_counts(self, word, n):
        assert syllables(word) == n

    def test_unknown_word_falls_back(self):
        assert syllables("zblorgenflap") >= 1

    def test_punctuation_only_is_zero(self):
        assert syllables("---") == 0


class TestSubsequence:
    def test_accepts_deletion(self):
        assert is_subsequence(["Call", "Ishmael", "world"], MOBY)

    def test_rejects_reordering(self):
        assert not is_subsequence(["Ishmael", "Call"], MOBY)

    def test_rejects_invented_words(self):
        assert not is_subsequence(["Call", "whale"], MOBY)

    def test_rejects_reuse(self):
        assert not is_subsequence(["world", "world"], MOBY)


class TestEnumerator:
    def test_every_candidate_matches_the_form(self):
        found = Enumerator(words(MOBY), (5, 7, 5), max_runs=2).all()
        assert found
        for c in found:
            counts = [sum(syllables(MOBY[i]) for i in line) for line in c.lines]
            assert counts == [5, 7, 5]

    def test_every_candidate_is_a_subsequence(self):
        for c in Enumerator(words(MOBY), (5, 7, 5), max_runs=2).all()[:50]:
            assert is_subsequence([MOBY[i] for i in c.indices()], MOBY)

    def test_contiguity_shrinks_the_space_hard(self):
        loose = Enumerator(words(MOBY), (5, 7, 5), max_runs=99).count()
        tight = Enumerator(words(MOBY), (5, 7, 5), max_runs=2).count()
        assert tight < loose / 1000

    def test_one_run_means_an_unbroken_span(self):
        for c in Enumerator(words(MOBY), (5, 7, 5), max_runs=1).all():
            idx = c.indices()
            assert idx == list(range(idx[0], idx[0] + len(idx)))

    def test_count_agrees_with_enumeration(self):
        e = Enumerator(words(MOBY), (5, 7, 5), max_runs=1)
        assert e.count() == len(e.all())

    def test_impossible_form_yields_nothing(self):
        assert Enumerator(words(["cat"]), (5, 7, 5), max_runs=2).all() == []


class TestCandidate:
    def test_render_joins_lines(self):
        c = Candidate(((0, 1), (2,)), runs=1)
        assert c.render(words(MOBY)) == "Call me\nIshmael"


class TestMeter:
    def test_scans_accepts_an_iambic_line(self):
        from redactor.prosody import scans
        line = "I never learned the names of all the birds".split()
        assert scans(line, "0101010101")

    def test_scans_rejects_a_trochaic_opening(self):
        from redactor.prosody import scans
        # "watery" is stressed-unstressed-unstressed, so it cannot start an iamb
        assert not scans(["watery", "part", "of", "the", "world"], "0101010101")

    def test_scans_rejects_wrong_length(self):
        from redactor.prosody import scans
        assert not scans(["cat"], "0101010101")

    def test_meter_filters_the_candidate_set(self):
        from redactor.candidates import Enumerator
        from redactor.prosody import METERS
        plain = Enumerator(words(MOBY), (10,), max_runs=2)
        metered = Enumerator(words(MOBY), (10,), max_runs=2,
                             meter=METERS["pentameter"])
        assert len(metered.all()) < len(plain.all())

    def test_every_metered_candidate_scans(self):
        from redactor.candidates import Enumerator
        from redactor.prosody import METERS, scans
        for c in Enumerator(words(MOBY), (10,), max_runs=2,
                            meter=METERS["pentameter"]).all():
            assert scans([MOBY[i] for i in c.indices()], "0101010101")


class TestShapes:
    def test_snowball_grows_by_one_letter(self):
        from redactor import shapes
        src = "a it the week Start Ollama exactly partners connector".split()
        keep = shapes.longest(words(src), shapes.snowball())
        lengths = [len(src[i]) for i in keep]
        assert lengths == list(range(1, len(lengths) + 1))

    def test_snowball_rejects_stray_single_glyphs(self):
        from redactor import shapes
        # 'v' is a chevron Tesseract read as a letter, not a word
        keep = shapes.longest(words(["v", "it", "the"]), shapes.snowball())
        assert "v" not in [["v", "it", "the"][i] for i in keep]

    def test_univocalic_admits_one_vowel_only(self):
        from redactor import shapes
        src = "a an and plan start always money".split()
        keep = shapes.longest(words(src), shapes.build("univocalic:a"))
        assert "money" not in [src[i] for i in keep]
        assert len(keep) >= 4

    def test_lipogram_excludes_its_letter(self):
        from redactor import shapes
        src = "call me ishmael some years ago never".split()
        keep = shapes.longest(words(src), shapes.build("lipogram:e"))
        assert all("e" not in src[i] for i in keep)

    def test_abecedarian_advances_the_alphabet(self):
        from redactor import shapes
        src = "an build computer disposable elements".split()
        keep = shapes.longest(words(src), shapes.abecedarian())
        initials = [src[i][0] for i in keep]
        assert initials == ["a", "b", "c", "d", "e"]

    def test_result_is_always_a_subsequence(self):
        from redactor import shapes
        keep = shapes.longest(words(MOBY), shapes.build("univocalic:o"))
        assert keep == sorted(keep)

    def test_unknown_shape_is_rejected(self):
        from redactor import shapes
        with pytest.raises(ValueError):
            shapes.build("sestina")


class TestLadder:
    def test_hardest_form_comes_first(self):
        from redactor.ladder import RUNGS
        assert RUNGS[0] == "ballad"
        assert RUNGS.index("pentameter") < RUNGS.index("haiku")

    def test_climb_prefers_a_metrical_form_when_one_fits(self):
        from redactor import ladder
        rung = ladder.climb(words(MOBY), max_runs=2)
        assert rung is not None
        assert rung.form in ladder.RUNGS

    def test_climb_returns_candidates_that_match_their_form(self):
        from redactor import ladder
        from redactor.prosody import FORMS, METERS, scans, syllables
        rung = ladder.climb(words(MOBY), max_runs=2)
        form = FORMS[rung.form]
        for c in rung.candidates[:20]:
            counts = [sum(syllables(MOBY[i]) for i in line) for line in c.lines]
            assert counts == list(form)
            meter = METERS.get(rung.form)
            if meter:
                for line, pattern in zip(c.lines, meter.split("/")):
                    assert scans([MOBY[i] for i in line], pattern)

    def test_climb_gives_up_on_a_page_with_no_words(self):
        from redactor import ladder
        assert ladder.climb(words(["cat"]), max_runs=2) is None


class TestScansionEvidence:
    def test_accepts_shakespeare(self):
        from redactor.prosody import scans
        assert scans("Shall I compare thee to a summer's day".split(),
                     "0101010101")

    def test_accepts_an_all_monosyllabic_pentameter(self):
        from redactor.prosody import scans
        # no polysyllable to offer stress evidence, but five content words
        assert scans("When I do count the clock that tells the time".split(),
                     "0101010101")

    def test_rejects_a_line_of_one_repeated_word(self):
        from redactor.prosody import scans
        assert not scans(["the"] * 10, "0101010101")

    def test_rejects_a_line_of_only_function_words(self):
        from redactor.prosody import scans
        assert not scans("of the and to in on at by for with".split(),
                         "0101010101")

    def test_content_words_ignores_function_words(self):
        from redactor.prosody import content_words
        assert content_words("the clock that tells the time".split()) == 3


class TestFluidColor:
    """The whiteout tone is mixed from the page rather than fixed.

    The numbers come from the work the look is taken from: a scan of Mary
    Ruefle's *A Little White Shadow*, where the paper reads (237,212,188) and
    the correction fluid over it (244,240,242).
    """

    RUEFLE_PAPER = (237, 212, 188)
    RUEFLE_FLUID = (244, 240, 242)

    def test_reproduces_the_reference(self):
        mixed = render.fluid_color(self.RUEFLE_PAPER)
        got = tuple(int(mixed[i:i + 2], 16) for i in (1, 3, 5))
        assert all(abs(a - b) <= 4 for a, b in zip(got, self.RUEFLE_FLUID)), got

    def test_takes_the_color_out(self):
        r, g, b = (int(render.fluid_color(self.RUEFLE_PAPER)[i:i + 2], 16)
                   for i in (1, 3, 5))
        assert max(r, g, b) - min(r, g, b) < 10

    def test_lightens_ordinary_paper(self):
        paper = (200, 190, 180)
        fluid = int(render.fluid_color(paper)[1:3], 16)
        assert fluid > paper[0]

    @pytest.mark.parametrize("paper", [
        (255, 255, 255), (250, 250, 240), (237, 212, 188), (200, 190, 180),
        (128, 128, 128), (26, 26, 30), (0, 0, 0), (255, 0, 0), (10, 40, 90),
    ])
    def test_is_never_darker_than_the_paper(self, paper):
        """The invariant the look depends on.

        Fluid sits on top of a page and catches more light than the page. Mix
        it darker and the eye reads the result backwards: the covered column
        becomes a wash and the paper around each surviving word becomes the
        brightest thing on the page, so the erasure looks applied to the words
        that were kept.
        """
        fluid = tuple(int(render.fluid_color(paper)[i:i + 2], 16)
                      for i in (1, 3, 5))
        assert sum(fluid) >= sum(paper), f"{paper} -> {fluid} is darker"

    def test_white_paper_gets_white_fluid(self):
        """Nowhere lighter to go, so the stroke reads by its edges and its
        texture. Blank where words went is right; painted over the words that
        stayed is not."""
        assert render.fluid_color((255, 255, 255)) == "#ffffff"

    def test_handles_a_dark_page(self):
        fluid = int(render.fluid_color((20, 20, 24))[1:3], 16)
        assert fluid > 20


class TestHalo:
    """The paper left around a kept run must not uncover its neighbours."""

    def row(self, *spans):
        return [Word(t, left=l, top=10, width=w, height=12, line="1")
                for t, l, w in spans]

    def test_stops_short_of_a_close_neighbour(self):
        ws = self.row(("kept", 100, 40), ("next", 148, 40))
        left, top, right, bottom = render._halo([0], ws, pad=20)
        assert right <= 148, f"halo reached {right}, neighbour starts at 148"

    def test_splits_the_gap_rather_than_taking_it_all(self):
        ws = self.row(("kept", 100, 40), ("next", 160, 40))
        _, _, right, _ = render._halo([0], ws, pad=20)
        assert right == 140 + (20 - render.SAFETY) // 2

    def test_holds_back_a_safety_margin(self):
        """OCR boxes can sit inside their own glyphs, so an exact half-gap is
        not a safe stopping place."""
        ws = self.row(("kept", 100, 40), ("next", 140 + render.SAFETY, 40))
        _, _, right, _ = render._halo([0], ws, pad=20)
        assert right == 140

    def test_uses_the_full_pad_with_room_to_spare(self):
        ws = self.row(("kept", 100, 40), ("next", 400, 40))
        _, _, right, _ = render._halo([0], ws, pad=7)
        assert right == 147

    def test_clamps_against_the_line_above(self):
        ws = [Word("above", left=100, top=0, width=40, height=12, line="1"),
              Word("kept", left=100, top=16, width=40, height=12, line="2")]
        _, top, _, _ = render._halo([1], ws, pad=20)
        assert top >= 12, f"halo reached {top}, line above ends at 12"

    def test_ignores_a_word_that_does_not_sit_over_the_run(self):
        """A word on the line above but elsewhere across the page cannot be
        uncovered by padding upward, so it must not clamp the halo."""
        ws = [Word("elsewhere", left=400, top=0, width=40, height=12, line="1"),
              Word("kept", left=100, top=16, width=40, height=12, line="2")]
        _, top, _, _ = render._halo([1], ws, pad=6)
        assert top == 10


class TestErase:
    def test_rejects_an_unknown_style(self):
        with pytest.raises(ValueError, match="unknown style"):
            render.erase(Path("x.png"), [], [], Path("y.png"), style="scribble")

    def test_needs_positioned_words(self):
        with pytest.raises(ValueError, match="positioned"):
            render.column([Word("unplaced")])


@pytest.mark.skipif(shutil.which("magick") is None, reason="needs ImageMagick")
class TestErasePixels:
    """Whatever the style, a word the poem does not keep must not survive."""

    def page(self, tmp_path):
        """Two dark bars on tan paper, standing in for two words."""
        png = tmp_path / "page.png"
        subprocess.run(
            ["magick", "-size", "400x120", "xc:#edd4bc", "-fill", "#2a2018",
             "-draw", "rectangle 40,40 140,64",
             "-draw", "rectangle 240,40 340,64", str(png)], check=True)
        return png, [Word("kept", left=40, top=40, width=100, height=24, line="1"),
                     Word("gone", left=240, top=40, width=100, height=24, line="1")]

    def contrast(self, png, box, around=10):
        """Spread of tone over a word and the paper around it.

        Not darkness: a black bar laid over a word is as dark as the word was,
        so darkness cannot tell a covered word from an uncovered one. What
        covering a word destroys is the difference between its ink and the page
        it sits on, whatever color it was covered with.
        """
        x0, y0, x1, y1 = (box[0] - around, box[1] - around,
                          box[2] + around, box[3] + around)
        out = subprocess.run(
            ["magick", str(png), "-crop", f"{x1 - x0}x{y1 - y0}+{x0}+{y0}",
             "+repage", "-colorspace", "Gray",
             "-format", "%[fx:standard_deviation]", "info:"],
            capture_output=True, text=True, check=True).stdout
        return float(out)

    @pytest.mark.parametrize("style", ["black", "whiteout"])
    def test_the_erased_word_goes_and_the_kept_word_stays(self, tmp_path, style):
        png, ws = self.page(tmp_path)
        dest = render.erase(png, ws, [0], tmp_path / "out.png", style=style,
                            seed=1)
        assert self.contrast(dest, (40, 40, 140, 64)) > 0.15, "kept word lost"
        assert self.contrast(dest, (240, 40, 340, 64)) < 0.06, "erased word survived"

    def test_whiteout_is_mixed_from_the_page(self, tmp_path):
        png, ws = self.page(tmp_path)
        box = render.column(ws)
        assert render.page_background(png, box) == (237, 212, 188)

    def test_the_same_seed_renders_the_same_page(self, tmp_path):
        png, ws = self.page(tmp_path)
        a = render.erase(png, ws, [0], tmp_path / "a.png", style="whiteout", seed=3)
        b = render.erase(png, ws, [0], tmp_path / "b.png", style="whiteout", seed=3)
        # `compare -metric AE` reports "N (normalised)"; the count is the first
        # field.
        differing = subprocess.run(
            ["magick", "compare", "-metric", "AE", str(a), str(b), "null:"],
            capture_output=True, text=True).stderr.strip().split()[0]
        assert differing == "0", f"{differing} pixels differ between seeds"
