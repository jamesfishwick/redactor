import shutil
import subprocess
from pathlib import Path

from redactor import source

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
        # rhymed forms sit above metrical ones, metrical above syllabic
        assert RUNGS[0] == "quatrain"
        assert RUNGS.index("couplet") < RUNGS.index("ballad")
        assert RUNGS.index("ballad") < RUNGS.index("pentameter")
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


class TestVisualRuns:
    def _laid_out(self, tokens, lines):
        """Words with explicit page-line ids, as OCR would report them."""
        from redactor.source import Word
        return [Word(t, left=0, top=0, width=10, height=10, line=l)
                for t, l in zip(tokens, lines)]

    def test_a_run_cannot_cross_a_page_line(self):
        from redactor.candidates import Enumerator
        # adjacent in reading order, but the page puts them in different blocks
        src = "I thought I would sail about a little and see".split()
        same = self._laid_out(src, ["1-1-1"] * len(src))
        split = self._laid_out(src, ["1-1-1"] * 5 + ["9-9-9"] * 5)
        assert Enumerator(same, (10,), max_runs=1).count() >= \
               Enumerator(split, (10,), max_runs=1).count()

    def test_one_run_stays_on_one_line(self):
        from redactor.candidates import Enumerator
        src = "I thought I would sail about a little and see the watery part".split()
        w = self._laid_out(src, ["a"] * 6 + ["b"] * 7)
        for c in Enumerator(w, (10,), max_runs=1).all():
            idx = c.indices()
            assert len({w[i].line for i in idx}) == 1

    def test_count_still_agrees_with_enumeration(self):
        from redactor.candidates import Enumerator
        src = "I thought I would sail about a little and see the watery part".split()
        w = self._laid_out(src, ["a"] * 6 + ["b"] * 7)
        e = Enumerator(w, (10,), max_runs=2)
        assert e.count() == len(e.all())


class TestLongPages:
    def test_a_long_page_does_not_blow_the_stack(self):
        from redactor.candidates import Enumerator
        from redactor.source import Word
        # far past the default recursion limit, which the DOM reader reaches
        src = ("I thought I would sail about a little and see the watery "
               "part of the world ") * 400
        w = [Word(t, left=0, top=0, width=9, height=9, line="a")
             for t in src.split()]
        assert len(w) > 5000
        # capped below Python's frame limit rather than overflowing it
        assert Enumerator(w, (5, 7, 5), max_runs=1, limit=20).all()
        assert Enumerator(w, (5, 7, 5), max_runs=1).MAX_WORDS < 1000


class TestSpace:
    def _page(self, repeat=1):
        from redactor.source import Word
        src = (MOBY * repeat)
        return [Word(t, left=0, top=0, width=9, height=9, line=f"l{i // 12}")
                for i, t in enumerate(src)]

    def test_count_agrees_with_the_recursive_enumerator(self):
        from redactor.candidates import Enumerator, Space
        w = self._page()
        assert Space(w, (5, 7, 5), max_runs=2).count() == \
               Enumerator(w, (5, 7, 5), max_runs=2).count()

    def test_handles_a_page_that_overflows_recursion(self):
        from redactor.candidates import Space
        w = self._page(repeat=40)      # ~1700 words
        assert len(w) > 1500
        assert Space(w, (5, 7, 5), max_runs=2).count() > 0

    def test_samples_are_valid_poems(self):
        from redactor.candidates import Space, is_subsequence
        from redactor.prosody import syllables
        w = self._page(repeat=3)
        space = Space(w, (5, 7, 5), max_runs=2)
        for c in space.sample(25, __import__("random").Random(1)):
            counts = [sum(syllables(w[i].text) for i in line) for line in c.lines]
            assert counts == [5, 7, 5]
            assert is_subsequence([w[i].text for i in c.indices()],
                                  [x.text for x in w])

    def test_sampling_spreads_across_the_page(self):
        from redactor.candidates import Space
        w = self._page(repeat=6)
        got = Space(w, (5, 7, 5), max_runs=2).sample(40, __import__("random").Random(2))
        starts = [c.indices()[0] for c in got]
        # a slice of the enumeration would cluster; a sample should not
        assert max(starts) - min(starts) > len(w) // 4

    def test_empty_space_samples_nothing(self):
        from redactor.candidates import Space
        from redactor.source import Word
        assert Space([Word("cat")], (5, 7, 5), max_runs=2).sample(5) == []


