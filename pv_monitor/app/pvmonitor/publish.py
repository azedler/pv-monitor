"""What the add-on hands to Home Assistant (Doc 143).

Three things, and nothing else:
1. the state ``sensor.pv_monitor_anlage`` that describes the roof layout,
2. the roof card file (and its number font) in ``www/pv-monitor/`` of the
   Home Assistant configuration,
3. the one Lovelace resource that loads that card.

The add-on may write to the whole configuration folder (Home Assistant has no
narrower mapping), so every write below it goes through ``_write_card_file``,
which refuses any path outside ``CARD_DIR``. CARD_DIR is defined only here.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import socket
from pathlib import Path

from . import ha, plant

log = logging.getLogger("pvmonitor.publish")

ENTITY_ID = "sensor.pv_monitor_anlage"
SCHEMA = 1
MAX_ATTRIBUTE_BYTES = 8 * 1024

STATIC = Path(__file__).parent / "static"
CARD_SOURCE = STATIC / "pv-monitor-card.js"
FONT_SOURCE = STATIC / "fonts" / "space-grotesk.woff2"

# The configuration folder as the supervisor mounts it for `homeassistant_config`.
HA_CONFIG = Path(os.environ.get("PVMON_HA_CONFIG", "/homeassistant"))
# The only place below the Home Assistant configuration the add-on writes to (B'1).
CARD_DIR = HA_CONFIG / "www" / "pv-monitor"
CARD_FILES = {"pv-monitor-card.js": CARD_SOURCE, "space-grotesk.woff2": FONT_SOURCE}
RESOURCE_PATH = "/local/pv-monitor/pv-monitor-card.js"

CHECK_SECONDS = 60


def version() -> str:
    return os.environ.get("PVMON_VERSION") or "dev"


def panel_path():
    """Sidebar path of the add-on's ingress panel, e.g. /2cf783c6_pv_monitor."""
    slug = os.environ.get("PVMON_SLUG")
    if not slug and os.environ.get("SUPERVISOR_TOKEN"):
        slug = socket.gethostname().replace("-", "_")  # the supervisor names the container after the slug
    return f"/{slug}" if slug else None


# ------------------------------------------------------------------ the state


def anlage(layout):
    """(state, attributes) of sensor.pv_monitor_anlage for a layout.

    The state is a short fingerprint of the layout, so a change is visible as
    a state change; the attributes carry what the card needs to draw it.
    """
    counts = plant.module_counts(layout)
    strings = []
    for s in layout["strings"]:
        kwp = counts[s["id"]] * s["module_watts"] / 1000 if s["module_watts"] else None
        strings.append({
            "id": s["id"],
            "name": s["name"],
            "modules": counts[s["id"]],
            "kwp": round(kwp, 3) if kwp else None,
            "power_entity": s["power_entity"],
        })
    areas = [{
        "id": a["id"],
        "name": a["name"],
        "azimuth": a["azimuth"],
        "cols": a["cols"],
        "rows": a["rows"],
        # one character per cell: "." empty, otherwise the string's position in "strings"
        "cells": "".join("." if c is None else _cell_code(layout, c) for c in a["cells"]),
    } for a in layout["areas"]]
    body = {"schema": SCHEMA, "strings": strings, "areas": areas}
    fingerprint = hashlib.sha1(json.dumps(body, sort_keys=True).encode()).hexdigest()[:10]
    attributes = {
        **body,
        "addon_version": version(),
        "panel": panel_path(),
        "friendly_name": "PV Monitor Anlage",
        "icon": "mdi:solar-panel-large",
    }
    return fingerprint, attributes


CODES = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _cell_code(layout, string_id):
    index = next(i for i, s in enumerate(layout["strings"]) if s["id"] == string_id)
    return CODES[index]


def attribute_bytes(attributes) -> int:
    return len(json.dumps(attributes, ensure_ascii=False).encode())


async def publish_state(layout):
    state, attributes = anlage(layout)
    if attribute_bytes(attributes) > MAX_ATTRIBUTE_BYTES:
        raise ValueError("Die Anordnung ist für den Zustand zu groß")
    await ha.set_state(ENTITY_ID, state, attributes)
    return state


async def ensure_state(layout):
    """Set the state if Home Assistant lacks it or holds an older one (after a
    restart of Home Assistant it is gone). Returns True if it was written."""
    if not layout["strings"] or not layout["areas"]:
        return False
    state, _ = anlage(layout)
    current = await ha.get_state(ENTITY_ID)
    if current and current.get("state") == state and (current.get("attributes") or {}).get("addon_version") == version():
        return False
    await publish_state(layout)
    return True


# ------------------------------------------------------------------ the card


def _write_card_file(name: str, data: bytes) -> Path:
    """The single write below the Home Assistant configuration (B'1)."""
    target = (CARD_DIR / name).resolve()
    if target.parent != CARD_DIR.resolve():
        raise PermissionError(f"Schreiben außerhalb von {CARD_DIR} ist nicht erlaubt: {name}")
    CARD_DIR.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    temp.write_bytes(data)
    temp.replace(target)
    return target


def install_card_files():
    """Copy the card and its font next to each other; unchanged files are left alone."""
    if not HA_CONFIG.is_dir():
        return []
    written = []
    for name, source in CARD_FILES.items():
        data = source.read_bytes()
        target = CARD_DIR / name
        if target.is_file() and target.read_bytes() == data:
            continue
        written.append(_write_card_file(name, data))
    return written


def resource_url() -> str:
    return f"{RESOURCE_PATH}?v={version()}"


def is_own_resource(resource) -> bool:
    """Only the resource that loads this card counts as ours (B'2)."""
    return str(resource.get("url", "")).split("?", 1)[0] == RESOURCE_PATH


async def ensure_resource():
    """Create or update the Lovelace resource of the card; touch no other.

    Returns "created", "updated" or "unchanged".
    """
    (resources,) = await ha.ws_commands([{"type": "lovelace/resources"}])
    own = [r for r in resources or [] if is_own_resource(r)]
    url = resource_url()
    if not own:
        await ha.ws_commands([{"type": "lovelace/resources/create", "res_type": "module", "url": url}])
        return "created"
    first = own[0]
    if first.get("url") == url and first.get("type") == "module":
        return "unchanged"
    await ha.ws_commands([{"type": "lovelace/resources/update", "resource_id": first["id"], "res_type": "module", "url": url}])
    return "updated"


# ------------------------------------------------------------------ the keeper


async def keep(load_layout, stop: asyncio.Event, interval: float = CHECK_SECONDS):
    """Background task: card files once, then resource and state until they hold.

    The state is checked every ``interval`` seconds, so a restart of Home
    Assistant (which drops states set through the API) is repaired within it.
    """
    try:
        for path in install_card_files():
            log.info("Karte geschrieben: %s", path)
    except OSError as exc:
        log.warning("Karte nicht geschrieben: %s", exc)
    resource_done = False
    while not stop.is_set():
        if ha.available():
            try:
                if not resource_done:
                    log.info("Lovelace-Ressource: %s", await ensure_resource())
                    resource_done = True
            except ha.HaError as exc:
                log.warning("Lovelace-Ressource nicht gesetzt: %s", exc)
            try:
                if await ensure_state(load_layout()):
                    log.info("%s gesetzt", ENTITY_ID)
            except (ha.HaError, ValueError) as exc:
                log.warning("%s nicht gesetzt: %s", ENTITY_ID, exc)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
