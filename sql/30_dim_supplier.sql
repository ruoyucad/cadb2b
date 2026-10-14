-- One row per supplier (matched on supplier_key).
CREATE OR REPLACE TABLE dim_supplier AS
WITH c AS (SELECT * FROM fct_contract),
name_pick AS (   -- most frequently used legal name = display name (ties -> most recent)
  SELECT supplier_key, arg_max(supplier_legal_name, (n, last_dt)) AS display_name
  FROM (SELECT supplier_key, supplier_legal_name, count(*) AS n, max(award_date) AS last_dt FROM c
        WHERE supplier_legal_name IS NOT NULL GROUP BY supplier_key, supplier_legal_name)
  GROUP BY supplier_key
),
latest_addr AS ( -- address / size from the most recent contract
  SELECT supplier_key,
    arg_max(supplier_operating_name, award_date) AS operating_name,
    arg_max(supplier_address_line, award_date) AS address_line,
    arg_max(supplier_address_city, award_date) AS city,
    arg_max(supplier_address_province, award_date) AS province,
    arg_max(supplier_address_postal_code, award_date) AS postal_code,
    arg_max(supplier_address_country, award_date) AS country,
    arg_max(supplier_employee_count, award_date) FILTER (WHERE supplier_employee_count IS NOT NULL) AS employee_count
  FROM c GROUP BY supplier_key
),
agg AS (
  SELECT supplier_key,
    count(*) AS n_contracts,
    count(*) FILTER (WHERE is_goods) AS n_goods_contracts,
    sum(value_cad) AS total_value_cad,
    sum(value_cad) FILTER (WHERE is_goods) AS goods_value_cad,
    min(award_date) AS first_award_date,
    max(award_date) AS last_award_date,
    count(DISTINCT award_year) AS n_active_years,
    count(DISTINCT buyer) AS n_buyers,
    count(*) FILTER (WHERE china_origin_reported) AS n_china_origin_contracts
  FROM c GROUP BY supplier_key
),
top_buyers AS (
  SELECT supplier_key, string_agg(buyer, ' | ' ORDER BY v DESC) AS top_buyers
  FROM (SELECT supplier_key, buyer, sum(value_cad) AS v,
          row_number() OVER (PARTITION BY supplier_key ORDER BY sum(value_cad) DESC NULLS LAST) AS r
        FROM c WHERE buyer IS NOT NULL GROUP BY supplier_key, buyer)
  WHERE r <= 3 GROUP BY supplier_key
),
top_segments AS (
  SELECT supplier_key,
    string_agg(segment_zh, '、' ORDER BY v DESC) AS top_segments_zh,
    string_agg(segment_en, ' | ' ORDER BY v DESC) AS top_segments_en
  FROM (SELECT supplier_key, segment_zh, segment_en, sum(value_cad) AS v,
          row_number() OVER (PARTITION BY supplier_key ORDER BY sum(value_cad) DESC NULLS LAST) AS r
        FROM c WHERE segment_zh IS NOT NULL GROUP BY supplier_key, segment_zh, segment_en)
  WHERE r <= 3 GROUP BY supplier_key
)
SELECT
  md5(a.supplier_key) AS supplier_id,
  a.supplier_key, n.display_name, l.operating_name,
  l.address_line, l.city, l.province, l.postal_code, l.country, l.employee_count,
  a.n_contracts, a.n_goods_contracts, a.total_value_cad, a.goods_value_cad,
  a.first_award_date, a.last_award_date, a.n_active_years, a.n_buyers,
  a.n_china_origin_contracts,
  b.top_buyers, s.top_segments_zh, s.top_segments_en,
  -- Placeholders filled later by the enrichment step (website / public sales contact).
  NULL::VARCHAR AS website, NULL::VARCHAR AS public_email, NULL::VARCHAR AS public_phone,
  NULL::VARCHAR AS summary_zh
FROM agg a
JOIN name_pick n USING (supplier_key)
JOIN latest_addr l USING (supplier_key)
LEFT JOIN top_buyers b USING (supplier_key)
LEFT JOIN top_segments s USING (supplier_key);
