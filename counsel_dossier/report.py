"""Standalone HTML dossier report generator."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Template

from . import analyze


REPORT_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Counsel Dossier :: {{ attorney }}</title>
<style>
:root {
  color-scheme: light;
  --bg: #ffffff; --surface: #f7f7f5; --surface-2: #ececea; --border: #d9d9d4;
  --text: #1a1a1a; --muted: #5c5c5c; --accent: #7a1f4f; --accent-soft: #f7e9f0;
  --flag-bg: #fdecec; --flag-border: #e3a9a9; --warn-bg: #fff8e7; --warn-border: #e6d58a;
}
* { box-sizing: border-box; }
body { margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  background: var(--bg); color: var(--text); line-height: 1.5; -webkit-font-smoothing: antialiased; }
.container { max-width: 1100px; margin: 0 auto; padding: 40px 24px 80px; }
h1 { font-size: 26px; margin: 0 0 4px; letter-spacing: -0.01em; font-weight: 700; }
h2 { font-size: 18px; margin: 36px 0 10px; padding-bottom: 6px; border-bottom: 1px solid var(--border); }
.subtitle { color: var(--muted); font-size: 14px; margin: 0 0 4px; }
.meta { color: var(--muted); font-size: 13px; margin-bottom: 8px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 16px 0 24px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 14px 16px; }
.card.flag { background: var(--flag-bg); border-color: var(--flag-border); }
.card .label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
.card .value { font-size: 22px; font-weight: 600; margin-top: 4px; font-variant-numeric: tabular-nums; }
.card .value.small { font-size: 14px; font-weight: 500; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border); vertical-align: top; }
th { background: var(--surface); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); }
tr:last-child td { border-bottom: none; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
td.bar-cell { width: 28%; }
.bar { background: var(--surface-2); height: 6px; border-radius: 3px; overflow: hidden; }
.bar > span { display: block; height: 100%; background: var(--accent); }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
@media (max-width: 800px) { .two-col { grid-template-columns: 1fr; } }
.empty { color: var(--muted); font-style: italic; padding: 12px 0; }
.passage { background: var(--surface); border: 1px solid var(--border); border-left: 3px solid var(--accent);
  border-radius: 5px; padding: 12px 14px; margin: 10px 0; }
.passage .pmeta { font-size: 12px; color: var(--muted); margin-bottom: 6px; }
.passage .ptext { font-family: ui-monospace, Menlo, monospace; font-size: 12.5px; white-space: pre-wrap;
  background: var(--bg); border: 1px solid var(--border); border-radius: 4px; padding: 8px 10px; }
.note { background: var(--warn-bg); border: 1px solid var(--warn-border); border-radius: 6px; padding: 12px 14px;
  margin: 20px 0; font-size: 13px; line-height: 1.55; }
.footnote { margin-top: 36px; padding-top: 16px; border-top: 1px solid var(--border); font-size: 12px; color: var(--muted); }
code { font-family: ui-monospace, Menlo, monospace; font-size: 12px; background: var(--surface); padding: 1px 5px; border-radius: 3px; }
</style>
</head>
<body>
<div class="container">

<h1>Counsel Dossier</h1>
<p class="subtitle">Federal Litigation Profile :: <strong>{{ attorney }}</strong></p>
<div class="meta">Target <code>{{ target_id }}</code> :: generated {{ generated_at }} from local CourtListener data</div>

<div class="cards">
  <div class="card"><div class="label">Federal dockets</div><div class="value">{{ "{:,}".format(total) }}</div></div>
  <div class="card"><div class="label">Date range</div><div class="value small">{{ date_min }} to {{ date_max }}</div></div>
  <div class="card"><div class="label">Courts</div><div class="value">{{ court_count }}</div></div>
  <div class="card {{ 'flag' if flag_count else '' }}"><div class="label">Flagged category hits</div><div class="value">{{ flag_count }}</div></div>
  <div class="card {{ 'flag' if passage_count else '' }}"><div class="label">Reused passages</div><div class="value">{{ passage_count }}</div></div>
</div>

<h2>Caseload by year</h2>
{% if yearly %}
<table><thead><tr><th>Year</th><th class="num">Dockets</th><th class="bar-cell"></th></tr></thead><tbody>
{% for row in yearly %}<tr><td>{{ row.year }}</td><td class="num">{{ row.n }}</td>
<td class="bar-cell"><div class="bar"><span style="width: {{ "%.1f"|format(row.n / max_yearly * 100) }}%"></span></div></td></tr>{% endfor %}
</tbody></table>
{% else %}<div class="empty">No dated dockets.</div>{% endif %}

<div class="two-col">
  <div>
    <h2>Courts</h2>
    {% if courts %}<table><thead><tr><th>Court</th><th class="num">Dockets</th></tr></thead><tbody>
    {% for row in courts %}<tr><td>{{ row.court or "(unknown)" }}</td><td class="num">{{ row.n }}</td></tr>{% endfor %}
    </tbody></table>{% else %}<div class="empty">No court data.</div>{% endif %}
  </div>
  <div>
    <h2>Judge exposure</h2>
    {% if judges %}<table><thead><tr><th>Assigned judge</th><th class="num">Dockets</th></tr></thead><tbody>
    {% for row in judges[:15] %}<tr><td>{{ row.assigned_judge }}</td><td class="num">{{ row.n }}</td></tr>{% endfor %}
    </tbody></table>{% else %}<div class="empty">No judge data.</div>{% endif %}
  </div>
</div>

<h2>Nature of suit</h2>
{% if suits %}<table><thead><tr><th>Nature of suit</th><th class="num">Dockets</th></tr></thead><tbody>
{% for row in suits[:20] %}<tr><td>{{ row.nature_of_suit }}</td><td class="num">{{ row.n }}</td></tr>{% endfor %}
</tbody></table>{% else %}<div class="empty">No nature-of-suit data.</div>{% endif %}

<div class="two-col">
  <div>
    <h2>Parties represented</h2>
    {% if parties %}<table><thead><tr><th>Party</th><th class="num">Dockets</th></tr></thead><tbody>
    {% for row in parties[:15] %}<tr><td>{{ row.party_name }}</td><td class="num">{{ row.n }}</td></tr>{% endfor %}
    </tbody></table>{% else %}<div class="empty">No party data (pull parties to populate).</div>{% endif %}
  </div>
  <div>
    <h2>Disposition</h2>
    {% if dispositions %}<table><thead><tr><th>Disposition</th><th class="num">Dockets</th></tr></thead><tbody>
    {% for row in dispositions %}<tr><td>{{ row.idb_disposition }}</td><td class="num">{{ row.n }}</td></tr>{% endfor %}
    </tbody></table>{% else %}<div class="empty">No disposition data.</div>{% endif %}
  </div>
</div>

<h2>Classification flags</h2>
<p class="meta">Counts of opinions or order text matching each taxonomy category (for example sanctions or Rule 11 language).</p>
{% if categories %}<table><thead><tr><th>Category</th><th class="num">Matched items</th></tr></thead><tbody>
{% for row in categories %}<tr><td>{{ row.category }}</td><td class="num">{{ row.n }}</td></tr>{% endfor %}
</tbody></table>{% else %}<div class="empty">No classifications. Run <code>classify</code> first.</div>{% endif %}

<h2>Motion outcomes</h2>
<p class="meta">Motion types seen in this attorney's dockets, with dispositions read from order text. Success rate counts a grant as a win and a split as half. It reflects how the motion type fared in these cases and is a lead to verify, not a certified personal win rate.</p>
{% if motions %}
<table><thead><tr><th>Motion type</th><th class="num">Filed</th><th class="num">Granted</th><th class="num">Denied</th><th class="num">Part</th><th class="num">Success</th></tr></thead><tbody>
{% for m in motions %}
<tr>
  <td>{{ m.motion_type }}</td>
  <td class="num">{{ m.filed_count }}</td>
  <td class="num">{{ m.granted }}</td>
  <td class="num">{{ m.denied }}</td>
  <td class="num">{{ m.partial }}</td>
  <td class="num">{{ ("%.0f%%"|format(m.success_rate)) if m.success_rate is not none else "n/a" }}</td>
</tr>
{% endfor %}
</tbody></table>
{% else %}<div class="empty">No motion data. Run <code>pull --with-docs</code> then <code>analytics</code>.</div>{% endif %}

<h2>Frequently cited cases</h2>
<p class="meta">Authorities this attorney cites most, ranked by how many distinct filings cite them. This is the spine of what they argue.</p>
{% if cites %}
<table><thead><tr><th>Authority</th><th>Citation</th><th class="num">Filings</th><th class="num">Total</th></tr></thead><tbody>
{% for c in cites %}
<tr>
  <td>{{ c.case_name or "(name not captured)" }}</td>
  <td><code>{{ c.citation }}</code></td>
  <td class="num">{{ c.doc_count }}</td>
  <td class="num">{{ c.total_count }}</td>
</tr>
{% endfor %}
</tbody></table>
{% else %}<div class="empty">No citations extracted. Run <code>analytics</code>.</div>{% endif %}

<h2>Most cited authority by motion type</h2>
<p class="meta">What this attorney leans on when making each kind of motion.</p>
{% if cites_by_motion %}
{% for motion_type, rows in cites_by_motion.items() %}
<h3 style="font-size:13px;margin:18px 0 6px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;">{{ motion_type }}</h3>
<table><thead><tr><th>Authority</th><th>Citation</th><th class="num">Filings</th></tr></thead><tbody>
{% for c in rows %}<tr><td>{{ c.case_name or "(name not captured)" }}</td><td><code>{{ c.citation }}</code></td><td class="num">{{ c.doc_count }}</td></tr>{% endfor %}
</tbody></table>
{% endfor %}
{% else %}<div class="empty">No motion-bucketed citations. Run <code>analytics</code>.</div>{% endif %}

<h2>Recurring phrases</h2>
<p class="meta">Multi-word phrases reused across this attorney's filings. The short-grain companion to the reused-passage detector below: their habitual phrasing and stock arguments.</p>
{% if phrases %}
<table><thead><tr><th>Phrase</th><th class="num">Filings</th><th class="num">Total</th></tr></thead><tbody>
{% for p in phrases %}
<tr><td>{{ p.phrase }}</td><td class="num">{{ p.doc_count }}</td><td class="num">{{ p.total_count }}</td></tr>
{% endfor %}
</tbody></table>
{% else %}<div class="empty">No recurring phrases. Run <code>analytics</code>.</div>{% endif %}

<h2>Reused language (boilerplate)</h2>
<p class="meta">Verbatim passages found in more than one of this attorney's filings, longest and most-repeated first.</p>
{% if passages %}
{% for p in passages %}
<div class="passage">
  <div class="pmeta">Appears in {{ p.doc_count }} documents :: {{ p.word_count }} words :: document ids {{ p.doc_ids }}</div>
  <div class="ptext">{{ p.passage_text }}</div>
</div>
{% endfor %}
{% else %}<div class="empty">No reused passages found. Fetch document text and run <code>fingerprint</code> first.</div>{% endif %}

<div class="note">
<strong>Evidentiary framing.</strong>
This dossier aggregates public federal court records. Caseload, court, and
disposition figures come from docket metadata and the Federal Judicial Center
Integrated Database. Classification flags reflect language found in opinion or
order text and are pointers for review, not adjudicated findings. Reused-passage
detection shows verbatim overlap between an attorney's own filings; it is a fact
about their drafting, not a legal conclusion. Coverage is federal only and is
limited to records present in the local data set, so any count is a floor.
</div>

<div class="footnote">
Source: CourtListener / RECAP Archive, public API
<code>courtlistener.com/api/rest/v4/</code>.
Generated by Counsel Dossier. Designed by PinkViper Labs.
</div>

</div>
</body>
</html>
"""


