# Exports the star schema to csv files that the Power BI model reads (data/powerbi/).

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "powerbi"

QUERIES = {
    "fact_lot": """
        SELECT lot_key, publication_number, publication_date, buyer_key, winner_key,
               cpv_division, left(cpv, 3) AS cpv_group, nuts2, contract_nature, procedure_type,
               framework, n_offers::INTEGER AS n_offers, least(n_offers, 10)::INTEGER AS offers_capped,
               single_offer,
               round(value_pln, 2) AS value_pln, round(estimated_pln, 2) AS estimated_pln,
               round(price_to_estimate, 4) AS price_to_estimate
        FROM fact_lot
    """,
    "dim_buyer": "SELECT buyer_key, buyer_name, buyer_type FROM dim_buyer",
    "dim_winner": "SELECT winner_key, winner_name FROM dim_winner",
    "dim_cpv": "SELECT cpv_division, division_name_pl, division_name_en FROM dim_cpv",
    "dim_cpv_group": """
        SELECT left(cpv, 3) AS cpv_group, name_pl AS group_name_pl, name_en AS group_name_en,
               left(cpv, 2) AS cpv_division
        FROM ref_cpv
        WHERE cpv LIKE '___00000'
    """,
    "dim_region": "SELECT nuts2, voivodeship FROM dim_region",
    "dim_date": "SELECT * FROM dim_date",
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(ROOT / "data" / "tenders.duckdb"), read_only=True)
    for name, sql in QUERIES.items():
        path = (OUT / f"{name}.csv").as_posix()
        con.execute(f"COPY ({sql}) TO '{path}' (HEADER, DELIMITER ',')")
        print(name, con.sql(f"SELECT count(*) FROM ({sql})").fetchone()[0])


if __name__ == "__main__":
    main()
