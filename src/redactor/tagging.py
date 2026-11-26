"""Optional part-of-speech pruning.

Trigrams are learned from the source itself rather than shipped, so the filter
reflects the register being erased. Bigrams were measured and discarded: they
cut the candidate space by 2x, because almost any tag may follow any other.
Trigrams manage 211x, which is worth having but still leaves millions.
"""

from __future__ import annotations


def load(model: str = "en_core_web_sm"):
    try:
        import spacy
    except ImportError:
        return None
    try:
        return spacy.load(model)
    except OSError:
        return None


def tag(nlp, words) -> list[str] | None:
    if nlp is None:
        return None
    doc = nlp(" ".join(w.text for w in words))
    tags = [t.pos_ for t in doc if not t.is_space]
    # spaCy splits punctuation off, so realign by consuming one tag per word
    out, i = [], 0
    for w in words:
        while i < len(tags) and tags[i] == "PUNCT":
            i += 1
        out.append(tags[i] if i < len(tags) else "X")
        i += 1
    return out


def trigrams(nlp, reference: str) -> set[tuple[str, str, str]] | None:
    if nlp is None:
        return None
    tags = [t.pos_ for t in nlp(reference) if not t.is_space]
    return {(tags[i], tags[i + 1], tags[i + 2]) for i in range(len(tags) - 2)}
