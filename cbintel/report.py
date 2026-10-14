"""Export product-ready files: Excel-friendly CSVs and a Chinese sample report."""
from __future__ import annotations

from pathlib import Path

import duckdb

from .build import DB_PATH

OUT = Path("output")


def report(db_path: Path = DB_PATH, top_n: int = 50, segments: list[str] | None = None) -> list[Path]:
    OUT.mkdir(exist_ok=True)
    con = duckdb.connect(str(db_path), read_only=True)
    seg_filter = ""
    if segments:
        seg_filter = "AND segment IN (" + ",".join(f"'{s}'" for s in segments) + ")"

    files = []
    lb = OUT / "supplier_leaderboard.csv"
    con.execute(f"""COPY (
        SELECT segment AS 品类代码, segment_zh AS 品类, rank_in_segment AS 排名,
               display_name AS 公司名称, operating_name AS 经营名称, city AS 城市, province AS 省份,
               employee_count AS 员工规模, n_contracts AS 近5年中标次数, value_cad AS 近5年中标金额_加元,
               n_years AS 中标年数, n_buyers AS 服务政府部门数, last_award_date AS 最近中标日期,
               n_china_origin AS 申报含中国产品合同数, top_buyers AS 主要采购方, commodities AS 中标品目,
               website AS 官网, public_email AS 公开邮箱, public_phone AS 公开电话
        FROM mart_supplier_leaderboard
        WHERE rank_in_segment <= {top_n} {seg_filter}
        ORDER BY segment, rank_in_segment
    ) TO '{lb}' (HEADER, DELIMITER ',')""")
    files.append(lb)

    tn = OUT / "open_goods_tenders.csv"
    con.execute(f"""COPY (
        SELECT segment_zh AS 品类, title AS 标题, buyer AS 采购方, published AS 发布日期,
               closing AS 截止时间, unspsc_description AS 品目, past_winners AS 该品目历史中标者,
               regions_of_delivery AS 交付地区, notice_url AS 链接
        FROM mart_open_goods_tenders WHERE coalesce(china_fit, true)
        ORDER BY closing NULLS LAST
    ) TO '{tn}' (HEADER, DELIMITER ',')""")
    files.append(tn)

    # Add a UTF-8 BOM so Excel on Windows shows Chinese correctly.
    for f in files:
        data = f.read_bytes()
        if not data.startswith(b"\xef\xbb\xbf"):
            f.write_bytes(b"\xef\xbb\xbf" + data)

    # Overview by segment — the first thing to look at when choosing a niche.
    md = OUT / "segment_overview.md"
    rows = con.execute("""
        SELECT segment, segment_zh, count(*) AS suppliers, sum(n_contracts) AS contracts,
               round(sum(value_cad)/1e6, 1) AS value_m, sum(n_china_origin) AS china_origin
        FROM mart_supplier_segment GROUP BY segment, segment_zh ORDER BY value_m DESC NULLS LAST
    """).fetchall()
    lines = ["# 品类概览（近5年，联邦政府货物类合同）", "",
             "| 代码 | 品类 | 中标公司数 | 合同数 | 金额(百万加元) | 申报含中国产品的合同 |",
             "|---|---|---:|---:|---:|---:|"]
    lines += [f"| {r[0]} | {r[1]} | {r[2]:,} | {r[3]:,} | {r[4] or 0:,} | {r[5]:,} |" for r in rows]
    lines += ["", "数据来源：CanadaBuys 开放数据。Contains information licensed under the Open Government Licence – Canada."]
    md.write_text("\n".join(lines), encoding="utf-8")
    files.append(md)
    con.close()
    for f in files:
        print(f"[out]  {f}")
    return files
