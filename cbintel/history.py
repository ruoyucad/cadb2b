"""Durable history that survives rebuilds.

The analytical database is rebuilt from scratch on every run, which is fine for
contracts and award notices (the government publishes complete files). Tenders
are different: the open-tenders file only lists what is open *today*, so a
tender vanishes once it closes. We keep every tender ever seen, plus a log of
each pipeline run, in a separate file so deleting or rebuilding
data/cbintel.duckdb never loses them.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import duckdb

HIST_PATH = Path("data/history.duckdb")

SCHEMA = """
CREATE TABLE IF NOT EXISTS hist.tender_history (
  tender_id VARCHAR PRIMARY KEY,
  title VARCHAR, buyer VARCHAR, published DATE, closing TIMESTAMP, status VARCHAR,
  procurement_category VARCHAR, is_goods BOOLEAN,
  unspsc VARCHAR, unspsc_description VARCHAR, segment VARCHAR,
  regions_of_delivery VARCHAR, notice_url VARCHAR,
  first_seen_at TIMESTAMP, last_seen_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS hist.supplier_contact (   -- filled by `cbintel enrich`
  supplier_key VARCHAR PRIMARY KEY, display_name VARCHAR,
  website VARCHAR, emails VARCHAR, phones VARCHAR, contact_page VARCHAR,
  match_score INTEGER, match_reason VARCHAR, method VARCHAR, checked_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS hist.run_log (
  started_at TIMESTAMP, finished_at TIMESTAMP, command VARCHAR, status VARCHAR,
  downloads VARCHAR,          -- JSON: file name -> ok / skip / fail
  stats VARCHAR,              -- JSON: row counts after the run
  error VARCHAR
);
"""


def attach(con: duckdb.DuckDBPyConnection, path: Path = HIST_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if "hist" not in {r[0] for r in con.execute("SELECT database_name FROM duckdb_databases()").fetchall()}:
        con.execute(f"ATTACH '{path}' AS hist")
    con.execute(SCHEMA)


def record_tenders(con: duckdb.DuckDBPyConnection, now: datetime | None = None) -> dict[str, int]:
    """Upsert today's tender notices into hist.tender_history (needs stg_tenders_latest)."""
    now = now or datetime.now()
    attach(con)
    before = con.execute("SELECT count(*) FROM hist.tender_history").fetchone()[0]
    con.execute("""
        INSERT INTO hist.tender_history
        SELECT
          coalesce(nullif(solicitation_number, ''), nullif(reference_number, '')) AS tender_id,
          any_value(title), any_value(first_line(contracting_entity_name)),
          any_value(dt(publication_date)),
          any_value(try_cast(replace(left(tender_closing_date, 19), 'T', ' ') AS TIMESTAMP)),
          any_value(tender_status), any_value(procurement_category),
          any_value(regexp_matches(upper(coalesce(procurement_category, '')), '(^|[^A-Z])GD($|[^A-Z])')
                    OR coalesce(gsin, '') LIKE 'N%'),
          any_value(nullif(regexp_extract(coalesce(unspsc, ''), '[0-9]{8}'), '')),
          any_value(first_line(unspsc_description)),
          any_value(nullif(left(regexp_extract(coalesce(unspsc, ''), '[0-9]{8}'), 2), '')),
          any_value(regions_of_delivery), any_value(notice_url),
          ?::TIMESTAMP, ?::TIMESTAMP
        FROM stg_tenders_latest
        WHERE coalesce(nullif(solicitation_number, ''), nullif(reference_number, '')) IS NOT NULL
        GROUP BY 1
        ON CONFLICT (tender_id) DO UPDATE SET
          title = EXCLUDED.title, buyer = EXCLUDED.buyer, published = EXCLUDED.published,
          closing = EXCLUDED.closing, status = EXCLUDED.status,
          procurement_category = EXCLUDED.procurement_category, is_goods = EXCLUDED.is_goods,
          unspsc = EXCLUDED.unspsc, unspsc_description = EXCLUDED.unspsc_description,
          segment = EXCLUDED.segment, regions_of_delivery = EXCLUDED.regions_of_delivery,
          notice_url = EXCLUDED.notice_url, last_seen_at = EXCLUDED.last_seen_at
    """, [now, now])
    after = con.execute("SELECT count(*) FROM hist.tender_history").fetchone()[0]
    return {"tender_history": after, "new_tenders": after - before}


def log_run(started_at: datetime, command: str, status: str, downloads: dict | None = None,
            stats: dict | None = None, error: str | None = None, path: Path = HIST_PATH) -> None:
    con = duckdb.connect()
    attach(con, path)
    con.execute("INSERT INTO hist.run_log VALUES (?, ?, ?, ?, ?, ?, ?)",
                [started_at, datetime.now(), command, status,
                 json.dumps(downloads or {}), json.dumps(stats or {}), error])
    con.close()


def show_history(limit: int = 10, path: Path = HIST_PATH) -> None:
    if not path.exists():
        print("no runs recorded yet")
        return
    con = duckdb.connect()
    con.execute(f"ATTACH '{path}' AS hist (READ_ONLY)")
    for started, finished, cmd, status, downloads, stats in con.execute(
            "SELECT started_at, finished_at, command, status, downloads, stats FROM hist.run_log "
            "ORDER BY started_at DESC LIMIT ?", [limit]).fetchall():
        s = json.loads(stats or "{}")
        changed = [k for k, v in json.loads(downloads or "{}").items() if v != "skip"]
        mins = (finished - started).total_seconds() / 60
        print(f"{started:%Y-%m-%d %H:%M}  {cmd:<5} {status:<7} {mins:4.1f} min  "
              f"new tenders: {s.get('new_tenders', '-')}  downloaded: {', '.join(changed) or '-'}")
    (n, goods, open_now), = con.execute(
        "SELECT count(*), count(*) FILTER (WHERE is_goods), "
        "count(*) FILTER (WHERE closing IS NULL OR closing >= current_date) FROM hist.tender_history").fetchall()
    print(f"\ntender_history: {n:,} tenders kept ({goods:,} goods, {open_now:,} still open)")
    con.close()
