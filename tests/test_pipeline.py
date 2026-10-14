import os

import duckdb
import pytest

from cbintel.build import build, snake
from cbintel.report import report
from tests.fixtures import write_fixtures


def test_snake():
    assert snake("supplierLegalName-nomLegalFournisseur-eng") == "supplier_legal_name"
    assert snake("supplierLegalName-nomLegalFournisseur-fra") is None
    assert snake("noticeURL-URLavis-eng") == "notice_url"
    assert snake("﻿amendmentDate-dateModification") == "amendment_date"
    assert snake("unspscDescription-eng") == "unspsc_description"
    assert snake("gsin-nibs") == "gsin"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    work = tmp_path_factory.mktemp("work")
    cwd = os.getcwd()
    os.chdir(work)
    write_fixtures(work / "data" / "raw")
    build()
    report()
    con = duckdb.connect("data/cbintel.duckdb", read_only=True)
    yield con, work
    con.close()
    os.chdir(cwd)


def q(con, sql):
    return con.execute(sql).fetchall()


def test_supplier_variants_merge(db):
    con, _ = db
    rows = q(con, "SELECT supplier_key, n_contracts FROM dim_supplier WHERE supplier_key LIKE 'ACME%'")
    assert rows == [("ACME SAFETY SUPPLY", 3)]


def test_latest_amendment_value(db):
    con, _ = db
    (v,), = q(con, "SELECT value_cad FROM fct_contract WHERE contract_id='C-001'")
    assert v == 120000  # total after amendment, not double-counted


def test_award_notice_dedup(db):
    con, _ = db
    ids = {r[0] for r in q(con, "SELECT contract_id FROM fct_contract WHERE dataset='award_notices'")}
    assert ids == {"C-900"}


def test_leaderboard_goods_only_and_canadian(db):
    con, _ = db
    names = {r[0] for r in q(con, "SELECT display_name FROM mart_supplier_leaderboard")}
    assert "Big Consulting LLP" not in names            # services excluded
    assert "Shenzhen Gloves Co., Ltd." not in names     # foreign excluded
    assert {"Acme Safety Supply Inc.", "Northern Office Furniture Ltd.", "Maple Lighting Corp"} <= names


def test_china_origin_flag(db):
    con, _ = db
    (n,), = q(con, "SELECT n_china_origin_contracts FROM dim_supplier WHERE supplier_key='ACME SAFETY SUPPLY'")
    assert n == 1


def test_multiline_supplier_first_line(db):
    con, _ = db
    (name,), = q(con, "SELECT supplier_legal_name FROM fct_contract WHERE contract_id='C-007'")
    assert name == "Northern Office Furniture Ltd."


def test_open_tenders_with_incumbents(db):
    con, _ = db
    rows = q(con, "SELECT tender_id, title, past_winners FROM mart_open_goods_tenders")
    assert len(rows) == 1
    tid, title, winners = rows[0]
    assert tid == "T-1" and "amended" in title           # latest amendment
    assert "Acme Safety Supply Inc." in winners


def test_report_files(db):
    _, work = db
    lb = (work / "output" / "supplier_leaderboard.csv").read_bytes()
    assert lb.startswith(b"\xef\xbb\xbf") and "公司名称".encode() in lb
    assert (work / "output" / "segment_overview.md").exists()


def test_tender_history_survives_rebuild(tmp_path, monkeypatch):
    work = tmp_path
    monkeypatch.chdir(work)
    write_fixtures(work / "data" / "raw")
    build()
    hist = duckdb.connect("data/history.duckdb", read_only=True)
    rows = hist.execute("SELECT tender_id, title, first_seen_at FROM tender_history ORDER BY 1").fetchall()
    hist.close()
    assert [r[0] for r in rows] == ["T-1", "T-2", "T-3"]
    assert "amended" in rows[0][1]

    # A rebuild (fresh analytical DB) adds nothing new and keeps first_seen_at.
    (work / "data" / "cbintel.duckdb").unlink()
    stats = build()
    assert stats["new_tenders"] == 0 and stats["tender_history"] == 3
    hist = duckdb.connect("data/history.duckdb", read_only=True)
    again = hist.execute("SELECT tender_id, title, first_seen_at FROM tender_history ORDER BY 1").fetchall()
    hist.close()
    assert [(r[0], r[2]) for r in again] == [(r[0], r[2]) for r in rows]
    assert (work / "data" / "parquet" / "hist_tender_history.parquet").exists()


def test_run_log(db, tmp_path):
    from datetime import datetime
    from cbintel.history import log_run
    path = tmp_path / "h.duckdb"
    log_run(datetime(2026, 1, 1), "all", "ok", {"tenders_open": "ok"}, {"new_tenders": 2}, path=path)
    con = duckdb.connect(str(path), read_only=True)
    (cmd, status, downloads), = con.execute("SELECT command, status, downloads FROM run_log").fetchall()
    con.close()
    assert (cmd, status) == ("all", "ok") and "tenders_open" in downloads
