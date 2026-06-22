"""CourtListener v4 API client and pull pipeline.

Counsel Dossier is bring-your-own-credential. It never ships a token and never
talks to anything but the public CourtListener API. The user supplies their own
API token via the COURTLISTENER_TOKEN environment variable. Federal court data
only; CourtListener does not carry most state trial courts.

Reference: https://www.courtlistener.com/help/api/rest/v4/

The v4 API requires authentication: anonymous requests receive HTTP 401. Get a
free token from your CourtListener profile.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import requests
import yaml

API_BASE = "https://www.courtlistener.com/api/rest/v4"
SEARCH_ENDPOINT = f"{API_BASE}/search/"
DOCKETS_ENDPOINT = f"{API_BASE}/dockets/"
PARTIES_ENDPOINT = f"{API_BASE}/parties/"
ATTORNEYS_ENDPOINT = f"{API_BASE}/attorneys/"
OPINIONS_ENDPOINT = f"{API_BASE}/opinions/"
DOCUMENTS_ENDPOINT = f"{API_BASE}/recap-documents/"

REQUEST_TIMEOUT = 120
PAGE_SLEEP_SECONDS = 0.5
TOKEN_ENV = "COURTLISTENER_TOKEN"


class AuthError(RuntimeError):
    """Raised when no token is configured or the API rejects the token."""


def get_token() -> str:
    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        raise AuthError(
            f"No CourtListener token found. Set the {TOKEN_ENV} environment "
            f"variable to your token from https://www.courtlistener.com/profile/"
        )
    return token


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Token {token}", "Accept": "application/json"}


def _get(url: str, token: str, params: list[tuple[str, str]] | dict | None = None) -> dict:
    resp = requests.get(url, headers=_headers(token), params=params, timeout=REQUEST_TIMEOUT)
    if resp.status_code == 401:
        raise AuthError("CourtListener rejected the token (HTTP 401). Check COURTLISTENER_TOKEN.")
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Attorney name normalization (the per-docket-extracted-name disambiguation
# problem). Same alias pattern as a company normalizer: collapse known variants
# of one attorney into a single canonical name.
# ---------------------------------------------------------------------------

def load_aliases(path: str | Path) -> dict[str, str]:
    """Load an attorney alias map: VARIANT (upper) -> canonical name."""
    p = Path(path)
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    reverse: dict[str, str] = {}
    for canonical, variants in data.items():
        can = " ".join(str(canonical).split()).strip()
        if not can:
            continue
        reverse[can.upper()] = can
        for variant in (variants or []):
            v = " ".join(str(variant).split()).strip()
            if v:
                reverse[v.upper()] = can
    return reverse


def normalize_attorney(name: str | None, aliases: dict[str, str] | None = None) -> str | None:
    """Canonicalize an attorney name.

    Strips honorifics and trailing credentials, collapses whitespace and case,
    then applies the alias map if supplied.
    """
    if not name:
        return None
    n = " ".join(name.strip().split())
    raw_upper = n.upper()
    if aliases and raw_upper in aliases:
        return aliases[raw_upper]
    upper = raw_upper
    # Drop trailing credentials like ", ESQ." or ", ESQ"
    for tail in (", ESQ.", " ESQ.", ", ESQ", " ESQ", ", J.D.", " J.D."):
        if upper.endswith(tail):
            upper = upper[: -len(tail)].strip().rstrip(",").strip()
    if aliases and upper in aliases:
        return aliases[upper]
    return upper


# ---------------------------------------------------------------------------
# Search: find dockets where a target attorney appears.
# ---------------------------------------------------------------------------

def build_search_params(attorney_name: str, filters: dict[str, Any]) -> list[tuple[str, str]]:
    """Build search params to find RECAP dockets for an attorney.

    Uses the fielded `attorney` query against the RECAP search type. Optional
    court and date filters narrow the result set.
    """
    params: list[tuple[str, str]] = [
        ("type", "r"),
        ("q", f'attorney:("{attorney_name}")'),
        ("order_by", "dateFiled desc"),
    ]
    if filters.get("court"):
        params.append(("court", str(filters["court"])))
    if filters.get("date_filed_min"):
        params.append(("filed_after", str(filters["date_filed_min"])))
    if filters.get("date_filed_max"):
        params.append(("filed_before", str(filters["date_filed_max"])))
    return params


def iter_search_dockets(
    attorney_name: str,
    filters: dict[str, Any],
    token: str,
    max_pages: int | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield search result rows (one per matching docket) via cursor pagination."""
    params = build_search_params(attorney_name, filters)
    url = SEARCH_ENDPOINT
    page = 0
    next_params: list[tuple[str, str]] | None = params
    next_url = url
    while True:
        if max_pages is not None and page >= max_pages:
            return
        data = _get(next_url, token, next_params)
        for row in data.get("results", []) or []:
            yield row
        nxt = data.get("next")
        if not nxt:
            return
        # The 'next' URL already carries the cursor and query; follow it directly.
        next_url = nxt
        next_params = None
        page += 1
        time.sleep(PAGE_SLEEP_SECONDS)


