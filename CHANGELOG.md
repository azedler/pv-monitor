# Changelog

## 0.11.3 (24.11.2026)

- Investment categories are the build targets: **PV-Anlage, Speicher,
  Hundehütte**. Categories already in the data stay choosable; nothing is
  renamed. "Speicher" still feeds the storage page.

## 0.11.2 (24.11.2026)

Wide tables and categories in the investment list (Doc 142 §12.3 B1, B3). No
change to stored data or to how figures are computed.

- **Wide tables**: every table scrolls sideways inside its own box, never the
  page; the first column stays in place. A fade at the edge shows that there
  are more columns (scroll bars are hidden on tablets and Macs). The monthly
  table ("Erfassung") also scrolls vertically inside its box with a fixed
  header, so its sideways scroll bar is on screen instead of below 30 rows.
  Headers are written out ("Eigenverbrauchsquote", "Batterie-Wirkungsgrad",
  "Erlös kumuliert").
- **Investments**: a column "Kategorie" with a choice field in each row. A
  change is saved at once for that post only (just the category) and the row
  says "gespeichert"; if saving fails, the old value stays and the row shows
  why. Posts without a category are marked and counted above the list. Below
  the list: the sum per category; the sum "Speicher" is the cost the storage
  page uses. Offered categories: see 0.11.3, plus every
  category already in the data (nothing is renamed). The form keeps free text with these as
  suggestions.
- New API: `PUT api/investments/<id>/category` with `{"category": ...}`.

## 0.11.1 (24.11.2026)

Cache protection after updates (Doc 142 §11.1). No change to data, figures or
the roof card.

- The page (`index.html`) is sent with `Cache-Control: no-cache`, so the
  browser asks for it again on every load.
- The page names every script and style sheet with the add-on version
  (`app.js?v=0.11.1` …). After an update the browser therefore fetches the new
  files instead of running cached ones; a mix of new page and old scripts (which
  leaves pages empty) can no longer happen.
- Once only: a browser that still holds the page of 0.9.2 or 0.10.0/0.11.0 may
  keep it until its cache is cleared one more time (F12 → right-click on reload →
  "Empty cache and hard reload", or delete the site data of Home Assistant).
  From 0.11.1 on this is not needed after updates.

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
