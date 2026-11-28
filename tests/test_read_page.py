"""The shared page read, and the pairing it has to preserve.

`read_page` hands back words and the image those words are positioned
against. OCR writes its screenshot over the DOM's capture at a different
scale, so returning one reader's words beside the other's image would put
every cover rectangle in the wrong place. These pin that it cannot.
"""

from __future__ import annotations

import pytest

from redactor import dom, source
from redactor.source import Word


def words(n: int, tag: str = "w"):
    return [Word(f"{tag}{i}", left=10, top=i * 20, width=40, height=12)
            for i in range(n)]


@pytest.fixture
def readers(monkeypatch, tmp_path):
    """Both readers stubbed, each returning a count the test chooses."""
    state = {"dom": None, "ocr": [], "ocr_png": tmp_path / "ocr.png"}

    def fake_read(url, png, **kw):
        if state["dom"] is None:
            return None
        return dom.Read(state["dom"], str(png), "title", [])

    monkeypatch.setattr(dom, "read", fake_read)
    monkeypatch.setattr(source, "screenshot",
                        lambda url, png, **kw: state["ocr_png"])
    monkeypatch.setattr(source, "page_html", lambda url: None)
    monkeypatch.setattr(source, "from_image", lambda png, **kw: state["ocr"])
    return state


class TestReadPage:
    def test_a_good_dom_read_never_reaches_ocr(self, readers, tmp_path):
        readers["dom"] = words(200, "d")
        readers["ocr"] = words(999, "o")   # would win if it were consulted
        got, shot = dom.read_page("u", tmp_path / "p.png", least=120)
        assert next(w.text for w in got) == "d0"
        assert shot == tmp_path / "p.png"

    def test_ocr_words_come_with_the_ocr_image(self, readers, tmp_path):
        readers["dom"] = words(50, "d")
        readers["ocr"] = words(300, "o")
        got, shot = dom.read_page("u", tmp_path / "p.png", least=120)
        assert next(w.text for w in got) == "o0"
        assert shot == readers["ocr_png"]

    def test_dom_words_are_never_paired_with_the_ocr_image(self, readers,
                                                           tmp_path):
        # The DOM read is too thin to accept and OCR does no better, so the
        # only way to return anything here would be DOM words against the
        # screenshot OCR just wrote over them.
        readers["dom"] = words(50, "d")
        readers["ocr"] = words(30, "o")
        assert dom.read_page("u", tmp_path / "p.png", least=120) is None

    def test_a_thin_page_passes_when_the_caller_allows_it(self, readers,
                                                           tmp_path):
        readers["dom"] = words(50, "d")
        readers["ocr"] = words(30, "o")
        got, shot = dom.read_page("u", tmp_path / "p.png", least=20)
        assert len(got) == 50
        assert shot == tmp_path / "p.png"

    def test_neither_reader_answering_is_not_an_erasure(self, readers,
                                                        tmp_path):
        readers["dom"] = None
        readers["ocr"] = []
        assert dom.read_page("u", tmp_path / "p.png", least=20) is None

    def test_a_challenge_page_is_refused(self, readers, monkeypatch, tmp_path):
        readers["dom"] = None
        readers["ocr"] = [Word(t) for t in
                          ["Verifying", "you", "are", "human", "This", "may", "take", "a", "few", "seconds"]]
        monkeypatch.setattr(dom, "is_challenge", lambda ws: True)
        assert dom.read_page("u", tmp_path / "p.png", least=1) is None
