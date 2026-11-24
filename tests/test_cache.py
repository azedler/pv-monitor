"""After an update the browser must load the new page and the new scripts.

index.html is revalidated on every load (Cache-Control: no-cache) and names
every script and style sheet with ?v=<version>, so an old cached copy of a
script can never run under a new page.

Run: python3 tests/test_cache.py
"""

import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pv_monitor" / "app"))
STATIC = ROOT / "pv_monitor" / "app" / "pvmonitor" / "static"

os.environ["PVMON_DB"] = os.path.join(tempfile.mkdtemp(), "test.sqlite")
os.environ.pop("SUPERVISOR_TOKEN", None)
os.environ["PVMON_PUBLISH"] = "0"

from starlette.testclient import TestClient  # noqa: E402

from pvmonitor.server import app  # noqa: E402

RAW = (STATIC / "index.html").read_text(encoding="utf-8")
LOCAL_REFS = re.findall(r'(?:src|href)="([\w.-]+\.(?:js|css))"', RAW)


def page_refs(html):
    return re.findall(r'(?:src|href)="([\w.-]+\.(?:js|css))(?:\?v=([^"]+))?"', html)


def test_release_version():
    os.environ["PVMON_VERSION"] = "0.11.1"
    c = TestClient(app)
    for path in ("/", "/index.html"):
        r = c.get(path)
        assert r.status_code == 200, path
        assert r.headers["cache-control"] == "no-cache", path
        refs = page_refs(r.text)
        # every script and style sheet of the page, each with the version
        assert sorted(n for n, _ in refs) == sorted(LOCAL_REFS), refs
        assert all(v == "0.11.1" for _, v in refs), refs
    assert set(LOCAL_REFS) >= {"style.css", "app.js", "story.js", "plant.js", "charts.js"}
    # the versioned addresses are served
    for name in LOCAL_REFS:
        assert c.get(f"/{name}?v=0.11.1").status_code == 200, name
    # the data is not cached by the page either: API answers are JSON per request
    assert c.get("/api/state").status_code == 200


def test_development_hash():
    os.environ["PVMON_VERSION"] = "dev"
    refs = page_refs(TestClient(app).get("/").text)
    assert all(re.fullmatch(r"dev-[0-9a-f]{8}", v) for _, v in refs), refs


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
