# PV Monitor

Home Assistant add-on for a private PV system. The start page tells the year:
yield and grid draw per month, autarky, value, where the energy went; further
pages show the months since start and the battery with its own payback. The
plant page draws the roof with its strings, grid, battery and consumers, live or
for a day, month or year. The economics part covers investments,
tariff history with energy and base price, monthly values, amortisation and
effective price per drawn kWh, plus a forecast of the running billing period.

## Install

In Home Assistant: Settings → Add-ons → Add-on Store → ⋮ → Repositories, add
`https://github.com/azedler/pv-monitor`, then install **PV Monitor** and open it
from the sidebar. The data lives in the add-on's `/data` folder and is part of
its backup.

The add-on also provides a roof card for dashboards: add a card of type
`custom:pv-monitor-roof-card`. It is installed by the add-on itself (files in
`/config/www/pv-monitor/`, one Lovelace resource) and draws the layout from the
state `sensor.pv_monitor_anlage`. Removal is described in `CHANGELOG.md` 0.11.0.

## Develop

```
pip install -r pv_monitor/requirements.txt httpx
python tests/fake_ha.py 8123 &   # optional stand-in for Home Assistant
export PVMON_HA_URL=http://127.0.0.1:8123 PVMON_HA_TOKEN=test-token
cd pv_monitor/app && PVMON_DB=/tmp/pv.sqlite python -m uvicorn pvmonitor.server:app --port 8099
```

Tests are standalone scripts:

```
python tests/test_calc_rules.py
python tests/test_api.py
python tests/test_plant.py
python tests/test_migration.py
python tests/test_publish.py
python tests/test_cache.py
python tests/test_investment_categories.py
python tests/test_targets.py
```

Captured values (readings, monthly values, tariffs, investments) are stored;
everything derived is recomputed on every request in `pvmonitor/calc.py`.

Changes per version: `CHANGELOG.md`. The fonts Inter and Space Grotesk ship
with the add-on under the SIL Open Font License 1.1
(`pv_monitor/app/pvmonitor/static/fonts/OFL.txt`).
