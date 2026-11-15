"""Pure calculation core.

Everything in here is derived, never stored: it can be recomputed at any time
from readings, monthly values, tariffs and investments. The formulas follow the
workbook this application replaces (sheet ``Verbrauch_Ertrag``).

Months are ``"YYYY-MM"`` strings, dates are ``"YYYY-MM-DD"`` strings.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

GRID = "grid"
HEAT = "heat"
FEED_IN = "feed_in"

MODE_MONTHLY = "monthly"
MODE_DAILY = "daily"


def month_add(month: str, n: int) -> str:
    y, m = int(month[:4]), int(month[5:7])
    idx = y * 12 + (m - 1) + n
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def billed_month(reading_date: str) -> str:
    """A reading taken in month N settles month N-1."""
    return month_add(reading_date[:7], -1)


def _month_days(month: str) -> list[str]:
    y, m = int(month[:4]), int(month[5:7])
    return [f"{month}-{d:02d}" for d in range(1, calendar.monthrange(y, m)[1] + 1)]


def _latest(tariffs, kind, field, day, start_key):
    best = None
    for t in tariffs:
        if t["kind"] != kind or t.get(field) is None:
            continue
        start = start_key(t)
        if start <= day and (best is None or start >= start_key(best)):
            best = t
    return None if best is None else best[field]


def tariff_value(tariffs, kind: str, field: str, month: str, mode: str):
    """Value of ``field`` (energy_price or base_price_year) valid in ``month``.

    monthly: the latest tariff whose billing month has begun, as the workbook
    does. daily: weighted by the days each tariff was really in force, using
    ``starts_on`` where the real contract date is known.
    """
    if mode != MODE_DAILY:
        return _latest(tariffs, kind, field, f"{month}-01", lambda t: t["valid_from"])
    values = [
        _latest(tariffs, kind, field, day, lambda t: t.get("starts_on") or t["valid_from"])
        for day in _month_days(month)
    ]
    known = [v for v in values if v is not None]
    if not known:
        return None
    return sum(known) / len(known)


def _diff(cur, prev):
    if cur is None or prev is None:
        return 0.0
    return cur - prev


def _ratio(a, b):
    if a is None or not b:
        return None
    return a / b


def invested_until(investments, month: str) -> float:
    """Investment in force at the end of ``month``; undated items always count."""
    last_day = _month_days(month)[-1]
    return sum(i["amount"] for i in investments if not i.get("date") or i["date"] <= last_day)


def derive_months(months, tariffs, investments, mode: str = MODE_MONTHLY):
    """Derive all per-month figures.

    ``months`` is a list of dicts with ``month``, ``reading_date``,
    ``grid_reading``, ``feed_reading``, ``heat_reading``, ``pv_yield``,
    ``battery_charged``, ``battery_discharged``. The first entry is the
    baseline: it only anchors the meter differences.
    """
    rows = sorted(months, key=lambda r: r["month"])
    out = []
    cum = 0.0
    prev = None
    for row in rows:
        month = row["month"]
        baseline = prev is None
        grid = 0.0 if baseline else _diff(row.get("grid_reading"), prev.get("grid_reading"))
        heat = 0.0 if baseline else _diff(row.get("heat_reading"), prev.get("heat_reading"))
        feed = 0.0 if baseline else _diff(row.get("feed_reading"), prev.get("feed_reading"))
        pv = row.get("pv_yield") or 0.0
        self_use = pv - feed
        total = self_use + heat + grid
        charged = row.get("battery_charged")
        discharged = row.get("battery_discharged")

        price = tariff_value(tariffs, GRID, "energy_price", month, mode)
        heat_price = tariff_value(tariffs, HEAT, "energy_price", month, mode)
        feed_price = tariff_value(tariffs, FEED_IN, "energy_price", month, mode)
        base_year = tariff_value(tariffs, GRID, "base_price_year", month, mode)
        base_month = None if base_year is None else base_year / 12

        cost_grid = (price or 0.0) * grid
        cost_heat = (heat_price or 0.0) * heat
        cost_energy = cost_grid + cost_heat if (cost_grid or cost_heat) else None
        if cost_energy is None and base_month is None:
            cost_total = None
        else:
            cost_total = (cost_energy or 0.0) + (base_month or 0.0)
        drawn = grid + heat

        feed_revenue = (feed_price or 0.0) * feed
        saving = (price or 0.0) * self_use
        revenue = saving + feed_revenue
        cum += revenue
        invested = invested_until(investments, month)

        out.append(
            {
                "month": month,
                "reading_date": row.get("reading_date"),
                "baseline": baseline,
                "grid_reading": row.get("grid_reading"),
                "feed_reading": row.get("feed_reading"),
                "heat_reading": row.get("heat_reading"),
                "grid_kwh": grid,
                "heat_kwh": heat,
                "feed_kwh": feed,
                "pv_yield": pv,
                "self_use": self_use,
                "battery_charged": charged,
                "battery_discharged": discharged,
                "battery_efficiency": _ratio(discharged, charged),
                "total_consumption": total,
                "autarky": _ratio(self_use, total),
                "own_consumption_quota": _ratio(self_use, pv),
                "price": price,
                "heat_price": heat_price,
                "feed_price": feed_price,
                "cost_energy": cost_energy,
                "base_month": base_month,
                "cost_total": cost_total,
                "effective_price": None if cost_total is None or not drawn else cost_total / drawn,
                "feed_revenue": feed_revenue,
                "saving": saving,
                "battery_saving": (price or 0.0) * (discharged or 0.0),
                "revenue": revenue,
                "revenue_cum": cum,
                "invested": invested,
                "amortisation": _ratio(cum, invested),
            }
        )
        prev = row

    for i, d in enumerate(out):
        window = [w for w in out[max(0, i - 11) : i + 1] if not w["baseline"]]
        d["rolling12_autarky"] = _ratio(
            sum(w["self_use"] for w in window), sum(w["total_consumption"] for w in window)
        )
        d["rolling12_quota"] = _ratio(
            sum(w["self_use"] for w in window), sum(w["pv_yield"] for w in window)
        )
    return out


def project_break_even(derived, invest_total: float, max_years: int = 60):
    """Month in which cumulated revenue reaches the investment.

    Seasonal, not linear: every future month earns what the most recent
    same calendar month really earned.
    """
    real = [d for d in derived if not d["baseline"]]
    if not real:
        return None
    cum = real[-1]["revenue_cum"]
    for d in real:
        if d["revenue_cum"] >= invest_total:
            return {"month": d["month"], "reached": True, "curve": []}
    profile = {}
    for d in real[-12:]:
        profile[d["month"][5:7]] = d["revenue"]
    if sum(profile.values()) <= 0:
        return None
    month = real[-1]["month"]
    curve = []
    for _ in range(max_years * 12):
        month = month_add(month, 1)
        gain = profile.get(month[5:7])
        if gain is None:
            gain = sum(profile.values()) / len(profile)
        cum += gain
        curve.append({"month": month, "revenue_cum": cum})
        if cum >= invest_total:
            return {"month": month, "reached": False, "curve": curve}
    return None


def summarize(derived, investments):
    real = [d for d in derived if not d["baseline"]]
    invest_total = sum(i["amount"] for i in investments)
    revenue_total = real[-1]["revenue_cum"] if real else 0.0
    positive = [d["revenue"] / invest_total for d in real if invest_total and d["revenue"] > 0]
    mean_roi_month = sum(positive) / len(positive) if positive else None
    last12 = real[-12:]
    cost12 = [d["cost_total"] for d in last12 if d["cost_total"] is not None]
    return {
        "invest_total": invest_total,
        "revenue_total": revenue_total,
        "remaining": invest_total - revenue_total,
        "amortisation": _ratio(revenue_total, invest_total),
        "mean_roi_month": mean_roi_month,
        "mean_roi_year": None if mean_roi_month is None else mean_roi_month * 12,
        "years_to_roi_linear": None if not mean_roi_month else 1 / (mean_roi_month * 12),
        "break_even": project_break_even(derived, invest_total),
        "last_month": real[-1]["month"] if real else None,
        "rolling12": {
            "months": len(last12),
            "pv_yield": sum(d["pv_yield"] for d in last12),
            "grid_kwh": sum(d["grid_kwh"] for d in last12),
            "feed_kwh": sum(d["feed_kwh"] for d in last12),
            "self_use": sum(d["self_use"] for d in last12),
            "revenue": sum(d["revenue"] for d in last12),
            "cost_total": sum(cost12) if cost12 else None,
            "autarky": real[-1]["rolling12_autarky"] if real else None,
            "own_consumption_quota": real[-1]["rolling12_quota"] if real else None,
        },
    }


def compare_tariff(derived, energy_price: float, base_price_year: float, months: int = 12):
    """What an alternative tariff would have cost for the real grid draw."""
    window = [d for d in derived if not d["baseline"]][-months:]
    kwh = sum(d["grid_kwh"] for d in window)
    actual = [d for d in window if d["cost_total"] is not None]
    alternative = kwh * energy_price + base_price_year / 12 * len(window)
    actual_cost = sum(
        (d["price"] or 0.0) * d["grid_kwh"] + (d["base_month"] or 0.0) for d in actual
    )
    return {
        "months": len(window),
        "grid_kwh": kwh,
        "actual_cost": actual_cost if len(actual) == len(window) else None,
        "alternative_cost": alternative,
    }


def tariff_break_even_kwh(price_a, base_a, price_b, base_b):
    """Yearly draw at which two tariffs cost the same; None if they never cross."""
    if price_a == price_b:
        return None
    kwh = (base_b - base_a) / (price_a - price_b)
    return kwh if kwh > 0 else None


def check_month(derived, month: str):
    """Plausibility rules from the workbook's input sheet for one month."""
    by_month = {d["month"]: d for d in derived}
    d = by_month.get(month)
    if d is None:
        return []
    idx = derived.index(d)
    prev = derived[idx - 1] if idx > 0 else None
    checks = []

    def add(rule, ok, message=None):
        checks.append({"rule": rule, "ok": ok, "message": message})

    def forward(key, rule):
        cur = d.get(key)
        before = prev.get(key) if prev else None
        if cur is None or before is None:
            add(rule, None, "kein Vergleichswert")
        elif cur >= before:
            add(rule, True)
        else:
            add(rule, False, f"{cur:g} ist kleiner als im Vormonat ({before:g})")

    forward("grid_reading", "Zählerstand Hausstrom läuft vorwärts")
    forward("feed_reading", "Zählerstand Einspeisung läuft vorwärts")

    if d["self_use"] >= 0:
        add("Einspeisung passt in den Ertrag", True)
    else:
        add(
            "Einspeisung passt in den Ertrag",
            False,
            f"{d['feed_kwh']:g} kWh eingespeist, aber nur {d['pv_yield']:g} kWh erzeugt",
        )

    charged, discharged = d["battery_charged"], d["battery_discharged"]
    if charged is None or discharged is None:
        add("Batterie: entladen ≤ geladen", None, "keine Batteriewerte")
        add("Batteriewirkungsgrad 70–100 %", None, "keine Batteriewerte")
    else:
        add(
            "Batterie: entladen ≤ geladen",
            discharged <= charged,
            None if discharged <= charged else "mehr entladen als geladen",
        )
        if charged < 10:
            add("Batteriewirkungsgrad 70–100 %", None, "zu wenig Durchsatz")
        else:
            eff = discharged / charged
            ok = 0.7 <= eff <= 1
            add("Batteriewirkungsgrad 70–100 %", ok, None if ok else f"{eff * 100:.0f} %")

    last_year = by_month.get(month_add(month, -12))
    if last_year is None or last_year["baseline"] or not last_year["pv_yield"]:
        add("PV-Ertrag gegen Vorjahresmonat", None, "kein Vorjahreswert")
    else:
        dev = d["pv_yield"] / last_year["pv_yield"] - 1
        ok = abs(dev) <= 0.5
        add(
            "PV-Ertrag gegen Vorjahresmonat",
            ok,
            None
            if ok
            else f"{d['pv_yield']:g} kWh gegen {last_year['pv_yield']:g} kWh im Vorjahr ({dev * 100:+.0f} %)",
        )

    autarky = d["autarky"]
    if autarky is None:
        add("Autarkiegrad zwischen 0 und 100 %", None, "kein Verbrauch")
    else:
        ok = 0 <= autarky <= 1
        add("Autarkiegrad zwischen 0 und 100 %", ok, None if ok else f"{autarky * 100:.0f} %")

    add(
        "Strompreis hinterlegt",
        bool(d["price"]),
        None if d["price"] else "für diesen Monat gilt kein Tarif",
    )
    return checks


