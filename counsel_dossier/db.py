"""SQLite schema and helpers for Counsel Dossier."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS targets (
    target_id TEXT PRIMARY KEY,
    name TEXT,
    config_json TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS dockets (
    docket_id INTEGER PRIMARY KEY,
    target_id TEXT,
    court TEXT,
    docket_number TEXT,
    case_name TEXT,
    date_filed TEXT,
    date_terminated TEXT,
    nature_of_suit TEXT,
    cause TEXT,
    jurisdiction TEXT,
    assigned_judge TEXT,
    idb_disposition TEXT,
    raw_json TEXT,
    pulled_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_dockets_target ON dockets(target_id);
CREATE INDEX IF NOT EXISTS idx_dockets_court ON dockets(court);
CREATE INDEX IF NOT EXISTS idx_dockets_date ON dockets(date_filed);

CREATE TABLE IF NOT EXISTS attorneys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cl_attorney_id INTEGER,
    target_id TEXT,
    docket_id INTEGER,
    name TEXT,
    name_normalized TEXT,
    firm TEXT,
    party_name TEXT,
    contact_raw TEXT,
    raw_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_attys_target ON attorneys(target_id);
CREATE INDEX IF NOT EXISTS idx_attys_norm ON attorneys(name_normalized);
CREATE INDEX IF NOT EXISTS idx_attys_docket ON attorneys(docket_id);

CREATE TABLE IF NOT EXISTS opinions (
    opinion_id INTEGER PRIMARY KEY,
    target_id TEXT,
    cluster_id INTEGER,
    docket_id INTEGER,
    court TEXT,
    date_filed TEXT,
    type TEXT,
    plain_text TEXT,
    raw_json TEXT,
    pulled_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_opinions_target ON opinions(target_id);
CREATE INDEX IF NOT EXISTS idx_opinions_docket ON opinions(docket_id);

CREATE TABLE IF NOT EXISTS documents (
    recap_document_id INTEGER PRIMARY KEY,
    target_id TEXT,
    docket_id INTEGER,
    docket_entry_id INTEGER,
    description TEXT,
    page_count INTEGER,
    is_available INTEGER,
    sha1 TEXT,
    plain_text TEXT,
    raw_json TEXT,
    pulled_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_documents_target ON documents(target_id);
CREATE INDEX IF NOT EXISTS idx_documents_docket ON documents(docket_id);

CREATE TABLE IF NOT EXISTS classifications (
    item_type TEXT,
    item_id INTEGER,
    target_id TEXT,
    category TEXT,
    matched INTEGER,
    match_terms TEXT,
    score REAL,
    classified_at TEXT,
    PRIMARY KEY (item_type, item_id, target_id, category)
);

CREATE INDEX IF NOT EXISTS idx_class_target ON classifications(target_id, category, matched);

CREATE TABLE IF NOT EXISTS shared_passages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id TEXT,
    passage_hash TEXT,
    passage_text TEXT,
    word_count INTEGER,
    doc_count INTEGER,
    doc_ids_json TEXT,
    created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_passages_target ON shared_passages(target_id, doc_count);

CREATE TABLE IF NOT EXISTS pull_log (
    pull_id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id TEXT,
    phase TEXT,
    started_at TEXT,
    completed_at TEXT,
    records_fetched INTEGER,
    records_new INTEGER,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS motion_stats (
    target_id TEXT,
    motion_type TEXT,
    filed_count INTEGER,
    granted INTEGER,
    denied INTEGER,
    partial INTEGER,
    decided INTEGER,
    success_rate REAL,
    computed_at TEXT,
    PRIMARY KEY (target_id, motion_type)
);

CREATE TABLE IF NOT EXISTS citations (
    target_id TEXT,
    citation TEXT,
    case_name TEXT,
    total_count INTEGER,
    doc_count INTEGER,
    doc_ids_json TEXT,
    computed_at TEXT,
    PRIMARY KEY (target_id, citation)
);

CREATE TABLE IF NOT EXISTS phrases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id TEXT,
    phrase TEXT,
    n INTEGER,
    doc_count INTEGER,
    total_count INTEGER,
    computed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_phrases_target ON phrases(target_id, doc_count);

CREATE TABLE IF NOT EXISTS citations_by_motion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id TEXT,
    motion_type TEXT,
    citation TEXT,
    case_name TEXT,
    total_count INTEGER,
    doc_count INTEGER,
    computed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_cbm_target ON citations_by_motion(target_id, motion_type, doc_count);
"""


