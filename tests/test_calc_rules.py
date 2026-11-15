"""Rules that go beyond the workbook: daily tariff weighting, dated
investments, plausibility checks, projection.

Run: python3 tests/test_calc_rules.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pv_monitor" / "app"))

from pvmonitor import calc, db, excel_import  # noqa: E402

sys.path.insert(0, str(ROOT / "tests"))
import workbook_fixture as fx  # noqa: E402


def load():
    con = db.connect(":memory:")
    excel_import.import_workbook(con, fx.build())
    return (
        db.month_rows(con),
        db.rows(con, "SELECT * FROM tariffs"),
        db.rows(con, "SELECT * FROM investments"),
    )


def near(a, b, tol=1e-9):
    return abs(a - b) <= tol


def test_daily_weighting():
    months, tariffs, investments = load()
    grid = sorted((t for t in tariffs if t["kind"] == "grid"), key=lambda t: t["valid_from"])
    switch = next(t for t in grid if t["starts_on"] == "2024-02-24")
    before = grid[grid.index(switch) - 1]
    monthly = {d["month"]: d for d in calc.derive_months(months, tariffs, investments, "monthly")}
    daily = {d["month"]: d for d in calc.derive_months(months, tariffs, investments, "daily")}
    # February 2024 has 29 days: 23 on the old price, 6 on the new one.
    expected = (23 * before["energy_price"] + 6 * switch["energy_price"]) / 29
    assert near(daily["2024-02"]["price"], expected), daily["2024-02"]["price"]
    assert near(monthly["2024-02"]["price"], switch["energy_price"])
    # A month without a switch is identical in both modes.
    assert near(daily["2024-06"]["price"], monthly["2024-06"]["price"])
    assert near(daily["2024-06"]["revenue"], monthly["2024-06"]["revenue"])
    assert (before["energy_price"], switch["energy_price"]) == (0.30, 0.28)
    # Two switches happened mid-month, so exactly two months differ.
    differing = [m for m in monthly if not near(monthly[m]["price"] or 0, daily[m]["price"] or 0)]
    assert differing == ["2024-02", "2025-02"], differing
    # The base price is weighted the same way; before the first one there is none.
    assert monthly["2024-01"]["base_month"] is None
    assert near(monthly["2024-02"]["base_month"], 10.0)
    assert near(daily["2025-02"]["base_month"], (23 * 120 + 5 * 300) / 28 / 12)


def test_dated_investment_is_not_retroactive():
    months, tariffs, investments = load()
    total = sum(i["amount"] for i in investments)
    late = dict(investments[0], id=999, date="2025-06-15", amount=1000.0, label="late")
    derived = {
        d["month"]: d
        for d in calc.derive_months(months, tariffs, investments + [late], "monthly")
    }
    assert near(derived["2025-05"]["invested"], total)
    assert near(derived["2025-06"]["invested"], total + 1000)
    undated = [i for i in investments if not i["date"]]
    assert len(undated) == 2, "undated items must count from the start"
    # at the baseline month only the items dated before it and the undated ones count
    assert near(derived[min(derived)]["invested"], fx.INVEST_TOTAL)
    early = dict(investments[0], id=998, date="2023-12-01", amount=7.0, label="early")
    d2 = {d["month"]: d for d in calc.derive_months(months, tariffs, investments + [early], "monthly")}
    assert near(d2["2023-11"]["invested"], total) and near(d2["2023-12"]["invested"], total + 7)


def test_checks():
    months, tariffs, investments = load()
    derived = calc.derive_months(months, tariffs, investments, "monthly")
    ok = calc.check_month(derived, "2025-07")
    assert len(ok) == 8 and all(c["ok"] is True for c in ok), ok
    # no battery values and no previous year yet: not judged, not passed
    early = {c["rule"]: c["ok"] for c in calc.check_month(derived, "2024-03")}
    assert early["Batterie: entladen ≤ geladen"] is None
    assert early["PV-Ertrag gegen Vorjahresmonat"] is None

    dip = [dict(m) for m in months]
    jan = next(m for m in dip if m["month"] == "2025-01")
    jan["pv_yield"] = 30.0  # January 2024 had 150 kWh
    jan["feed_reading"] = next(m for m in dip if m["month"] == "2024-12")["feed_reading"]
    rules = {
        c["rule"]: c
        for c in calc.check_month(calc.derive_months(dip, tariffs, investments, "monthly"), "2025-01")
    }
    assert rules["PV-Ertrag gegen Vorjahresmonat"]["ok"] is False, rules
    assert "150" in rules["PV-Ertrag gegen Vorjahresmonat"]["message"]

    broken = [dict(m) for m in months]
    last = broken[-1]
    last["grid_reading"] = broken[-2]["grid_reading"] - 5
    last["feed_reading"] = broken[-2]["feed_reading"] + last["pv_yield"] + 100
    last["battery_charged"], last["battery_discharged"] = 100.0, 150.0
    bad = {
        c["rule"]: c["ok"]
        for c in calc.check_month(
            calc.derive_months(broken, tariffs, investments, "monthly"), last["month"]
        )
    }
    assert bad["Zählerstand Hausstrom läuft vorwärts"] is False
    assert bad["Einspeisung passt in den Ertrag"] is False
    assert bad["Batterie: entladen ≤ geladen"] is False
    assert bad["Batteriewirkungsgrad 70–100 %"] is False

    no_tariff = calc.check_month(calc.derive_months(months, [], investments, "monthly"), "2025-07")
    assert {c["rule"]: c["ok"] for c in no_tariff}["Strompreis hinterlegt"] is False


def test_projection_and_comparison():
    months, tariffs, investments = load()
    derived = calc.derive_months(months, tariffs, investments, "monthly")
    summary = calc.summarize(derived, investments)
    be = summary["break_even"]
    assert be and not be["reached"] and be["month"] > fx.LAST_MONTH, be
    assert be["curve"][-2]["revenue_cum"] < summary["invest_total"]
    assert near(summary["invest_total"], fx.INVEST_TOTAL)
    assert be["curve"][-1]["revenue_cum"] >= summary["invest_total"]
    last12 = sum(d["revenue"] for d in derived[-12:])
    twelve = be["curve"][11]["revenue_cum"] - summary["revenue_total"]
    assert near(twelve, last12, 1e-6), (twelve, last12)

    r = calc.compare_tariff(derived, 0.30, 120.0)
    assert r["months"] == 12
    assert near(r["alternative_cost"], r["grid_kwh"] * 0.30 + 120.0, 1e-6)
    assert r["actual_cost"] is not None
    assert near(calc.tariff_break_even_kwh(0.25, 300.0, 0.28, 120.0), 6000.0, 1e-6)
    assert calc.tariff_break_even_kwh(0.25, 120.0, 0.28, 300.0) is None  # never crosses
    assert calc.tariff_break_even_kwh(0.30, 100, 0.30, 120) is None


def test_months():
    assert calc.month_add("2023-12", 1) == "2024-01"
    assert calc.month_add("2024-01", -1) == "2023-12"
    assert calc.billed_month("2024-01-07") == "2023-12"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
