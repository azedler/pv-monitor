"""The plant picture end to end: layout, live values and history, against a
stand-in Home Assistant that speaks the real REST and websocket protocol.

Run: python3 tests/test_plant.py
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pv_monitor" / "app"))
sys.path.insert(0, str(ROOT / "tests"))

import fake_ha  # noqa: E402

PORT = 18123
os.environ["PVMON_DB"] = os.path.join(tempfile.mkdtemp(), "plant.sqlite")
os.environ.pop("SUPERVISOR_TOKEN", None)
os.environ["PVMON_HA_URL"] = f"http://127.0.0.1:{PORT}"
os.environ["PVMON_HA_TOKEN"] = fake_ha.TOKEN

from starlette.testclient import TestClient  # noqa: E402

from pvmonitor import plant  # noqa: E402
from pvmonitor.server import app  # noqa: E402

LAYOUT = {
    "strings": [
        {"id": "a", "name": "A", "module_watts": 400, "power_entity": "sensor.string_a_power", "energy_entity": "sensor.string_a_energy"},
        {"id": "b", "name": "B", "module_watts": 400, "power_entity": "sensor.string_b_power", "energy_entity": "sensor.string_b_energy"},
        {"id": "c", "name": "C", "module_watts": 400, "power_entity": "sensor.string_c_power"},
        {"id": "h1", "name": "Hut 1", "module_watts": 400, "power_entity": "sensor.hut_1_power"},
        {"id": "h2", "name": "Hut 2", "power_entity": "sensor.hut_2_power"},
    ],
    "areas": [
        {"id": "north", "name": "North", "azimuth": 333, "cols": 2, "rows": 3, "cells": ["a", "a", None, "a", "a", "a"]},
        {"id": "south", "name": "South", "azimuth": 153, "tilt": 20, "cols": 2, "rows": 4, "cells": ["b", "b", "b", "b", "c", "c", "c", "c"]},
        {"id": "hut", "name": "Hut", "cols": 2, "rows": 1, "cells": ["h1", "h2"]},
    ],
    "devices": [
        {"id": "grid", "kind": "grid", "name": "Grid", "power_entity": "sensor.grid_import_power", "power_entity_2": "sensor.grid_export_power", "energy_entity": "sensor.grid_import_energy", "energy_entity_2": "sensor.grid_export_energy"},
        {"id": "bat", "kind": "battery", "name": "Battery", "power_entity": "sensor.battery_power", "invert": True, "soc_entity": "sensor.battery_soc", "energy_entity": "sensor.battery_charge_energy", "energy_entity_2": "sensor.battery_discharge_energy"},
        {"id": "hp", "kind": "consumer", "name": "Heat pump", "icon": "🌡️", "power_entity": "sensor.heat_pump_power", "energy_entity": "sensor.heat_pump_energy"},
        {"id": "wb", "kind": "consumer", "name": "Wallbox", "power_entity": "sensor.wallbox_power"},
    ],
}


def near(a, b, tol=1e-6):
    return a is not None and abs(a - b) <= tol


def test_layout(c):
    empty = c.get("/api/plant/layout").json()
    assert empty == {"layout": {"areas": [], "strings": [], "devices": [], "yield_entity": None}, "ha": True}
    saved = c.put("/api/plant/layout", json=LAYOUT)
    assert saved.status_code == 200, saved.text
    layout = c.get("/api/plant/layout").json()["layout"]
    assert [s["id"] for s in layout["strings"]] == ["a", "b", "c", "h1", "h2"]
    assert layout["strings"][4]["module_watts"] is None
    assert plant.module_counts(layout) == {"a": 5, "b": 4, "c": 4, "h1": 1, "h2": 1}

    def bad(change):
        doc = {k: [dict(i) for i in v] for k, v in LAYOUT.items()}
        change(doc)
        return c.put("/api/plant/layout", json=doc).status_code

    assert bad(lambda d: d["areas"][0].update(cells=["a"])) == 400
    assert bad(lambda d: d["areas"][0].update(cells=["zz"] * 6)) == 400
    assert bad(lambda d: d["strings"][0].update(power_entity="sensor.x; drop")) == 400
    assert bad(lambda d: d["strings"].append(dict(d["strings"][0]))) == 400
    assert bad(lambda d: d["devices"].append(dict(d["devices"][0], id="grid2"))) == 400
    assert bad(lambda d: d["devices"][2].update(kind="spaceship")) == 400
    assert c.put("/api/plant/layout", content=b"{").status_code == 400
    # a rejected layout leaves the stored one untouched
    assert c.get("/api/plant/layout").json()["layout"] == layout


def test_entities(c):
    found = {e["entity_id"]: e for e in c.get("/api/plant/entities").json()["entities"]}
    assert "sensor.string_b_power" in found and found["sensor.string_b_power"]["unit"] == "kW"
    assert "sensor.battery_soc" in found
    assert "sensor.outdoor_temperature" not in found and "light.kitchen" not in found


def test_live(c):
    live = c.get("/api/plant/live").json()
    by = {s["id"]: s for s in live["strings"]}
    assert by["a"]["value"] == 3900 and by["b"]["value"] == 2800  # kW became W
    assert by["h2"]["value"] is None and by["h2"]["has_sensor"]  # unavailable is no value
    assert near(by["a"]["kwp"], 2.0) and near(by["a"]["specific"], 1950)
    assert by["h2"]["kwp"] is None and by["h2"]["specific"] is None
    assert near(live["pv"], 3900 + 2800 + 2650 + 210)
    assert live["grid"]["in"] == 0 and live["grid"]["out"] == 4100 and live["grid"]["net"] == -4100
    # the battery sensor is signed and inverted: -1500 W means charging
    assert live["battery"]["in"] == 1500 and live["battery"]["out"] == 0 and live["battery"]["soc"] == 64
    assert near(live["house"], 9560 - 4100 - 1500)
    assert [x["value"] for x in live["consumers"]] == [1800, 0]
    assert near(live["other"], 3960 - 1800)


def test_history(c):
    day = c.get("/api/plant/history?period=day&date=2026-06-15").json()
    asked = fake_ha.requests_seen[-1]
    assert asked["period"] == "hour" and asked["start_time"] == "2026-06-15T00:00:00+02:00"
    assert asked["end_time"] == "2026-06-16T00:00:00+02:00"
    assert "sensor.string_a_energy" in asked["statistic_ids"]
    assert "sensor.string_a_power" not in asked["statistic_ids"]  # the meter wins
    assert "sensor.string_c_power" in asked["statistic_ids"]  # no meter: mean power
    assert "sensor.battery_soc" not in asked["statistic_ids"]
    by = {s["id"]: s for s in day["strings"]}
    assert near(by["a"]["value"], 24.0, 0.05) and near(by["b"]["value"], 18.0, 0.05)
    # string c has only a power sensor: its mean power is integrated
    assert near(by["c"]["value"], 2.4 * 7.596, 0.05), by["c"]
    assert near(by["a"]["specific"], 12.0, 0.05)
    assert by["h2"]["value"] is None
    assert near(day["grid"]["in"], 6.0, 0.05) and near(day["grid"]["out"], 30.0, 0.05)
    assert near(day["battery"]["in"], 5.0, 0.05) and near(day["battery"]["out"], 4.0, 0.05)
    assert "soc" not in day["battery"]
    assert near(day["house"], day["pv"] + 6.0 - 30.0 - (5.0 - 4.0), 0.1)
    assert len(day["steps"]) == 24
    noon = day["steps"][12]["strings"]
    assert noon["a"] > day["steps"][7]["strings"]["a"] > 0 and day["steps"][2]["strings"]["a"] == 0

    month = c.get("/api/plant/history?period=month&date=2026-06-15").json()
    asked = fake_ha.requests_seen[-1]
    assert asked["period"] == "day" and asked["start_time"].startswith("2026-06-01T00:00:00")
    assert asked["end_time"].startswith("2026-07-01T00:00:00")
    assert near({s["id"]: s for s in month["strings"]}["a"]["value"], 24.0 * 30, 0.5)
    assert len(month["steps"]) == 30

    year = c.get("/api/plant/history?period=year&date=2026-06-15").json()
    assert fake_ha.requests_seen[-1]["period"] == "month" and len(year["steps"]) == 12

    assert c.get("/api/plant/history?period=week&date=2026-06-15").status_code == 400
    assert c.get("/api/plant/history?period=day&date=15.06.2026").status_code == 400


def test_month_suggest(c):
    """The monthly values the app fills in itself."""
    # without a yield meter the strings are summed, but only if every one delivers:
    # string h2 has no statistics, so there is no yield rather than one that is too small
    r = c.get("/api/months/2026-06/suggest").json()
    assert r["values"]["pv_yield"] is None and near(r["values"]["battery_charged"], 150.0, 0.2), r
    without_h2 = dict(LAYOUT, strings=LAYOUT["strings"][:4], areas=LAYOUT["areas"][:2])
    assert c.put("/api/plant/layout", json=without_h2).status_code == 200
    # two meters and two power sensors
    r = c.get("/api/months/2026-06/suggest").json()
    asked = fake_ha.requests_seen[-1]
    assert asked["period"] == "day" and asked["start_time"].startswith("2026-06-01T00:00:00")
    assert asked["end_time"].startswith("2026-07-01T00:00:00")
    assert r["complete"] is True
    assert near(r["values"]["pv_yield"], 24 * 30 + 18 * 30 + 14.4 * 30 + 1.8 * 30, 0.2), r
    assert near(r["values"]["battery_charged"], 150.0, 0.2) and near(r["values"]["battery_discharged"], 120.0, 0.2)

    saved = c.put("/api/plant/layout", json=dict(LAYOUT, yield_entity="sensor.pv_total_energy"))
    assert saved.status_code == 200 and saved.json()["layout"]["yield_entity"] == "sensor.pv_total_energy"
    r = c.get("/api/months/2026-06/suggest").json()
    assert fake_ha.requests_seen[-1]["statistic_ids"] == sorted(
        ["sensor.pv_total_energy", "sensor.battery_charge_energy", "sensor.battery_discharge_energy"]
    )
    assert near(r["values"]["pv_yield"], 1800.0, 0.2), r

    # a month that has not ended is marked; a source without data gives no value
    assert c.get("/api/months/2099-01/suggest").json()["complete"] is False
    c.put("/api/plant/layout", json=dict(LAYOUT, yield_entity="sensor.does_not_exist"))
    r = c.get("/api/months/2026-06/suggest").json()
    assert r["values"]["pv_yield"] is None and near(r["values"]["battery_charged"], 150.0, 0.2)
    # a battery with only a signed power sensor has no meters to read
    no_meters = dict(LAYOUT, devices=[dict(d, energy_entity=None, energy_entity_2=None) if d["kind"] == "battery" else d for d in LAYOUT["devices"]])
    c.put("/api/plant/layout", json=no_meters)
    r = c.get("/api/months/2026-06/suggest").json()
    assert r["values"]["battery_charged"] is None and r["values"]["battery_discharged"] is None
    assert c.get("/api/months/2026-6/suggest").status_code == 400
    c.put("/api/plant/layout", json=LAYOUT)


def test_helpers():
    assert plant.shift("day", "2026-03-01", -1) == "2026-02-28"
    assert plant.shift("month", "2026-01-31", -1) == "2025-12-01"
    assert plant.shift("month", "2026-12-15", 1) == "2027-01-01"
    assert plant.shift("year", "2026-06-15", 1) == "2027-01-01"
    # the day of the switch to summer time has 23 hours
    start, end = plant.period_range("day", "2026-03-29", "Europe/Berlin")
    assert end.timestamp() - start.timestamp() == 23 * 3600


def test_unreachable(c):
    os.environ["PVMON_HA_TOKEN"] = "wrong"
    try:
        assert c.get("/api/plant/live").status_code == 502
        assert c.get("/api/plant/history?period=day&date=2026-06-15").status_code == 502
    finally:
        os.environ["PVMON_HA_TOKEN"] = fake_ha.TOKEN
    os.environ["PVMON_HA_URL"] = "http://127.0.0.1:9"
    try:
        r = c.get("/api/plant/live")
        assert r.status_code == 502 and "nicht erreichbar" in r.json()["error"]
    finally:
        os.environ["PVMON_HA_URL"] = f"http://127.0.0.1:{PORT}"
    del os.environ["PVMON_HA_URL"]
    try:
        assert c.get("/api/plant/layout").json()["ha"] is False
        assert c.get("/api/plant/live").status_code == 502
    finally:
        os.environ["PVMON_HA_URL"] = f"http://127.0.0.1:{PORT}"


if __name__ == "__main__":
    fake_ha.start_in_thread(PORT)
    client = TestClient(app)
    test_helpers()
    print("ok test_helpers")
    for fn in (test_layout, test_entities, test_live, test_history, test_month_suggest, test_unreachable):
        fn(client)
        print("ok", fn.__name__)
