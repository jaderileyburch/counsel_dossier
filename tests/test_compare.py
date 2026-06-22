"""Tests for cross-attorney comparison logic."""
from counsel_dossier.compare import cross_corpus_passages


def test_cross_corpus_overlap_detects_shared_template():
    shared = ("the parties hereby stipulate and agree that all currently operative deadlines "
              "shall be extended by a period of thirty days from the date of this order")
    docs_a = {1: "Attorney A intro unique. " + shared + " A-specific tail.",
              2: "A second filing entirely distinct with no template language at all here."}
    docs_b = {10: "Attorney B different opening. " + shared + " B-specific tail."}
    rows = cross_corpus_passages(docs_a, docs_b, min_words=15)
    assert rows, "expected shared passage across the two corpora"
    assert "stipulate and agree" in rows[0]["text"]


def test_cross_corpus_no_overlap():
    docs_a = {1: "wholly bespoke filing one with singular phrasing"}
    docs_b = {2: "an utterly different document sharing nothing in common"}
    assert cross_corpus_passages(docs_a, docs_b, min_words=10) == []