class TestSectionSlice:
    def _words(self, text):
        from redactor.source import Word
        return [Word(t, left=0, top=0, width=9, height=9, line="l")
                for t in text.split()]

    def test_takes_the_named_section(self):
        from redactor.dom import slice_between
        w = self._words("preamble here § 106 exclusive rights blah "
                        "§ 107 fair use is a defense § 108 libraries may copy")
        got = [x.text for x in slice_between(w, "§ 107", "§ 108")]
        assert "fair" in got and "use" in got
        assert "libraries" not in got
        assert "exclusive" not in got

    def test_runs_to_the_end_without_an_end_marker(self):
        from redactor.dom import slice_between
        w = self._words("alpha beta § 107 gamma delta")
        got = [x.text for x in slice_between(w, "§ 107")]
        assert "gamma" in got and "alpha" not in got

    def test_missing_start_yields_nothing(self):
        from redactor.dom import slice_between
        assert slice_between(self._words("alpha beta"), "§ 999") == []

    def test_matches_across_whitespace_and_case(self):
        from redactor.dom import slice_between
        w = self._words("x § 107 Fair Use y")
        assert slice_between(w, "§ 107 fair use") != []


class TestLargestSection:
    def _read(self, groups):
        from redactor.dom import Read
        from redactor.source import Word
        words, secs = [], []
        for n, (sec, count) in enumerate(groups):
            for i in range(count):
                words.append(Word(f"w{sec}_{i}", left=0, top=0,
                                  width=9, height=9, line=f"l{sec}"))
                secs.append(sec)
        return Read(words, "x.png", "t", secs)

    def test_picks_the_longest_run_under_one_heading(self):
        from redactor.dom import largest_section
        got = largest_section(self._read([(0, 50), (1, 400), (2, 60)]), floor=150)
        assert len(got) == 400
        assert all(w.text.startswith("w1_") for w in got)

    def test_keeps_the_whole_page_when_no_section_is_big_enough(self):
        from redactor.dom import largest_section
        r = self._read([(0, 100), (1, 120), (2, 110)])
        assert len(largest_section(r, floor=150)) == len(r.words)

    def test_short_pages_are_left_alone(self):
        from redactor.dom import largest_section
        r = self._read([(0, 40), (1, 60)])
        assert largest_section(r, floor=150) == r.words


class TestMeteredSpace:
    def _words(self, text):
        from redactor.source import Word
        return [Word(t, left=0, top=0, width=9, height=9, line="l")
                for t in text.split()]

    def test_every_sample_already_scans(self):
        from redactor.candidates import Space
        from redactor.prosody import METERS, scans
        w = self._words(" ".join(MOBY * 4))
        got = Space(w, (10,), max_runs=2,
                    meter=METERS["pentameter"]).sample(40, __import__("random").Random(3))
        assert got
        for c in got:
            assert scans([w[i].text for i in c.indices()], "0101010101",
                         min_fixed=0, min_content=0)

    def test_metered_space_is_a_subset_of_the_plain_one(self):
        from redactor.candidates import Space
        from redactor.prosody import METERS
        w = self._words(" ".join(MOBY * 2))
        plain = Space(w, (10,), max_runs=2).count()
        metered = Space(w, (10,), max_runs=2, meter=METERS["pentameter"]).count()
        assert 0 < metered < plain

    def test_an_unsatisfiable_meter_counts_zero(self):
        from redactor.candidates import Space
        # ten syllables of one trochee repeated cannot be iambic
        w = self._words("watery watery watery watery")
        assert Space(w, (10,), max_runs=4, meter="0101010101").count() == 0


