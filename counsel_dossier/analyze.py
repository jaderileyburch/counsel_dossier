"""Aggregation queries that turn pulled records into dossier figures."""
from __future__ import annotations

import sqlite3
from typing import Any


def total_dockets(conn: sqlite3.Connection, target_id: str) -> int:
    return int(conn.execute(
        "SELECT COUNT(*) AS n FROM dockets WHERE target_id = ?", (target_id,)
    ).fetchone()["n"])


def yearly_caseload(conn: sqlite3.Connection, target_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT substr(date_filed, 1, 4) AS year, COUNT(*) AS n
        FROM dockets
        WHERE target_id = ? AND date_filed IS NOT NULL
        GROUP BY year ORDER BY year
        """,
        (target_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def court_breakdown(conn: sqlite3.Connection, target_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT court, COUNT(*) AS n FROM dockets
        WHERE target_id = ? GROUP BY court ORDER BY n DESC
        """,
        (target_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def nature_of_suit_breakdown(conn: sqlite3.Connection, target_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT nature_of_suit, COUNT(*) AS n FROM dockets
        WHERE target_id = ? AND nature_of_suit IS NOT NULL AND nature_of_suit != ''
        GROUP BY nature_of_suit ORDER BY n DESC
        """,
        (target_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def judge_exposure(conn: sqlite3.Connection, target_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT assigned_judge, COUNT(*) AS n FROM dockets
        WHERE target_id = ? AND assigned_judge IS NOT NULL AND assigned_judge != ''
        GROUP BY assigned_judge ORDER BY n DESC
        """,
        (target_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def disposition_breakdown(conn: sqlite3.Connection, target_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT idb_disposition, COUNT(*) AS n FROM dockets
        WHERE target_id = ? AND idb_disposition IS NOT NULL AND idb_disposition != ''
        GROUP BY idb_disposition ORDER BY n DESC
        """,
        (target_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def party_side_breakdown(conn: sqlite3.Connection, target_id: str) -> list[dict[str, Any]]:
    """Which parties the target attorney represented, by frequency."""
    rows = conn.execute(
        """
        SELECT party_name, COUNT(DISTINCT docket_id) AS n FROM attorneys
        WHERE target_id = ? AND party_name IS NOT NULL AND party_name != ''
        GROUP BY party_name ORDER BY n DESC
        """,
        (target_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def firm_breakdown(conn: sqlite3.Connection, target_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT firm, COUNT(DISTINCT docket_id) AS n FROM attorneys
        WHERE target_id = ? AND firm IS NOT NULL AND firm != ''
        GROUP BY firm ORDER BY n DESC
        """,
        (target_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def category_counts(conn: sqlite3.Connection, target_id: str) -> list[dict[str, Any]]:
    """Classification category match counts across all classified items."""
    rows = conn.execute(
        """
        SELECT category, COUNT(*) AS n FROM classifications
        WHERE target_id = ? AND matched = 1
        GROUP BY category ORDER BY n DESC
        """,
        (target_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def matched_items(
    conn: sqlite3.Connection,
    target_id: str,
    category: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Items that matched a category, joined to docket context where possible."""
    rows = conn.execute(
        """
        SELECT cl.item_type, cl.item_id, cl.match_terms,
               o.docket_id AS op_docket, o.court AS op_court, o.date_filed AS op_date
        FROM classifications cl
        LEFT JOIN opinions o
          ON cl.item_type = 'opinion' AND o.opinion_id = cl.item_id
        WHERE cl.target_id = ? AND cl.category = ? AND cl.matched = 1
        ORDER BY o.date_filed DESC
        LIMIT ?
        """,
        (target_id, category, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def documents_with_text(conn: sqlite3.Connection, target_id: str) -> dict[int, str]:
    """All documents that have plain_text, for the fingerprinter."""
    rows = conn.execute(
        """
        SELECT recap_document_id, plain_text FROM documents
        WHERE target_id = ? AND plain_text IS NOT NULL AND plain_text != ''
        """,
        (target_id,),
    ).fetchall()
    return {r["recap_document_id"]: r["plain_text"] for r in rows}


def top_passages(conn: sqlite3.Connection, target_id: str, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT passage_text, word_count, doc_count, doc_ids_json
        FROM shared_passages
        WHERE target_id = ?
        ORDER BY doc_count DESC, word_count DESC
        LIMIT ?
        """,
        (target_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def motion_stats(conn: sqlite3.Connection, target_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT motion_type, filed_count, granted, denied, partial, decided, success_rate
        FROM motion_stats WHERE target_id = ?
        ORDER BY (filed_count + decided) DESC, motion_type
        """,
        (target_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def top_citations(conn: sqlite3.Connection, target_id: str, limit: int = 25) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT citation, case_name, total_count, doc_count
        FROM citations WHERE target_id = ?
        ORDER BY doc_count DESC, total_count DESC
        LIMIT ?
        """,
        (target_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def top_phrases_stored(conn: sqlite3.Connection, target_id: str, limit: int = 25) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT phrase, n, doc_count, total_count
        FROM phrases WHERE target_id = ?
        ORDER BY doc_count DESC, total_count DESC
        LIMIT ?
        """,
        (target_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def documents_for_analytics(conn: sqlite3.Connection, target_id: str) -> list[dict[str, Any]]:
    """Documents with text, including description, for motion/citation/phrase analysis."""
    rows = conn.execute(
        """
        SELECT recap_document_id AS id, description, plain_text AS text
        FROM documents
        WHERE target_id = ? AND plain_text IS NOT NULL AND plain_text != ''
        """,
        (target_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def citations_by_motion(conn: sqlite3.Connection, target_id: str, per_type: int = 8) -> dict[str, list[dict[str, Any]]]:
    """Return motion_type -> ranked citation rows, capped per type."""
    rows = conn.execute(
        """
        SELECT motion_type, citation, case_name, total_count, doc_count
        FROM citations_by_motion WHERE target_id = ?
        ORDER BY motion_type, doc_count DESC, total_count DESC
        """,
        (target_id,),
    ).fetchall()
    out: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        bucket = out.setdefault(r["motion_type"], [])
        if len(bucket) < per_type:
            bucket.append(dict(r))
    return out
