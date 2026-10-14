-- Product-facing tables.

-- 1) Supplier x category: who wins goods contracts in each UNSPSC segment,
--    last 5 years, Canadian-based suppliers. This is the "channel customer"
--    list a Chinese factory in that category would want.
CREATE OR REPLACE TABLE mart_supplier_segment AS
SELECT
  c.segment, any_value(c.segment_zh) AS segment_zh, any_value(c.segment_en) AS segment_en,
  c.supplier_key,
  count(*) AS n_contracts,
  sum(c.value_cad) AS value_cad,
  max(c.award_date) AS last_award_date,
  count(DISTINCT c.award_year) AS n_years,
  count(DISTINCT c.buyer) AS n_buyers,
  count(*) FILTER (WHERE c.china_origin_reported) AS n_china_origin,
  string_agg(DISTINCT c.unspsc_description, ' | ') AS commodities
FROM fct_contract c
WHERE c.is_goods AND c.china_fit
  AND c.award_date >= current_date - INTERVAL 5 YEAR
GROUP BY c.segment, c.supplier_key;

-- 2) Leaderboard: rank suppliers within each segment. The score favours
--    repeat winners (recurring demand) over one-off big contracts.
CREATE OR REPLACE TABLE mart_supplier_leaderboard AS
SELECT
  m.segment, m.segment_zh, m.segment_en,
  row_number() OVER (PARTITION BY m.segment ORDER BY score DESC) AS rank_in_segment,
  d.supplier_id, d.display_name, d.operating_name, d.city, d.province, d.country, d.employee_count,
  m.n_contracts, round(m.value_cad, 0) AS value_cad, m.last_award_date, m.n_years, m.n_buyers,
  m.n_china_origin, left(m.commodities, 500) AS commodities,
  d.top_buyers, d.website, d.public_email, d.public_phone, d.summary_zh,
  round(score, 3) AS score
FROM (
  SELECT *,
    ln(1 + n_contracts) * 2
    + ln(1 + coalesce(value_cad, 0)) / 4
    + n_years * 0.5
    + ln(1 + n_buyers)
    + CASE WHEN last_award_date >= current_date - INTERVAL 1 YEAR THEN 1 ELSE 0 END
    + CASE WHEN n_china_origin > 0 THEN 1 ELSE 0 END   -- already imports from China
    AS score
  FROM mart_supplier_segment
) m
JOIN dim_supplier d USING (supplier_key)
WHERE coalesce(upper(d.country), 'CANADA') IN ('CANADA', 'CA', 'CAN', '');

-- 3) Open goods tenders, each with the suppliers who previously won the same
--    commodity code — the people a Chinese factory should pitch right now.
CREATE OR REPLACE TABLE stg_tenders_latest AS
SELECT * EXCLUDE (rn) FROM (
  SELECT *,
    row_number() OVER (
      PARTITION BY coalesce(nullif(solicitation_number, ''), reference_number, title)
      ORDER BY try_cast(regexp_extract(coalesce(amendment_number, '0'), '[0-9]+') AS INTEGER) DESC NULLS LAST,
               dt(amendment_date) DESC NULLS LAST) AS rn
  FROM stg_tenders
) WHERE rn = 1;

CREATE OR REPLACE TABLE mart_open_goods_tenders AS
WITH t AS (
  SELECT
    coalesce(nullif(solicitation_number, ''), reference_number) AS tender_id,
    title, left(tender_description, 2000) AS description,
    first_line(contracting_entity_name) AS buyer,
    dt(publication_date) AS published,
    try_cast(replace(left(tender_closing_date, 19), 'T', ' ') AS TIMESTAMP) AS closing,
    procurement_category, regions_of_delivery, trade_agreements,
    regexp_extract(coalesce(unspsc, ''), '[0-9]{8}') AS unspsc,
    first_line(unspsc_description) AS unspsc_description,
    contact_info_name, contact_info_email, contact_info_phone,
    notice_url
  FROM stg_tenders_latest
  WHERE upper(coalesce(tender_status, 'OPEN')) IN ('OPEN', 'ACTIVE')
    AND (regexp_matches(upper(coalesce(procurement_category, '')), '(^|[^A-Z])GD($|[^A-Z])')
         OR coalesce(gsin, '') LIKE 'N%')
),
incumbents AS (
  SELECT unspsc, string_agg(display_name, ' | ' ORDER BY n DESC) AS past_winners
  FROM (
    SELECT c.unspsc, d.display_name, count(*) AS n,
      row_number() OVER (PARTITION BY c.unspsc ORDER BY count(*) DESC) AS r
    FROM fct_contract c JOIN dim_supplier d USING (supplier_key)
    WHERE c.unspsc IS NOT NULL GROUP BY c.unspsc, d.display_name
  ) WHERE r <= 5 GROUP BY unspsc
)
SELECT t.*, s.segment_zh, s.china_fit, i.past_winners
FROM t
LEFT JOIN ref_unspsc_segment s ON s.segment = left(t.unspsc, 2)
LEFT JOIN incumbents i ON i.unspsc = t.unspsc
WHERE t.closing IS NULL OR t.closing >= current_date;
