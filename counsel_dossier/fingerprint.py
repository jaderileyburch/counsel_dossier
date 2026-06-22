"""Boilerplate fingerprinting.

Detects language an attorney reuses across filings. Two layers:

1. Document similarity. Each document is reduced to a set of hashed word
   shingles; pairwise Jaccard similarity flags documents that are largely the
   same brief refiled.

2. Verbatim shared passages. For similar document pairs, the longest exact
   matching blocks are extracted, normalized, and aggregated across the whole
   corpus so you can say "this exact passage appears in N filings" and list
   them.

Pure standard library plus a hash. Pairwise comparison is O(n^2), which is fine
for a single attorney's corpus (tens to low hundreds of documents). For very
large corpora, raise the similarity threshold or pre-filter by court or year.
"""
from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher
from typing import Iterable

_WORD_RE = re.compile(r"[A-Za-z0-9']+")


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens, punctuation stripped."""
    if not text:
        return []
    return _WORD_RE.findall(text.lower())


def shingles(tokens: list[str], k: int = 5) -> set[int]:
    """Set of hashed k-word shingles."""
    if k <= 0:
        raise ValueError("k must be positive")
    if len(tokens) < k:
        # Short text: hash the whole thing as one shingle so it still compares.
        if not tokens:
            return set()
        return {_hash(" ".join(tokens))}
    out: set[int] = set()
    for i in range(len(tokens) - k + 1):
        out.add(_hash(" ".join(tokens[i:i + k])))
    return out


def _hash(s: str) -> int:
    return int.from_bytes(hashlib.blake2b(s.encode("utf-8"), digest_size=8).digest(), "big")


def jaccard(a: set[int], b: set[int]) -> float:
    """Jaccard similarity of two shingle sets."""
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def normalize_passage(text: str) -> str:
    """Canonical form of a passage for cross-document aggregation."""
    return " ".join(text.lower().split())


def shared_passages(
    tokens_a: list[str],
    tokens_b: list[str],
    min_words: int = 25,
) -> list[str]:
    """Return verbatim passages (>= min_words tokens) shared by two token lists."""
    matcher = SequenceMatcher(None, tokens_a, tokens_b, autojunk=False)
    out: list[str] = []
    for block in matcher.get_matching_blocks():
        if block.size >= min_words:
            out.append(" ".join(tokens_a[block.a:block.a + block.size]))
    return out


def find_boilerplate(
    docs: dict[int, str],
    k: int = 5,
    similarity_threshold: float = 0.4,
    min_passage_words: int = 25,
) -> dict[str, object]:
    """Analyze a corpus of documents for reused language.

    docs maps a document id to its text.

    Returns:
        {
          "similar_pairs": [(id_a, id_b, jaccard), ...] above threshold,
          "passages": [
            {"text": str, "word_count": int, "doc_ids": [..], "doc_count": int},
            ...
          ] sorted by doc_count desc then word_count desc,
        }
    """
    ids = list(docs.keys())
    token_lists = {i: tokenize(docs[i]) for i in ids}
    shingle_sets = {i: shingles(token_lists[i], k) for i in ids}

    similar_pairs: list[tuple[int, int, float]] = []
    # passage_hash -> {"text", "word_count", "doc_ids": set}
    passage_index: dict[str, dict[str, object]] = {}

    for x in range(len(ids)):
        for y in range(x + 1, len(ids)):
            ia, ib = ids[x], ids[y]
            sim = jaccard(shingle_sets[ia], shingle_sets[ib])
            if sim < similarity_threshold and sim == 0.0:
                # No overlap at all; skip passage extraction.
                continue
            if sim >= similarity_threshold:
                similar_pairs.append((ia, ib, round(sim, 4)))
            # Extract verbatim passages even for moderate overlap, because a
            # recycled paragraph can hide in an otherwise distinct brief.
            for passage in shared_passages(token_lists[ia], token_lists[ib], min_passage_words):
                norm = normalize_passage(passage)
                h = hashlib.blake2b(norm.encode("utf-8"), digest_size=16).hexdigest()
                entry = passage_index.get(h)
                if entry is None:
                    passage_index[h] = {
                        "text": passage,
                        "word_count": len(passage.split()),
                        "doc_ids": {ia, ib},
                    }
                else:
                    entry["doc_ids"].update({ia, ib})  # type: ignore[union-attr]

    passages = []
    for h, entry in passage_index.items():
        doc_ids = sorted(entry["doc_ids"])  # type: ignore[arg-type]
        passages.append({
            "hash": h,
            "text": entry["text"],
            "word_count": entry["word_count"],
            "doc_ids": doc_ids,
            "doc_count": len(doc_ids),
        })
    passages.sort(key=lambda p: (-p["doc_count"], -p["word_count"]))

    similar_pairs.sort(key=lambda t: -t[2])
    return {"similar_pairs": similar_pairs, "passages": passages}
