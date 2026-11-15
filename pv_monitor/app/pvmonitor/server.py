"""HTTP API and static frontend. Runs behind Home Assistant ingress."""

from __future__ import annotations

import json
import os
import re
import time
from contextlib import closing
from datetime import date, datetime
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import calc, db, ha, plant

STATIC = Path(__file__).parent / "static"
INGRESS_PROXY = "172.30.32.2"
MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
DATE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")
MODES = (calc.MODE_MONTHLY, calc.MODE_DAILY)
DEFAULT_MODE = calc.MODE_DAILY


class Invalid(ValueError):
    pass


def _today() -> str:
    """Today as YYYY-MM-DD; PVMON_TODAY pins it for tests."""
    return os.environ.get("PVMON_TODAY") or date.today().isoformat()


def db_path() -> str:
    return os.environ.get("PVMON_DB", "/data/pvmonitor.sqlite")


class IngressOnly(BaseHTTPMiddleware):
    """Inside the add-on only the supervisor's ingress proxy may connect."""

    async def dispatch(self, request, call_next):
        if os.environ.get("SUPERVISOR_TOKEN") and (
            request.client is None or request.client.host != INGRESS_PROXY
        ):
            return PlainTextResponse("Forbidden", status_code=403)
        return await call_next(request)


def _number(data, key, required=False):
    value = data.get(key)
    if value in (None, ""):
        if required:
            raise Invalid(f"„{key}“ fehlt")
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Invalid(f"„{key}“ muss eine Zahl sein")
    return float(value)


def _date(data, key, required=False):
    value = data.get(key)
    if value in (None, ""):
        if required:
            raise Invalid(f"„{key}“ fehlt")
        return None
    if not isinstance(value, str) or not DATE.match(value):
        raise Invalid(f"„{key}“ muss ein Datum JJJJ-MM-TT sein")
    return value


def _text(data, key, required=False):
    value = data.get(key)
    if value in (None, ""):
        if required:
            raise Invalid(f"„{key}“ fehlt")
        return None
    if not isinstance(value, str):
        raise Invalid(f"„{key}“ muss Text sein")
    return value.strip()[:500]


def clean_investment(data):
    return {
        "date": _date(data, "date"),
        "quantity": _number(data, "quantity"),
        "label": _text(data, "label", required=True),
        "amount": _number(data, "amount", required=True),
        "category": _text(data, "category"),
    }


def clean_tariff(data):
    kind = data.get("kind") or calc.GRID
    if kind not in (calc.GRID, calc.HEAT, calc.FEED_IN):
        raise Invalid("unbekannte Tarifart")
    valid_from = _date(data, "valid_from", required=True)
    price = _number(data, "energy_price", required=True)
    if price < 0:
        raise Invalid("der Arbeitspreis darf nicht negativ sein")
    return {
        "kind": kind,
        "valid_from": valid_from[:7] + "-01",
        "starts_on": _date(data, "starts_on"),
        "energy_price": price,
        "base_price_year": _number(data, "base_price_year"),
        "provider": _text(data, "provider"),
        "note": _text(data, "note"),
        "contract_end": _date(data, "contract_end"),
        "price_guarantee_until": _date(data, "price_guarantee_until"),
        "monthly_payment": _number(data, "monthly_payment"),
    }


def clean_month(data):
    return {
        "reading_date": _date(data, "reading_date"),
        "grid_reading": _number(data, "grid_reading", required=True),
        "feed_reading": _number(data, "feed_reading", required=True),
        "heat_reading": _number(data, "heat_reading"),
        "pv_yield": _number(data, "pv_yield", required=True),
        "battery_charged": _number(data, "battery_charged"),
        "battery_discharged": _number(data, "battery_discharged"),
    }


