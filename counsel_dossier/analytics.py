"""Deterministic litigation analytics. No models, just pattern matching.

Three independent analyzers, all running over the text of documents already
pulled into the local database:

1. Motion outcomes. Classify filings into motion types and read disposition
   language out of order text to estimate how each motion type fares.
2. Citation frequency. Extract reporter citations and rank the cases an
   attorney cites most across their filings.
3. Recurring phrases. Rank the multi-word phrases an attorney reuses across
   filings, the shorter-grain companion to the verbatim boilerplate detector.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable

from .fingerprint import tokenize


# ---------------------------------------------------------------------------
# 1. Motion outcomes
# ---------------------------------------------------------------------------

MOTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Motion to Dismiss", re.compile(r"motion to dismiss", re.I)),
    ("Motion for Summary Judgment", re.compile(r"motion for (?:partial )?summary judgment", re.I)),
    ("Motion for Judgment on the Pleadings", re.compile(r"motion for judgment on the pleadings", re.I)),
    ("Motion to Compel", re.compile(r"motion to compel", re.I)),
    ("Motion for Sanctions", re.compile(r"motion for (?:rule 11 )?sanctions", re.I)),
    ("Motion to Remand", re.compile(r"motion to remand", re.I)),
    ("Motion for Default Judgment", re.compile(r"motion for (?:entry of )?default judgment", re.I)),
    ("Motion to Strike", re.compile(r"motion to strike", re.I)),
    ("Motion for Reconsideration", re.compile(r"motion for reconsideration", re.I)),
    ("Motion to Amend", re.compile(r"motion (?:for leave )?to (?:file an )?amend", re.I)),
    ("Motion in Limine", re.compile(r"motion in limine", re.I)),
    ("Motion to Quash", re.compile(r"motion to quash", re.I)),
    ("Motion for Preliminary Injunction", re.compile(r"motion for (?:a )?preliminary injunction|motion for (?:a )?temporary restraining order", re.I)),
]

_ORDER_HINT = re.compile(r"\bORDER(?:ED|S)?\b|\bIT IS (?:HEREBY )?ORDERED\b|\bis (?:hereby )?(?:GRANTED|DENIED)\b", re.I)


def classify_motion(text: str | None) -> str | None:
    """Return the first motion type whose pattern appears in the text, else None."""
    if not text:
        return None
    for label, pat in MOTION_PATTERNS:
        if pat.search(text):
            return label
    return None


def is_order(description: str | None, text: str | None) -> bool:
    """Heuristic: does this document look like an order that resolves something?"""
    desc = (description or "")
    if re.match(r"\s*order\b", desc, re.I):
        return True
    return bool(_ORDER_HINT.search(text or ""))


def _disposition_near(text: str, start: int) -> str | None:
    """Read the disposition verb in a window around a motion mention."""
    window = text[max(0, start - 70): start + 140].lower()
    has_grant = "grant" in window
    has_deny = "den" in window  # denied, denying, deny
    if has_grant and has_deny:
        return "partial"
    if has_grant:
        return "granted"
    if has_deny:
        return "denied"
    return None


def analyze_motions(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Estimate motion outcomes from a corpus.

    Each item is {"id", "description", "text"}. Returns one row per motion type
    that was seen, with how many were filed, the dispositions read out of order
    text, and a success rate.

    Success rate is computed from observed dispositions as
    (granted + 0.5 * partial) / (granted + denied + partial). It reflects how
    that motion type fared in the attorney's dockets; it does not by itself
    prove the attorney was the movant on each one. Treat it as a lead to verify,
    not a certified win rate.
    """
    filed: Counter[str] = Counter()
    disp: dict[str, Counter[str]] = {}

    for it in items:
        desc = it.get("description") or ""
        text = it.get("text") or ""
        order = is_order(desc, text)

        if not order:
            mt = classify_motion(desc) or classify_motion(text[:200])
            if mt:
                filed[mt] += 1
            continue

        # Order document: tally a disposition per motion type referenced.
        haystack = (desc + "\n" + text) if text else desc
        for label, pat in MOTION_PATTERNS:
            m = pat.search(haystack)
            if not m:
                continue
            d = _disposition_near(haystack, m.start())
            if d:
                disp.setdefault(label, Counter())[d] += 1

    rows: list[dict[str, Any]] = []
    all_types = set(filed) | set(disp)
    for label in all_types:
        c = disp.get(label, Counter())
        granted, denied, partial = c.get("granted", 0), c.get("denied", 0), c.get("partial", 0)
        decided = granted + denied + partial
        success = round((granted + 0.5 * partial) / decided * 100, 1) if decided else None
        rows.append({
            "motion_type": label,
            "filed_count": filed.get(label, 0),
            "granted": granted,
            "denied": denied,
            "partial": partial,
            "decided": decided,
            "success_rate": success,
        })
    rows.sort(key=lambda r: (-(r["filed_count"] + r["decided"]), r["motion_type"]))
    return rows


# ---------------------------------------------------------------------------
# 2. Citation frequency
# ---------------------------------------------------------------------------