def generate_report(conn: sqlite3.Connection, target_id: str, attorney: str, out_path: Path) -> None:
    total = analyze.total_dockets(conn, target_id)
    yearly = analyze.yearly_caseload(conn, target_id)
    courts = analyze.court_breakdown(conn, target_id)
    suits = analyze.nature_of_suit_breakdown(conn, target_id)
    judges = analyze.judge_exposure(conn, target_id)
    dispositions = analyze.disposition_breakdown(conn, target_id)
    parties = analyze.party_side_breakdown(conn, target_id)
    categories = analyze.category_counts(conn, target_id)
    passages = analyze.top_passages(conn, target_id, limit=25)
    motions = analyze.motion_stats(conn, target_id)
    cites = analyze.top_citations(conn, target_id, limit=25)
    cites_by_motion = analyze.citations_by_motion(conn, target_id, per_type=6)
    phrases = analyze.top_phrases_stored(conn, target_id, limit=25)

    date_row = conn.execute(
        "SELECT MIN(date_filed) AS dmin, MAX(date_filed) AS dmax FROM dockets WHERE target_id = ?",
        (target_id,),
    ).fetchone()

    max_yearly = max((r["n"] for r in yearly), default=1) or 1
    flag_count = sum(r["n"] for r in categories)

    html = Template(REPORT_TEMPLATE).render(
        attorney=attorney,
        target_id=target_id,
        generated_at=datetime.now(timezone.utc).isoformat(),
        total=total,
        date_min=(date_row["dmin"] or "")[:10] if date_row and date_row["dmin"] else "(none)",
        date_max=(date_row["dmax"] or "")[:10] if date_row and date_row["dmax"] else "(none)",
        court_count=len(courts),
        flag_count=flag_count,
        passage_count=len(passages),
        yearly=yearly,
        max_yearly=max_yearly,
        courts=courts,
        suits=suits,
        judges=judges,
        dispositions=dispositions,
        parties=parties,
        categories=categories,
        passages=passages,
        motions=motions,
        cites=cites,
        cites_by_motion=cites_by_motion,
        phrases=phrases,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
