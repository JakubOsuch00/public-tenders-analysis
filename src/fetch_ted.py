# Downloads Polish contract award notices from the TED search API, one file per month.
# python src/fetch_ted.py --start 2024-01 --end 2026-10

import argparse
import json
import time
from datetime import date
from pathlib import Path

import requests

API = "https://api.ted.europa.eu/v3/notices/search"
RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"

FIELDS = [
    "publication-number",
    "publication-date",
    "notice-type",
    "procedure-type",
    "contract-nature-main-proc",
    "main-classification-proc",
    "buyer-name",
    "buyer-identifier",
    "buyer-legal-type",
    "framework-agreement-lot",
    "identifier-lot",
    "main-classification-lot",
    "place-of-performance-subdiv-lot",
    "estimated-value-lot",
    "estimated-value-cur-lot",
    "BT-13713-LotResult",  # lot id of each result
    "BT-759-LotResult",  # number of received submissions
    "BT-760-LotResult",  # type of the submissions count
    "BT-720-Tender",  # winning tender value
    "BT-720-Tender-Currency",
    "winner-name",
    "winner-identifier",
    "winner-size",
    "total-value",
    "total-value-cur",
]


def month_range(start: str, end: str):
    y, m = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    while (y, m) <= (ey, em):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def post(body: dict) -> dict:
    for attempt in range(5):
        resp = requests.post(API, json=body, timeout=120)
        if resp.status_code == 200:
            return resp.json()
        print(f"  {resp.status_code}, retrying...")
        time.sleep(5 * (attempt + 1))
    resp.raise_for_status()


def fetch_month(y: int, m: int) -> list[dict]:
    start = date(y, m, 1)
    end = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
    query = (
        "buyer-country=POL AND notice-type=can-standard "
        f"AND publication-date>={start:%Y%m%d} AND publication-date<{end:%Y%m%d}"
    )
    body = {"query": query, "fields": FIELDS, "limit": 250, "paginationMode": "ITERATION"}

    notices = []
    while True:
        data = post(body)
        notices.extend(data.get("notices", []))
        token = data.get("iterationNextToken")
        if not token or not data.get("notices"):
            break
        body["iterationNextToken"] = token
    for n in notices:
        n.pop("links", None)
    return notices


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2024-01")
    parser.add_argument("--end", default="2026-10")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for y, m in month_range(args.start, args.end):
        out = RAW_DIR / f"ted_{y}-{m:02d}.json"
        if out.exists() and not args.force:
            continue
        notices = fetch_month(y, m)
        out.write_text(json.dumps(notices, ensure_ascii=False), encoding="utf-8")
        print(f"{y}-{m:02d}: {len(notices)} notices")


if __name__ == "__main__":
    main()
