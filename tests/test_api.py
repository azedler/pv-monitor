"""HTTP API end to end against a temporary database with invented history.

Run: python3 tests/test_api.py
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pv_monitor" / "app"))

tmp = tempfile.mkdtemp()
os.environ["PVMON_DB"] = os.path.join(tmp, "test.sqlite")
os.environ.pop("SUPERVISOR_TOKEN", None)
os.environ["PVMON_TODAY"] = "2025-12-10"

from starlette.testclient import TestClient  # noqa: E402

from pvmonitor import db  # noqa: E402
from pvmonitor.server import app  # noqa: E402

sys.path.insert(0, str(ROOT / "tests"))
import sample_data as fx  # noqa: E402


N = fx.MONTH_COUNT
NEXT = "2025-12"


def main():
    c = TestClient(app)

    empty = c.get("/api/state").json()
    assert empty["months"] == [] and empty["summary"]["last_month"] is None
    assert c.get("/").status_code == 200 and "PV Monitor" in c.get("/").text
    for script in ("app.js", "charts.js", "plant.js", "story.js", "style.css"):
        assert script in c.get("/").text and c.get(f"/{script}").status_code == 200, script
    # fonts ship with the add-on; the page names no outside host at all
    css = c.get("/style.css").text
    for font in ("fonts/inter.woff2", "fonts/space-grotesk.woff2"):
        assert font in css and c.get(f"/{font}").status_code == 200, font
    for path in ("/", "/style.css", "/app.js", "/story.js", "/plant.js", "/charts.js"):
        body = c.get(path).text
        assert "http://" not in body.replace("http://www.w3.org", "") and "https://" not in body, path

    con = db.connect(os.environ["PVMON_DB"])
    fx.fill(con)
    con.close()

    state = c.get("/api/state").json()
    assert state["settings"]["tariff_mode"] == "daily"
    assert len(state["months"]) == N and state["next_month"] == NEXT
    assert abs(state["summary"]["invest_total"] - fx.INVEST_TOTAL) < 1e-6
    assert [m["kind"] for m in state["meters"]] == ["grid", "feed_in", "heat"]
    assert state["meters"][2]["active_to"] == "2024-10-01"
    daily_total = state["summary"]["revenue_total"]

    # the tariff mode re-values the months in which a tariff changed
    state = c.put("/api/settings", json={"tariff_mode": "monthly"}).json()
    assert state["settings"]["tariff_mode"] == "monthly"
    assert abs(state["summary"]["revenue_total"] - daily_total) > 0.01, state["summary"]
    assert c.put("/api/settings", json={"tariff_mode": "x"}).status_code == 400

    LAST_GRID = state["months"][-1]["grid_reading"]
    LAST_FEED = state["months"][-1]["feed_reading"]
    # an entry is checked first and not stored by the check
    entry = {
        "reading_date": "2026-01-03",
        "grid_reading": LAST_GRID + 580,
        "feed_reading": LAST_FEED + 43,
        "pv_yield": 150,
        "battery_charged": 120,
        "battery_discharged": 100,
    }
    chk = c.post("/api/months/2025-12/check", json=entry).json()
    assert chk["month"]["grid_kwh"] == 580 and chk["month"]["feed_kwh"] == 43
    assert all(x["ok"] is not False for x in chk["checks"]), chk["checks"]
    assert len(c.get("/api/state").json()["months"]) == N

    bad = dict(entry, grid_reading=100)
    rules = {x["rule"]: x["ok"] for x in c.post("/api/months/2025-12/check", json=bad).json()["checks"]}
    assert rules["Zählerstand Hausstrom läuft vorwärts"] is False

    state = c.put("/api/months/2025-12", json=entry).json()
    assert len(state["months"]) == N + 1 and state["months"][-1]["self_use"] == 107
    assert state["summary"]["last_month"] == "2025-12"
    state = c.put("/api/months/2025-12", json=dict(entry, pv_yield=160)).json()
    assert len(state["months"]) == N + 1 and state["months"][-1]["pv_yield"] == 160
    state = c.delete("/api/months/2025-12").json()
    assert len(state["months"]) == N

    assert c.put("/api/months/2025-13", json=entry).status_code == 400
    assert c.put("/api/months/2025-12", json={"pv_yield": 1}).status_code == 400
    assert c.put("/api/months/2025-12", json=dict(entry, pv_yield="abc")).status_code == 400

    # a corrected tariff re-values history
    before = state["summary"]["revenue_total"]
    tariffs = c.get("/api/state").json()["tariffs"]
    old = next(t for t in tariffs if t["kind"] == "grid" and t["energy_price"] == 0.28)
    state = c.put(f"/api/tariffs/{old['id']}", json=dict(old, energy_price=0.29)).json()
    assert state["summary"]["revenue_total"] > before + 1
    monthly_2024_06 = next(m for m in state["months"] if m["month"] == "2024-06")
    assert monthly_2024_06["price"] == 0.29

    n = len(state["tariffs"])
    state = c.post("/api/tariffs", json={"valid_from": "2027-03-15", "energy_price": 0.319, "base_price_year": 144}).json()
    assert len(state["tariffs"]) == n + 1
    new = max(state["tariffs"], key=lambda t: t["id"])
    assert new["valid_from"] == "2027-03-01" and new["kind"] == "grid"
    assert len(c.delete(f"/api/tariffs/{new['id']}").json()["tariffs"]) == n
    assert c.delete(f"/api/tariffs/{new['id']}").status_code == 404
    assert c.post("/api/tariffs", json={"valid_from": "2027-03-01"}).status_code == 400

    # forecast: the running tariff, its payment and the next period
    fc = c.get("/api/state").json()["forecast"]
    assert fc["current"]["start"] == "2025-02-24" and fc["current"]["balance"] is None
    running = fc["current"]["tariff"]
    state = c.put(f"/api/tariffs/{running['id']}", json=dict(running, monthly_payment=140)).json()
    assert state["forecast"]["current"]["payments_total"] == 140 * 12
    assert abs(state["forecast"]["current"]["balance"] - (1680 - state["forecast"]["current"]["cost"])) < 1e-6
    assert c.put(f"/api/tariffs/{running['id']}", json=dict(running, monthly_payment="x")).status_code == 400

    # staged feed-in rate: the price is a formula of the plant's power
    assert c.put("/api/settings", json={"plant_kwp": 24.96}).json()["settings"]["plant_kwp"] == 24.96
    feed = next(t for t in c.get("/api/state").json()["tariffs"] if t["kind"] == "feed_in")
    before_total = c.get("/api/state").json()["summary"]["revenue_total"]
    state = c.put(f"/api/tariffs/{feed['id']}", json=dict(feed, energy_price=None, rate_to_10=0.0803, rate_10_40=0.0695)).json()
    staged = next(t for t in state["tariffs"] if t["id"] == feed["id"])
    assert staged["computed"] and round(staged["energy_price"], 5) == 0.07383
    assert state["summary"]["revenue_total"] < before_total  # 7.38 ct instead of the 8 ct before
    state = c.put("/api/settings", json={"plant_kwp": 9.9}).json()  # the formula follows the power
    assert next(t for t in state["tariffs"] if t["id"] == feed["id"])["energy_price"] == 0.0803
    assert state["settings"]["tariff_mode"] == "monthly"  # untouched by the other setting
    assert c.put(f"/api/tariffs/{feed['id']}", json=dict(feed, rate_to_10=0.08)).status_code == 400  # one rate alone
    grid_t = next(t for t in state["tariffs"] if t["kind"] == "grid")
    assert c.put(f"/api/tariffs/{grid_t['id']}", json=dict(grid_t, rate_to_10=0.08, rate_10_40=0.07)).status_code == 400
    assert c.put("/api/settings", json={}).status_code == 400 and c.put("/api/settings", json={"plant_kwp": -1}).status_code == 400
    state = c.put("/api/settings", json={"eeg_date": "2024-12-06"}).json()
    assert state["settings"]["eeg_date"] == "2024-12-06"
    assert c.put("/api/settings", json={"eeg_date": "6.12.2024"}).status_code == 400
    assert c.put("/api/settings", json={"eeg_date": None}).json()["settings"]["eeg_date"] is None
    assert [p["key"] for p in state["periods"]][0] == "last12" and state["storage"]["cost"] == 0
    c.put(f"/api/tariffs/{feed['id']}", json=feed)
    c.put("/api/settings", json={"plant_kwp": None})

    cmp_ = c.post("/api/tariffs/compare", json={"energy_price": 0.28, "base_price_year": 120}).json()
    assert round(cmp_["break_even_kwh"]) == 6000 and cmp_["months"] == 12, cmp_
    nxt = cmp_["next_period"]
    assert nxt["start"] == "2026-02-24" and "end" not in nxt and abs(nxt["cost"] - (nxt["kwh"] * 0.28 + 120)) < 1e-6
    assert abs(nxt["recommended_payment"] - nxt["cost"] / 12) < 1e-9

    total = state["summary"]["invest_total"]
    state = c.post("/api/investments", json={"label": "Test", "amount": -100, "date": "2025-10-01"}).json()
    assert abs(state["summary"]["invest_total"] - (total - 100)) < 1e-6
    inv = max(state["investments"], key=lambda i: i["id"])
    state = c.put(f"/api/investments/{inv['id']}", json={"label": "Test", "amount": 50}).json()
    assert abs(state["summary"]["invest_total"] - (total + 50)) < 1e-6
    state = c.delete(f"/api/investments/{inv['id']}").json()
    assert abs(state["summary"]["invest_total"] - total) < 1e-6
    assert c.post("/api/investments", json={"label": "x"}).status_code == 400
    assert c.post("/api/investments", content=b"{").status_code == 400

    # inside the add-on only the ingress proxy may connect
    os.environ["SUPERVISOR_TOKEN"] = "x"
    try:
        assert c.get("/api/state").status_code == 403
        assert TestClient(app, client=("172.30.32.2", 5000)).get("/api/state").status_code == 200
    finally:
        os.environ.pop("SUPERVISOR_TOKEN")
    print("ok: api")


if __name__ == "__main__":
    main()
