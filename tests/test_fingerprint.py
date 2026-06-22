"""Tests for the boilerplate fingerprinting logic."""
from counsel_dossier.fingerprint import (
    tokenize, shingles, jaccard, shared_passages, find_boilerplate, normalize_passage,
)


def test_tokenize_strips_punctuation_and_lowercases():
    assert tokenize("Plaintiff's MOTION, filed!") == ["plaintiff's", "motion", "filed"]


def test_shingles_count_and_overlap():
    toks = "a b c d e f".split()
    s = shingles(toks, k=3)
    assert len(s) == 4  # abc bcd cde def


def test_shingles_short_text_single_shingle():
    assert len(shingles(["only", "two"], k=5)) == 1
    assert shingles([], k=5) == set()


def test_jaccard_identical_and_disjoint():
    a = shingles("the quick brown fox jumps".split(), 3)
    assert jaccard(a, a) == 1.0
    b = shingles("completely different words here entirely".split(), 3)
    assert jaccard(a, b) == 0.0


def test_shared_passages_finds_verbatim_block():
    common = "the parties hereby stipulate and agree that all deadlines shall be extended by thirty days"
    a = tokenize("Preliminary unrelated text. " + common + " and then something else.")
    b = tokenize("Different opening entirely. " + common + " with a different tail.")
    passages = shared_passages(a, b, min_words=10)
    assert any("stipulate and agree" in p for p in passages)


def test_shared_passages_respects_min_words():
    a = tokenize("alpha beta gamma delta")
    b = tokenize("zeta alpha beta omega")
    # shared run "alpha beta" is only 2 words; min_words=5 should drop it
    assert shared_passages(a, b, min_words=5) == []


def test_find_boilerplate_counts_doc_occurrences():
    boiler = ("comes now the defendant and respectfully moves this honorable court "
              "for an order dismissing the complaint in its entirety for failure to state a claim")
    docs = {
        1: "Case one intro. " + boiler + " Case one specifics about contracts.",
        2: "Case two preamble. " + boiler + " Case two specifics about torts.",
        3: "Wholly unrelated filing about an entirely different unrelated matter and subject.",
    }
    result = find_boilerplate(docs, k=5, similarity_threshold=0.2, min_passage_words=20)
    passages = result["passages"]
    assert passages, "expected at least one reused passage"
    top = passages[0]
    assert top["doc_count"] == 2
    assert set(top["doc_ids"]) == {1, 2}
    assert "respectfully moves this honorable court" in top["text"]


def test_find_boilerplate_three_way_overlap():
    boiler = "this paragraph appears verbatim in every single one of these distinct separate filings without exception here"
    docs = {
        10: "intro ten " + boiler + " tail ten",
        11: "intro eleven " + boiler + " tail eleven",
        12: "intro twelve " + boiler + " tail twelve",
    }
    result = find_boilerplate(docs, k=5, similarity_threshold=0.1, min_passage_words=15)
    top = result["passages"][0]
    assert top["doc_count"] == 3
    assert set(top["doc_ids"]) == {10, 11, 12}


def test_normalize_passage_canonicalizes_whitespace_case():
    assert normalize_passage("The   PARTIES\nagree") == "the parties agree"
