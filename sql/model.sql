-- Star schema used by the notebooks and the Power BI report.

CREATE OR REPLACE TABLE ref_cpv AS
SELECT * FROM read_csv('{REF}/cpv.csv', header = true, all_varchar = true);

CREATE OR REPLACE TABLE ref_fx AS
SELECT currency, rate_date::DATE AS rate_date, pln_rate::DOUBLE AS pln_rate
FROM read_csv('{REF}/fx_rates.csv', header = true);

-- NUTS 2 regions -> voivodeships (Mazowieckie is split into two NUTS 2 regions)
CREATE OR REPLACE TABLE dim_region AS
SELECT * FROM (VALUES
    ('PL21', 'Małopolskie'), ('PL22', 'Śląskie'), ('PL41', 'Wielkopolskie'),
    ('PL42', 'Zachodniopomorskie'), ('PL43', 'Lubuskie'), ('PL51', 'Dolnośląskie'),
    ('PL52', 'Opolskie'), ('PL61', 'Kujawsko-pomorskie'), ('PL62', 'Warmińsko-mazurskie'),
    ('PL63', 'Pomorskie'), ('PL71', 'Łódzkie'), ('PL72', 'Świętokrzyskie'),
    ('PL81', 'Lubelskie'), ('PL82', 'Podkarpackie'), ('PL84', 'Podlaskie'),
    ('PL91', 'Mazowieckie'), ('PL92', 'Mazowieckie'), ('PLZZ', 'Whole country'),
    ('n/a', 'Unknown')
) t(nuts2, voivodeship);

CREATE OR REPLACE TABLE dim_cpv AS
SELECT
    left(cpv, 2) AS cpv_division,
    name_pl AS division_name_pl,
    name_en AS division_name_en
FROM ref_cpv
WHERE cpv LIKE '__000000'
UNION ALL
SELECT 'n/a', 'Brak danych', 'Unknown';

CREATE OR REPLACE TABLE dim_buyer AS
WITH latest AS (
    SELECT
        coalesce(buyer_id, buyer_name) AS buyer_key,
        arg_max(buyer_name, publication_date) AS buyer_name,
        arg_max(buyer_legal_type, publication_date) AS legal_type,
        count(*) AS n_notices
    FROM raw_notices
    GROUP BY 1
)
SELECT
    buyer_key,
    buyer_name,
    legal_type AS buyer_legal_type,
    CASE
        WHEN legal_type IN ('la', 'ra') THEN 'Local government'
        WHEN legal_type IN ('cga', 'def-cont') THEN 'Central government'
        WHEN legal_type LIKE 'body-pl%' THEN 'Public law body'
        WHEN legal_type LIKE 'pub-undert%' OR legal_type = 'spec-rights-entity' THEN 'Public company'
        ELSE 'Other'
    END AS buyer_type,
    n_notices
FROM latest;

CREATE OR REPLACE TABLE fact_lot AS
WITH lots AS (
    SELECT
        l.*,
        n.publication_date::DATE AS publication_date,
        n.procedure_type,
        n.contract_nature,
        coalesce(n.buyer_id, n.buyer_name) AS buyer_key,
        CASE WHEN n.total_value_cur = l.value_cur THEN n.total_value END AS notice_total
    FROM raw_lots l
    JOIN raw_notices n USING (publication_number)
),
-- value in PLN using the NBP rate from the publication day (or the last day before)
with_value AS (
    SELECT lots.*,
        CASE WHEN value_cur = 'PLN' THEN value ELSE value * fx.pln_rate END AS value_pln
    FROM lots
    ASOF LEFT JOIN ref_fx fx
        ON fx.currency = lots.value_cur AND lots.publication_date >= fx.rate_date
),
with_estimate AS (
    SELECT with_value.*,
        CASE WHEN estimated_cur = 'PLN' THEN estimated_value ELSE estimated_value * fx.pln_rate END
            AS estimated_pln
    FROM with_value
    ASOF LEFT JOIN ref_fx fx
        ON fx.currency = with_value.estimated_cur AND with_value.publication_date >= fx.rate_date
)
SELECT
    publication_number || '/' || lot_id AS lot_key,
    publication_number,
    lot_id,
    publication_date,
    date_trunc('month', publication_date)::DATE AS publication_month,
    year(publication_date) AS year,
    buyer_key,
    coalesce(left(cpv, 2), 'n/a') AS cpv_division,
    cpv,
    CASE WHEN left(nuts, 2) = 'PL' THEN left(nuts, 4) ELSE 'n/a' END AS nuts2,
    nuts AS nuts3,
    coalesce(contract_nature, 'n/a') AS contract_nature,
    coalesce(procedure_type, 'n/a') AS procedure_type,
    framework,
    -- 0, negative or e.g. 201872 offers are typos
    CASE WHEN n_offers BETWEEN 1 AND 200 THEN n_offers END AS n_offers,
    CASE WHEN n_offers BETWEEN 1 AND 200 THEN n_offers = 1 END AS single_offer,
    n_winners,
    winner_key,
    winner_name,
    value_flag,
    CASE WHEN value_flag = 'ok' THEN value_pln END AS value_pln,
    CASE WHEN estimated_pln BETWEEN 1000 AND 1e10 THEN estimated_pln END AS estimated_pln
FROM (
    -- a lot of values are typos (e.g. 9 bln PLN for portable toilets), see notebook 01
    SELECT *,
        CASE
            WHEN value_pln IS NULL THEN 'missing'
            WHEN value_pln < 1000 THEN 'too_low'
            WHEN notice_total IS NOT NULL AND value > notice_total * 1.01 THEN 'above_notice_total'
            WHEN value_pln > 1e9
                 AND NOT coalesce(value_pln / estimated_pln BETWEEN 0.3 AND 3, false)
                THEN 'over_1bn_unverified'
            ELSE 'ok'
        END AS value_flag
    FROM with_estimate
);

-- winning price compared to the buyer's estimate, only where it makes sense
ALTER TABLE fact_lot ADD COLUMN price_to_estimate DOUBLE;
UPDATE fact_lot
SET price_to_estimate = value_pln / estimated_pln
WHERE value_pln IS NOT NULL
  AND estimated_pln IS NOT NULL
  AND n_winners = 1
  AND NOT framework
  AND value_pln / estimated_pln BETWEEN 0.2 AND 3;

CREATE OR REPLACE TABLE dim_winner AS
SELECT
    winner_key,
    arg_max(winner_name, publication_date) AS winner_name,
    count(*) AS n_lots_won
FROM fact_lot
WHERE winner_key IS NOT NULL
GROUP BY 1;

CREATE OR REPLACE TABLE dim_date AS
SELECT
    d::DATE AS date,
    year(d) AS year,
    month(d) AS month,
    strftime(d, '%Y-%m') AS year_month,
    quarter(d) AS quarter
FROM range(DATE '2024-01-01', DATE '2027-01-01', INTERVAL 1 DAY) t(d);
