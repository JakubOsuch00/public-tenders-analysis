# CPV dictionary (TED) and NBP exchange rates used to convert values to PLN.

import io
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

REF_DIR = Path(__file__).resolve().parents[1] / "data" / "ref"
CPV_URL = "https://ted.europa.eu/documents/d/ted/cpv_2008_xls"
NBP_URL = "https://api.nbp.pl/api/exchangerates/rates/a/{cur}/{start}/{end}/?format=json"


def fetch_cpv():
    resp = requests.get(CPV_URL, timeout=120)
    resp.raise_for_status()
    xlsx = zipfile.ZipFile(io.BytesIO(resp.content)).open("cpv_2008_ver_2013.xlsx")
    df = pd.read_excel(xlsx, usecols=["CODE", "PL", "EN"])
    df["cpv"] = df["CODE"].str[:8]
    df = df.rename(columns={"PL": "name_pl", "EN": "name_en"})[["cpv", "name_pl", "name_en"]]
    df.to_csv(REF_DIR / "cpv.csv", index=False)
    print(f"cpv: {len(df)} codes")


def fetch_rates(currencies, start=date(2023, 12, 1), end=None):
    end = end or date.today()
    rows = []
    for cur in currencies:
        d = start
        # NBP allows max 367 days per request
        while d <= end:
            chunk_end = min(d + timedelta(days=360), end)
            url = NBP_URL.format(cur=cur.lower(), start=d, end=chunk_end)
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            rows += [(cur, r["effectiveDate"], r["mid"]) for r in resp.json()["rates"]]
            d = chunk_end + timedelta(days=1)
    df = pd.DataFrame(rows, columns=["currency", "rate_date", "pln_rate"])
    df.to_csv(REF_DIR / "fx_rates.csv", index=False)
    print(f"fx rates: {len(df)} rows")


if __name__ == "__main__":
    REF_DIR.mkdir(parents=True, exist_ok=True)
    fetch_cpv()
    fetch_rates(["EUR", "USD", "GBP", "CHF"])
