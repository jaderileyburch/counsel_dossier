"""Command line interface for Counsel Dossier.

Federal attorney litigation profiles built from public CourtListener data.
Bring your own token: set COURTLISTENER_TOKEN. Designed by PinkViper Labs.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import click
import yaml

from counsel_dossier import analyze as analyze_mod
from counsel_dossier import analytics as analytics_mod
from counsel_dossier import classify as classify_mod
from counsel_dossier import db as db_mod
from counsel_dossier import fingerprint as fp_mod
from counsel_dossier import pull as pull_mod
from counsel_dossier import report as report_mod


DEFAULT_DB = "data/dossier.db"
DEFAULT_TARGETS_DIR = "config/targets"
DEFAULT_ALIASES = "config/aliases.yaml"
DEFAULT_EXPORT_DIR = "exports"


def load_target(target_id: str, targets_dir: str) -> dict:
    path = Path(targets_dir) / f"{target_id}.yaml"
    if not path.exists():
        raise click.ClickException(f"Target config not found: {path}")
    with path.open() as f:
        return yaml.safe_load(f)


def attorney_names(target: dict) -> list[str]:
    atty = target.get("attorney") or {}
    names = atty.get("names") or []
    if isinstance(names, str):
        names = [names]
    return [str(n) for n in names if n]


def attorney_label(target: dict, target_id: str) -> str:
    names = attorney_names(target)
    return names[0] if names else target.get("name", target_id)


@click.group()
@click.option("--db", default=DEFAULT_DB, show_default=True, help="SQLite database path.")
@click.option("--targets-dir", default=DEFAULT_TARGETS_DIR, show_default=True, help="Directory of target YAML configs.")
@click.option("--aliases", default=DEFAULT_ALIASES, show_default=True, help="Attorney alias map (YAML).")
@click.pass_context
def cli(ctx: click.Context, db: str, targets_dir: str, aliases: str) -> None:
    """Counsel Dossier: federal litigation profiles from public court records.

    Designed by PinkViper Labs.
    """
    ctx.ensure_object(dict)
    ctx.obj["db"] = db
    ctx.obj["targets_dir"] = targets_dir
    ctx.obj["aliases"] = aliases


@cli.command()
@click.pass_context
def init(ctx: click.Context) -> None:
    """Initialize or upgrade the SQLite schema."""
    db_mod.init_db(ctx.obj["db"])
    click.echo(f"Database initialized: {ctx.obj['db']}")


@cli.command()
@click.pass_context
def targets(ctx: click.Context) -> None:
    """List available target configurations."""
    d = Path(ctx.obj["targets_dir"])
    if not d.exists():
        click.echo(f"No targets directory at {d}")
        return
    files = sorted(p for p in d.glob("*.yaml") if not p.stem.startswith("_"))
    if not files:
        click.echo("No target configurations found.")
        return
    for path in files:
        try:
            cfg = yaml.safe_load(path.read_text()) or {}
            click.echo(f"  {path.stem:<24} {cfg.get('name', '(unnamed)')}")
        except Exception as e:
            click.echo(f"  {path.stem:<24} ERROR: {e}")


@cli.command()
@click.argument("target_id")
@click.option("--with-parties/--no-parties", default=True, help="Also pull parties and attorneys per docket.")
@click.option("--with-docs", is_flag=True, default=False,
              help="Also pull RECAP document text already in the archive (free). Needed for fingerprinting.")
@click.option("--enrich/--no-enrich", default=True, help="Fetch full docket objects for IDB fields (slower).")
@click.option("--max-pages", default=None, type=int, help="Cap search pages (for testing).")
@click.pass_context
def pull(ctx, target_id, with_parties, with_docs, enrich, max_pages):
    """Pull federal dockets for a target attorney from CourtListener.

    Requires COURTLISTENER_TOKEN. Federal courts only.
    """
    target = load_target(target_id, ctx.obj["targets_dir"])
    filters = dict(target.get("filters", {}) or {})
    aliases = pull_mod.load_aliases(ctx.obj["aliases"])
    names = attorney_names(target)
    if not names:
        raise click.ClickException(f"Target '{target_id}' has no attorney.names defined.")

    try:
        token = pull_mod.get_token()
    except pull_mod.AuthError as e:
        raise click.ClickException(str(e))

    db_mod.init_db(ctx.obj["db"])
    conn = db_mod.open_db(ctx.obj["db"])
    db_mod.clear_attorneys_for_target(conn, target_id)

    started = datetime.now(timezone.utc).isoformat()
    seen: set[int] = set()
    dockets_new = 0
    note = "ok"

    try:
        for name in names:
            click.echo(f"Searching dockets for attorney: {name}")
            for row in pull_mod.iter_search_dockets(name, filters, token, max_pages):
                did = row.get("docket_id") or row.get("id")
                if not did or did in seen:
                    continue
                seen.add(did)

                if enrich:
                    try:
                        full = pull_mod.fetch_docket(did, token)
                        rec = pull_mod.to_docket_record(full, target_id)
                    except Exception:
                        rec = pull_mod.to_search_docket_record(row, target_id)
                else:
                    rec = pull_mod.to_search_docket_record(row, target_id)

                if db_mod.upsert_docket(conn, rec):
                    dockets_new += 1

                if with_parties:
                    try:
                        parties = pull_mod.fetch_parties(did, token)
                        for arec in pull_mod.extract_attorneys_from_parties(parties, did, target_id, aliases):
                            db_mod.insert_attorney(conn, arec)
                    except Exception as e:
                        click.echo(f"  parties fetch failed for docket {did}: {e}", err=True)

                if with_docs:
                    try:
                        for draw in pull_mod.fetch_recap_documents(did, token):
                            db_mod.upsert_document(conn, pull_mod.to_document_record(draw, did, target_id))
                    except Exception as e:
                        click.echo(f"  documents fetch failed for docket {did}: {e}", err=True)

                conn.commit()
            click.echo(f"  dockets so far: {len(seen)}")
    except pull_mod.AuthError as e:
        note = f"auth error: {e}"
        click.echo(note, err=True)
    except Exception as e:
        note = f"error: {e}"
        click.echo(f"Pull aborted: {e}", err=True)

    completed = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO pull_log (target_id, phase, started_at, completed_at, records_fetched, records_new, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (target_id, "pull", started, completed, len(seen), dockets_new, note),
    )
    conn.execute(
        "INSERT OR REPLACE INTO targets (target_id, name, config_json, created_at, updated_at) "
        "VALUES (?, ?, ?, COALESCE((SELECT created_at FROM targets WHERE target_id = ?), ?), ?)",
        (target_id, target.get("name", target_id), json.dumps(target), target_id, started, completed),
    )
    conn.commit()
    conn.close()
    click.echo(f"Done. {len(seen)} dockets ({dockets_new} new). {note}")


@cli.command()
@click.argument("target_id")
@click.option("--item-type", type=click.Choice(["document", "opinion"]), default="document", show_default=True)
@click.pass_context
def classify(ctx, target_id, item_type):
    """Run the target's taxonomy across pulled text (order/opinion text)."""
    target = load_target(target_id, ctx.obj["targets_dir"])
    taxonomy = target.get("taxonomy") or {}
    if not taxonomy:
        raise click.ClickException(f"Target '{target_id}' has no taxonomy defined.")
    conn = db_mod.open_db(ctx.obj["db"])
    counts = classify_mod.classify_target(conn, target_id, taxonomy, item_type)
    conn.close()
    click.echo(f"Classification ({item_type}) for '{target_id}':")
    for cat, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        click.echo(f"  {cat:<28} {n}")