class TestSectionRequests:
    def test_reads_a_named_section_from_the_title(self):
        from redactor.agent import SECTION_IN_TITLE, URL_IN_TITLE
        title = "erase: https://example.com/doc section: § 107 Fair use"
        assert URL_IN_TITLE.search(title).group(1) == "https://example.com/doc"
        assert SECTION_IN_TITLE.search(title).group(1) == "§ 107 Fair use"

    def test_a_plain_request_names_no_section(self):
        from redactor.agent import SECTION_IN_TITLE
        assert SECTION_IN_TITLE.search("erase: https://example.com") is None


class TestNamedSection:
    def _read(self, groups):
        from redactor.dom import Read
        from redactor.source import Word
        words, secs = [], []
        for sec, tokens in groups:
            for t in tokens.split():
                words.append(Word(t, left=0, top=0, width=9, height=9,
                                  line=f"l{sec}"))
                secs.append(sec)
        return Read(words, "x.png", "t", secs)

    def test_stops_at_the_next_heading(self):
        from redactor.dom import named_section
        r = self._read([(0, "intro words here"),
                        (1, "107. Fair use"),
                        (2, "is a defense to infringement of copyright"),
                        (3, "108. Libraries"),
                        (4, "may reproduce copies")])
        got = [w.text for w in named_section(r, "107. Fair use")]
        assert "defense" in got and "copyright" in got
        assert "Libraries" not in got and "reproduce" not in got
        assert "intro" not in got

    def test_unknown_heading_returns_nothing(self):
        from redactor.dom import named_section
        r = self._read([(0, "alpha beta gamma")])
        assert named_section(r, "999. Nope") == []

    def test_caps_a_runaway_section(self):
        from redactor.dom import named_section
        r = self._read([(0, "start " + "word " * 9000)])
        assert len(named_section(r, "start", cap=500)) == 500


class TestTightCrop:
    def _words(self, tops):
        from redactor.source import Word
        return [Word("w", left=10, top=t, width=20, height=10, line=f"P-{t}")
                for t in tops]

    def test_height_follows_the_kept_words(self):
        from redactor.render import column
        _, top, _, bottom = column(self._words([0, 5000, 9000]), margin=5,
                                   keep=[1])
        assert bottom - top < 100

    def test_width_still_spans_the_column(self):
        from redactor.source import Word
        from redactor.render import column
        w = [Word("a", left=10, top=0, width=20, height=10, line="P-0"),
             Word("b", left=500, top=0, width=20, height=10, line="P-0")]
        left, _, right, _ = column(w, margin=5, keep=[0])
        assert right - left > 500

    def test_the_box_stops_at_the_capture(self):
        from redactor.render import column
        _, _, _, bottom = column(self._words([0, 9000]), margin=5, keep=[1],
                                 page_height=4000)
        assert bottom <= 4000

class TestChallengePages:
    def test_spots_a_bot_wall(self):
        from redactor.dom import is_challenge
        assert is_challenge(
            "Performing security verification This website uses a security "
            "service to protect against malicious bots".split())

    def test_spots_a_cloudflare_interstitial(self):
        from redactor.dom import is_challenge
        assert is_challenge("Just a moment ... Enable JavaScript and cookies "
                            "to continue".split())

    def test_leaves_an_ordinary_page_alone(self):
        from redactor.dom import is_challenge
        assert not is_challenge(MOBY)

    def test_only_looks_at_the_opening(self):
        from redactor.dom import is_challenge
        # the phrase appearing deep in a long article is not a challenge
        assert not is_challenge(MOBY * 3 + ["just", "a", "moment"])


