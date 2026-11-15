# PV Monitor

Home Assistant add-on for a private PV system. The start page draws the roof
with its strings, grid, battery and consumers, live or for a day, month or
year, from sensors picked in a setup page. The economics part covers investments,
tariff history with energy and base price, monthly values, amortisation and
effective price per drawn kWh. It replaces an Excel workbook and reproduces its
figures.

## Install

In Home Assistant: Settings → Add-ons → Add-on Store → ⋮ → Repositories, add
`https://github.com/azedler/pv-monitor`, then install **PV Monitor** and open it
from the sidebar. The data lives in the add-on's `/data` folder and is part of
its backup.

The history is imported once under **Daten** from the workbook.

## Develop

```
pip install -r pv_monitor/requirements.txt httpx
python tests/fake_ha.py 8123 &   # optional stand-in for Home Assistant
export PVMON_HA_URL=http://127.0.0.1:8123 PVMON_HA_TOKEN=test-token
cd pv_monitor/app && PVMON_DB=/tmp/pv.sqlite python -m uvicorn pvmonitor.server:app --port 8099
```

Tests are standalone scripts:

```
python tests/test_calc_against_workbook.py   # needs the private workbook, see its docstring
python tests/test_calc_rules.py
python tests/test_api.py
python tests/test_plant.py
python tests/test_migration.py
```

Captured values (readings, monthly values, tariffs, investments) are stored;
everything derived is recomputed on every request in `pvmonitor/calc.py`.