@cli.command()
@click.argument("target_id")
@click.option("--k", default=None, type=int, help="Shingle size (default from target config or 5).")
@click.option("--threshold", default=None, type=float, help="Jaccard similarity threshold (default 0.4).")
@click.option("--min-words", default=None, type=int, help="Minimum shared passage length in words (default 25).")
@click.pass_context
def fingerprint(ctx, target_id, k, threshold, min_words):
    """Detect reused/boilerplate language across the target's pulled documents.

    Operates on document text already pulled with `pull --with-docs`.
    """
    target = load_target(target_id, ctx.obj["targets_dir"])
    fcfg = target.get("fingerprint") or {}
    k = k or int(fcfg.get("shingle_size", 5))
    threshold = threshold if threshold is not None else float(fcfg.get("similarity_threshold", 0.4))
    min_words = min_words or int(fcfg.get("min_passage_words", 25))

    conn = db_mod.open_db(ctx.obj["db"])
    docs = analyze_mod.documents_with_text(conn, target_id)
    if len(docs) < 2:
        click.echo(f"Need at least 2 documents with text; found {len(docs)}. Run `pull --with-docs` first.")
        conn.close()
        return

    result = fp_mod.find_boilerplate(docs, k=k, similarity_threshold=threshold, min_passage_words=min_words)
    conn.execute("DELETE FROM shared_passages WHERE target_id = ?", (target_id,))
    now = datetime.now(timezone.utc).isoformat()
    for p in result["passages"]:
        conn.execute(
            "INSERT INTO shared_passages (target_id, passage_hash, passage_text, word_count, doc_count, doc_ids_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (target_id, p["hash"], p["text"], p["word_count"], p["doc_count"], json.dumps(p["doc_ids"]), now),
        )
    conn.commit()
    conn.close()

    pairs = result["similar_pairs"]
    passages = result["passages"]
    click.echo(f"Analyzed {len(docs)} documents.")
    click.echo(f"Near-duplicate document pairs (Jaccard >= {threshold}): {len(pairs)}")
    click.echo(f"Distinct reused passages (>= {min_words} words, in 2+ docs): {len(passages)}")
    for p in passages[:5]:
        preview = " ".join(p["text"].split()[:14])
        click.echo(f"  in {p['doc_count']} docs, {p['word_count']} words: \"{preview} ...\"")