class TestSectionReachesTheReader:
    def test_erase_page_passes_the_section_to_the_reader(self, monkeypatch):
        from redactor import agent, dom
        seen = {}

        def fake_read(url, png, **kw):
            seen.update(kw)
            return None

        monkeypatch.setattr(dom, "read", fake_read)
        monkeypatch.setattr(agent, "MIN_WORDS", 1)
        agent.erase_page("https://example.com", out=__import__("pathlib").Path("/tmp"),
                         section="§ 107")
        assert seen.get("section") == "§ 107"


class TestBudgetFallthrough:
    def _page(self):
        from redactor.source import Word
        src = ("I thought I would sail about a little and see the watery "
               "part of the world ") * 12
        return [Word(t, left=0, top=0, width=9, height=9, line=f"P-{i // 11}")
                for i, t in enumerate(src.split())]

    def test_a_spent_budget_still_reaches_an_easier_form(self):
        from redactor import ladder
        w = self._page()
        assert ladder.climb(w, max_runs=2) is not None
        # metered rungs get nothing, but a syllabic one needs no sampling budget
        fallen = ladder.climb(w, max_runs=2, budget_s=0.0)
        assert fallen is not None
        assert fallen.metered is False

    def test_the_budget_is_per_rung(self):
        import inspect
        from redactor import ladder
        body = inspect.getsource(ladder.climb)
        # the deadline is set inside the loop over rungs, not before it
        assert body.index("for name in RUNGS") < body.index("deadline =")


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