def build_state(con, candidate=None):
    """Everything the frontend shows, freshly derived.

    ``candidate`` is an unsaved month laid over the stored ones, so an entry
    can be checked before it is written.
    """
    months = db.month_rows(con)
    if candidate is not None:
        months = [m for m in months if m["month"] != candidate["month"]] + [candidate]
    tariffs = db.rows(con, "SELECT * FROM tariffs ORDER BY kind, valid_from")
    investments = db.rows(con, "SELECT * FROM investments ORDER BY date IS NULL, date, id")
    mode = db.get_setting(con, "tariff_mode", DEFAULT_MODE)
    derived = calc.derive_months(months, tariffs, investments, mode)
    summary = calc.summarize(derived, investments)
    last = derived[-1]["month"] if derived else None
    return {
        "settings": {"tariff_mode": mode},
        "investments": investments,
        "tariffs": tariffs,
        "meters": db.rows(con, "SELECT * FROM meters ORDER BY id"),
        "months": derived,
        "summary": summary,
        "next_month": calc.month_add(last, 1) if last else calc.month_add(calc.today_month(), -1),
        "forecast": calc.forecast_billing(derived, tariffs, _today()),
        "checks": calc.check_month(derived, summary["last_month"]) if summary["last_month"] else [],
    }


def _json_error(message, status=400):
    return JSONResponse({"error": message}, status_code=status)


def endpoint(fn):
    """Open a connection, run ``fn(con, request, body)``, return the fresh state."""

    async def handler(request):
        body = None
        if request.method in ("POST", "PUT"):
            try:
                body = await request.json()
            except ValueError:
                return _json_error("ungültiges JSON")
            if not isinstance(body, dict):
                return _json_error("ein JSON-Objekt wird erwartet")
        with closing(db.connect(db_path())) as con:
            try:
                result = fn(con, request, body)
            except Invalid as exc:
                return _json_error(str(exc))
            except LookupError:
                return _json_error("nicht gefunden", 404)
            con.commit()
            return JSONResponse(result if result is not None else build_state(con))

    return handler


def get_state(con, request, body):
    return build_state(con)


def create_investment(con, request, body):
    db.insert(con, "investments", db.INVESTMENT_FIELDS, clean_investment(body))


def update_investment(con, request, body):
    if not db.update(
        con, "investments", db.INVESTMENT_FIELDS, request.path_params["id"], clean_investment(body)
    ):
        raise LookupError


def create_tariff(con, request, body):
    db.insert(con, "tariffs", db.TARIFF_FIELDS, clean_tariff(body))


def update_tariff(con, request, body):
    if not db.update(con, "tariffs", db.TARIFF_FIELDS, request.path_params["id"], clean_tariff(body)):
        raise LookupError


def delete_row(table):
    def fn(con, request, body):
        cur = con.execute(f"DELETE FROM {table} WHERE id = ?", (request.path_params["id"],))
        if cur.rowcount == 0:
            raise LookupError

    return fn


def _month_param(request):
    month = request.path_params["month"]
    if not MONTH.match(month):
        raise Invalid("Monat muss JJJJ-MM sein")
    return month


def save_month(con, request, body):
    db.save_month(con, _month_param(request), clean_month(body))


def check_month(con, request, body):
    """Plausibility of an entry that is not saved yet."""
    month = _month_param(request)
    candidate = dict(clean_month(body), month=month)
    state = build_state(con, candidate)
    row = next(m for m in state["months"] if m["month"] == month)
    con.rollback()
    return {"month": row, "checks": calc.check_month(state["months"], month)}


def delete_month(con, request, body):
    db.delete_month(con, _month_param(request))


def save_settings(con, request, body):
    mode = body.get("tariff_mode")
    if mode not in MODES:
        raise Invalid("unbekannter Tarifmodus")
    db.set_setting(con, "tariff_mode", mode)