@cli.command()
@click.argument("target_id")
@click.option("--phrase-n", default=6, show_default=True, help="Phrase length in words for recurring-phrase analysis.")
@click.option("--phrase-min-docs", default=2, show_default=True, help="Minimum distinct filings a phrase must appear in.")
@click.pass_context
def analytics(ctx, target_id, phrase_n, phrase_min_docs):
    """Compute motion outcomes, cited-case frequency, and recurring phrases.

    Pure pattern matching over pulled document text. No models. Operates on
    documents pulled with `pull --with-docs`.
    """
    conn = db_mod.open_db(ctx.obj["db"])
    items = analyze_mod.documents_for_analytics(conn, target_id)
    if not items:
        click.echo("No document text found. Run `pull --with-docs` first.")
        conn.close()
        return
    docs_text = {it["id"]: it["text"] for it in items}
    now = datetime.now(timezone.utc).isoformat()

    # Motion outcomes
    motions = analytics_mod.analyze_motions(items)
    conn.execute("DELETE FROM motion_stats WHERE target_id = ?", (target_id,))
    for m in motions:
        conn.execute(
            "INSERT OR REPLACE INTO motion_stats "
            "(target_id, motion_type, filed_count, granted, denied, partial, decided, success_rate, computed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (target_id, m["motion_type"], m["filed_count"], m["granted"], m["denied"],
             m["partial"], m["decided"], m["success_rate"], now),
        )

    # Cited cases
    cites = analytics_mod.analyze_citations(docs_text)
    conn.execute("DELETE FROM citations WHERE target_id = ?", (target_id,))
    for c in cites:
        conn.execute(
            "INSERT OR REPLACE INTO citations "
            "(target_id, citation, case_name, total_count, doc_count, doc_ids_json, computed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (target_id, c["citation"], c["case_name"], c["total_count"], c["doc_count"],
             json.dumps(c["doc_ids"]), now),
        )

    # Recurring phrases
    phrases = analytics_mod.analyze_phrases(docs_text, n=phrase_n, min_doc_count=phrase_min_docs)
    conn.execute("DELETE FROM phrases WHERE target_id = ?", (target_id,))
    for p in phrases:
        conn.execute(
            "INSERT INTO phrases (target_id, phrase, n, doc_count, total_count, computed_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (target_id, p["phrase"], p["n"], p["doc_count"], p["total_count"], now),
        )

    # Cited authority by motion type
    cbm = analytics_mod.analyze_citations_by_motion(items)
    conn.execute("DELETE FROM citations_by_motion WHERE target_id = ?", (target_id,))
    for motion_type, rows in cbm.items():
        for c in rows:
            conn.execute(
                "INSERT INTO citations_by_motion "
                "(target_id, motion_type, citation, case_name, total_count, doc_count, computed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (target_id, motion_type, c["citation"], c["case_name"], c["total_count"], c["doc_count"], now),
            )

    conn.commit()
    conn.close()

    click.echo(f"Analytics for '{target_id}' over {len(items)} documents:")
    click.echo(f"\nMotion outcomes ({len([m for m in motions if m['decided']])} types with dispositions):")
    for m in motions:
        rate = f"{m['success_rate']}%" if m["success_rate"] is not None else "n/a"
        click.echo(f"  {m['motion_type']:<38} filed={m['filed_count']:<3} "
                   f"G/D/P={m['granted']}/{m['denied']}/{m['partial']:<3} success={rate}")
    click.echo(f"\nTop cited cases:")
    for c in cites[:8]:
        label = c["case_name"] or c["citation"]
        click.echo(f"  in {c['doc_count']} filings: {label} ({c['citation']})")
    click.echo(f"\nTop recurring phrases ({phrase_n}-grams):")
    for p in phrases[:8]:
        click.echo(f"  in {p['doc_count']} filings: \"{p['phrase']}\"")
    click.echo(f"\nMost cited authority by motion type:")
    for mt, rows in cbm.items():
        top = rows[0] if rows else None
        if top:
            label = top["case_name"] or top["citation"]
            click.echo(f"  {mt:<34} {label} ({top['citation']}) in {top['doc_count']}")


