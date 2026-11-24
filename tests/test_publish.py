"""Doc 143: the state sensor.pv_monitor_anlage, the roof card file and its
Lovelace resource, against a stand-in Home Assistant.

B'1: below the Home Assistant configuration only www/pv-monitor/ is written.
B'2: only the card's own Lovelace resource is created or changed.

Run: python3 tests/test_publish.py
"""

import asyncio
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "pv_monitor" / "app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(ROOT / "tests"))

import fake_ha  # noqa: E402

PORT = 18124
CONFIG = Path(tempfile.mkdtemp()) / "homeassistant"
os.environ.update(
    PVMON_DB=str(Path(tempfile.mkdtemp()) / "pub.sqlite"),
    PVMON_HA_URL=f"http://127.0.0.1:{PORT}",
    PVMON_HA_TOKEN=fake_ha.TOKEN,
    PVMON_HA_CONFIG=str(CONFIG),
    PVMON_VERSION="0.11.0",
    PVMON_SLUG="2cf783c6_pv_monitor",
)
os.environ.pop("SUPERVISOR_TOKEN", None)

from pvmonitor import plant, publish  # noqa: E402

N = lambda n, s: [s] * n  # noqa: E731
# the real roof: north 28 modules with a gap, south 18 + 18, hut 2 x 1
LAYOUT = plant.validate_layout({
    "strings": [
        {"id": "s11", "name": "1.1", "module_watts": 390, "power_entity": "sensor.string_a_power"},
        {"id": "s12", "name": "1.2", "module_watts": 390, "power_entity": "sensor.string_b_power"},
        {"id": "s13", "name": "1.3", "module_watts": 390, "power_entity": "sensor.string_c_power"},
        {"id": "h1", "name": "H1", "module_watts": 200, "power_entity": "sensor.hut_1_power"},
        {"id": "h2", "name": "H2", "module_watts": 200, "power_entity": "sensor.hut_2_power"},
    ],
    "areas": [
        {"id": "nord", "name": "Nord", "azimuth": 333, "cols": 4, "rows": 9, "cells": N(4, "s11") + N(4, None) + [None, None, "s11", "s11"] * 2 + N(20, "s11")},
        {"id": "sued", "name": "Süd", "azimuth": 153, "cols": 4, "rows": 9, "cells": N(18, "s12") + N(18, "s13")},
        {"id": "huette", "name": "Hütte", "cols": 1, "rows": 2, "cells": ["h1", "h2"]},
    ],
    "devices": [],
})