def compare_tariff(con, request, body):
    price = _number(body, "energy_price", required=True)
    base = _number(body, "base_price_year", required=True)
    state = build_state(con)
    result = calc.compare_tariff(state["months"], price, base)
    current = [t for t in state["tariffs"] if t["kind"] == calc.GRID]
    upcoming = (state["forecast"] or {}).get("next")
    if upcoming:
        # the same expected draw, priced with the tariff that is being considered
        cost = upcoming["kwh"] * price + base
        result["next_period"] = {
            "start": upcoming["start"],
            "end": upcoming["end"],
            "kwh": upcoming["kwh"],
            "cost": cost,
            "recommended_payment": cost / 12,
        }
    result["break_even_kwh"] = None
    if current and current[-1].get("base_price_year") is not None:
        result["break_even_kwh"] = calc.tariff_break_even_kwh(
            current[-1]["energy_price"], current[-1]["base_price_year"], price, base
        )
        result["current"] = current[-1]
    return result


def load_layout(con):
    raw = db.get_setting(con, "plant_layout")
    if not raw:
        return dict(plant.EMPTY)
    try:
        return plant.validate_layout(json.loads(raw))
    except (ValueError, plant.Invalid):
        return dict(plant.EMPTY)


def _layout():
    with closing(db.connect(db_path())) as con:
        return load_layout(con)


async def get_layout(request):
    return JSONResponse({"layout": _layout(), "ha": ha.available()})


async def put_layout(request):
    try:
        layout = plant.validate_layout(await request.json())
    except ValueError as exc:  # plant.Invalid and malformed JSON
        return _json_error(str(exc) if isinstance(exc, plant.Invalid) else "ungültiges JSON")
    with closing(db.connect(db_path())) as con:
        db.set_setting(con, "plant_layout", json.dumps(layout))
        con.commit()
    return JSONResponse({"layout": layout, "ha": ha.available()})


def ha_endpoint(fn):
    """Run ``fn(request)`` and turn Home Assistant failures into a 502."""

    async def handler(request):
        try:
            return JSONResponse(await fn(request))
        except ha.HaError as exc:
            return _json_error(str(exc), 502)
        except plant.Invalid as exc:
            return _json_error(str(exc))

    return handler


async def plant_entities(request):
    return {"entities": await ha.entities()}


async def plant_live(request):
    layout = _layout()
    values = await ha.states(plant.entities(layout, plant.LIVE))
    # An inverter asleep at night reports "unavailable". After sunset that is
    # 0 W; by day a missing value stays missing, because then it is a fault.
    night = any(values.get(s["power_entity"]) is None for s in layout["strings"] if s["power_entity"]) and await ha.sun_is_down()
    if night:
        for s in layout["strings"]:
            if s["power_entity"] and values.get(s["power_entity"]) is None:
                values[s["power_entity"]] = 0.0
    result = plant.compose(layout, values, plant.LIVE)
    result["night"] = night
    today, tomorrow = (layout.get(key) for key in plant.FORECAST_KEYS)
    if today or tomorrow:
        result["forecast"] = {
            "today": values.get(today) if today else None,
            "tomorrow": values.get(tomorrow) if tomorrow else None,
            "so_far": await _yield_today(layout),
        }
    return result


_yield_cache = {}  # sources -> (monotonic time, kWh); the page polls every few seconds


async def _yield_today(layout):
    """Energy produced since local midnight, from the 5-minute statistics."""
    sources = tuple(plant.month_sources(layout)["pv_yield"])
    if not sources:
        return None
    cached = _yield_cache.get(sources)
    if cached and time.monotonic() - cached[0] < 60:
        return cached[1]
    tz = await ha.time_zone()
    start, _ = plant.period_range("day", datetime.now(plant.zone(tz)).strftime("%Y-%m-%d"), tz)
    rows = await ha.statistics(sources, start.isoformat(), datetime.now(start.tzinfo).isoformat(), "5minute")
    parts = [ha.row_energy_kwh(r) for e in sources for r in rows.get(e, [])]
    parts = [p for p in parts if p is not None]
    if not rows:
        value = 0.0  # early in the day there is no row yet: nothing produced, not unknown
    elif all(rows.get(e) for e in sources):
        value = round(sum(parts), 2)
    else:
        value = None  # one source is missing: no figure rather than one that is too small
    _yield_cache[sources] = (time.monotonic(), value)
    return value


