"""Read-only Home Assistant client: current states and long-term statistics.

Inside the add-on the supervisor proxy and its token are used. For development
set PVMON_HA_URL and PVMON_HA_TOKEN instead.
"""

from __future__ import annotations

import asyncio
import os

import aiohttp

POWER_FACTORS = {"W": 1.0, "kW": 1000.0, "MW": 1_000_000.0}
ENERGY_FACTORS = {"Wh": 0.001, "kWh": 1.0, "MWh": 1000.0}
PICKER_UNITS = set(POWER_FACTORS) | set(ENERGY_FACTORS) | {"%"}
TIMEOUT = aiohttp.ClientTimeout(total=20)


class HaError(RuntimeError):
    """Home Assistant is not reachable or refused the request."""


def _endpoints():
    token = os.environ.get("SUPERVISOR_TOKEN")
    if token:
        return "http://supervisor/core/api", "ws://supervisor/core/websocket", token
    url = (os.environ.get("PVMON_HA_URL") or "").rstrip("/")
    token = os.environ.get("PVMON_HA_TOKEN")
    if url and token:
        return f"{url}/api", url.replace("http", "ws", 1) + "/api/websocket", token
    return None


def available() -> bool:
    return _endpoints() is not None


def _normalize(state):
    """A state as a number in W, kWh or %, or None when it is not a number."""
    unit = (state.get("attributes") or {}).get("unit_of_measurement")
    try:
        value = float(state.get("state"))
    except (TypeError, ValueError):
        return None, unit
    if value != value or value in (float("inf"), float("-inf")):
        return None, unit
    if unit in POWER_FACTORS:
        return value * POWER_FACTORS[unit], "W"
    if unit in ENERGY_FACTORS:
        return value * ENERGY_FACTORS[unit], "kWh"
    return value, unit


async def _get(session, base, path):
    try:
        async with session.get(f"{base}{path}") as resp:
            if resp.status == 404:
                return None
            if resp.status >= 400:
                raise HaError(f"Home Assistant antwortet mit {resp.status}")
            return await resp.json()
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        raise HaError("Home Assistant ist nicht erreichbar") from exc


def _session(token):
    return aiohttp.ClientSession(
        headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT
    )


def _require():
    endpoints = _endpoints()
    if endpoints is None:
        raise HaError("Keine Verbindung zu Home Assistant eingerichtet")
    return endpoints


async def states(entity_ids):
    """Current value per entity; an unknown or non-numeric entity is None."""
    base, _, token = _require()
    ids = sorted(set(entity_ids))
    async with _session(token) as session:
        raw = await asyncio.gather(*(_get(session, base, f"/states/{e}") for e in ids))
    out = {}
    for entity_id, state in zip(ids, raw):
        out[entity_id] = None if state is None else _normalize(state)[0]
    return out


async def entities():
    """Sensors that can be picked: power, energy and percentage."""
    base, _, token = _require()
    async with _session(token) as session:
        raw = await _get(session, base, "/states") or []
    out = []
    for state in raw:
        entity_id = state.get("entity_id", "")
        attrs = state.get("attributes") or {}
        unit = attrs.get("unit_of_measurement")
        if entity_id.startswith("sensor.") and unit in PICKER_UNITS:
            out.append(
                {"entity_id": entity_id, "name": attrs.get("friendly_name") or entity_id, "unit": unit}
            )
    return sorted(out, key=lambda e: e["entity_id"])


async def time_zone() -> str:
    base, _, token = _require()
    async with _session(token) as session:
        config = await _get(session, base, "/config") or {}
    return config.get("time_zone") or "UTC"


async def statistics(statistic_ids, start_iso, end_iso, period):
    """Long-term statistics rows per id, energy in kWh and power in W.

    Each row has ``start``/``end`` in epoch milliseconds and ``change`` (meters)
    or ``mean`` (measurements), whichever the statistic carries.
    """
    _, ws_url, token = _require()
    ids = sorted(set(statistic_ids))
    if not ids:
        return {}
    try:
        async with _session(token) as session:
            async with session.ws_connect(ws_url, max_msg_size=32 * 1024 * 1024) as ws:
                if (await ws.receive_json()).get("type") != "auth_required":
                    raise HaError("unerwartete Antwort von Home Assistant")
                await ws.send_json({"type": "auth", "access_token": token})
                if (await ws.receive_json()).get("type") != "auth_ok":
                    raise HaError("Home Assistant lehnt die Anmeldung ab")
                await ws.send_json(
                    {
                        "id": 1,
                        "type": "recorder/statistics_during_period",
                        "start_time": start_iso,
                        "end_time": end_iso,
                        "statistic_ids": ids,
                        "period": period,
                        "types": ["change", "mean"],
                        "units": {"energy": "kWh", "power": "W"},
                    }
                )
                while True:
                    msg = await ws.receive_json()
                    if msg.get("id") == 1 and msg.get("type") == "result":
                        break
                if not msg.get("success"):
                    detail = (msg.get("error") or {}).get("message") or "Fehler"
                    raise HaError(f"Statistik-Abfrage abgelehnt: {detail}")
                return msg.get("result") or {}
    except (aiohttp.ClientError, asyncio.TimeoutError, TypeError, ValueError) as exc:
        raise HaError("Home Assistant ist nicht erreichbar") from exc


def row_energy_kwh(row):
    """Energy of one statistics row: a meter's change, or mean power × duration."""
    change = row.get("change")
    if change is not None:
        return float(change)
    mean = row.get("mean")
    if mean is None:
        return None
    hours = (row["end"] - row["start"]) / 3_600_000
    return float(mean) * hours / 1000
