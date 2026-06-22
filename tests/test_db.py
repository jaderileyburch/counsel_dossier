"""Tests for schema creation and upsert/insert behavior."""
from counsel_dossier import db as db_mod


def _docket(did, target="t1", court="nvd"):
    return {
        "docket_id": did, "target_id": target, "court": court,
        "docket_number": "2:24-cv-00001", "case_name": "Foo v. Bar",
        "date_filed": "2024-01-02", "date_terminated": None,
        "nature_of_suit": "Contract", "cause": "28:1331", "jurisdiction": "FQ",
        "assigned_judge": "Judge Smith", "idb_disposition": "Dismissed",
        "raw_json": "{}", "pulled_at": "2026-01-01T00:00:00+00:00",
    }


def test_init_creates_tables(tmp_path):
    p = tmp_path / "d.db"
    db_mod.init_db(p)
    conn = db_mod.open_db(p)
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ("targets", "dockets", "attorneys", "opinions", "documents", "classifications", "shared_passages", "pull_log"):
        assert t in names
    conn.close()


def test_upsert_docket_new_then_replace(tmp_path):
    p = tmp_path / "d.db"
    db_mod.init_db(p)
    conn = db_mod.open_db(p)
    assert db_mod.upsert_docket(conn, _docket(1)) is True
    assert db_mod.upsert_docket(conn, _docket(1)) is False
    assert db_mod.count(conn, "dockets") == 1
    assert db_mod.count(conn, "dockets", "t1") == 1
    conn.close()


def test_insert_and_clear_attorneys(tmp_path):
    p = tmp_path / "d.db"
    db_mod.init_db(p)
    conn = db_mod.open_db(p)
    db_mod.insert_attorney(conn, {
        "cl_attorney_id": 9, "target_id": "t1", "docket_id": 1,
        "name": "Jane Attorney", "name_normalized": "JANE ATTORNEY",
        "firm": "Example LLP", "party_name": "Defendant", "contact_raw": None, "raw_json": "{}",
    })
    assert db_mod.count(conn, "attorneys", "t1") == 1
    db_mod.clear_attorneys_for_target(conn, "t1")
    assert db_mod.count(conn, "attorneys", "t1") == 0
    conn.close()


def test_upsert_document(tmp_path):
    p = tmp_path / "d.db"
    db_mod.init_db(p)
    conn = db_mod.open_db(p)
    rec = {
        "recap_document_id": 5, "target_id": "t1", "docket_id": 1, "docket_entry_id": 2,
        "description": "Motion to Dismiss", "page_count": 12, "is_available": 1,
        "sha1": "abc", "plain_text": "comes now the defendant", "raw_json": "{}",
        "pulled_at": "2026-01-01T00:00:00+00:00",
    }
    assert db_mod.upsert_document(conn, rec) is True
    assert db_mod.upsert_document(conn, rec) is False
    assert db_mod.count(conn, "documents", "t1") == 1
    conn.close()