class TestTsvParsing:
    """Tesseract's TSV is tab separated and unquoted, but the words in it are
    whatever was on the page, double quotes included."""

    HEADER = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
              "left\ttop\twidth\theight\tconf\ttext")

    def tsv(self, *words):
        """Word rows only, at level 5. Real output interleaves page, block,
        paragraph and line rows, which test_hierarchy_rows_are_dropped covers
        separately. A word may carry its own line key, since that key is what
        render splits restored runs on."""
        rows = [self.HEADER]
        for n, word in enumerate(words, 1):
            text, top, conf = word[:3]
            block, par, line = word[3] if len(word) > 3 else (1, 1, 1)
            rows.append(f"5\t1\t{block}\t{par}\t{line}\t{n}\t"
                        f"{n * 50}\t{top}\t40\t12\t{conf}\t{text}")
        return "\n".join(rows) + "\n"

    def test_a_quoted_word_does_not_eat_the_rows_after_it(self):
        """The bug this guards: the default CSV dialect treats a leading quote
        as opening a quoted field and swallows every row up to the next one."""
        got = source.words_from_tsv(self.tsv(
            ("Call", 10, 99), ('"Did', 10, 99), ("you", 10, 99),
            ("read", 10, 99), ('that"', 30, 99), ("afterward", 30, 99)))
        assert [w.text for w in got] == ["Call", '"Did', "you", "read",
                                         'that"', "afterward"]

    def test_the_last_word_on_a_quoting_page_still_has_a_position(self):
        """render.erase sizes its cover from the words it is handed, so losing
        the last one shrinks the cover and leaves real text legible below it.
        The position matters as much as the word."""
        got = source.words_from_tsv(self.tsv(
            ('"Did', 10, 99), ("afterward", 1492, 99)))
        assert [w.text for w in got] == ['"Did', "afterward"]
        assert max(w.top for w in got) == 1492

    def test_an_unbalanced_quote_loses_nothing(self):
        """Real pages open a quote that the screenshot cuts off before it
        closes. Under the old dialect the remainder was swallowed into the
        opening row, which kept that row's position and lost every other."""
        got = source.words_from_tsv(self.tsv(
            ("opening", 10, 99), ('"unclosed', 10, 99), ("tail", 900, 99)))
        assert [w.text for w in got] == ["opening", '"unclosed', "tail"]

    def test_a_balanced_quote_keeps_its_quotes(self):
        """The axis an ordinary page actually hits. A word quoted at both ends
        is a well formed quoted field, so the old dialect lost no row and no
        position, and returned the word with its quotes stripped off. Nothing
        that counts rows or checks positions can see that."""
        got = source.words_from_tsv(self.tsv(
            ("he", 10, 99), ('"work"', 10, 99), ('hard."', 10, 99),
            ("ended", 10, 99)))
        assert [w.text for w in got] == ["he", '"work"', 'hard."', "ended"]

    def test_a_lone_quote_word_does_not_absorb_its_neighbours(self):
        """Tesseract segments an opening quote as its own token. Under the old
        dialect that token absorbed the rows after it and came back as a Word
        whose text was raw TSV, carrying the quote glyph's own small box. The
        bare quote is absent from the result either way, since normalize_ok
        drops a token with no letters in it."""
        got = source.words_from_tsv(self.tsv(
            ("alpha", 10, 99), ('"', 10, 99), ("beta", 10, 99),
            ("gamma", 10, 99)))
        assert [w.text for w in got] == ["alpha", "beta", "gamma"]

    def test_the_line_key_follows_the_row(self):
        """render splits a restored run where this key changes, so a key that
        goes empty or constant merges runs across a line break and composites
        one chip over two lines of the page. Reordering its parts cannot merge
        anything, since the triples stay distinct, but it mislabels them."""
        got = source.words_from_tsv(self.tsv(
            ("first", 10, 99, (1, 1, 1)), ("same", 10, 99, (1, 1, 1)),
            ("other", 30, 99, (2, 3, 4))))
        assert [w.line for w in got] == ["1-1-1", "1-1-1", "2-3-4"]

    def test_hierarchy_rows_are_dropped(self):
        """Every real page carries these. Tesseract emits one row per page,
        block, paragraph and line alongside the word rows, each with an empty
        text column and a confidence of -1. This asserts they never reach the
        word list. Three separate guards drop them, so it pins the outcome and
        not any one branch."""
        rows = [self.HEADER,
                "1\t1\t0\t0\t0\t0\t0\t0\t1000\t1500\t-1\t",
                "4\t1\t1\t1\t1\t0\t50\t10\t200\t12\t-1\t",
                "5\t1\t1\t1\t1\t1\t50\t10\t40\t12\t96.687843\tsurvivor"]
        got = source.words_from_tsv("\n".join(rows) + "\n")
        assert [w.text for w in got] == ["survivor"]

    def test_geometry_reaches_the_word_intact(self):
        """render.erase builds its cover from left plus width and top plus
        height, so a transposition of any pair ships a wrong cover with every
        text assertion still green."""
        got = source.words_from_tsv(self.tsv(("one", 10, 99), ("two", 30, 99)))
        assert [(w.left, w.top, w.width, w.height) for w in got] == [
            (50, 10, 40, 12), (100, 30, 40, 12)]

    def test_a_word_exactly_at_the_threshold_is_kept(self):
        """The comparison is `conf < min_conf`, and nothing else pins which
        side of it the boundary falls on."""
        got = source.words_from_tsv(self.tsv(
            ("kept", 10, source.MIN_CONF), ("dropped", 10, source.MIN_CONF - 1)))
        assert [w.text for w in got] == ["kept"]

    def test_min_conf_is_honoured_when_the_caller_sets_it(self):
        """The parameter is public API now, and the default path never
        exercises it."""
        rows = self.tsv(("high", 10, 95), ("low", 10, 60))
        assert [w.text for w in source.words_from_tsv(rows)] == ["high", "low"]
        assert [w.text for w in source.words_from_tsv(rows, 90)] == ["high"]

    def test_degenerate_input_yields_no_words(self):
        assert source.words_from_tsv(self.HEADER + "\n") == []

    def test_an_unparseable_conf_drops_the_row(self):
        """The one column wrapped in a try and except, so it loses a word in
        silence where its neighbours would raise."""
        rows = (self.HEADER + "\n"
                + "5\t1\t1\t1\t1\t1\t50\t10\t40\t12\t99\tgood\n"
                + "5\t1\t1\t1\t1\t2\t99\t10\t40\t12\tNOPE\tvanishes\n")
        assert [w.text for w in source.words_from_tsv(rows)] == ["good"]

    def test_unparseable_geometry_raises(self):
        """The asymmetry with conf above is not a design, it is where the
        try and except happens to sit."""
        rows = (self.HEADER + "\n"
                + "5\t1\t1\t1\t1\t1\tXX\t10\t40\t12\t99\tboom\n")
        with pytest.raises(ValueError):
            source.words_from_tsv(rows)

    def test_a_header_missing_any_column_is_refused(self):
        """A missing conf is the one that matters. The except around float()
        swallows its KeyError row by row, so the list empties in silence,
        which is the failure the guard exists to refuse."""
        cols = self.HEADER.split("\t")
        for drop in ("conf", "left", "block_num"):
            header = "\t".join(c for c in cols if c != drop)
            rows = header + "\n5\t1\t1\t1\t1\t1\t50\t10\t40\t12\t99\tword\n"
            with pytest.raises(ValueError, match=drop):
                source.words_from_tsv(rows)

    def test_a_stream_with_no_header_is_refused(self):
        """DictReader takes the first line as the header, so a caller that
        strips it loses a word and gets no error. Refuse instead."""
        headerless = "5\t1\t1\t1\t1\t1\t50\t10\t40\t12\t99\tword\n"
        with pytest.raises(ValueError, match="header"):
            source.words_from_tsv(headerless)

    def test_low_confidence_words_are_still_dropped(self):
        got = source.words_from_tsv(
            self.tsv(("solid", 10, 96), ("junk", 10, 12)))
        assert [w.text for w in got] == ["solid"]

    def test_words_without_letters_are_still_dropped(self):
        got = source.words_from_tsv(self.tsv(("real", 10, 96), ("--", 10, 96)))
        assert [w.text for w in got] == ["real"]


