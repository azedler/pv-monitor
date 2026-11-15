"""One-time import of the history from the workbook this application replaces.

Reads only captured cells (the yellow input cells, the investment list and the
tariff block). Derived columns are ignored: they are recomputed.
"""

from __future__ import annotations

import io
import re
from datetime import date, datetime

import openpyxl

from . import db
from .calc import FEED_IN, GRID, HEAT, billed_month

SHEET_MONTHS = "Verbrauch_Ertrag"
SHEET_INVEST = "Initial-Kosten"
SHEET_INPUT = "Eingabe"

# The workbook carries 1 / 0.0001 as placeholders before the battery existed.
BATTERY_PLACEHOLDER = (1, 0.0001)
STARTS_ON = re.compile(r"\bab (\d{2})\.(\d{2})\.(\d{4})")


class ImportError_(ValueError):
    """The file is not the expected workbook."""


def _iso(value):
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    return None


def _num(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _header_columns(ws, header_row):
    return {
        str(c.value).strip(): c.column for c in ws[header_row] if isinstance(c.value, str)
    }


def _find_header_row(ws, marker, max_row=40):
    for row in ws.iter_rows(min_row=1, max_row=max_row):
        for c in row:
            if c.value == marker:
                return c.row
    raise ImportError_(f"Spalte „{marker}“ nicht gefunden im Blatt „{ws.title}“")


def read_months(ws):
    head = _find_header_row(ws, "Zählerstand HS")
    col = _header_columns(ws, head)
    needed = ("Datum", "Zählerstand HS", "Zählerstand Einspeisung", "PV Ertrag")
    for name in needed:
        if name not in col:
            raise ImportError_(f"Spalte „{name}“ fehlt im Blatt „{ws.title}“")

    def cell(r, name):
        return ws.cell(r, col[name]).value if name in col else None

    months, heat_prices, feed_prices = [], [], []
    for r in range(head + 1, ws.max_row + 1):
        reading_date = _iso(cell(r, "Datum"))
        grid = _num(cell(r, "Zählerstand HS"))
        if reading_date is None or grid is None:
            continue
        month = billed_month(reading_date)
        charged = _num(cell(r, "Batterieladen"))
        discharged = _num(cell(r, "Batterieentladen"))
        if (charged, discharged) == BATTERY_PLACEHOLDER:
            charged = discharged = None
        months.append(
            {
                "month": month,
                "reading_date": reading_date,
                "grid_reading": grid,
                "feed_reading": _num(cell(r, "Zählerstand Einspeisung")),
                "heat_reading": _num(cell(r, "Zählerstand WS")),
                "pv_yield": _num(cell(r, "PV Ertrag")),
                "battery_charged": charged,
                "battery_discharged": discharged,
            }
        )
        heat_prices.append((month, _num(cell(r, "Strompreis WS"))))
        feed_prices.append((month, _num(cell(r, "Einspeisevergütung"))))
    if not months:
        raise ImportError_("Keine Monatswerte gefunden")
    return months, heat_prices, feed_prices


def _periods(kind, per_month, note):
    """Collapse a per-month price column into tariff periods."""
    tariffs, last = [], None
    for month, price in per_month:
        if price is None or price == last:
            continue
        tariffs.append(
            {"kind": kind, "valid_from": f"{month}-01", "energy_price": price, "note": note}
        )
        last = price
    return tariffs


def read_grid_tariffs(ws):
    head = _find_header_row(ws, "gilt ab Abrechnungsmonat", max_row=ws.max_row)
    col = _header_columns(ws, head)
    c_from = col["gilt ab Abrechnungsmonat"]
    c_price = next(v for k, v in col.items() if k.startswith("Arbeitspreis"))
    c_base = next(v for k, v in col.items() if k.startswith("Grundpreis"))
    c_note = next((v for k, v in col.items() if k.startswith("Anbieter")), None)
    tariffs = []
    for r in range(head + 1, ws.max_row + 1):
        valid_from = _iso(ws.cell(r, c_from).value)
        price = _num(ws.cell(r, c_price).value)
        if valid_from is None or price is None:
            continue
        note = ws.cell(r, c_note).value if c_note else None
        note = note.strip() if isinstance(note, str) else None
        starts_on = None
        provider = None
        if note:
            m = STARTS_ON.search(note)
            if m:
                starts_on = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
                provider = note[: m.start()].rstrip(" ,") or None
        tariffs.append(
            {
                "kind": GRID,
                "valid_from": valid_from,
                "starts_on": starts_on,
                "energy_price": price,
                "base_price_year": _num(ws.cell(r, c_base).value),
                "provider": provider,
                "note": note,
            }
        )
    if not tariffs:
        raise ImportError_("Kein Tarif im Tarifblock gefunden")
    return tariffs


def read_investments(ws):
    head = _find_header_row(ws, "Posten")
    col = _header_columns(ws, head)
    items = []
    for r in range(head + 1, ws.max_row + 1):
        label = ws.cell(r, col["Posten"]).value
        amount = _num(ws.cell(r, col["Kosten"]).value)
        if not isinstance(label, str) or amount is None:
            continue
        items.append(
            {
                "date": _iso(ws.cell(r, col["Datum"]).value) if "Datum" in col else None,
                "quantity": _num(ws.cell(r, col["Anzahl"]).value) if "Anzahl" in col else None,
                "label": label.strip(),
                "amount": amount,
            }
        )
    if not items:
        raise ImportError_("Keine Investitionsposten gefunden")
    return items


def parse_workbook(content: bytes):
    try:
        # data_only: an input cell may hold a small formula such as "=28806+1970"
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    except Exception as exc:  # openpyxl raises many types for a non-xlsx file
        raise ImportError_("Die Datei ist keine lesbare xlsx-Arbeitsmappe") from exc
    for name in (SHEET_MONTHS, SHEET_INVEST, SHEET_INPUT):
        if name not in wb.sheetnames:
            raise ImportError_(f"Blatt „{name}“ fehlt")
    months, heat_prices, feed_prices = read_months(wb[SHEET_MONTHS])
    tariffs = read_grid_tariffs(wb[SHEET_INPUT])
    tariffs += _periods(HEAT, heat_prices, "Wärmestrom, aus der Excel übernommen")
    tariffs += _periods(FEED_IN, feed_prices, "Einspeisevergütung, aus der Excel übernommen")
    return {"months": months, "tariffs": tariffs, "investments": read_investments(wb[SHEET_INVEST])}


def import_workbook(con, content: bytes):
    """Replace the stored history with the workbook's. Returns counts."""
    data = parse_workbook(content)
    db.clear_history(con)
    for item in data["investments"]:
        db.insert(con, "investments", db.INVESTMENT_FIELDS, item)
    for tariff in data["tariffs"]:
        db.insert(con, "tariffs", db.TARIFF_FIELDS, tariff)
    db.ensure_default_meters(con)
    heat_months = [m["month"] for m in data["months"] if m["heat_reading"] is not None]
    if heat_months:
        db.insert(
            con,
            "meters",
            ("label", "kind", "active_from", "active_to"),
            {
                "label": "Wärmestrom",
                "kind": HEAT,
                "active_from": f"{heat_months[0]}-01",
                "active_to": f"{heat_months[-1]}-01",
            },
        )
    for month in data["months"]:
        db.save_month(con, month["month"], month, source="import")
    con.commit()
    return {k: len(v) for k, v in data.items()}
