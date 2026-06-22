"""Configurable keyword and regex classification engine.

Runs a taxonomy (categories of keywords and regex patterns) across text items,
typically opinions or order text, to surface things like sanction language,
Rule 11 references, frivolousness findings, or fee awards naming the target.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from typing import Any


def compile_taxonomy(taxonomy: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Pre-compile keyword and regex patterns for each category."""
    compiled: dict[str, dict[str, Any]] = {}
    for cat_id, cat_def in taxonomy.items():
        patterns: list[tuple[str, re.Pattern[str]]] = []
        for kw in cat_def.get("keywords") or []:
            patterns.append((kw, re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)))
        for rx in cat_def.get("regex") or []:
            patterns.append((rx, re.compile(rx, re.IGNORECASE)))
        compiled[cat_id] = {
            "description": cat_def.get("description", ""),
            "patterns": patterns,
            "min_matches": int(cat_def.get("min_matches", 1)),
        }
    return compiled


def classify_text(
    text: str | None,
    compiled_taxonomy: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Return per-category match results for a single text item."""
    results: dict[str, dict[str, Any]] = {}
    if not text:
        for cat_id in compiled_taxonomy:
            results[cat_id] = {"matched": False, "match_terms": [], "score": 0.0}
        return results
    for cat_id, cat in compiled_taxonomy.items():
        hits: list[str] = []
        for term, pat in cat["patterns"]:
            if pat.search(text):
                hits.append(term)
        results[cat_id] = {
            "matched": len(hits) >= cat["min_matches"],
            "match_terms": hits,
            "score": float(len(hits)),
        }
    return results


def classify_target(
    conn: sqlite3.Connection,
    target_id: str,
    taxonomy: dict[str, dict[str, Any]],
    item_type: str = "opinion",
) -> dict[str, int]:
    """Classify every stored text item of the given type for a target.

    item_type is 'opinion' or 'document'. Returns category -> match count.
    """
    compiled = compile_taxonomy(taxonomy)

    if item_type == "opinion":
        sql = (
            "SELECT opinion_id AS item_id, plain_text AS text FROM opinions "
            "WHERE target_id = ? AND plain_text IS NOT NULL AND plain_text != ''"
        )
    elif item_type == "document":
        sql = (
            "SELECT recap_document_id AS item_id, plain_text AS text FROM documents "
            "WHERE target_id = ? AND plain_text IS NOT NULL AND plain_text != ''"
        )
    else:
        raise ValueError(f"Unknown item_type: {item_type}")

    rows = conn.execute(sql, (target_id,)).fetchall()
    counts: dict[str, int] = {cat: 0 for cat in compiled}
    now = datetime.now(timezone.utc).isoformat()

    for row in rows:
        results = classify_text(row["text"], compiled)
        for cat_id, result in results.items():
            conn.execute(
                "INSERT OR REPLACE INTO classifications "
                "(item_type, item_id, target_id, category, matched, match_terms, score, classified_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item_type,
                    row["item_id"],
                    target_id,
                    cat_id,
                    1 if result["matched"] else 0,
                    ", ".join(result["match_terms"]),
                    result["score"],
                    now,
                ),
            )
            if result["matched"]:
                counts[cat_id] += 1

    conn.commit()
    return counts
