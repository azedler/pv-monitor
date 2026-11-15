"""SQLite storage. Only captured values live here; nothing derived is stored."""

from __future__ import annotations

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS investments (
    id INTEGER PRIMARY KEY,
    date TEXT,
    quantity REAL,
    label TEXT NOT NULL,
    amount REAL NOT NULL,
    category TEXT
);
CREATE TABLE IF NOT EXISTS tariffs (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('grid', 'heat', 'feed_in')),
    valid_from TEXT NOT NULL,
    starts_on TEXT,
    energy_price REAL NOT NULL,
    base_price_year REAL,
    provider TEXT,
    note TEXT,
    contract_end TEXT,
    price_guarantee_until TEXT
);
CREATE TABLE IF NOT EXISTS meters (
    id INTEGER PRIMARY KEY,
    label TEXT NOT NULL,
    number TEXT,
    kind TEXT NOT NULL CHECK (kind IN ('grid', 'heat', 'feed_in')),
    active_from TEXT,
    active_to TEXT
);
CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY,
    meter_id INTEGER NOT NULL REFERENCES meters(id) ON DELETE CASCADE,
    month TEXT NOT NULL,
    date TEXT,
    value REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    photo TEXT,
    UNIQUE (meter_id, month)
);
CREATE TABLE IF NOT EXISTS monthly_values (
    month TEXT PRIMARY KEY,
    reading_date TEXT,
    pv_yield REAL,
    battery_charged REAL,
    battery_discharged REAL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

INVESTMENT_FIELDS = ("date", "quantity", "label", "amount", "category")
TARIFF_FIELDS = (
    "kind",
    "valid_from",
    "starts_on",
    "energy_price",
    "base_price_year",
    "provider",
    "note",
    "contract_end",
    "price_guarantee_until",
)
READING_KINDS = {"grid": "grid_reading", "feed_in": "feed_reading", "heat": "heat_reading"}
DEFAULT_METERS = (("Hausstrom", "grid"), ("Einspeisung", "feed_in"))


def connect(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    return con


def rows(con, sql, args=()):
    return [dict(r) for r in con.execute(sql, args)]


def insert(con, table, fields, data) -> int:
    cols = ", ".join(fields)
    marks = ", ".join("?" for _ in fields)
    cur = con.execute(
        f"INSERT INTO {table} ({cols}) VALUES ({marks})", [data.get(f) for f in fields]
    )
    return cur.lastrowid


def update(con, table, fields, row_id, data) -> bool:
    sets = ", ".join(f"{f} = ?" for f in fields)
    cur = con.execute(
        f"UPDATE {table} SET {sets} WHERE id = ?", [data.get(f) for f in fields] + [row_id]
    )
    return cur.rowcount > 0


def get_setting(con, key, default=None):
    row = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return default if row is None else row["value"]


def set_setting(con, key, value):
    con.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def meter_for(con, kind, create_label=None):
    row = con.execute(
        "SELECT id FROM meters WHERE kind = ? ORDER BY active_to IS NOT NULL, id DESC", (kind,)
    ).fetchone()
    if row:
        return row["id"]
    if create_label is None:
        return None
    return insert(con, "meters", ("label", "kind"), {"label": create_label, "kind": kind})


def ensure_default_meters(con):
    for label, kind in DEFAULT_METERS:
        meter_for(con, kind, create_label=label)


def month_rows(con):
    """Monthly values joined with the meter readings of that month."""
    months = {r["month"]: r for r in rows(con, "SELECT * FROM monthly_values")}
    for r in rows(
        con,
        "SELECT r.month, r.date, r.value, r.source, m.kind FROM readings r "
        "JOIN meters m ON m.id = r.meter_id",
    ):
        row = months.setdefault(r["month"], {"month": r["month"], "reading_date": r["date"]})
        row[READING_KINDS[r["kind"]]] = r["value"]
        if not row.get("reading_date"):
            row["reading_date"] = r["date"]
    return [months[m] for m in sorted(months)]


def save_month(con, month, data, source="manual"):
    con.execute(
        "INSERT INTO monthly_values (month, reading_date, pv_yield, battery_charged, "
        "battery_discharged) VALUES (?, ?, ?, ?, ?) ON CONFLICT(month) DO UPDATE SET "
        "reading_date = excluded.reading_date, pv_yield = excluded.pv_yield, "
        "battery_charged = excluded.battery_charged, "
        "battery_discharged = excluded.battery_discharged",
        (
            month,
            data.get("reading_date"),
            data.get("pv_yield"),
            data.get("battery_charged"),
            data.get("battery_discharged"),
        ),
    )
    labels = {"grid": "Hausstrom", "feed_in": "Einspeisung", "heat": "Wärmestrom"}
    for kind, field in READING_KINDS.items():
        value = data.get(field)
        meter_id = meter_for(con, kind, create_label=None if value is None else labels[kind])
        if meter_id is None:
            continue
        if value is None:
            con.execute("DELETE FROM readings WHERE meter_id = ? AND month = ?", (meter_id, month))
            continue
        con.execute(
            "INSERT INTO readings (meter_id, month, date, value, source) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(meter_id, month) DO UPDATE SET date = excluded.date, "
            "value = excluded.value, source = excluded.source",
            (meter_id, month, data.get("reading_date"), value, source),
        )


def delete_month(con, month):
    con.execute("DELETE FROM readings WHERE month = ?", (month,))
    con.execute("DELETE FROM monthly_values WHERE month = ?", (month,))


def clear_history(con):
    for table in ("readings", "monthly_values", "meters", "tariffs", "investments"):
        con.execute(f"DELETE FROM {table}")