@cli.command()
@click.argument("target_a")
@click.argument("target_b")
@click.option("--out", default=None, help="Output HTML path (default: exports/compare_<a>_<b>.html).")
@click.pass_context
def compare(ctx, target_a, target_b, out):
    """Compare two already-pulled attorneys head to head.

    Both targets must already be pulled and analyzed. Produces a side-by-side
    HTML report: shared authorities, judges, motion practice, disposition rates,
    and verbatim boilerplate overlap between the two.
    """
    from counsel_dossier import compare as compare_mod
    conn = db_mod.open_db(ctx.obj["db"])
    if db_mod.count(conn, "dockets", target_a) == 0 and db_mod.count(conn, "documents", target_a) == 0:
        conn.close()
        raise click.ClickException(f"No data for '{target_a}'. Pull it first.")
    if db_mod.count(conn, "dockets", target_b) == 0 and db_mod.count(conn, "documents", target_b) == 0:
        conn.close()
        raise click.ClickException(f"No data for '{target_b}'. Pull it first.")
    out_path = Path(out) if out else Path(DEFAULT_EXPORT_DIR) / f"compare_{target_a}_{target_b}.html"
    data = compare_mod.generate_comparison_report(conn, target_a, target_b, out_path)
    conn.close()
    click.echo(f"Comparison: {data['label_a']} ({data['total_a']} dockets) vs {data['label_b']} ({data['total_b']} dockets)")
    click.echo(f"  shared authorities: {len(data['shared_authorities'])}")
    click.echo(f"  shared judges:      {len(data['shared_judges'])}")
    click.echo(f"  boilerplate passages shared by both: {len(data['boilerplate_overlap'])}")
    click.echo(f"Wrote: {out_path}")


