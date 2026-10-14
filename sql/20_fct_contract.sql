-- One row per (contract, supplier): latest amendment wins for value,
-- earliest record gives the award date.

CREATE OR REPLACE MACRO money(x) AS
  try_cast(nullif(regexp_replace(coalesce(x, ''), '[^0-9.\-]', '', 'g'), '') AS DOUBLE);
CREATE OR REPLACE MACRO dt(x) AS try_cast(left(trim(x), 10) AS DATE);
-- Supplier matching key: uppercase, no accents/punctuation/legal suffixes.
CREATE OR REPLACE MACRO supplier_key(x) AS
  trim(regexp_replace(regexp_replace(
    regexp_replace(
      regexp_replace(upper(strip_accents(coalesce(x, ''))), '&', ' AND ', 'g'),
      '[^A-Z0-9 ]', ' ', 'g'),
    '\b(THE|INC|INCORPORATED|LTD|LIMITED|LTEE|LIMITEE|CORP|CORPORATION|CO|COMPANY|LLC|LLP|ULC|LP|SENC|SEC|INCORPOREE)\b', ' ', 'g'),
    '\s+', ' ', 'g'));
CREATE OR REPLACE MACRO first_line(x) AS nullif(trim(split_part(replace(coalesce(x, ''), chr(13), ''), chr(10), 1)), '');

CREATE OR REPLACE TABLE fct_contract AS
WITH unioned AS (
  SELECT 'contract_history' AS dataset,
    contract_number, solicitation_number, reference_number, title,
    NULL::VARCHAR AS description,
    amendment_number, amendment_date, contract_award_date, contract_start_date, contract_end_date,
    contract_amount, total_contract_value, contract_currency,
    contracting_entity_name, end_user_entities_name,
    procurement_category, procurement_method, gsin, gsin_description, unspsc, unspsc_description,
    supplier_legal_name, supplier_operating_name, supplier_standardized_name,
    supplier_address_line, supplier_address_city, supplier_address_province,
    supplier_address_postal_code, supplier_address_country, supplier_employee_count,
    percentage_of_goods_by_country, source_file
  FROM stg_contract_history
  UNION ALL BY NAME
  SELECT 'award_notices' AS dataset,
    contract_number, solicitation_number, reference_number, title, award_description AS description,
    amendment_number, amendment_date, contract_award_date, contract_start_date, contract_end_date,
    contract_amount, total_contract_value, contract_currency,
    contracting_entity_name, end_user_entities_name,
    procurement_category, procurement_method, gsin, gsin_description, unspsc, unspsc_description,
    supplier_legal_name, NULL AS supplier_operating_name, NULL AS supplier_standardized_name,
    supplier_address_line, supplier_address_city, supplier_address_province,
    supplier_address_postal_code, supplier_address_country, NULL AS supplier_employee_count,
    NULL AS percentage_of_goods_by_country, source_file
  FROM stg_award_notices
),
clean AS (
  SELECT *,
    coalesce(nullif(trim(contract_number), ''),
             nullif(trim(reference_number), ''),
             md5(concat_ws('|', solicitation_number, title, supplier_legal_name, contract_award_date))) AS contract_id,
    coalesce(nullif(trim(supplier_standardized_name), ''),
             nullif(trim(supplier_operating_name), ''),
             first_line(supplier_legal_name)) AS supplier_name_best,
    try_cast(regexp_extract(coalesce(amendment_number, '0'), '[0-9]+') AS INTEGER) AS amend_no,
    regexp_extract(coalesce(unspsc, ''), '[0-9]{8}') AS unspsc8,
    upper(coalesce(procurement_category, '')) AS cat
  FROM unioned
  WHERE coalesce(supplier_legal_name, supplier_standardized_name) IS NOT NULL
),
keyed AS (
  SELECT *, supplier_key(supplier_name_best) AS supplier_key FROM clean WHERE supplier_key(supplier_name_best) <> ''
),
ranked AS (
  SELECT *,
    row_number() OVER (PARTITION BY dataset, contract_id, supplier_key
                       ORDER BY amend_no DESC NULLS LAST, dt(amendment_date) DESC NULLS LAST) AS rn,
    min(dt(contract_award_date)) OVER (PARTITION BY dataset, contract_id, supplier_key) AS first_award_date,
    count(*) OVER (PARTITION BY dataset, contract_id, supplier_key) AS n_records,
    -- origin is often only reported on one record (e.g. the original award)
    bool_or(regexp_matches(coalesce(percentage_of_goods_by_country, ''), '(?i)(\bCN\b|china|chine|\bCHN\b)'))
      OVER (PARTITION BY dataset, contract_id, supplier_key) AS china_origin_any,
    string_agg(nullif(percentage_of_goods_by_country, ''), ' | ')
      OVER (PARTITION BY dataset, contract_id, supplier_key) AS goods_origin_all
  FROM keyed
),
latest AS (
  SELECT
    dataset, contract_id, supplier_key,
    first_line(supplier_legal_name) AS supplier_legal_name,
    supplier_operating_name, supplier_standardized_name,
    first_line(supplier_address_line) AS supplier_address_line,
    supplier_address_city, supplier_address_province, supplier_address_postal_code,
    supplier_address_country, supplier_employee_count, goods_origin_all AS percentage_of_goods_by_country,
    solicitation_number, title, description,
    coalesce(first_award_date, dt(contract_start_date)) AS award_date,
    dt(contract_end_date) AS end_date,
    coalesce(money(total_contract_value), money(contract_amount)) AS value_cad,
    coalesce(nullif(contract_currency, ''), 'CAD') AS currency,
    first_line(contracting_entity_name) AS buyer,
    first_line(end_user_entities_name) AS end_user,
    procurement_category, procurement_method,
    nullif(unspsc8, '') AS unspsc,
    first_line(unspsc_description) AS unspsc_description,
    first_line(gsin) AS gsin, first_line(gsin_description) AS gsin_description,
    -- Goods = category token GD, or a legacy GSIN starting with N (goods).
    (regexp_matches(cat, '(^|[^A-Z])GD($|[^A-Z])') OR coalesce(gsin, '') LIKE 'N%') AS is_goods,
    coalesce(china_origin_any, false) AS china_origin_reported,
    n_records, source_file
  FROM ranked WHERE rn = 1
)
SELECT l.*,
  left(l.unspsc, 2) AS segment,
  s.segment_zh, s.segment_en, coalesce(s.china_fit, false) AS china_fit,
  year(l.award_date) AS award_year
FROM latest l
LEFT JOIN ref_unspsc_segment s ON s.segment = left(l.unspsc, 2);

-- Award notices often duplicate contract-history rows. Keep award-notice rows
-- only when that contract+supplier is absent from contract history.
DELETE FROM fct_contract a
WHERE a.dataset = 'award_notices'
  AND EXISTS (SELECT 1 FROM fct_contract c
              WHERE c.dataset = 'contract_history'
                AND c.contract_id = a.contract_id AND c.supplier_key = a.supplier_key);
