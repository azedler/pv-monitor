# Changelog

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