_REPORTERS = [
    r"U\.\s?S\.", r"S\.\s?Ct\.", r"L\.\s?Ed\.(?:\s?2d)?",
    r"F\.(?:\s?(?:2d|3d|4th))?", r"F\.\s?Supp\.(?:\s?(?:2d|3d))?", r"F\.R\.D\.",
    r"F\.\s?App'?x\.?",
    r"P\.(?:\s?(?:2d|3d))?", r"A\.(?:\s?(?:2d|3d))?",
    r"N\.E\.(?:\s?(?:2d|3d))?", r"N\.W\.(?:\s?2d)?",
    r"S\.E\.(?:\s?2d)?", r"S\.W\.(?:\s?(?:2d|3d))?",
    r"So\.(?:\s?(?:2d|3d))?", r"Cal\.(?:\s?(?:App\.|Rptr\.))?(?:\s?(?:2d|3d|4th|5th))?",
]
CITATION_RE = re.compile(r"\b(\d{1,4})\s+(" + "|".join(_REPORTERS) + r")\s+(\d{1,5})\b")
_CASENAME_RE = re.compile(r"([A-Z][A-Za-z.&'\-]*(?:\s+[A-Za-z.&'\-]+){0,6}?\s+v\.?\s+[A-Z][A-Za-z.&'\-]*(?:\s+[A-Za-z.&'\-]+){0,6}?),?\s*$")
_SIGNAL_RE = re.compile(r"^(?:see also|see,?\s*e\.g\.,?|see|accord|cf\.?|e\.g\.,?|citing|quoting|but see|compare|contra)\s+", re.I)


def normalize_citation(raw: str) -> str:
    return re.sub(r"\s+", " ", raw).strip()


def _clean_case_name(name: str) -> str:
    return _SIGNAL_RE.sub("", re.sub(r"\s+", " ", name).strip()).strip()


def extract_citations(text: str | None) -> list[tuple[str, str | None]]:
    """Return (citation, case_name_or_None) pairs found in the text."""
    if not text:
        return []
    out: list[tuple[str, str | None]] = []
    for m in CITATION_RE.finditer(text):
        cite = normalize_citation(m.group(0))
        prefix = text[max(0, m.start() - 90):m.start()]
        name_match = _CASENAME_RE.search(prefix)
        name = _clean_case_name(name_match.group(1)) if name_match else None
        out.append((cite, name or None))
    return out


def analyze_citations(docs: dict[int, str]) -> list[dict[str, Any]]:
    """Rank cited authorities across a corpus by how many distinct filings cite them."""
    total: Counter[str] = Counter()
    doc_ids: dict[str, set[int]] = {}
    names: dict[str, str] = {}
    for doc_id, text in docs.items():
        for cite, name in extract_citations(text):
            total[cite] += 1
            doc_ids.setdefault(cite, set()).add(doc_id)
            if name and cite not in names:
                names[cite] = name
    rows = [{
        "citation": cite,
        "case_name": names.get(cite),
        "total_count": total[cite],
        "doc_count": len(doc_ids[cite]),
        "doc_ids": sorted(doc_ids[cite]),
    } for cite in total]
    rows.sort(key=lambda r: (-r["doc_count"], -r["total_count"]))
    return rows


def analyze_citations_by_motion(items: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Bucket cited authorities by the motion type of the filing they appear in.

    Only motion filings are considered (orders are skipped), so the result is
    what the attorney cites when making each kind of motion. Returns
    motion_type -> ranked list of citation rows.
    """
    buckets: dict[str, dict[str, dict[str, Any]]] = {}
    for it in items:
        desc = it.get("description") or ""
        text = it.get("text") or ""
        if is_order(desc, text):
            continue
        mt = classify_motion(desc) or classify_motion(text[:200])
        if not mt:
            continue
        bucket = buckets.setdefault(mt, {})
        for cite, name in extract_citations(text):
            entry = bucket.setdefault(cite, {"count": 0, "doc_ids": set(), "name": None})
            entry["count"] += 1
            entry["doc_ids"].add(it["id"])
            if name and not entry["name"]:
                entry["name"] = name
    out: dict[str, list[dict[str, Any]]] = {}
    for mt, bucket in buckets.items():
        rows = [{
            "citation": cite,
            "case_name": e["name"],
            "total_count": e["count"],
            "doc_count": len(e["doc_ids"]),
        } for cite, e in bucket.items()]
        rows.sort(key=lambda r: (-r["doc_count"], -r["total_count"]))
        out[mt] = rows
    return out


# ---------------------------------------------------------------------------
# 3. Recurring phrases (common arguments)
# ---------------------------------------------------------------------------

def _ngrams(tokens: list[str], n: int) -> list[str]:
    return [" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1)] if len(tokens) >= n else []


def analyze_phrases(
    docs: dict[int, str],
    n: int = 6,
    min_doc_count: int = 2,
    limit: int = 40,
) -> list[dict[str, Any]]:
    """Rank n-word phrases by how many distinct filings reuse them.

    The shorter-grain companion to the verbatim boilerplate detector: surfaces
    recurring argumentative phrasing even when the surrounding paragraph differs.
    """
    total: Counter[str] = Counter()
    doc_ids: dict[str, set[int]] = {}
    for doc_id, text in docs.items():
        toks = tokenize(text)
        seen: set[str] = set()
        for g in _ngrams(toks, n):
            total[g] += 1
            doc_ids.setdefault(g, set()).add(doc_id)
            seen.add(g)
    rows = [{
        "phrase": g,
        "n": n,
        "doc_count": len(doc_ids[g]),
        "total_count": total[g],
    } for g in total if len(doc_ids[g]) >= min_doc_count]
    rows.sort(key=lambda r: (-r["doc_count"], -r["total_count"], r["phrase"]))

    # Collapse overlapping windows of the same underlying sentence: skip a phrase
    # that shares most of its words with an already-kept, higher-ranked phrase.
    kept: list[dict[str, Any]] = []
    for r in rows:
        words = set(r["phrase"].split())
        if any(len(words & set(k["phrase"].split())) >= n - 2 for k in kept):
            continue
        kept.append(r)
        if len(kept) >= limit:
            break
    return kept
