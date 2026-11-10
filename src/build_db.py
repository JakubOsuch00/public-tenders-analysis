# Parses raw TED json into notices + lot results and builds the DuckDB model (sql/model.sql).

import json
import re
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
DB_PATH = ROOT / "data" / "tenders.duckdb"


def first(value):
    """TED returns some fields as lists, multilingual ones as {lang: [..]}."""
    if isinstance(value, dict):
        value = value.get("pol") or next(iter(value.values()), None)
    if isinstance(value, list):
        return value[0] if value else None
    return value


def names(value) -> list:
    if isinstance(value, dict):
        return value.get("pol") or next(iter(value.values()), [])
    return value or []


def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def split_stats(codes: list, vals: list, n: int):
    """Submission statistics per lot result. None if they can't be matched to lots."""
    if n == 0 or len(codes) != len(vals):
        return None
    if n == 1:
        return [list(zip(codes, vals, strict=True))]
    if len(codes) % n:
        return None
    k = len(codes) // n
    chunks = [list(zip(codes[i * k : (i + 1) * k], vals[i * k : (i + 1) * k], strict=True)) for i in range(n)]
    # every lot has to report the same kinds of counts, otherwise the order is ambiguous
    if len({tuple(c for c, _ in ch) for ch in chunks}) != 1:
        return None
    return chunks


def offers_count(stats):
    if stats is None:
        return None, None
    d = dict(stats)
    for code in ("tenders", "t-esubm"):
        if code in d:
            return int(float(d[code])), code
    return None, None


def per_lot(values: list, lot_ids: list, lot_id: str):
    """Pick the value for lot_id from a list that is either per lot or a single value."""
    if not values:
        return None
    if len(values) == len(lot_ids):
        return values[lot_ids.index(lot_id)]
    if len(set(values)) == 1:
        return values[0]
    return None


def parse_notice(n: dict):
    lot_ids = n.get("identifier-lot") or []
    result_ids = n.get("BT-13713-LotResult") or []
    tender_values = n.get("BT-720-Tender") or []
    tender_curs = n.get("BT-720-Tender-Currency") or []
    winners = names(n.get("winner-name"))
    winner_ids = n.get("winner-identifier") or []
    stats = split_stats(n.get("BT-760-LotResult") or [], n.get("BT-759-LotResult") or [], len(result_ids))

    notice = {
        "publication_number": n["publication-number"],
        "publication_date": n["publication-date"][:10],
        "procedure_type": first(n.get("procedure-type")),
        "contract_nature": first(n.get("contract-nature-main-proc")),
        "main_cpv": first(n.get("main-classification-proc")),
        "buyer_name": first(n.get("buyer-name")),
        "buyer_id": first(n.get("buyer-identifier")),
        "buyer_legal_type": first(n.get("buyer-legal-type")),
        "n_lots": len(lot_ids),
        "n_results": len(result_ids),
        "total_value": to_float(n.get("total-value")),
        "total_value_cur": first(n.get("total-value-cur")),
        "lots_parsed": False,
    }

    # one winning tender per lot result -> lists can be zipped
    aligned = len(tender_values) == len(winners) == len(result_ids)
    single = len(result_ids) == 1
    if not result_ids or not (aligned or single):
        return notice, []

    lots = []
    for i, lot_id in enumerate(result_ids):
        if aligned:
            # currencies come deduplicated, e.g. one "PLN" for all lots
            cur = tender_curs[i] if len(tender_curs) == len(tender_values) else first(tender_curs)
            value, winner, n_winners = to_float(tender_values[i]), winners[i], 1
            winner_id = winner_ids[i] if len(winner_ids) == len(winners) else None
        else:
            # single lot with several winners (framework) or no winner at all
            value = sum(filter(None, map(to_float, tender_values))) or None
            cur = first(tender_curs)
            n_winners = len(winners)
            winner = winners[0] if n_winners == 1 else None
            winner_id = winner_ids[0] if n_winners == 1 and len(winner_ids) == 1 else None
        if winner_id is None and len(set(winners)) == 1 and len(winner_ids) == 1:
            winner_id = winner_ids[0]

        n_offers, offers_type = offers_count(stats[i] if stats else None)
        lots.append(
            {
                "publication_number": n["publication-number"],
                "lot_id": lot_id,
                "cpv": per_lot(n.get("main-classification-lot") or [], lot_ids, lot_id)
                or first(n.get("main-classification-proc")),
                "nuts": per_lot(n.get("place-of-performance-subdiv-lot") or [], lot_ids, lot_id),
                "n_offers": n_offers,
                "offers_type": offers_type,
                "winner_name": winner,
                "winner_id": winner_id,
                "winner_key": winner_key(winner_id, winner),
                "n_winners": n_winners,
                "value": value,
                "value_cur": cur,
                "estimated_value": to_float(per_lot(n.get("estimated-value-lot") or [], lot_ids, lot_id)),
                "estimated_cur": per_lot(n.get("estimated-value-cur-lot") or [], lot_ids, lot_id),
                "framework": (per_lot(n.get("framework-agreement-lot") or [], lot_ids, lot_id) or "none")
                != "none",
            }
        )
    notice["lots_parsed"] = True
    return notice, lots


def normalize_name(name):
    if not name:
        return None
    s = name.lower()
    s = s.replace("spółka z ograniczoną odpowiedzialnością", "sp. z o.o.")
    s = s.replace("spółka akcyjna", "s.a.")
    s = re.sub(r"[\"„”'`]", "", s)
    s = re.sub(r"\s+", " ", s).strip(" .,")
    return s


def winner_key(winner_id, name):
    # polish companies usually have NIP (10 digits) as identifier, otherwise fall back to the name
    digits = re.sub(r"\D", "", winner_id or "")
    return digits if len(digits) == 10 else normalize_name(name)


def main():
    notices, lots = [], []
    for f in sorted(RAW_DIR.glob("ted_*.json")):
        for raw in json.loads(f.read_text(encoding="utf-8")):
            notice, notice_lots = parse_notice(raw)
            notices.append(notice)
            lots.extend(notice_lots)

    notices_df = pd.DataFrame(notices)
    lots_df = pd.DataFrame(lots)

    DB_PATH.unlink(missing_ok=True)
    con = duckdb.connect(str(DB_PATH))
    con.execute("CREATE TABLE raw_notices AS SELECT * FROM notices_df")
    con.execute("CREATE TABLE raw_lots AS SELECT * FROM lots_df")
    model = (ROOT / "sql" / "model.sql").read_text(encoding="utf-8")
    con.execute(model.replace("{REF}", (ROOT / "data" / "ref").as_posix()))

    parsed = notices_df["lots_parsed"].mean()
    print(f"notices: {len(notices_df)}, lot results: {len(lots_df)}, notices split into lots: {parsed:.1%}")
    con.close()


if __name__ == "__main__":
    main()
