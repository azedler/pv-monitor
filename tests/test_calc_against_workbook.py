"""The calculation core must reproduce the workbook it replaces.

Imports the real workbook, derives every month in monthly tariff mode and
compares against the values Excel itself cached in the derived columns.

The workbook is private and not in the repository. Put it at
tests/fixtures/Solar-Monitor.xlsx (ignored by git) or point PVMON_WORKBOOK at
it; without it this script reports SKIPPED.

Run: python3 tests/test_calc_against_workbook.py
"""

import os
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pv_monitor" / "app"))

from pvmonitor import calc, db, excel_import  # noqa: E402

WORKBOOK = Path(
    os.environ.get("PVMON_WORKBOOK") or ROOT / "tests" / "fixtures" / "Solar-Monitor.xlsx"
)

# workbook column header -> derived key
COLUMNS = {
    "Verbrauch HS": "grid_kwh",
    "Verbrauch Wärmestrom": "heat_kwh",
    "PV Einspeisung": "feed_kwh",
    "PV Eigennutzung": "self_use",
    "Gesamtstromverbrauch": "total_consumption",
    "Autarkiegrad": "autarky",
    "Eigenverbrauchsquote": "own_consumption_quota",
    "Strompreis HS": "price",
    "Kosten Strom": "cost_energy",
    "Ertrag Einspeisung": "feed_revenue",
    "Ersparnis Eigenverbrauch": "saving",
    "Erlös PV": "revenue",
    "Erlös gesamt": "revenue_cum",
    "Grundpreis": "base_month",
    "Kosten Strom gesamt": "cost_total",
    "Effektivpreis je kWh": "effective_price",
}


def close(a, b):
    return abs(a - b) <= 1e-6 * max(1.0, abs(a), abs(b))


def main():
    if not WORKBOOK.exists():
        print(f"SKIPPED: private workbook not found at {WORKBOOK}")
        return
    con = db.connect(":memory:")
    counts = excel_import.import_workbook(con, WORKBOOK.read_bytes())
    months = db.month_rows(con)
    tariffs = db.rows(con, "SELECT * FROM tariffs")
    investments = db.rows(con, "SELECT * FROM investments")
    derived = calc.derive_months(months, tariffs, investments, calc.MODE_MONTHLY)
    by_month = {d["month"]: d for d in derived}

    ws = openpyxl.load_workbook(WORKBOOK, data_only=True)["Verbrauch_Ertrag"]
    head = next(c.row for row in ws.iter_rows(max_row=40) for c in row if c.value == "Zählerstand HS")
    col = {c.value: c.column for c in ws[head] if isinstance(c.value, str)}

    failures, compared, rows_seen = [], 0, 0
    for r in range(head + 1, ws.max_row + 1):
        reading = ws.cell(r, col["Datum"]).value
        if not isinstance(ws.cell(r, col["Zählerstand HS"]).value, (int, float)):
            continue
        rows_seen += 1
        month = calc.billed_month(reading.strftime("%Y-%m-%d"))
        d = by_month[month]
        label = ws.cell(r, col["Monat"]).value
        assert label == f"{int(month[5:7])}/{month[:4]}", (label, month)
        for header, key in COLUMNS.items():
            expected = ws.cell(r, col[header]).value
            actual = d[key]
            if isinstance(expected, (int, float)):
                compared += 1
                if actual is None or not close(actual, expected):
                    failures.append(f"{month} {header}: workbook {expected!r}, app {actual!r}")
            elif actual not in (None, 0, 0.0):
                # the workbook shows an error or an empty cell: no value there
                failures.append(f"{month} {header}: workbook {expected!r}, app {actual!r}")

    summary = calc.summarize(derived, investments)
    totals = {ws.cell(r, 1).value: ws.cell(r, 2).value for r in range(1, 9)}
    for name, key in (
        ("Initialkosten", "invest_total"),
        ("Summe Ertrag", "revenue_total"),
        ("Restabschreibung", "remaining"),
        ("Mittelwert ROI/Monat", "mean_roi_month"),
        ("Jahre bis ROI bei durchschn. Ertrag", "years_to_roi_linear"),
        ("Amortisation", "amortisation"),
    ):
        compared += 1
        if not close(summary[key], totals[name]):
            failures.append(f"summary {name}: workbook {totals[name]!r}, app {summary[key]!r}")

    assert rows_seen == counts["months"] == len(derived), (rows_seen, counts, len(derived))
    assert rows_seen >= 30 and compared > 400, (rows_seen, compared)
    if failures:
        print("\n".join(failures))
        sys.exit(f"FAIL: {len(failures)} of {compared} values differ")
    print(f"ok: {compared} values over {rows_seen} months match the workbook")


if __name__ == "__main__":
    main()