def _add_year(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:  # 29 February
        return d.replace(year=d.year + 1, day=28)


def _period_months(start: date, end: date):
    """(month, share of that month inside the period) for start..end inclusive."""
    out = []
    cur = start.replace(day=1)
    while cur <= end:
        days = calendar.monthrange(cur.year, cur.month)[1]
        lo, hi = max(start, cur), min(end, cur.replace(day=days))
        out.append((cur.strftime("%Y-%m"), ((hi - lo).days + 1) / days))
        cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def _expected_grid(real, month: str):
    """Expected grid draw of a month without data: what the most recent same
    calendar month drew, with the span of the last two as (kwh, low, high)."""
    same = [d["grid_kwh"] for d in real if d["month"][5:7] == month[5:7]]
    if not same:
        if not real:
            return None
        mean = sum(d["grid_kwh"] for d in real[-12:]) / len(real[-12:])
        return mean, mean, mean
    return same[-1], min(same[-2:]), max(same[-2:])


def _forecast_period(real, start: date, end: date, price: float, base_year):
    by_month = {d["month"]: d for d in real}
    rows = []
    for month, share in _period_months(start, end):
        actual = by_month.get(month)
        if actual is not None:
            kwh = low = high = actual["grid_kwh"] * share
        else:
            expected = _expected_grid(real, month)
            if expected is None:
                return None
            kwh, low, high = (v * share for v in expected)
        rows.append({"month": month, "share": share, "actual": actual is not None, "kwh": kwh, "low": low, "high": high})
    months = sum(r["share"] for r in rows)
    base = (base_year or 0.0) * months / 12

    def cost(key, only=None):
        return sum(r[key] for r in rows if only is None or r["actual"] == only) * price

    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "months": months,
        "rows": rows,
        "kwh": sum(r["kwh"] for r in rows),
        "kwh_low": sum(r["low"] for r in rows),
        "kwh_high": sum(r["high"] for r in rows),
        "kwh_so_far": sum(r["kwh"] for r in rows if r["actual"]),
        "cost_energy": cost("kwh"),
        "cost_base": base,
        "cost": cost("kwh") + base,
        "cost_low": cost("low") + base,
        "cost_high": cost("high") + base,
        "cost_so_far": cost("kwh", True) + (base_year or 0.0) * sum(r["share"] for r in rows if r["actual"]) / 12,
    }


