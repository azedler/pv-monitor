"""The plant picture: roof areas, strings, grid, battery and consumers.

The layout is configuration, edited in the frontend and stored as one JSON
document. ``compose`` turns a layout plus sensor values into the figures the
picture shows; it is used for live power (W) and for history (kWh) alike.
"""

from __future__ import annotations

import calendar
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ENTITY = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")
IDENT = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
KINDS = ("grid", "battery", "consumer")
EMPTY = {"areas": [], "strings": [], "devices": []}
MAX_ITEMS = 60
MAX_SIDE = 40

LIVE = "live"
ENERGY = "energy"
PERIODS = {"day": "hour", "month": "day", "year": "month"}


class Invalid(ValueError):
    pass


def _obj(value, what):
    if not isinstance(value, dict):
        raise Invalid(f"{what}: Objekt erwartet")
    return value


def _list(doc, key):
    value = doc.get(key, [])
    if not isinstance(value, list) or len(value) > MAX_ITEMS:
        raise Invalid(f"„{key}“ muss eine Liste mit höchstens {MAX_ITEMS} Einträgen sein")
    return value


def _ident(item, what):
    value = item.get("id")
    if not isinstance(value, str) or not IDENT.match(value):
        raise Invalid(f"{what}: ungültige Kennung")
    return value


def _name(item, what):
    value = item.get("name")
    if not isinstance(value, str) or not value.strip():
        raise Invalid(f"{what}: Name fehlt")
    return value.strip()[:60]


def _entity(item, key):
    value = item.get(key)
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not ENTITY.match(value.strip()):
        raise Invalid(f"„{value}“ ist keine gültige Entität")
    return value.strip()


def _number(item, key, lo, hi, integer=False):
    value = item.get(key)
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi:
        raise Invalid(f"„{key}“ muss eine Zahl zwischen {lo} und {hi} sein")
    return int(value) if integer else float(value)


def validate_layout(doc):
    """Return a cleaned layout or raise Invalid."""
    doc = _obj(doc, "Layout")
    strings, seen = [], set()
    for raw in _list(doc, "strings"):
        raw = _obj(raw, "String")
        sid = _ident(raw, "String")
        if sid in seen:
            raise Invalid("String-Kennung doppelt vergeben")
        seen.add(sid)
        strings.append(
            {
                "id": sid,
                "name": _name(raw, "String"),
                "module_watts": _number(raw, "module_watts", 1, 2000),
                "inverter": (raw.get("inverter") or "").strip()[:60] if isinstance(raw.get("inverter"), str) else "",
                "power_entity": _entity(raw, "power_entity"),
                "energy_entity": _entity(raw, "energy_entity"),
            }
        )
    areas, area_ids = [], set()
    for raw in _list(doc, "areas"):
        raw = _obj(raw, "Dachfläche")
        aid = _ident(raw, "Dachfläche")
        if aid in area_ids:
            raise Invalid("Dachflächen-Kennung doppelt vergeben")
        area_ids.add(aid)
        cols = _number(raw, "cols", 1, MAX_SIDE, integer=True)
        rows = _number(raw, "rows", 1, MAX_SIDE, integer=True)
        if cols is None or rows is None:
            raise Invalid("Dachfläche: Spalten und Reihen fehlen")
        cells = raw.get("cells")
        if not isinstance(cells, list) or len(cells) != cols * rows:
            raise Invalid("Dachfläche: Raster passt nicht zu Spalten und Reihen")
        for cell in cells:
            if cell is not None and cell not in seen:
                raise Invalid("Dachfläche: Modul gehört zu einem unbekannten String")
        areas.append(
            {
                "id": aid,
                "name": _name(raw, "Dachfläche"),
                "azimuth": _number(raw, "azimuth", 0, 360),
                "tilt": _number(raw, "tilt", 0, 90),
                "cols": cols,
                "rows": rows,
                "cells": list(cells),
            }
        )
    devices, device_ids = [], set()
    for raw in _list(doc, "devices"):
        raw = _obj(raw, "Gerät")
        did = _ident(raw, "Gerät")
        if did in device_ids:
            raise Invalid("Geräte-Kennung doppelt vergeben")
        device_ids.add(did)
        if raw.get("kind") not in KINDS:
            raise Invalid("Gerät: unbekannte Art")
        icon = raw.get("icon")
        devices.append(
            {
                "id": did,
                "kind": raw["kind"],
                "name": _name(raw, "Gerät"),
                "icon": icon[:8] if isinstance(icon, str) else "",
                "power_entity": _entity(raw, "power_entity"),
                "power_entity_2": _entity(raw, "power_entity_2"),
                "energy_entity": _entity(raw, "energy_entity"),
                "energy_entity_2": _entity(raw, "energy_entity_2"),
                "soc_entity": _entity(raw, "soc_entity"),
                "invert": bool(raw.get("invert")),
            }
        )
    for kind in ("grid", "battery"):
        if sum(1 for d in devices if d["kind"] == kind) > 1:
            raise Invalid("Netz und Batterie dürfen je nur einmal vorkommen")
    return {"areas": areas, "strings": strings, "devices": devices}


