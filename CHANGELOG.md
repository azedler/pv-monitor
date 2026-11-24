# Changelog

## 0.11.0 (24.11.2026)

Roof card for Home Assistant dashboards (Doc 143). The add-on's own pages and
figures are unchanged.

- **New state `sensor.pv_monitor_anlage`**: the roof layout from "Einrichtung"
  (strings with module count, kWp and power sensor; areas with their cells),
  about 1 KB. Set at start, immediately when the layout is saved, and checked
  every 60 seconds, so it is back at most one minute after Home Assistant
  restarts. It is a plain state: no entity in the registry, no history needed.
- **New card `custom:pv-monitor-roof-card`**: modules at their place, coloured
  per string by power per kWp, total power, light/dark following Home
  Assistant, a button that opens the PV Monitor panel. Live values come
  straight from the power sensors, so the card keeps working while the add-on
  is stopped. Without the state it says "Anordnung nicht verfügbar".
- **The add-on now writes into the Home Assistant configuration**, and only
  there: the folder `www/pv-monitor/` (the card and its font). Home Assistant
  offers no narrower mapping than the whole configuration folder, so the code
  allows exactly one write function, which refuses every other path.
- **One Lovelace resource** `/local/pv-monitor/pv-monitor-card.js?v=<version>`
  is created, or updated on a new version. Other resources are not touched.
- Removal: stopping or uninstalling the add-on leaves the card, the resource
  and (until the next restart of Home Assistant) the state in place. To remove
  them, delete the folder `/config/www/pv-monitor/` and the resource under
  Settings → Dashboards → ⋮ → Resources, and take the card off the dashboards.

## 0.10.0 (24.11.2026)

New design (Doc 142 Teil B). The figures are computed exactly as before; only
the presentation and three new overview pages are new.

- **Start page "Jahr"**: the year as a sun (yield outwards, grid draw inwards,
  one segment per month), autarky, own-consumption quota and value, plus "where
  did the solar energy go" and "where did the consumption come from". Ranges:
  last 12 months, every calendar year, since start.
- **"Monate"**: yield against grid draw for the whole history, months before
  the EEG commissioning on a grey band, autarky per month, year comparison.
- **"Speicher"**: charged, discharged, loss and efficiency per month, and the
  battery's own payback from the investments of category "Speicher" (benefit =
  discharged kWh at that month's energy price minus charged kWh at the feed-in
  tariff; projection with 1.5 %/year ageing and 0/2/4 %/year price rise).
- Every page names the time range of its figures.
- Dark and light theme, following the device automatically, with a switch
  Auto / Hell / Dunkel stored per device.
- All other pages (Anlage, Wirtschaft, Auswertungen, Erfassung, Tarife,
  Investitionen, Einrichtung) in the new style; "Monate" (entry) is now
  "Erfassung".
- Fonts Inter and Space Grotesk ship with the add-on; the page loads nothing
  from outside.
- New setting "EEG-Inbetriebnahme" under Tarife → Anlage.

Before updating: tick "create backup" in the update dialog. That backup is the
way back to 0.9.2, because Home Assistant cannot install an older add-on version.

## 0.9.2 (15.11.2026)

Date and month fields and the pinned table corner fixed on iOS.
