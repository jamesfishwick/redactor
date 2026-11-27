import pytest

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
        # longer than the default recursion limit, which the DOM reader can reach
        src = ("I thought I would sail about a little and see the watery "
               "part of the world ") * 90
        w = [Word(t, left=0, top=0, width=9, height=9, line="a")
             for t in src.split()]
        assert len(w) > 1000
        assert Enumerator(w, (5, 7, 5), max_runs=1, limit=20).all()


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
    def test_frame_spans_the_kept_words_not_the_page(self, tmp_path, monkeypatch):
        import subprocess as sp
        from redactor import render
        from redactor.source import Word
        calls = []
        monkeypatch.setattr(sp, "run", lambda *a, **k: calls.append(a[0]) or
                            sp.CompletedProcess(a[0], 0))
        words = [Word("a", left=10, top=0, width=20, height=10, line="l"),
                 Word("b", left=10, top=5000, width=20, height=10, line="m"),
                 Word("c", left=10, top=9000, width=20, height=10, line="n")]
        render.erase(tmp_path / "p.png", words, [1], tmp_path / "out.png")
        crop = next(c[c.index("-crop") + 1] for c in calls if "-crop" in c)
        height = int(crop.split("x")[1].split("+")[0])
        # the kept word sits at 5000 with a 40px margin, so the frame is small
        assert height < 200


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
