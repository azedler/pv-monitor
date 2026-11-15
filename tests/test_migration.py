"""A database created by an earlier release is upgraded in place.

Run: python3 tests/test_migration.py
"""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pv_monitor" / "app"))

from pvmonitor import db  # noqa: E402

# the tariffs table exactly as release 0.1.0 created it
OLD_TARIFFS = """
CREATE TABLE tariffs (
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
"""


def main():
    path = os.path.join(tempfile.mkdtemp(), "old.sqlite")
    old = sqlite3.connect(path)
    old.executescript(OLD_TARIFFS)
    old.execute("INSERT INTO tariffs (kind, valid_from, energy_price, provider) VALUES ('grid', '2024-02-01', 0.28, 'A')")
    for note in db.STALE_NOTES + ("Monatswert, netto",):
        old.execute("INSERT INTO tariffs (kind, valid_from, energy_price, note) VALUES ('heat', '2023-10-01', 0.2, ?)", (note,))
    old.commit()
    old.close()

    con = db.connect(path)
    rows = db.rows(con, "SELECT * FROM tariffs")
    assert len(rows) == 4 and rows[0]["provider"] == "A" and rows[0]["monthly_payment"] is None, rows
    # the import's origin notes are gone, a note the user can use stays
    assert [r["note"] for r in rows[1:]] == [None, None, "Monatswert, netto"], rows
    assert db.update(con, "tariffs", db.TARIFF_FIELDS, rows[0]["id"], dict(rows[0], monthly_payment=120.0))
    con.commit()
    con.close()
    con = db.connect(path)  # a second start must not try to add the column again
    assert db.rows(con, "SELECT monthly_payment FROM tariffs")[0]["monthly_payment"] == 120.0
    # every field the code writes exists as a column
    columns = {r["name"] for r in con.execute("PRAGMA table_info(tariffs)")}
    assert set(db.TARIFF_FIELDS) <= columns, set(db.TARIFF_FIELDS) - columns
    print("ok: migration")


if __name__ == "__main__":
    main()
