"""Tests for the classifier and attorney name normalization."""
from counsel_dossier.classify import compile_taxonomy, classify_text
from counsel_dossier.pull import normalize_attorney, load_aliases, build_search_params


TAXONOMY = {
    "sanctions": {
        "description": "Sanction language",
        "keywords": ["sanction", "Rule 11", "bad faith"],
        "min_matches": 1,
    },
    "strong": {
        "description": "Two distinct hits required",
        "keywords": ["frivolous", "vexatious", "show cause"],
        "min_matches": 2,
    },
}


def test_classify_keyword_case_insensitive():
    c = compile_taxonomy(TAXONOMY)
    r = classify_text("The court imposed a SANCTION under Rule 11.", c)
    assert r["sanctions"]["matched"] is True
    assert r["sanctions"]["score"] == 2.0


def test_classify_min_matches():
    c = compile_taxonomy(TAXONOMY)
    one = classify_text("The filing was frivolous.", c)
    assert one["strong"]["matched"] is False
    two = classify_text("The frivolous and vexatious filing warranted show cause.", c)
    assert two["strong"]["matched"] is True


def test_classify_empty_text():
    c = compile_taxonomy(TAXONOMY)
    r = classify_text("", c)
    assert all(v["matched"] is False for v in r.values())


def test_normalize_strips_esq_and_folds_case():
    assert normalize_attorney("Aaron R. Dean, Esq.") == "AARON R. DEAN"
    assert normalize_attorney("  jane   q   attorney  ") == "JANE Q ATTORNEY"
    assert normalize_attorney(None) is None


def test_normalize_with_aliases(tmp_path):
    p = tmp_path / "aliases.yaml"
    p.write_text("AARON R DEAN:\n  - Aaron Dean\n  - A. R. Dean, Esq.\n", encoding="utf-8")
    rev = load_aliases(p)
    assert normalize_attorney("Aaron Dean", rev) == "AARON R DEAN"
    assert normalize_attorney("A. R. Dean, Esq.", rev) == "AARON R DEAN"


def test_load_aliases_missing_returns_empty(tmp_path):
    assert load_aliases(tmp_path / "none.yaml") == {}


def test_build_search_params_attorney_and_filters():
    params = build_search_params("Jane Attorney", {"court": "nvd", "date_filed_min": "2018-01-01"})
    keys = dict(params)
    assert keys["type"] == "r"
    assert 'attorney:("Jane Attorney")' == keys["q"]
    assert keys["court"] == "nvd"
    assert keys["filed_after"] == "2018-01-01"