def forecast_billing(derived, tariffs, today: str):
    """The running billing period of the current grid tariff and the next one.

    Months with readings count as they were; the rest is filled with the draw
    of the most recent same calendar month. The period runs from the tariff's
    real start to its contract end, the next tariff, or one year.
    """
    real = [d for d in derived if not d["baseline"]]
    start_of = lambda t: t.get("starts_on") or t["valid_from"]  # noqa: E731
    grid = sorted((t for t in tariffs if t["kind"] == GRID), key=start_of)
    running = [t for t in grid if start_of(t) <= today]
    if not running or not real:
        return None
    tariff = running[-1]
    start = date.fromisoformat(start_of(tariff))
    later = [t for t in grid if start_of(t) > start_of(tariff)]
    if later:
        end = date.fromisoformat(start_of(later[0])) - timedelta(days=1)
    elif tariff.get("contract_end"):
        end = date.fromisoformat(tariff["contract_end"])
    else:
        end = _add_year(start) - timedelta(days=1)
    if end < start:
        return None
    current = _forecast_period(real, start, end, tariff["energy_price"], tariff.get("base_price_year"))
    if current is None:
        return None
    payment = tariff.get("monthly_payment")
    count = max(1, round(current["months"]))
    current.update(
        tariff=tariff,
        payment_count=count,
        monthly_payment=payment,
        payments_total=None if payment is None else payment * count,
        # positive: money back, negative: additional payment
        balance=None if payment is None else payment * count - current["cost"],
        recommended_payment=current["cost"] / count,
    )
    next_start = end + timedelta(days=1)
    next_tariff = later[0] if later else tariff
    upcoming = _forecast_period(
        real, next_start, _add_year(next_start) - timedelta(days=1),
        next_tariff["energy_price"], next_tariff.get("base_price_year"),
    )
    upcoming.update(tariff=next_tariff, tariff_known=bool(later), recommended_payment=upcoming["cost"] / 12)
    return {"current": current, "next": upcoming}


def today_month() -> str:
    return date.today().strftime("%Y-%m")
