"""Invented history for the tests: investments, tariffs and 26 months of
readings, written through the same storage functions the app uses."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pv_monitor" / "app"))

from pvmonitor import db  # noqa: E402

PV_BY_MONTH = [150, 300, 900, 1800, 2300, 2600, 2700, 2400, 1700, 900, 300, 120]

TARIFFS = [
    {"kind": "grid", "valid_from": "2023-10-01", "energy_price": 0.30, "note": "Monatswert"},
    {"kind": "grid", "valid_from": "2024-02-01", "starts_on": "2024-02-24", "energy_price": 0.28, "base_price_year": 120.0, "provider": "Anbieter A"},
    {"kind": "grid", "valid_from": "2025-02-01", "starts_on": "2025-02-24", "energy_price": 0.25, "base_price_year": 300.0, "provider": "Anbieter B"},
    {"kind": "heat", "valid_from": "2023-10-01", "energy_price": 0.22},
    {"kind": "feed_in", "valid_from": "2023-10-01", "energy_price": 0.08},
]
INVESTMENTS = [
    {"date": "2023-04-05", "label": "Wechselrichter", "amount": 3000.0},
    {"date": "2023-05-01", "quantity": 40, "label": "Module", "amount": 12000.0},
    {"date": "2023-09-13", "label": "Kabel", "amount": 400.0},
    {"label": "Speicher", "amount": 4000.0},
    {"label": "Verkauf Altgerät", "amount": -500.0},
]
INVEST_TOTAL = sum(i["amount"] for i in INVESTMENTS)
MONTH_COUNT = 26  # baseline 2023-10 plus 25 months up to 2025-11
LAST_MONTH = "2025-11"
BATTERY_FROM = "2024-11"
HEAT_UNTIL = "2024-10"


def months():
    rows = []
    grid, heat, feed = 20000, 15000, 100
    year, month = 2023, 10
    for i in range(MONTH_COUNT):
        key = f"{year:04d}-{month:02d}"
        pv = 0 if i == 0 else PV_BY_MONTH[month - 1]
        if i:
            grid += 300 + (600 if month in (11, 12, 1, 2) else 0)
            feed += round(pv * 0.6)
        read_year, read_month = (year + 1, 1) if month == 12 else (year, month + 1)
        row = {
            "month": key,
            "reading_date": f"{read_year:04d}-{read_month:02d}-05",
            "grid_reading": float(grid),
            "feed_reading": float(feed),
            "pv_yield": float(pv),
        }
        if key <= HEAT_UNTIL:
            if i:
                heat += 100
            row["heat_reading"] = float(heat)
        if key >= BATTERY_FROM:
            row["battery_charged"], row["battery_discharged"] = 200.0, 172.0
        rows.append(row)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return rows


def fill(con):
    for item in INVESTMENTS:
        db.insert(con, "investments", db.INVESTMENT_FIELDS, item)
    for tariff in TARIFFS:
        db.insert(con, "tariffs", db.TARIFF_FIELDS, tariff)
    db.ensure_default_meters(con)
    db.insert(
        con, "meters", ("label", "kind", "active_from", "active_to"),
        {"label": "Wärmestrom", "kind": "heat", "active_from": "2023-10-01", "active_to": f"{HEAT_UNTIL}-01"},
    )
    for row in months():
        db.save_month(con, row["month"], row)
    con.commit()
