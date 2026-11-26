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