def files_under(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_schema():
    state, attrs = publish.anlage(LAYOUT)
    assert re.fullmatch(r"[0-9a-f]{10}", state)
    assert attrs["schema"] == 1 and attrs["addon_version"] == "0.11.0" and attrs["panel"] == "/2cf783c6_pv_monitor"
    by = {s["id"]: s for s in attrs["strings"]}
    assert (by["s11"]["modules"], by["s11"]["kwp"]) == (28, 10.92) and by["s12"]["kwp"] == 7.02 and by["h1"]["kwp"] == 0.2
    assert by["s11"]["power_entity"] == "sensor.string_a_power"
    nord = attrs["areas"][0]
    assert nord["cells"] == "0000" + "...." + "..00" * 2 + "0" * 20 and len(nord["cells"]) == 36
    assert attrs["areas"][2]["cells"] == "34"
    size = publish.attribute_bytes(attrs)
    assert size < publish.MAX_ATTRIBUTE_BYTES, size
    print("  attributes:", size, "bytes")
    # the fingerprint follows the layout, not the add-on version
    os.environ["PVMON_VERSION"] = "0.11.1"
    assert publish.anlage(LAYOUT)[0] == state
    os.environ["PVMON_VERSION"] = "0.11.0"
    moved = json.loads(json.dumps(LAYOUT))
    moved["areas"][2]["cells"] = ["h2", "h1"]
    assert publish.anlage(plant.validate_layout(moved))[0] != state


def test_card_files_only_in_their_folder():
    CONFIG.mkdir(parents=True)
    (CONFIG / "secrets.yaml").write_text("x: y\n")
    (CONFIG / "www").mkdir()
    (CONFIG / "www" / "other.js").write_text("// someone else's")
    before = files_under(CONFIG)
    written = publish.install_card_files()
    after = files_under(CONFIG)
    new = {k for k in after if k not in before}
    assert new == {"www/pv-monitor/pv-monitor-card.js", "www/pv-monitor/space-grotesk.woff2"}, new
    assert all(after[k] == v for k, v in before.items())  # nothing else changed
    assert len(written) == 2 and publish.install_card_files() == []  # unchanged files are left alone
    for bad in ("../secrets.yaml", "../../configuration.yaml", "sub/x.js", "/etc/passwd"):
        try:
            publish._write_card_file(bad, b"x")
        except PermissionError:
            continue
        raise AssertionError(f"wrote outside the card folder: {bad}")
    assert files_under(CONFIG).keys() == after.keys()


def test_single_write_path_in_code():
    """B'1 in the code: the configuration folder appears in one module, and in it
    every file operation goes through _write_card_file."""
    pkg = APP / "pvmonitor"
    hits = [p.name for p in pkg.glob("*.py") if "homeassistant\"" in p.read_text() or "HA_CONFIG" in p.read_text()]
    assert hits == ["publish.py"], hits
    src = (pkg / "publish.py").read_text()
    body = src[src.index("def _write_card_file"):src.index("def install_card_files")]
    rest = src.replace(body, "")
    for op in ("write_bytes(", "write_text(", "open(", "mkdir(", ".replace(target", "unlink(", "rmtree(", "rename("):
        assert op not in rest, f"file operation {op} outside _write_card_file"
    for other in pkg.glob("*.py"):
        if other.name != "publish.py":
            assert "CARD_DIR" not in other.read_text(), other.name


async def run_against_ha():
    fake_ha.POSTED.clear()
    # state: missing -> written, unchanged -> left, after a restart -> written again
    assert await publish.ensure_state(LAYOUT) is True
    posted = fake_ha.POSTED[publish.ENTITY_ID]
    assert posted["state"] == publish.anlage(LAYOUT)[0] and posted["attributes"]["areas"][1]["name"] == "Süd"
    assert await publish.ensure_state(LAYOUT) is False
    fake_ha.POSTED.clear()  # Home Assistant restarted
    assert await publish.ensure_state(LAYOUT) is True
    assert await publish.ensure_state({"strings": [], "areas": [], "devices": []}) is False

    # resource: created once, then unchanged, then moved to the new version; others untouched
    others = [dict(r) for r in fake_ha.RESOURCES]
    assert await publish.ensure_resource() == "created"
    own = [r for r in fake_ha.RESOURCES if publish.is_own_resource(r)]
    assert len(own) == 1 and own[0]["url"] == "/local/pv-monitor/pv-monitor-card.js?v=0.11.0" and own[0]["type"] == "module"
    assert await publish.ensure_resource() == "unchanged"
    os.environ["PVMON_VERSION"] = "0.11.1"
    assert await publish.ensure_resource() == "updated"
    os.environ["PVMON_VERSION"] = "0.11.0"
    assert len([r for r in fake_ha.RESOURCES if publish.is_own_resource(r)]) == 1
    assert [r for r in fake_ha.RESOURCES if not publish.is_own_resource(r)] == others
    writes = [c for c in fake_ha.resource_calls if c["type"] != "lovelace/resources"]
    assert all(c["type"] == "lovelace/resources/create" or c["resource_id"] == own[0]["id"] for c in writes)
    assert not publish.is_own_resource({"url": "/local/pv-monitor/pv-monitor-card.js.bak"})
    assert not publish.is_own_resource({"url": "/local/pv-monitor-card.js"})

    # the keeper repairs a restart within one interval and stops cleanly
    fake_ha.POSTED.clear()
    stop = asyncio.Event()
    task = asyncio.create_task(publish.keep(lambda: LAYOUT, stop, interval=0.05))
    for _ in range(100):
        if publish.ENTITY_ID in fake_ha.POSTED:
            break
        await asyncio.sleep(0.02)
    assert publish.ENTITY_ID in fake_ha.POSTED
    fake_ha.POSTED.clear()
    for _ in range(100):
        if publish.ENTITY_ID in fake_ha.POSTED:
            break
        await asyncio.sleep(0.02)
    assert publish.ENTITY_ID in fake_ha.POSTED, "not repaired after a restart"
    stop.set()
    await asyncio.wait_for(task, 2)


def test_against_ha():
    asyncio.run(run_against_ha())


def test_layout_save_publishes():
    from starlette.testclient import TestClient

    from pvmonitor.server import app

    fake_ha.POSTED.clear()
    os.environ["PVMON_PUBLISH"] = "0"  # no keeper here: the save itself must publish
    with TestClient(app) as c:
        doc = json.loads(json.dumps(LAYOUT))
        assert c.put("/api/plant/layout", json=doc).status_code == 200
        for _ in range(100):
            if publish.ENTITY_ID in fake_ha.POSTED:
                break
            import time

            time.sleep(0.02)
    assert fake_ha.POSTED[publish.ENTITY_ID]["state"] == publish.anlage(LAYOUT)[0]


if __name__ == "__main__":
    fake_ha.start_in_thread(PORT)
    for name, fn in [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]:
        fn()
        print("ok", name)
