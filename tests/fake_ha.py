"""A stand-in for Home Assistant: REST states/config and the statistics websocket.

Speaks the parts of the real API the add-on uses, with invented sensors.
Run standalone for manual work: python3 tests/fake_ha.py [port]
"""

import math
import sys
import threading
from datetime import datetime, timedelta

from aiohttp import web

TOKEN = "test-token"
TIME_ZONE = "Europe/Berlin"

# entity -> (state, unit)
STATES = {
    "sensor.string_a_power": ("3900", "W"),
    "sensor.string_b_power": ("2.8", "kW"),
    "sensor.string_c_power": ("2650", "W"),
    "sensor.hut_1_power": ("210", "W"),
    "sensor.hut_2_power": ("unavailable", "W"),
    "sensor.string_a_energy": ("5120.4", "kWh"),
    "sensor.string_b_energy": ("3801.0", "kWh"),
    "sensor.grid_import_power": ("0", "W"),
    "sensor.grid_export_power": ("4100", "W"),
    "sensor.grid_import_energy": ("43920", "kWh"),
    "sensor.grid_export_energy": ("33107", "kWh"),
    "sensor.battery_power": ("-1500", "W"),  # signed: negative = charging
    "sensor.battery_soc": ("64", "%"),
    "sensor.battery_charge_energy": ("2100", "kWh"),
    "sensor.battery_discharge_energy": ("1800", "kWh"),
    "sensor.heat_pump_power": ("1800", "W"),
    "sensor.heat_pump_energy": ("9000", "kWh"),
    "sensor.wallbox_power": ("0", "W"),
    "sensor.outdoor_temperature": ("4.5", "°C"),
    "light.kitchen": ("on", None),
}
# kWh per full day for energy meters, peak W for power sensors
DAILY_KWH = {
    "sensor.string_a_energy": 24.0,
    "sensor.string_b_energy": 18.0,
    "sensor.grid_import_energy": 6.0,
    "sensor.grid_export_energy": 30.0,
    "sensor.battery_charge_energy": 5.0,
    "sensor.battery_discharge_energy": 4.0,
    "sensor.heat_pump_energy": 12.0,
}
PEAK_W = {"sensor.string_c_power": 2400.0, "sensor.hut_1_power": 300.0, "sensor.wallbox_power": 0.0}

requests_seen = []


def _state(entity_id):
    state, unit = STATES[entity_id]
    attrs = {"friendly_name": entity_id.split(".")[1].replace("_", " ").title()}
    if unit:
        attrs["unit_of_measurement"] = unit
    return {"entity_id": entity_id, "state": state, "attributes": attrs}


def _authorized(request):
    return request.headers.get("Authorization") == f"Bearer {TOKEN}"


async def config(request):
    if not _authorized(request):
        return web.Response(status=401)
    return web.json_response({"time_zone": TIME_ZONE})


async def states(request):
    if not _authorized(request):
        return web.Response(status=401)
    return web.json_response([_state(e) for e in STATES])


async def state(request):
    if not _authorized(request):
        return web.Response(status=401)
    entity_id = request.match_info["entity_id"]
    if entity_id not in STATES:
        return web.Response(status=404)
    return web.json_response(_state(entity_id))


def _sun(hour):
    """Share of a day's yield in one hour: a bell between 6 and 18 o'clock."""
    return max(0.0, math.sin((hour - 6) / 12 * math.pi)) / 7.596


def _rows(entity_id, start, end, period):
    step = {"hour": timedelta(hours=1), "day": timedelta(days=1)}.get(period)
    rows, cur = [], start
    while cur < end:
        if step:
            nxt = cur + step
        else:  # month
            nxt = (cur.replace(day=1) + timedelta(days=32)).replace(day=1)
        hours = (nxt - cur).total_seconds() / 3600
        share = _sun(cur.hour) if period == "hour" else hours / 24
        row = {"start": int(cur.timestamp() * 1000), "end": int(nxt.timestamp() * 1000)}
        if entity_id in DAILY_KWH:
            row["change"] = DAILY_KWH[entity_id] * share
        else:
            row["mean"] = PEAK_W[entity_id] * (share * 7.596 if period == "hour" else 0.25)
        rows.append(row)
        cur = nxt
    return rows


async def websocket(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    await ws.send_json({"type": "auth_required"})
    auth = await ws.receive_json()
    if auth.get("access_token") != TOKEN:
        await ws.send_json({"type": "auth_invalid"})
        await ws.close()
        return ws
    await ws.send_json({"type": "auth_ok"})
    async for msg in ws:
        data = msg.json()
        requests_seen.append(data)
        if data.get("type") != "recorder/statistics_during_period":
            await ws.send_json({"id": data["id"], "type": "result", "success": False, "error": {"message": "unknown command"}})
            continue
        start = datetime.fromisoformat(data["start_time"])
        end = datetime.fromisoformat(data["end_time"])
        result = {
            e: _rows(e, start, end, data["period"])
            for e in data["statistic_ids"]
            if e in DAILY_KWH or e in PEAK_W
        }
        await ws.send_json({"id": data["id"], "type": "result", "success": True, "result": result})
    return ws


def make_app():
    app = web.Application()
    app.add_routes(
        [
            web.get("/api/config", config),
            web.get("/api/states", states),
            web.get("/api/states/{entity_id}", state),
            web.get("/api/websocket", websocket),
        ]
    )
    return app


def start_in_thread(port):
    """Serve on 127.0.0.1:port in a daemon thread; returns once it listens."""
    import asyncio

    ready = threading.Event()

    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        runner = web.AppRunner(make_app())
        loop.run_until_complete(runner.setup())
        loop.run_until_complete(web.TCPSite(runner, "127.0.0.1", port).start())
        ready.set()
        loop.run_forever()

    threading.Thread(target=run, daemon=True).start()
    ready.wait(10)


if __name__ == "__main__":
    web.run_app(make_app(), host="127.0.0.1", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8123)
