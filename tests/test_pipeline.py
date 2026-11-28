import pytest

from redactor.candidates import Candidate, Enumerator, is_subsequence
from redactor.prosody import syllables
from redactor import source
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
