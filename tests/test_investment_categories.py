"""Category per investment post, chosen in the list (Doc 142 §12.3 B3).

Runs through the real API and database: the inline field changes only the
category, the total stays, and the sum shown for "Speicher" is exactly the
cost the storage page uses.

Run: python3 tests/test_investment_categories.py
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pv_monitor" / "app"))
sys.path.insert(0, str(ROOT / "tests"))

os.environ["PVMON_DB"] = os.path.join(tempfile.mkdtemp(), "test.sqlite")
os.environ.pop("SUPERVISOR_TOKEN", None)
os.environ["PVMON_PUBLISH"] = "0"
os.environ["PVMON_TODAY"] = "2025-12-10"

from starlette.testclient import TestClient  # noqa: E402

import sample_data as fx  # noqa: E402
from pvmonitor import calc, db  # noqa: E402
from pvmonitor.server import app  # noqa: E402


def by_label(state, label):
    return next(i for i in state["investments"] if i["label"] == label)


def main():
    c = TestClient(app)
    c.get("/api/state")  # creates the schema
    con = db.connect(os.environ["PVMON_DB"])
    fx.fill(con)
    # a category typed by hand in an older version, in other spelling
    con.execute("UPDATE investments SET category = 'speicher ' WHERE label = 'Speicher'")
    con.execute("UPDATE investments SET category = 'Altbestand' WHERE label = 'Kabel'")
    con.commit()
    con.close()

    state = c.get("/api/state").json()
    cats = state["investment_categories"]
    # offered: the fixed list plus what the data already holds, nothing renamed
    for name in calc.INVESTMENT_CATEGORIES:
        assert name in cats["options"], name
    assert "Altbestand" in cats["options"] and "speicher " not in cats["options"]
    assert by_label(state, "Speicher")["category"] == "speicher "  # stored value untouched
    assert cats["uncategorized"] == 3
    total = state["summary"]["invest_total"]
    assert abs(cats["total"] - total) < 1e-9 and abs(total - fx.INVEST_TOTAL) < 1e-9

    def storage_row(s):
        return next((t for t in s["investment_categories"]["totals"] if t["category"] == "Speicher"), None)

    # the same key on both pages: "speicher " counts as Speicher
    assert storage_row(state)["total"] == state["storage"]["cost"] == 4000.0

    # inline change: only the category of this post
    inv = by_label(state, "Wechselrichter")
    after = c.put(f"/api/investments/{inv['id']}/category", json={"category": "Speicher"}).json()
    changed = by_label(after, "Wechselrichter")
    assert changed["category"] == "Speicher"
    assert {k: v for k, v in changed.items() if k != "category"} == {k: v for k, v in inv.items() if k != "category"}
    assert storage_row(after)["total"] == after["storage"]["cost"] == 7000.0 and after["storage"]["items"] == 2
    assert after["investment_categories"]["uncategorized"] == 2
    assert abs(after["summary"]["invest_total"] - fx.INVEST_TOTAL) < 1e-9

    # back to "without", and a category the list does not know yet
    after = c.put(f"/api/investments/{inv['id']}/category", json={"category": None}).json()
    assert by_label(after, "Wechselrichter")["category"] is None
    after = c.put(f"/api/investments/{inv['id']}/category", json={"category": "Hütte"}).json()
    assert by_label(after, "Wechselrichter")["category"] == "Hütte"
    hut = next(t for t in after["investment_categories"]["totals"] if t["category"] == "Hütte")
    assert hut == {"category": "Hütte", "total": 3000.0, "items": 1}
    # every post counted once
    rows = after["investment_categories"]["totals"]
    assert sum(t["items"] for t in rows) == len(after["investments"])
    assert abs(sum(t["total"] for t in rows) - fx.INVEST_TOTAL) < 1e-9

    # refused: unknown post, missing field, wrong type; nothing changes then
    assert c.put("/api/investments/9999/category", json={"category": "Module"}).status_code == 404
    assert c.put(f"/api/investments/{inv['id']}/category", json={}).status_code == 400
    assert c.put(f"/api/investments/{inv['id']}/category", json={"category": 5}).status_code == 400
    assert by_label(c.get("/api/state").json(), "Wechselrichter")["category"] == "Hütte"

    # the page offers the field and the sums
    js = c.get("/app.js").text
    assert "api/investments/${id}/category" in js and "cat-totals" in js
    print("ok test_investment_categories")


if __name__ == "__main__":
    main()