def module_counts(layout):
    counts = {s["id"]: 0 for s in layout["strings"]}
    for area in layout["areas"]:
        for cell in area["cells"]:
            if cell is not None:
                counts[cell] += 1
    return counts


def _keys(mode):
    """(primary, secondary) entity keys for the mode; history falls back to power."""
    if mode == LIVE:
        return ("power_entity",), ("power_entity_2",)
    return ("energy_entity", "power_entity"), ("energy_entity_2", "power_entity_2")


def _pick(item, keys):
    for key in keys:
        if item.get(key):
            return item[key]
    return None


def entities(layout, mode):
    """Every entity the picture needs in this mode."""
    primary, secondary = _keys(mode)
    out = set()
    for string in layout["strings"]:
        out.add(_pick(string, primary))
    for dev in layout["devices"]:
        out.add(_pick(dev, primary))
        if dev["kind"] != "consumer":
            out.add(_pick(dev, secondary))
        if mode == LIVE:
            out.add(dev.get("soc_entity"))
    out.discard(None)
    return out


def _two_way(device, values, mode):
    """(in, out) for grid (import, export) and battery (charge, discharge)."""
    primary, secondary = _keys(mode)
    first, second = _pick(device, primary), _pick(device, secondary)
    a = values.get(first) if first else None
    b = values.get(second) if second else None
    if second:
        return (None if a is None else abs(a)), (None if b is None else abs(b))
    if a is None:
        return None, None
    if mode == ENERGY and device.get("energy_entity"):
        return abs(a), None  # a meter counts one direction only
    if device["invert"]:
        a = -a
    return max(a, 0.0), max(-a, 0.0)


def _sum(parts):
    known = [p for p in parts if p is not None]
    return sum(known) if known else None


def compose(layout, values, mode):
    """The picture's figures: W in live mode, kWh in history."""
    primary, _ = _keys(mode)
    counts = module_counts(layout)
    strings = []
    for s in layout["strings"]:
        entity = _pick(s, primary)
        value = values.get(entity) if entity else None
        kwp = counts[s["id"]] * s["module_watts"] / 1000 if s["module_watts"] else None
        strings.append(
            {
                "id": s["id"],
                "name": s["name"],
                "modules": counts[s["id"]],
                "kwp": kwp or None,
                "value": value,
                "specific": None if value is None or not kwp else value / kwp,
                "has_sensor": entity is not None,
            }
        )
    pv = _sum(s["value"] for s in strings)

    def device(kind):
        return next((d for d in layout["devices"] if d["kind"] == kind), None)

    def two_way(dev):
        if dev is None:
            return None
        a, b = _two_way(dev, values, mode)
        net = None if a is None and b is None else (a or 0.0) - (b or 0.0)
        return {"id": dev["id"], "name": dev["name"], "in": a, "out": b, "net": net}

    grid = two_way(device("grid"))
    battery = two_way(device("battery"))
    if battery is not None and mode == LIVE:
        soc_entity = device("battery").get("soc_entity")
        battery["soc"] = values.get(soc_entity) if soc_entity else None

    house = None
    if pv is not None and grid is not None and grid["net"] is not None:
        house = pv + grid["net"] - ((battery or {}).get("net") or 0.0)
    consumers = []
    for dev in layout["devices"]:
        if dev["kind"] != "consumer":
            continue
        entity = _pick(dev, primary)
        value = values.get(entity) if entity else None
        consumers.append(
            {"id": dev["id"], "name": dev["name"], "icon": dev["icon"], "value": None if value is None else abs(value)}
        )
    known = _sum(c["value"] for c in consumers)
    other = None if house is None else max(house - (known or 0.0), 0.0)
    return {
        "mode": mode,
        "strings": strings,
        "pv": pv,
        "grid": grid,
        "battery": battery,
        "house": house,
        "consumers": consumers,
        "other": other if consumers else None,
    }


def period_range(period: str, day: str, tz_name: str):
    """(start, end, label) of the day, month or year containing ``day``."""
    if period not in PERIODS:
        raise Invalid("Zeitraum muss day, month oder year sein")
    try:
        d = datetime.strptime(day, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise Invalid("Datum muss JJJJ-MM-TT sein") from None
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("UTC")
    if period == "day":
        start = d
        end = d + timedelta(days=1)
    elif period == "month":
        start = d.replace(day=1)
        end = start + timedelta(days=calendar.monthrange(d.year, d.month)[1])
    else:
        start = d.replace(month=1, day=1)
        end = start.replace(year=start.year + 1)
    return start.replace(tzinfo=tz), end.replace(tzinfo=tz)


def shift(period: str, day: str, step: int) -> str:
    d = datetime.strptime(day, "%Y-%m-%d")
    if period == "day":
        d += timedelta(days=step)
    elif period == "month":
        idx = d.year * 12 + d.month - 1 + step
        d = d.replace(year=idx // 12, month=idx % 12 + 1, day=1)
    else:
        d = d.replace(year=d.year + step, month=1, day=1)
    return d.strftime("%Y-%m-%d")
