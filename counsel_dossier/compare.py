"""Opposing counsel comparison.

Compares two already-pulled targets head to head: cited authorities, judges,
motion practice, disposition rates, and verbatim boilerplate overlap between
the two attorneys' filings (a strong signal of shared templates, same firm, or
one copying the other).
"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Template

from . import analyze
from .fingerprint import tokenize, shared_passages, normalize_passage


def cross_corpus_passages(
    docs_a: dict[int, str],
    docs_b: dict[int, str],
    min_words: int = 25,
) -> list[dict[str, Any]]:
    """Verbatim passages that appear in BOTH attorneys' filings.

    Pairwise across the two corpora; aggregated so each passage carries how many
    A documents and how many B documents it appears in.
    """
    toks_a = {i: tokenize(t) for i, t in docs_a.items()}
    toks_b = {i: tokenize(t) for i, t in docs_b.items()}
    index: dict[str, dict[str, Any]] = {}
    for ta in toks_a.values():
        for tb in toks_b.values():
            for p in shared_passages(ta, tb, min_words):
                h = hashlib.blake2b(normalize_passage(p).encode("utf-8"), digest_size=16).hexdigest()
                entry = index.get(h)
                if entry is None:
                    index[h] = {"text": p, "word_count": len(p.split()), "count": 1}
                else:
                    entry["count"] += 1
    rows = list(index.values())
    rows.sort(key=lambda r: -r["word_count"])
    return rows


def _label(conn: sqlite3.Connection, target_id: str) -> str:
    row = conn.execute("SELECT name FROM targets WHERE target_id = ?", (target_id,)).fetchone()
    return row["name"] if row and row["name"] else target_id


def _shared_authorities(cites_a: list[dict], cites_b: list[dict]) -> list[dict[str, Any]]:
    a_by = {c["citation"]: c for c in cites_a}
    b_by = {c["citation"]: c for c in cites_b}
    shared = []
    for cite in set(a_by) & set(b_by):
        shared.append({
            "citation": cite,
            "case_name": a_by[cite].get("case_name") or b_by[cite].get("case_name"),
            "a_docs": a_by[cite]["doc_count"],
            "b_docs": b_by[cite]["doc_count"],
        })
    shared.sort(key=lambda r: -(r["a_docs"] + r["b_docs"]))
    return shared


def _shared_judges(judges_a: list[dict], judges_b: list[dict]) -> list[dict[str, Any]]:
    a_by = {j["assigned_judge"]: j["n"] for j in judges_a}
    b_by = {j["assigned_judge"]: j["n"] for j in judges_b}
    shared = [{"judge": j, "a": a_by[j], "b": b_by[j]} for j in set(a_by) & set(b_by)]
    shared.sort(key=lambda r: -(r["a"] + r["b"]))
    return shared


def build_comparison(conn: sqlite3.Connection, target_a: str, target_b: str) -> dict[str, Any]:
    cites_a = analyze.top_citations(conn, target_a, limit=25)
    cites_b = analyze.top_citations(conn, target_b, limit=25)
    judges_a = analyze.judge_exposure(conn, target_a)
    judges_b = analyze.judge_exposure(conn, target_b)
    docs_a = analyze.documents_with_text(conn, target_a)
    docs_b = analyze.documents_with_text(conn, target_b)

    return {
        "label_a": _label(conn, target_a),
        "label_b": _label(conn, target_b),
        "total_a": analyze.total_dockets(conn, target_a),
        "total_b": analyze.total_dockets(conn, target_b),
        "cites_a": cites_a,
        "cites_b": cites_b,
        "shared_authorities": _shared_authorities(cites_a, cites_b),
        "judges_a": judges_a[:10],
        "judges_b": judges_b[:10],
        "shared_judges": _shared_judges(judges_a, judges_b),
        "motions_a": analyze.motion_stats(conn, target_a),
        "motions_b": analyze.motion_stats(conn, target_b),
        "disp_a": analyze.disposition_breakdown(conn, target_a),
        "disp_b": analyze.disposition_breakdown(conn, target_b),
        "boilerplate_overlap": cross_corpus_passages(docs_a, docs_b),
    }


COMPARE_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Counsel Comparison :: {{ label_a }} vs {{ label_b }}</title>
<style>
:root { color-scheme: light; --bg:#fff; --surface:#f7f7f5; --border:#d9d9d4; --text:#1a1a1a; --muted:#5c5c5c;
  --a:#7a1f4f; --b:#1f5c7a; --flag-bg:#fdecec; --flag-border:#e3a9a9; --warn-bg:#fff8e7; --warn-border:#e6d58a; }
* { box-sizing:border-box; }
body { margin:0; font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; background:var(--bg); color:var(--text); line-height:1.5; }
.container { max-width:1100px; margin:0 auto; padding:40px 24px 80px; }
h1 { font-size:25px; margin:0 0 4px; font-weight:700; }
h2 { font-size:18px; margin:34px 0 10px; padding-bottom:6px; border-bottom:1px solid var(--border); }
.subtitle { color:var(--muted); font-size:14px; margin:0 0 6px; }
.subtitle .na { color:var(--a); font-weight:600; } .subtitle .nb { color:var(--b); font-weight:600; }
.meta { color:var(--muted); font-size:13px; margin-bottom:8px; }
.two { display:grid; grid-template-columns:1fr 1fr; gap:22px; }
@media (max-width:800px){ .two{ grid-template-columns:1fr; } }
.colhead { font-size:12px; text-transform:uppercase; letter-spacing:.05em; font-weight:700; margin:0 0 6px; }
.colhead.a { color:var(--a); } .colhead.b { color:var(--b); }
table { width:100%; border-collapse:collapse; font-size:13.5px; }
th,td { text-align:left; padding:7px 9px; border-bottom:1px solid var(--border); vertical-align:top; }
th { background:var(--surface); font-size:11px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); }
td.num,th.num { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
code { font-family:ui-monospace,Menlo,monospace; font-size:12px; background:var(--surface); padding:1px 5px; border-radius:3px; }
.empty { color:var(--muted); font-style:italic; padding:10px 0; }
.passage { background:var(--flag-bg); border:1px solid var(--flag-border); border-radius:5px; padding:10px 12px; margin:8px 0; }
.passage .pmeta { font-size:12px; color:var(--muted); margin-bottom:5px; }
.passage .ptext { font-family:ui-monospace,Menlo,monospace; font-size:12px; white-space:pre-wrap; background:var(--bg); border:1px solid var(--border); border-radius:4px; padding:7px 9px; }
.cards { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin:14px 0 8px; }
.card { background:var(--surface); border:1px solid var(--border); border-radius:6px; padding:12px 14px; }
.card.a { border-left:3px solid var(--a); } .card.b { border-left:3px solid var(--b); }
.card .label { font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:.05em; }
.card .value { font-size:20px; font-weight:600; margin-top:3px; }
.footnote { margin-top:36px; padding-top:16px; border-top:1px solid var(--border); font-size:12px; color:var(--muted); }
.note { background:var(--warn-bg); border:1px solid var(--warn-border); border-radius:6px; padding:12px 14px; margin:18px 0; font-size:13px; }
</style></head><body><div class="container">

<h1>Counsel Comparison</h1>
<p class="subtitle"><span class="na">{{ label_a }}</span> vs <span class="nb">{{ label_b }}</span></p>
<div class="meta">Generated {{ generated_at }} from local CourtListener data</div>

<div class="cards">
  <div class="card a"><div class="label">{{ label_a }} federal dockets</div><div class="value">{{ total_a }}</div></div>
  <div class="card b"><div class="label">{{ label_b }} federal dockets</div><div class="value">{{ total_b }}</div></div>
</div>

<h2>Boilerplate overlap</h2>
<p class="meta">Verbatim passages found in the filings of BOTH attorneys. Strong overlap suggests a shared template, the same firm, or one drawing on the other.</p>
{% if boilerplate_overlap %}
{% for p in boilerplate_overlap[:10] %}
<div class="passage"><div class="pmeta">{{ p.word_count }} words, shared across both attorneys' filings</div><div class="ptext">{{ p.text }}</div></div>
{% endfor %}
{% else %}<div class="empty">No verbatim overlap found between the two attorneys' pulled filings.</div>{% endif %}

<h2>Shared authorities</h2>
<p class="meta">Cases both attorneys cite.</p>
{% if shared_authorities %}
<table><thead><tr><th>Authority</th><th>Citation</th><th class="num">{{ label_a }}</th><th class="num">{{ label_b }}</th></tr></thead><tbody>
{% for s in shared_authorities %}
<tr><td>{{ s.case_name or "(name not captured)" }}</td><td><code>{{ s.citation }}</code></td><td class="num">{{ s.a_docs }}</td><td class="num">{{ s.b_docs }}</td></tr>
{% endfor %}
</tbody></table>
{% else %}<div class="empty">No shared authorities.</div>{% endif %}

<h2>Most-cited authorities, side by side</h2>
<div class="two">
  <div><p class="colhead a">{{ label_a }}</p>
    {% if cites_a %}<table><tbody>{% for c in cites_a[:12] %}<tr><td>{{ c.case_name or c.citation }}</td><td class="num">{{ c.doc_count }}</td></tr>{% endfor %}</tbody></table>{% else %}<div class="empty">No citations.</div>{% endif %}
  </div>
  <div><p class="colhead b">{{ label_b }}</p>
    {% if cites_b %}<table><tbody>{% for c in cites_b[:12] %}<tr><td>{{ c.case_name or c.citation }}</td><td class="num">{{ c.doc_count }}</td></tr>{% endfor %}</tbody></table>{% else %}<div class="empty">No citations.</div>{% endif %}
  </div>
</div>

<h2>Motion practice</h2>
<div class="two">
  <div><p class="colhead a">{{ label_a }}</p>
    {% if motions_a %}<table><thead><tr><th>Motion</th><th class="num">Dec.</th><th class="num">Succ.</th></tr></thead><tbody>
    {% for m in motions_a %}<tr><td>{{ m.motion_type }}</td><td class="num">{{ m.decided }}</td><td class="num">{{ ("%.0f%%"|format(m.success_rate)) if m.success_rate is not none else "n/a" }}</td></tr>{% endfor %}
    </tbody></table>{% else %}<div class="empty">No motion data.</div>{% endif %}
  </div>
  <div><p class="colhead b">{{ label_b }}</p>
    {% if motions_b %}<table><thead><tr><th>Motion</th><th class="num">Dec.</th><th class="num">Succ.</th></tr></thead><tbody>
    {% for m in motions_b %}<tr><td>{{ m.motion_type }}</td><td class="num">{{ m.decided }}</td><td class="num">{{ ("%.0f%%"|format(m.success_rate)) if m.success_rate is not none else "n/a" }}</td></tr>{% endfor %}
    </tbody></table>{% else %}<div class="empty">No motion data.</div>{% endif %}
  </div>
</div>

<h2>Judges</h2>
{% if shared_judges %}
<p class="meta">Judges both attorneys have appeared before.</p>
<table><thead><tr><th>Judge</th><th class="num">{{ label_a }}</th><th class="num">{{ label_b }}</th></tr></thead><tbody>
{% for j in shared_judges %}<tr><td>{{ j.judge }}</td><td class="num">{{ j.a }}</td><td class="num">{{ j.b }}</td></tr>{% endfor %}
</tbody></table>
{% else %}<div class="empty">No shared judges in the pulled data.</div>{% endif %}

<h2>Disposition rates</h2>
<div class="two">
  <div><p class="colhead a">{{ label_a }}</p>
    {% if disp_a %}<table><tbody>{% for d in disp_a %}<tr><td>{{ d.idb_disposition }}</td><td class="num">{{ d.n }}</td></tr>{% endfor %}</tbody></table>{% else %}<div class="empty">No disposition data.</div>{% endif %}
  </div>
  <div><p class="colhead b">{{ label_b }}</p>
    {% if disp_b %}<table><tbody>{% for d in disp_b %}<tr><td>{{ d.idb_disposition }}</td><td class="num">{{ d.n }}</td></tr>{% endfor %}</tbody></table>{% else %}<div class="empty">No disposition data.</div>{% endif %}
  </div>
</div>

<div class="note"><strong>Read with care.</strong> Counts reflect only records in your local data set and are floors. Motion success rates describe how a motion type fared in each attorney's dockets, not a certified personal win rate. Boilerplate overlap is a fact about shared wording, not a legal conclusion.</div>

<div class="footnote">Source: CourtListener / RECAP Archive. Generated by Counsel Dossier. Designed by PinkViper Labs.</div>

</div></body></html>
"""


def generate_comparison_report(conn: sqlite3.Connection, target_a: str, target_b: str, out_path: Path) -> dict[str, Any]:
    data = build_comparison(conn, target_a, target_b)
    html = Template(COMPARE_TEMPLATE).render(generated_at=datetime.now(timezone.utc).isoformat(), **data)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return data