class TestGapClosing:
    def _spread(self, tops):
        from redactor.source import Word
        return [Word("w", left=10, top=t, width=40, height=12, line=f"P-{t}")
                for t in tops]

    def test_a_poem_on_one_line_is_left_alone(self, monkeypatch, tmp_path):
        import subprocess as sp
        from redactor import render
        calls = []
        monkeypatch.setattr(render, "_run", lambda c: calls.append(c))
        monkeypatch.setattr(render, "page_height", lambda *a, **k: 400)
        out = render._close_the_gaps(tmp_path / "r.png", self._spread([0, 10]),
                                     [0, 1], (0, 0, 500, 100), "magick")
        assert out == tmp_path / "r.png"
        assert not calls          # nothing to close

    def test_a_poem_split_down_a_page_is_stacked(self, monkeypatch, tmp_path):
        from redactor import render
        calls = []
        monkeypatch.setattr(render, "_run", lambda c: calls.append(c))
        monkeypatch.setattr(render, "page_height", lambda *a, **k: 9000)
        render._close_the_gaps(tmp_path / "r.png", self._spread([0, 4000, 8000]),
                               [0, 1, 2], (0, 0, 500, 9000), "magick")
        crops = [c for c in calls if "-crop" in c]
        assert len(crops) == 3            # one band per line that carries words
        assert any("-append" in c for c in calls)

    def test_each_band_is_short(self, monkeypatch, tmp_path):
        from redactor import render
        calls = []
        monkeypatch.setattr(render, "_run", lambda c: calls.append(c))
        monkeypatch.setattr(render, "page_height", lambda *a, **k: 9000)
        render._close_the_gaps(tmp_path / "r.png", self._spread([0, 4000]),
                               [0, 1], (0, 0, 500, 9000), "magick")
        for c in calls:
            if "-crop" in c:
                geom = c[c.index("-crop") + 1]
                assert int(geom.split("x")[1].split("+")[0]) < 100
                # page coordinates, not shifted by a crop origin
                assert int(geom.split("+")[2]) in (0, 3988)
