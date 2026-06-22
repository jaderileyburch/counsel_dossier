"""Tests for the deterministic litigation analytics."""
from counsel_dossier.analytics import (
    classify_motion, is_order, analyze_motions,
    extract_citations, analyze_citations, analyze_phrases, normalize_citation,
)


def test_classify_motion_types():
    assert classify_motion("Defendant's Motion to Dismiss") == "Motion to Dismiss"
    assert classify_motion("MOTION FOR SUMMARY JUDGMENT") == "Motion for Summary Judgment"
    assert classify_motion("Motion to Compel Discovery") == "Motion to Compel"
    assert classify_motion("Notice of Appearance") is None


def test_is_order_detection():
    assert is_order("Order Granting Motion to Dismiss", "") is True
    assert is_order("Motion to Dismiss", "Comes now the defendant and moves to dismiss.") is False
    assert is_order("", "IT IS HEREBY ORDERED that the motion is GRANTED.") is True


def test_analyze_motions_success_rates():
    items = [
        {"id": 1, "description": "Defendant's Motion to Dismiss", "text": "comes now the defendant"},
        {"id": 2, "description": "Defendant's Motion to Dismiss", "text": "comes now the defendant"},
        {"id": 3, "description": "Order Granting Motion to Dismiss", "text": "the Motion to Dismiss is GRANTED"},
        {"id": 4, "description": "Order Denying Motion for Summary Judgment", "text": "the Motion for Summary Judgment is DENIED"},
    ]
    rows = {r["motion_type"]: r for r in analyze_motions(items)}
    mtd = rows["Motion to Dismiss"]
    assert mtd["filed_count"] == 2
    assert mtd["granted"] == 1 and mtd["denied"] == 0
    assert mtd["success_rate"] == 100.0
    msj = rows["Motion for Summary Judgment"]
    assert msj["denied"] == 1
    assert msj["success_rate"] == 0.0


def test_analyze_motions_partial():
    items = [{
        "id": 1,
        "description": "Order on Motion to Compel",
        "text": "the Motion to Compel is GRANTED in part and DENIED in part",
    }]
    rows = {r["motion_type"]: r for r in analyze_motions(items)}
    assert rows["Motion to Compel"]["partial"] == 1
    assert rows["Motion to Compel"]["success_rate"] == 50.0


def test_extract_citations_and_case_name():
    text = "As held in Bell Atlantic Corp. v. Twombly, 550 U.S. 544 (2007), the standard..."
    cites = extract_citations(text)
    assert ("550 U.S. 544", ) == (cites[0][0],)
    assert cites[0][1] is not None and "Twombly" in cites[0][1]


def test_extract_citations_multiple_reporters():
    text = "See 556 U.S. 662; 129 S. Ct. 1937; 778 F.3d 1004; 5 F. Supp. 2d 12."
    found = {c for c, _ in extract_citations(text)}
    assert "556 U.S. 662" in found
    assert "778 F.3d 1004" in found
    assert "5 F. Supp. 2d 12" in found


def test_analyze_citations_doc_count():
    docs = {
        1: "relying on 550 U.S. 544 and also 556 U.S. 662",
        2: "again citing 550 U.S. 544 here",
        3: "no citations in this filing at all",
    }
    rows = {r["citation"]: r for r in analyze_citations(docs)}
    assert rows["550 U.S. 544"]["doc_count"] == 2
    assert rows["556 U.S. 662"]["doc_count"] == 1


def test_normalize_citation_collapses_space():
    assert normalize_citation("550   U.S.\n544") == "550 U.S. 544"


def test_analyze_phrases_recurring():
    shared = "the plaintiff has failed to state a claim upon which relief"
    docs = {
        1: "intro one " + shared + " tail one",
        2: "intro two " + shared + " tail two",
        3: "a completely different filing with none of the same recurring phrasing here",
    }
    rows = analyze_phrases(docs, n=6, min_doc_count=2)
    assert rows, "expected a recurring phrase"
    assert rows[0]["doc_count"] == 2


def test_citations_by_motion_buckets():
    from counsel_dossier.analytics import analyze_citations_by_motion
    items = [
        {"id": 1, "description": "Motion to Dismiss",
         "text": "Per Bell Atlantic Corp. v. Twombly, 550 U.S. 544, the complaint fails."},
        {"id": 2, "description": "Motion to Dismiss",
         "text": "Again citing 550 U.S. 544 and Ashcroft v. Iqbal, 556 U.S. 662."},
        {"id": 3, "description": "Motion for Summary Judgment",
         "text": "Under Celotex Corp. v. Catrett, 477 U.S. 317, no genuine dispute exists."},
        {"id": 4, "description": "Order Granting Motion to Dismiss",
         "text": "The Motion to Dismiss is GRANTED. See 550 U.S. 544."},
    ]
    out = analyze_citations_by_motion(items)
    mtd = {r["citation"]: r for r in out["Motion to Dismiss"]}
    # 550 U.S. 544 appears in both MTD motions (not counted from the order)
    assert mtd["550 U.S. 544"]["doc_count"] == 2
    assert "Motion for Summary Judgment" in out
    assert out["Motion for Summary Judgment"][0]["citation"] == "477 U.S. 317"