def open_db(path: str | Path) -> sqlite3.Connection:
    """Open a connection with sensible pragmas."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(path: str | Path) -> None:
    """Create the schema if it does not already exist."""
    conn = open_db(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def upsert_docket(conn: sqlite3.Connection, record: dict[str, Any]) -> bool:
    """Insert or replace a docket. Returns True if the row was new."""
    cols = [
        "docket_id", "target_id", "court", "docket_number", "case_name",
        "date_filed", "date_terminated", "nature_of_suit", "cause",
        "jurisdiction", "assigned_judge", "idb_disposition", "raw_json", "pulled_at",
    ]
    existing = conn.execute(
        "SELECT 1 FROM dockets WHERE docket_id = ?", (record["docket_id"],)
    ).fetchone()
    placeholders = ", ".join(["?"] * len(cols))
    conn.execute(
        f"INSERT OR REPLACE INTO dockets ({', '.join(cols)}) VALUES ({placeholders})",
        [record.get(c) for c in cols],
    )
    return existing is None


def insert_attorney(conn: sqlite3.Connection, record: dict[str, Any]) -> None:
    cols = [
        "cl_attorney_id", "target_id", "docket_id", "name", "name_normalized",
        "firm", "party_name", "contact_raw", "raw_json",
    ]
    placeholders = ", ".join(["?"] * len(cols))
    conn.execute(
        f"INSERT INTO attorneys ({', '.join(cols)}) VALUES ({placeholders})",
        [record.get(c) for c in cols],
    )


def upsert_opinion(conn: sqlite3.Connection, record: dict[str, Any]) -> bool:
    cols = [
        "opinion_id", "target_id", "cluster_id", "docket_id", "court",
        "date_filed", "type", "plain_text", "raw_json", "pulled_at",
    ]
    existing = conn.execute(
        "SELECT 1 FROM opinions WHERE opinion_id = ?", (record["opinion_id"],)
    ).fetchone()
    placeholders = ", ".join(["?"] * len(cols))
    conn.execute(
        f"INSERT OR REPLACE INTO opinions ({', '.join(cols)}) VALUES ({placeholders})",
        [record.get(c) for c in cols],
    )
    return existing is None


def upsert_document(conn: sqlite3.Connection, record: dict[str, Any]) -> bool:
    cols = [
        "recap_document_id", "target_id", "docket_id", "docket_entry_id",
        "description", "page_count", "is_available", "sha1", "plain_text",
        "raw_json", "pulled_at",
    ]
    existing = conn.execute(
        "SELECT 1 FROM documents WHERE recap_document_id = ?",
        (record["recap_document_id"],),
    ).fetchone()
    placeholders = ", ".join(["?"] * len(cols))
    conn.execute(
        f"INSERT OR REPLACE INTO documents ({', '.join(cols)}) VALUES ({placeholders})",
        [record.get(c) for c in cols],
    )
    return existing is None


def clear_attorneys_for_target(conn: sqlite3.Connection, target_id: str) -> None:
    """Attorneys are per-docket appearances re-derived on each pull, so clear first."""
    conn.execute("DELETE FROM attorneys WHERE target_id = ?", (target_id,))


def count(conn: sqlite3.Connection, table: str, target_id: str | None = None) -> int:
    if target_id:
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE target_id = ?", (target_id,)
        ).fetchone()
    else:
        row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
    return int(row["n"])
