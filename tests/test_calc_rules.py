"""The calculation core: monthly figures, daily tariff weighting, dated
investments, plausibility checks, projection and billing forecast.

Run: python3 tests/test_calc_rules.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pv_monitor" / "app"))

from pvmonitor import calc, db  # noqa: E402

sys.path.insert(0, str(ROOT / "tests"))
import sample_data as fx  # noqa: E402


def load():
    con = db.connect(":memory:")
    fx.fill(con)
    return (
        db.month_rows(con),
        db.rows(con, "SELECT * FROM tariffs"),
        db.rows(con, "SELECT * FROM investments"),
    )


def near(a, b, tol=1e-9):
    return abs(a - b) <= tol


def test_monthly_figures():
    """One month by hand: readings become draw, yield becomes revenue."""
    months, tariffs, investments = load()
    derived = {d["month"]: d for d in calc.derive_months(months, tariffs, investments, "monthly")}
    assert derived["2023-10"]["baseline"] and derived["2023-10"]["revenue"] == 0
    d = derived["2025-06"]  # 2600 kWh yield, 1560 fed in, 300 drawn, tariff 0.25 + 300/year
    assert (d["grid_kwh"], d["feed_kwh"], d["heat_kwh"], d["self_use"]) == (300, 1560, 0, 1040)
    assert d["total_consumption"] == 1340 and near(d["autarky"], 1040 / 1340)
    assert near(d["own_consumption_quota"], 0.4) and near(d["battery_efficiency"], 0.86)
    assert near(d["saving"], 260.0) and near(d["feed_revenue"], 124.8) and near(d["revenue"], 384.8)
    # the base price is part of the cost and the effective price, not of the saving
    assert near(d["cost_energy"], 75.0) and near(d["base_month"], 25.0) and near(d["cost_total"], 100.0)
    assert near(d["effective_price"], 100.0 / 300)
    # while the heat meter existed its draw counts as consumption and cost
    h = derived["2024-03"]
    assert h["heat_kwh"] == 100 and near(h["cost_energy"], 300 * 0.28 + 100 * 0.22)
    assert h["battery_efficiency"] is None
    total = sum(x["revenue"] for x in derived.values())
    assert near(derived["2025-11"]["revenue_cum"], total, 1e-6)
    summary = calc.summarize(list(derived.values()), investments)
    assert near(summary["amortisation"], total / fx.INVEST_TOTAL)


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


def test_forecast_billing():
    months, tariffs, investments = load()
    derived = calc.derive_months(months, tariffs, investments, "monthly")
    by = {d["month"]: d for d in derived}
    for t in tariffs:
        if t.get("starts_on") == "2025-02-24":
            t["monthly_payment"] = 150.0
    f = calc.forecast_billing(derived, tariffs, "2025-12-10")
    cur = f["current"]
    # the running tariff began on 24 Feb 2025 and has no end: one year
    assert (cur["start"], cur["end"]) == ("2025-02-24", "2026-02-23"), cur["start"]
    assert cur["tariff"]["energy_price"] == 0.25 and cur["payment_count"] == 12
    rows = {r["month"]: r for r in cur["rows"]}
    assert list(rows)[0] == "2025-02" and list(rows)[-1] == "2026-02" and len(rows) == 13
    assert near(rows["2025-02"]["share"], 5 / 28) and near(rows["2026-02"]["share"], 23 / 28)
    assert near(sum(r["share"] for r in rows.values()), 12.0)
    # months with readings count as they were, weighted by their share
    assert rows["2025-06"]["actual"] and near(rows["2025-06"]["kwh"], by["2025-06"]["grid_kwh"])
    assert near(rows["2025-02"]["kwh"], by["2025-02"]["grid_kwh"] * 5 / 28)
    # the rest is the most recent same calendar month
    assert not rows["2025-12"]["actual"] and near(rows["2025-12"]["kwh"], by["2024-12"]["grid_kwh"])
    assert near(rows["2026-02"]["kwh"], by["2025-02"]["grid_kwh"] * 23 / 28)
    kwh = sum(r["kwh"] for r in rows.values())
    assert near(cur["kwh"], kwh) and near(cur["cost"], kwh * 0.25 + 300.0, 1e-6)
    assert near(cur["payments_total"], 1800.0) and near(cur["balance"], 1800.0 - cur["cost"], 1e-6)
    assert near(cur["recommended_payment"], cur["cost"] / 12, 1e-9)
    assert cur["kwh_low"] <= cur["kwh"] <= cur["kwh_high"]
    assert near(cur["kwh_so_far"], sum(r["kwh"] for r in rows.values() if r["actual"]))

    nxt = f["next"]
    assert (nxt["start"], nxt["end"]) == ("2026-02-24", "2027-02-23") and not nxt["tariff_known"]
    assert near(nxt["months"], 12.0) and all(not r["actual"] for r in nxt["rows"])
    assert near(nxt["recommended_payment"], (nxt["kwh"] * 0.25 + 300.0) / 12, 1e-6)
    assert nxt["payment_count"] == 12 and near(nxt["year_kwh"], nxt["kwh"])

    # a follow-up tariff that is already entered ends with its contract, not after a year
    follow = {"id": 99, "kind": "grid", "valid_from": "2026-03-01", "starts_on": "2026-02-24", "energy_price": 0.32,
              "base_price_year": 144.0, "contract_end": "2026-12-31"}
    f2 = calc.forecast_billing(derived, tariffs + [follow], "2025-12-10")
    assert f2["current"]["end"] == "2026-02-23"
    n2 = f2["next"]
    assert (n2["start"], n2["end"]) == ("2026-02-24", "2026-12-31") and n2["tariff_known"]
    assert n2["payment_count"] == 10 and near(n2["months"], 5 / 28 + 10)
    assert near(n2["cost"], n2["kwh"] * 0.32 + 144.0 * n2["months"] / 12, 1e-6)
    assert near(n2["recommended_payment"], n2["cost"] / 10, 1e-9)
    assert n2["kwh"] < n2["year_kwh"] and near(n2["year_kwh"], nxt["kwh"])  # the winter months after the end are missing

    # a contract end shortens the period; no payment set means no balance
    for t in tariffs:
        if t.get("starts_on") == "2025-02-24":
            t.update(contract_end="2025-12-31", monthly_payment=None)
    short = calc.forecast_billing(derived, tariffs, "2025-12-10")["current"]
    assert short["end"] == "2025-12-31" and short["balance"] is None and short["payments_total"] is None
    # before the first tariff, or without data, there is nothing to say
    assert calc.forecast_billing(derived, tariffs, "2020-01-01") is None
    assert calc.forecast_billing([], tariffs, "2025-12-10") is None


def test_feed_in_mix():
    # 24.96 kWp: 10 at the first rate, 14.96 at the second
    assert near(calc.feed_in_mix(0.0803, 0.0695, 24.96), (10 * 0.0803 + 14.96 * 0.0695) / 24.96)
    assert round(calc.feed_in_mix(0.0803, 0.0695, 24.96), 5) == 0.07383
    assert calc.feed_in_mix(0.0803, 0.0695, 8.0) == 0.0803 and calc.feed_in_mix(0.0803, 0.0695, None) == 0.0803
    assert near(calc.feed_in_mix(0.08, 0.07, 55.0), (10 * 0.08 + 30 * 0.07) / 40)  # capped at 40 kWp


def test_periods_and_shares():
    months, tariffs, investments = load()
    derived = calc.derive_months(months, tariffs, investments, "monthly")
    ps = {p["key"]: p for p in calc.periods(derived)}
    assert list(ps) == ["last12", "y2023", "y2024", "y2025", "all"], list(ps)
    assert ps["last12"]["span"] == "Dezember 2024 – November 2025" and ps["last12"]["months"] == 12
    assert ps["y2023"]["label"] == "2023 ab Nov." and ps["y2024"]["label"] == "2024"
    assert ps["y2025"]["label"] == "2025 bisher" and ps["y2025"]["span"] == "Januar 2025 – November 2025"
    assert ps["all"]["months"] == fx.MONTH_COUNT - 1  # the baseline month only anchors the meters
    y = ps["y2024"]
    rows = [d for d in derived if d["month"].startswith("2024")]
    assert near(y["pv_yield"], sum(r["pv_yield"] for r in rows))
    assert near(y["grid_kwh"], sum(r["grid_kwh"] + r["heat_kwh"] for r in rows))
    assert near(y["revenue"], sum(r["revenue"] for r in rows), 1e-6)
    assert near(y["autarky"], y["self_use"] / (y["self_use"] + y["grid_kwh"]))
    # 2024-11/12 have a battery: 200 kWh in, 172 out each
    assert near(y["battery_charged"], 400) and near(y["battery_loss"], 56) and near(y["battery_efficiency"], 0.86)
    for key in ("went", "came"):
        assert near(sum(y[key].values()), 1.0), y[key]
    # direct use = yield - feed-in - charging, month by month
    direct = sum(max(r["pv_yield"] - r["feed_kwh"] - (r["battery_charged"] or 0), 0) for r in rows)
    # November 2024: 300 kWh yield, 180 fed in, 200 charged -> no negative direct use
    nov = next(r for r in rows if r["month"] == "2024-11")
    assert nov["pv_yield"] - nov["feed_kwh"] - nov["battery_charged"] < 0
    assert near(y["direct"], direct)
    assert near(y["went"]["battery"], 400 / (direct + 400 + y["feed_kwh"]))
    assert near(y["came"]["grid"], y["grid_kwh"] / (direct + y["battery_discharged"] + y["grid_kwh"]))
    assert y["peak_yield"] == "2024-07"
    assert calc.periods([]) == []


def test_storage_economics():
    months, tariffs, investments = load()
    derived = calc.derive_months(months, tariffs, investments, "monthly")
    assert calc.storage_economics(derived, investments)["cost"] == 0  # nothing marked "Speicher" yet
    items = investments + [
        dict(investments[0], id=901, date="2024-11-01", label="Speicher", amount=3000.0, category="Speicher"),
        dict(investments[0], id=902, date=None, label="Montage", amount=500.0, category=" speicher "),
    ]
    st = calc.storage_economics(derived, items)
    assert st["cost"] == 3500.0 and st["items"] == 2 and st["undated_items"] == 1
    assert st["install_month"] == "2024-11"
    # 13 months with battery: 172 kWh saved at the energy price, minus 200 kWh at the feed-in rate
    by = {d["month"]: d for d in derived}
    expected = sum(172 * by[m]["price"] - 200 * 0.08 for m in by if m >= "2024-11")
    assert near(st["benefit_total"], expected, 1e-6) and len(st["monthly"]) == 13
    assert near(st["share"], expected / 3500)
    growth = [sc["growth"] for sc in st["scenarios"]]
    assert growth == [0.0, 0.02, 0.04] and all(sc["month"] for sc in st["scenarios"])
    months_found = [sc["month"] for sc in st["scenarios"]]
    assert months_found == sorted(months_found, reverse=True)  # rising prices pay back sooner
    # a cheap battery is already paid back; no battery data at all means nothing to say
    cheap = calc.storage_economics(derived, [dict(items[-2], amount=100.0)])
    assert all(sc["month"] == "2025-11" for sc in cheap["scenarios"])
    no_battery = [dict(m, battery_charged=None, battery_discharged=None) for m in months]
    assert calc.storage_economics(calc.derive_months(no_battery, tariffs, investments, "monthly"), investments) is None


def test_months():
    assert calc.month_add("2023-12", 1) == "2024-01"
    assert calc.month_add("2024-01", -1) == "2023-12"
    assert calc.billed_month("2024-01-07") == "2023-12"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
