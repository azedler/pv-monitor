"""A synthetic workbook with the layout of the real one and invented figures.

The real workbook is private and not part of the repository. Sheet names,
header texts and header positions here mirror it, so the importer is exercised
on the same shape.
"""

import io
from datetime import datetime

import openpyxl

PV_BY_MONTH = [150, 300, 900, 1800, 2300, 2600, 2700, 2400, 1700, 900, 300, 120]

# (valid from, energy price, base price per year, note)
GRID_TARIFFS = [
    (datetime(2023, 10, 1), 0.30, None, "Monatswert"),
    (datetime(2024, 2, 1), 0.28, 120.0, "Anbieter A, ab 24.02.2024"),
    (datetime(2025, 2, 1), 0.25, 300.0, "Anbieter B, ab 24.02.2025"),
]
FEED_IN_PRICE = 0.08
HEAT_PRICE = 0.22

# (date, quantity, label, amount)
INVESTMENTS = [
    (datetime(2023, 4, 5), None, "Wechselrichter", 3000.0),
    (datetime(2023, 5, 1), 40, "Module", 12000.0),
    (datetime(2023, 9, 13), None, "Kabel", 400.0),
    (None, None, "Speicher", 4000.0),
    (None, None, "Verkauf Altgerät", -500.0),
]
INVEST_TOTAL = sum(i[3] for i in INVESTMENTS)
MONTH_COUNT = 26  # baseline 2023-10 plus 25 months up to 2025-11
LAST_MONTH = "2025-11"
BATTERY_FROM = (2024, 11)
HEAT_UNTIL = (2024, 10)


def build() -> bytes:
    wb = openpyxl.Workbook()
    inp = wb.active
    inp.title = "Eingabe"
    for col, text in zip(
        "BCDE",
        (
            "gilt ab Abrechnungsmonat",
            "Arbeitspreis €/kWh brutto",
            "Grundpreis €/Jahr brutto",
            "Anbieter / Notiz",
        ),
    ):
        inp[f"{col}39"] = text
    for i, (valid_from, price, base, note) in enumerate(GRID_TARIFFS):
        inp[f"B{40 + i}"], inp[f"C{40 + i}"], inp[f"E{40 + i}"] = valid_from, price, note
        if base is not None:
            inp[f"D{40 + i}"] = base

    inv = wb.create_sheet("Initial-Kosten")
    for col, text in zip("CDEF", ("Datum", "Anzahl", "Posten", "Kosten")):
        inv[f"{col}2"] = text
    for i, (when, qty, label, amount) in enumerate(INVESTMENTS):
        r = 3 + i
        if when:
            inv[f"C{r}"] = when
        if qty:
            inv[f"D{r}"] = qty
        inv[f"E{r}"], inv[f"F{r}"] = label, amount
    inv[f"C{4 + len(INVESTMENTS)}"] = "Ergebnis"

    ws = wb.create_sheet("Verbrauch_Ertrag")
    headers = {
        "A": "Datum", "D": "Monat", "E": "Zählerstand HS", "G": "Zählerstand WS",
        "I": "Zählerstand Einspeisung", "K": "PV Ertrag", "M": "Batterieladen",
        "N": "Batterieentladen", "T": "Strompreis WS", "X": "Einspeisevergütung",
    }
    ws["A1"] = "Initialkosten"
    for col, text in headers.items():
        ws[f"{col}11"] = text
    grid, heat, feed = 20000, 15000, 100
    year, month = 2023, 10  # billed month
    for i in range(MONTH_COUNT):
        r = 12 + i
        pv = 0 if i == 0 else PV_BY_MONTH[month - 1]
        if i:
            grid += 300 + (600 if month in (11, 12, 1, 2) else 0)
            feed += round(pv * 0.6)
        read_year, read_month = (year + 1, 1) if month == 12 else (year, month + 1)
        ws[f"A{r}"] = datetime(read_year, read_month, 5)
        ws[f"D{r}"] = f"{month}/{year}"
        ws[f"E{r}"], ws[f"I{r}"], ws[f"K{r}"] = grid, feed, pv
        if (year, month) <= HEAT_UNTIL:
            if i:
                heat += 100
            ws[f"G{r}"], ws[f"T{r}"] = heat, HEAT_PRICE
        if (year, month) >= BATTERY_FROM:
            ws[f"M{r}"], ws[f"N{r}"] = 200, 172
        else:
            ws[f"M{r}"], ws[f"N{r}"] = 1, 0.0001
        ws[f"X{r}"] = FEED_IN_PRICE
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