async def plant_history(request):
    """Energy per element for a day, month or year from the long-term statistics."""
    period = request.query_params.get("period", "day")
    day = request.query_params.get("date", "")
    layout = _layout()
    start, end = plant.period_range(period, day, await ha.time_zone())
    ids = plant.entities(layout, plant.ENERGY)
    rows = await ha.statistics(ids, start.isoformat(), end.isoformat(), plant.PERIODS[period])
    values, buckets = {}, {}
    for entity, entity_rows in rows.items():
        total = None
        for row in entity_rows:
            energy = ha.row_energy_kwh(row)
            if energy is None:
                continue
            total = (total or 0.0) + energy
            buckets.setdefault(row["start"], {})[entity] = energy
        values[entity] = total
    result = plant.compose(layout, values, plant.ENERGY)
    result.update(period=period, start=start.isoformat(), end=end.isoformat())
    # the same picture per statistics bucket, for the time slider and the curves
    result["steps"] = [
        {
            "start": start_ms,
            "strings": {
                s["id"]: s["value"]
                for s in plant.compose(layout, buckets[start_ms], plant.ENERGY)["strings"]
            },
        }
        for start_ms in sorted(buckets)
    ]
    return result


async def month_suggest(request):
    """PV yield and battery throughput of a month from the long-term statistics."""
    month = request.path_params["month"]
    if not MONTH.match(month):
        raise plant.Invalid("Monat muss JJJJ-MM sein")
    sources = plant.month_sources(_layout())
    ids = {e for entities in sources.values() for e in entities}
    values = dict.fromkeys(sources)
    if not ids:
        return {"month": month, "values": values, "complete": False}
    start, end = plant.period_range("month", f"{month}-01", await ha.time_zone())
    rows = await ha.statistics(ids, start.isoformat(), end.isoformat(), "day")
    for key, entities in sources.items():
        parts = [ha.row_energy_kwh(r) for e in entities for r in rows.get(e, [])]
        parts = [p for p in parts if p is not None]
        # every source must have delivered, or the sum would silently be too small
        if entities and parts and all(rows.get(e) for e in entities):
            values[key] = round(sum(parts), 1)
    return {"month": month, "values": values, "complete": end.isoformat() <= datetime.now(start.tzinfo).isoformat()}


routes = [
    Route("/api/months/{month}/suggest", ha_endpoint(month_suggest)),
    Route("/api/plant/layout", get_layout),
    Route("/api/plant/layout", put_layout, methods=["PUT"]),
    Route("/api/plant/entities", ha_endpoint(plant_entities)),
    Route("/api/plant/live", ha_endpoint(plant_live)),
    Route("/api/plant/history", ha_endpoint(plant_history)),
    Route("/api/state", endpoint(get_state)),
    Route("/api/investments", endpoint(create_investment), methods=["POST"]),
    Route("/api/investments/{id:int}", endpoint(update_investment), methods=["PUT"]),
    Route("/api/investments/{id:int}", endpoint(delete_row("investments")), methods=["DELETE"]),
    Route("/api/tariffs", endpoint(create_tariff), methods=["POST"]),
    Route("/api/tariffs/{id:int}", endpoint(update_tariff), methods=["PUT"]),
    Route("/api/tariffs/{id:int}", endpoint(delete_row("tariffs")), methods=["DELETE"]),
    Route("/api/tariffs/compare", endpoint(compare_tariff), methods=["POST"]),
    Route("/api/months/{month}", endpoint(save_month), methods=["PUT"]),
    Route("/api/months/{month}", endpoint(delete_month), methods=["DELETE"]),
    Route("/api/months/{month}/check", endpoint(check_month), methods=["POST"]),
    Route("/api/settings", endpoint(save_settings), methods=["PUT"]),
    Mount("/", StaticFiles(directory=STATIC, html=True)),
]

app = Starlette(routes=routes, middleware=[Middleware(IngressOnly)])
