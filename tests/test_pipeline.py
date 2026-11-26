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