# ---------------------------------------------------------------------------
# Detail fetches.
# ---------------------------------------------------------------------------

def fetch_docket(docket_id: int, token: str) -> dict[str, Any]:
    return _get(f"{DOCKETS_ENDPOINT}{docket_id}/", token)


def fetch_parties(docket_id: int, token: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    data = _get(PARTIES_ENDPOINT, token, [("docket", str(docket_id)), ("filter_nested_results", "true")])
    while True:
        out.extend(data.get("results", []) or [])
        nxt = data.get("next")
        if not nxt:
            break
        data = _get(nxt, token)
        time.sleep(PAGE_SLEEP_SECONDS)
    return out


def fetch_recap_documents(docket_id: int, token: str, max_pages: int | None = None) -> Iterator[dict[str, Any]]:
    """Yield RECAP documents for a docket, including plain_text where available.

    Documents already in the RECAP Archive carry plain_text for free over the
    API. Documents not yet in the archive have no text here and would need to be
    purchased from PACER with the user's own credential (see recap-fetch).
    """
    data = _get(DOCUMENTS_ENDPOINT, token, [("docket_entry__docket", str(docket_id))])
    page = 0
    while True:
        for row in data.get("results", []) or []:
            yield row
        nxt = data.get("next")
        if not nxt:
            return
        page += 1
        if max_pages is not None and page >= max_pages:
            return
        data = _get(nxt, token)
        time.sleep(PAGE_SLEEP_SECONDS)


# ---------------------------------------------------------------------------
# Record transforms.
# ---------------------------------------------------------------------------

def to_docket_record(raw: dict[str, Any], target_id: str) -> dict[str, Any]:
    idb = raw.get("idb_data") or {}
    return {
        "docket_id": raw.get("id"),
        "target_id": target_id,
        "court": raw.get("court_id") or raw.get("court"),
        "docket_number": raw.get("docket_number"),
        "case_name": raw.get("case_name") or raw.get("case_name_full"),
        "date_filed": raw.get("date_filed"),
        "date_terminated": raw.get("date_terminated"),
        "nature_of_suit": raw.get("nature_of_suit") or idb.get("nature_of_suit"),
        "cause": raw.get("cause"),
        "jurisdiction": raw.get("jurisdiction_type") or idb.get("jurisdiction"),
        "assigned_judge": raw.get("assigned_to_str"),
        "idb_disposition": idb.get("disposition"),
        "raw_json": json.dumps(raw, separators=(",", ":")),
        "pulled_at": datetime.now(timezone.utc).isoformat(),
    }


def to_search_docket_record(row: dict[str, Any], target_id: str) -> dict[str, Any]:
    """Build a lightweight docket record from a search result row.

    Search rows are shallower than the full docket object. Used when pulling
    metadata-only (no detail fetch).
    """
    return {
        "docket_id": row.get("docket_id") or row.get("id"),
        "target_id": target_id,
        "court": row.get("court_id"),
        "docket_number": row.get("docketNumber"),
        "case_name": row.get("caseName"),
        "date_filed": row.get("dateFiled"),
        "date_terminated": row.get("dateTerminated"),
        "nature_of_suit": row.get("suitNature"),
        "cause": row.get("cause"),
        "jurisdiction": row.get("court_id"),
        "assigned_judge": row.get("assignedTo") or row.get("judge"),
        "idb_disposition": None,
        "raw_json": json.dumps(row, separators=(",", ":")),
        "pulled_at": datetime.now(timezone.utc).isoformat(),
    }


def extract_attorneys_from_parties(
    parties: list[dict[str, Any]],
    docket_id: int,
    target_id: str,
    aliases: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Flatten nested attorney records out of the parties payload."""
    records: list[dict[str, Any]] = []
    for party in parties:
        party_name = party.get("name")
        for atty in party.get("attorneys", []) or []:
            name = atty.get("name")
            firm = None
            # Contact blob often carries the firm on the first line.
            contact = atty.get("contact_raw") or ""
            if contact:
                firm = contact.splitlines()[0].strip() or None
            records.append({
                "cl_attorney_id": atty.get("id"),
                "target_id": target_id,
                "docket_id": docket_id,
                "name": name,
                "name_normalized": normalize_attorney(name, aliases),
                "firm": firm,
                "party_name": party_name,
                "contact_raw": contact or None,
                "raw_json": json.dumps(atty, separators=(",", ":")),
            })
    return records


def to_document_record(raw: dict[str, Any], docket_id: int, target_id: str) -> dict[str, Any]:
    return {
        "recap_document_id": raw.get("id"),
        "target_id": target_id,
        "docket_id": docket_id,
        "docket_entry_id": raw.get("docket_entry"),
        "description": raw.get("description") or raw.get("document_type"),
        "page_count": raw.get("page_count"),
        "is_available": 1 if raw.get("is_available") else 0,
        "sha1": raw.get("sha1"),
        "plain_text": raw.get("plain_text") or None,
        "raw_json": json.dumps(raw, separators=(",", ":")),
        "pulled_at": datetime.now(timezone.utc).isoformat(),
    }