@cli.command()
@click.argument("target_id")
@click.pass_context
def profile(ctx, target_id):
    """Print the dossier summary to the terminal."""
    target = load_target(target_id, ctx.obj["targets_dir"])
    label = attorney_label(target, target_id)
    conn = db_mod.open_db(ctx.obj["db"])

    total = analyze_mod.total_dockets(conn, target_id)
    click.echo(f"\nDossier: {label}  (target {target_id})")
    click.echo(f"Federal dockets: {total}\n")

    click.echo("Caseload by year:")
    for r in analyze_mod.yearly_caseload(conn, target_id):
        click.echo(f"  {r['year']:<6} {r['n']:>5}")

    click.echo("\nTop courts:")
    for r in analyze_mod.court_breakdown(conn, target_id)[:10]:
        click.echo(f"  {r['n']:>5}  {r['court'] or '(unknown)'}")

    click.echo("\nClassification flags:")
    cats = analyze_mod.category_counts(conn, target_id)
    if cats:
        for r in cats:
            click.echo(f"  {r['category']:<28} {r['n']:>5}")
    else:
        click.echo("  (none; run classify)")

    passages = analyze_mod.top_passages(conn, target_id, limit=5)
    click.echo("\nReused passages (top):")
    if passages:
        for p in passages:
            preview = " ".join(p["passage_text"].split()[:12])
            click.echo(f"  in {p['doc_count']} docs, {p['word_count']}w: \"{preview} ...\"")
    else:
        click.echo("  (none; run pull --with-docs then fingerprint)")
    conn.close()


@cli.command()
@click.argument("target_id")
@click.option("--out", default=None, help="Output HTML path (default: exports/<target_id>/dossier.html).")
@click.pass_context
def report(ctx, target_id, out):
    """Generate a standalone HTML dossier."""
    target = load_target(target_id, ctx.obj["targets_dir"])
    label = attorney_label(target, target_id)
    conn = db_mod.open_db(ctx.obj["db"])
    out_path = Path(out) if out else Path(DEFAULT_EXPORT_DIR) / target_id / "dossier.html"
    report_mod.generate_report(conn, target_id, label, out_path)
    conn.close()
    click.echo(f"Wrote: {out_path}")


@cli.command()
@click.pass_context
def renormalize(ctx):
    """Recompute attorney name_normalized for stored rows using the current alias map."""
    aliases = pull_mod.load_aliases(ctx.obj["aliases"])
    conn = db_mod.open_db(ctx.obj["db"])
    rows = conn.execute("SELECT id, name FROM attorneys").fetchall()
    for r in rows:
        conn.execute(
            "UPDATE attorneys SET name_normalized = ? WHERE id = ?",
            (pull_mod.normalize_attorney(r["name"], aliases), r["id"]),
        )
    conn.commit()
    n = conn.execute("SELECT COUNT(DISTINCT name_normalized) AS n FROM attorneys").fetchone()["n"]
    conn.close()
    click.echo(f"Renormalized {len(rows)} attorney rows into {n} distinct canonical names.")


@cli.command()
@click.pass_context
def status(ctx):
    """Show row counts and recent pulls."""
    conn = db_mod.open_db(ctx.obj["db"])
    for t in ("dockets", "attorneys", "opinions", "documents", "shared_passages"):
        click.echo(f"{t:<16} {db_mod.count(conn, t)}")
    rows = conn.execute(
        "SELECT target_id, started_at, records_fetched, records_new, notes FROM pull_log ORDER BY pull_id DESC LIMIT 5"
    ).fetchall()
    if rows:
        click.echo("\nRecent pulls:")
        for r in rows:
            click.echo(f"  {r['started_at']}  {r['target_id']:<18} fetched={r['records_fetched']} new={r['records_new']} note={r['notes']}")
    conn.close()


if __name__ == "__main__":
    cli(obj={})
