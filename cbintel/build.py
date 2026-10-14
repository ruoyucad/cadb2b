"""Load raw CSVs into DuckDB, normalize columns, run the SQL models.

Output:
  data/cbintel.duckdb          the analytical database
  data/parquet/<table>.parquet one Parquet file per staging/mart table
"""
from __future__ import annotations

import re
from pathlib import Path

import duckdb

from .history import attach, record_tenders
from .sources import SOURCES

RAW = Path("data/raw")
DB_PATH = Path("data/cbintel.duckdb")
PARQUET = Path("data/parquet")
SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def snake(col: str) -> str | None:
    """'supplierLegalName-nomLegalFournisseur-eng' -> 'supplier_legal_name'.

    French duplicate columns ('...-fra') are dropped; everything we need has an
    English twin. Unilingual columns ('unspsc', 'contractAmount-montantContrat')
    keep their first (English) segment.
    """
    c = col.strip().lstrip("﻿")
    if c.endswith("-fra"):
        return None
    head = c.split("-")[0]
    # camelCase -> snake_case, keeping acronyms together (noticeURL -> notice_url)
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", head).lower()
    return re.sub(r"[^a-z0-9_]", "_", s)


def _read_csv(con: duckdb.DuckDBPyConnection, path: Path, table: str) -> None:
    for enc in ("utf-8", "latin-1"):
        try:
            con.execute(
                f"""CREATE OR REPLACE TEMP TABLE {table} AS
                SELECT * FROM read_csv(?, all_varchar=true, header=true,
                    encoding='{enc}', max_line_size=10000000,
                    strict_mode=false)""",
                [str(path)],
            )
            return
        except duckdb.Error as e:
            last = e
    raise last


def load_staging(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    groups: dict[str, list[str]] = {}
    for name, (_url, group) in SOURCES.items():
        path = RAW / f"{name}.csv"
        if not path.exists():
            continue
        tmp = f"raw_{name}"
        _read_csv(con, path, tmp)
        cols = [r[0] for r in con.execute(f"DESCRIBE {tmp}").fetchall()]
        seen, select = set(), []
        for c in cols:
            s = snake(c)
            if s and s not in seen:
                seen.add(s)
                select.append(f'"{c}" AS {s}')
        select.append(f"'{name}' AS source_file")
        view = f"norm_{name}"
        con.execute(f"CREATE OR REPLACE TEMP VIEW {view} AS SELECT {', '.join(select)} FROM {tmp}")
        groups.setdefault(group, []).append(view)

    counts = {}
    for group, views in groups.items():
        union = " UNION ALL BY NAME ".join(f"SELECT * FROM {v}" for v in views)
        con.execute(f"CREATE OR REPLACE TABLE stg_{group} AS {union}")
        counts[f"stg_{group}"] = con.execute(f"SELECT count(*) FROM stg_{group}").fetchone()[0]
    # Make sure every expected table exists so downstream SQL never breaks
    # just because one file failed to download.
    for group in {g for _u, g in SOURCES.values()}:
        con.execute(f"CREATE TABLE IF NOT EXISTS stg_{group} AS SELECT NULL::VARCHAR AS source_file WHERE false")
    return counts


def ensure_columns(con: duckdb.DuckDBPyConnection) -> None:
    """Add any column the models reference but the source lacked (legacy files)."""
    needed = (SQL_DIR / "_required_columns.txt").read_text(encoding="utf-8").split()
    for line in needed:
        table, col = line.split(".")
        have = {r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()}
        if col not in have:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {col} VARCHAR")


def run_models(con: duckdb.DuckDBPyConnection) -> None:
    for f in sorted(SQL_DIR.glob("[0-9]*.sql")):
        try:
            con.execute(f.read_text(encoding="utf-8"))
        except duckdb.Error as e:
            raise RuntimeError(f"{f.name}: {e}") from e
        print(f"[sql]  {f.name}")


def export_parquet(con: duckdb.DuckDBPyConnection) -> None:
    PARQUET.mkdir(parents=True, exist_ok=True)
    tables = con.execute(
        "SELECT table_catalog, table_name FROM information_schema.tables "
        "WHERE table_schema='main' AND table_catalog IN (current_database(), 'hist')").fetchall()
    for db, t in tables:
        # History tables are written as hist_<name>.parquet: a backup of data that
        # cannot be re-downloaded.
        out = PARQUET / (f"hist_{t}" if db == "hist" else t)
        con.execute(f"COPY {db}.{t} TO '{out}.parquet' (FORMAT parquet, COMPRESSION zstd)")


def build(db_path: Path = DB_PATH) -> dict[str, int]:
    """Rebuild the database; returns row counts for the run log."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    counts = load_staging(con)
    for t, n in counts.items():
        print(f"[load] {t}: {n:,} rows")
    ensure_columns(con)
    attach(con)   # models read hist.supplier_contact
    run_models(con)
    hist = record_tenders(con)
    print(f"[hist] tender_history: {hist['tender_history']:,} rows ({hist['new_tenders']:,} new)")
    export_parquet(con)
    for t in ("fct_contract", "dim_supplier", "mart_supplier_leaderboard", "mart_open_goods_tenders"):
        n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        counts[t] = n
        print(f"[mart] {t}: {n:,} rows")
    con.close()
    return {**counts, **hist}
