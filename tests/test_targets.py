"""Payback per build target (Doc 142 §12.8) through the real API.

The parts must add up to the whole: costs to the investment total, benefits
to the cumulated revenue, in every state of the data (no hut values yet, hut
values from the meter, one typed by hand, hut not contained in the yield).
The hut's monthly yield comes from its meter's statistics in a stand-in Home
Assistant; a value typed by hand is never overwritten.

Run: python3 tests/test_targets.py
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pv_monitor" / "app"))
sys.path.insert(0, str(ROOT / "tests"))

import fake_ha  # noqa: E402

PORT = 18125
os.environ["PVMON_DB"] = os.path.join(tempfile.mkdtemp(), "targets.sqlite")
os.environ.pop("SUPERVISOR_TOKEN", None)
os.environ["PVMON_HA_URL"] = f"http://127.0.0.1:{PORT}"
os.environ["PVMON_HA_TOKEN"] = fake_ha.TOKEN
os.environ["PVMON_PUBLISH"] = "0"
os.environ["PVMON_TODAY"] = "2025-12-10"

from starlette.testclient import TestClient  # noqa: E402

import sample_data as fx  # noqa: E402
from pvmonitor import calc, db  # noqa: E402
from pvmonitor.server import app  # noqa: E402

EPS = 1e-6
LAYOUT = {
    "strings": [{"id": "a", "name": "A", "module_watts": 400, "power_entity": "sensor.string_a_power"}],
    "areas": [{"id": "n", "name": "Nord", "cols": 1, "rows": 1, "cells": ["a"]}],
    "devices": [],
    "yield_entity": "sensor.pv_total_energy",
    "hut_entity": "sensor.hut_energy_total",
}
CATEGORY = {"Wechselrichter": "PV-Anlage", "Module": "PV-Anlage", "Kabel": "PV-Anlage", "Speicher": "Speicher"}


def target(state, key):
    return next(t for t in state["targets"]["targets"] if t["key"] == key)


def assert_parts_add_up(state):
    T = state["targets"]
    c = T["check"]
    assert c["ok"], c
    assert abs(c["cost_total"] - state["summary"]["invest_total"]) < EPS
    assert abs(c["benefit_total"] - state["summary"]["revenue_total"]) < EPS
    # and month by month: pv + storage + hut = revenue of the month
    real = [m for m in state["months"] if not m["baseline"]]
    per = {k: {h["month"]: h["gain"] for h in target(state, k)["monthly"]} for k in ("pv", "storage", "hut")}
    for m in real:
        parts = sum(per[k].get(m["month"], 0.0) for k in per)
        assert abs(parts - m["revenue"]) < EPS, (m["month"], parts, m["revenue"])


def main():
    c = TestClient(app)
    c.get("/api/state")
    con = db.connect(os.environ["PVMON_DB"])
    fx.fill(con)
    con.close()
    state = c.get("/api/state").json()
    for inv in state["investments"]:
        if inv["label"] in CATEGORY:
            c.put(f"/api/investments/{inv['id']}/category", json={"category": CATEGORY[inv["label"]]})
    c.post("/api/investments", json={"date": "2024-06-01", "label": "Hütte Module", "amount": 300.0, "category": "Hundehütte"})
    state = c.get("/api/state").json()
    revenue_before = state["summary"]["revenue_total"]
    break_even_before = state["summary"]["break_even"]

    # one post without a target: it counts only in the whole, and is announced
    T = state["targets"]
    assert T["without_target"] == 1
    none = next(r for r in T["rows"] if r["key"] == "none")
    assert none["items"] == 1 and none["cost"] == -500.0 and none["benefit"] == 0.0
    assert_parts_add_up(state)

    # storage: the storage page's own figures, not a second calculation
    st, storage = target(state, "storage"), state["storage"]
    assert st["cost"] == storage["cost"] == 4000.0
    assert abs(st["benefit_total"] - storage["benefit_total"]) < EPS
    assert st["since"] == storage["install_month"] and st["scenarios"] == storage["scenarios"]
    # no hut values yet: the hut has no benefit, the PV plant gets the rest
    hut = target(state, "hut")
    assert hut["benefit_total"] == 0.0 and hut["months"] == [] and hut["since"] is None
    assert hut["cost"] == 300.0 and hut["break_even"] is None
    pv = target(state, "pv")
    assert abs(pv["benefit_total"] - (revenue_before - storage["benefit_total"])) < EPS
    assert pv["cost"] == 15400.0 and pv["items"] == 3

    # "Sonstiges" is its own row without benefit, not a target of its own
    sale = next(i for i in state["investments"] if i["label"] == "Verkauf Altgerät")
    state = c.put(f"/api/investments/{sale['id']}/category", json={"category": "Sonstiges"}).json()
    assert state["targets"]["without_target"] == 0
    assert [t["key"] for t in state["targets"]["targets"]] == ["pv", "storage", "hut"]
    other = next(r for r in state["targets"]["rows"] if r["key"] == "other")
    assert other["cost"] == -500.0 and other["benefit"] == 0.0
    assert not any(r["key"] == "none" for r in state["targets"]["rows"])
    assert_parts_add_up(state)

    # the hut's meter, and one month typed by hand before the meter is read
    assert c.put("/api/plant/layout", json=LAYOUT).status_code == 200
    m = next(x for x in state["months"] if x["month"] == "2025-11")
    body = {k: m[k] for k in ("reading_date", "grid_reading", "feed_reading", "heat_reading", "pv_yield", "battery_charged", "battery_discharged")}
    state = c.put("/api/months/2025-11", json=dict(body, hut_yield=7.5)).json()
    assert state["targets"]["hut_meter"] == "sensor.hut_energy_total"

    res = c.post("/api/hut/fill").json()
    assert "2025-11" not in res["written"] and len(res["written"]) == fx.MONTH_COUNT - 2, res
    assert fx.months()[0]["month"] not in res["written"]  # the baseline month only anchors the readings
    state = c.get("/api/state").json()
    months = {x["month"]: x for x in state["months"]}
    assert months["2025-11"]["hut_yield"] == 7.5  # typed by hand: kept
    assert months["2025-10"]["hut_yield"] == 15.5  # 31 days x 0.5 kWh from the meter
    assert c.post("/api/hut/fill").json() == {"written": [], "missing": []}  # nothing left, nothing overwritten

    hut = target(state, "hut")
    oct_ = next(h for h in hut["months"] if h["month"] == "2025-10")
    assert abs(oct_["share"] - 15.5 / months["2025-10"]["pv_yield"]) < EPS
    assert hut["benefit_total"] > 0 and hut["since"] == fx.months()[1]["month"]
    assert hut["hut_in_yield"] is True
    # the hut takes its share from the PV plant, never from the whole
    assert abs(state["summary"]["revenue_total"] - revenue_before) < EPS
    assert state["summary"]["break_even"] == break_even_before
    assert_parts_add_up(state)
    pv = target(state, "pv")
    assert abs(pv["benefit_total"] + hut["benefit_total"] + state["storage"]["benefit_total"] - revenue_before) < EPS

    # a yield without the hut: its share is hut / (yield + hut), still adding up
    state_in = state
    assert c.put("/api/plant/layout", json=dict(LAYOUT, hut_in_yield=False)).status_code == 200
    state = c.get("/api/state").json()
    oct_out = next(h for h in target(state, "hut")["months"] if h["month"] == "2025-10")
    assert abs(oct_out["share"] - 15.5 / (months["2025-10"]["pv_yield"] + 15.5)) < EPS
    assert target(state, "hut")["benefit_total"] < target(state_in, "hut")["benefit_total"]
    assert_parts_add_up(state)

    # projections: seasonal like the whole for PV and hut, only with 12 months of data
    for key in ("pv", "hut"):
        t = target(state, key)
        assert t["projection_months"] == len(t["monthly"]) >= calc.MIN_PROJECTION_MONTHS
        assert t["break_even"] is not None, (key, t["cost"], t["benefit_total"], t["projection_months"])
    short = calc.targets_economics(
        [m for m in state["months"] if m["month"] >= "2025-05"], state["investments"], state["storage"], True
    )
    assert next(t for t in short["targets"] if t["key"] == "pv")["break_even"] is None

    # without a meter the fill is refused instead of guessing
    assert c.put("/api/plant/layout", json=dict(LAYOUT, hut_entity=None)).status_code == 200
    r = c.post("/api/hut/fill")
    assert r.status_code == 400 and "Hundehütte" in r.json()["error"]

    # the page has the switch and the note
    js = c.get("/app.js").text
    assert "Gesamt" in js and "Hundehütte" in js and "api/hut/fill" in js
    assert calc.TARGET_NOTE == "Die Aufteilung des Nutzens ist eine Zuordnung, keine Messung."
    print("ok test_targets")


if __name__ == "__main__":
    fake_ha.start_in_thread(PORT)
    main()
