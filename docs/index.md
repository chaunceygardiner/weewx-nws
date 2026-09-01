---
title: Home
layout: default
nav_order: 1
permalink: /
description: National Weather Service forecasts and alerts for WeeWX — twelve-hour and one-hour forecasts, active alerts, $nwsforecast tags and a sample forecast report.
---

# weewx-nws — National Weather Service forecasts and alerts for WeeWX

**Twelve-hour forecasts, one-hour forecasts and active alerts** for your station's own
location, kept fresh in the background and served to every report as `$nwsforecast` tags.

[View on GitHub](https://github.com/chaunceygardiner/weewx-nws){: .btn .btn-primary }
[Download weewx-nws.zip](https://github.com/chaunceygardiner/weewx-nws/releases/latest/download/weewx-nws.zip){: .btn }
[Report an issue](https://github.com/chaunceygardiner/weewx-nws/issues){: .btn }

weewx-nws polls [api.weather.gov](https://api.weather.gov) for the latitude and longitude
your station already reports — forecasts every thirty minutes, alerts every ten — and keeps
what it gets in a small database of its own (`nws.sdb`).  Reports read it through the
`$nwsforecast` tags: `$nwsforecast.twelve_hour_forecasts()`,
`$nwsforecast.one_hour_forecasts()`, `$nwsforecast.alerts()` and `$nwsforecast.alert_count()`.

Installing the extension also installs a **sample report** — three pages of forecasts and
alerts, with weather icons, published to `<HTML_ROOT>/nws/`.  Forecasts appear on your site
at the first report cycle after the install, before you write a line of template code.

![The sample report's seven-day page](images/sample-report-days.png)

## Highlights

- **Three kinds of forecast, one extension.**  Twelve-hour periods (daytime and nighttime,
  6.5 days out), one-hour periods (156 hours out) and every active NWS alert for your
  location, each on its own polling schedule.  See [Report tags](tags.md).
- **Nothing to configure to get going.**  The station's latitude and longitude come from
  `[Station]` in `weewx.conf`, and NWS's own `/points` endpoint turns them into the
  gridpoint URLs to fetch.  The one option worth editing is `User-Agent`, which NWS's API
  rules ask you to set — see [Configuration](configuration.md).
- **A sample report that works out of the box.**  A seven-day page, an hourly page and an
  alerts page, with drawn weather icons.  Use it as it stands, or read it as worked
  examples for your own skin.  See [The sample report](sample-report.md).
- **Alerts, handled properly.**  Test, exercise, system and draft alerts are ignored;
  superseded alerts are dropped; expired alerts are deleted; and when NWS reports no alerts
  at all, the stale ones are cleared.  See [Alert fields](fields.md#alert-fields).
- **Values you can format like any other.**  Times, temperatures, wind, dewpoint, humidity
  and probability of precipitation come back as WeeWX `ValueHelper`s: `.format('%.0f')`,
  `.ordinal_compass`, `.degree_C`, `.raw` — the methods a skin already uses.
  See [Values, and formatting them](tags.md#values-and-formatting-them).
- **Polite to NWS, and patient with it.**  Requests carry `If-Modified-Since`, so an
  unchanged forecast costs a `304`; malformed json is rejected and logged with the raw
  response; and failures back off rather than hammer.  See [How it works](how-it-works.md).
- **Diagnostics built in.**  `nws.py` runs from the command line: fetch and print what NWS
  is serving your location right now, run every active US alert through the parser, or
  inspect the database.  See [Command-line utilities](utilities.md).

## Where to start

| If you want to | Read |
|---|---|
| Install it | [Installation](installation.md) |
| Set it up, or change a default | [Configuration](configuration.md) |
| Put forecasts in your own skin | [Report tags](tags.md) and [Recipes](recipes.md) |
| Know what every field means | [Forecast and alert fields](fields.md) |
| Understand the bundled pages | [The sample report](sample-report.md) |
| Know what it is doing in the background | [How it works](how-it-works.md) |
| Fix something | [Troubleshooting](troubleshooting.md) |

## weewx-nws in action

The forecast page at
[www.paloaltoweather.com/forecast.html](https://www.paloaltoweather.com/forecast.html) is
driven by these tags: the **7 Day** tab from `twelve_hour_forecasts()`, the **Hourly** tab
from `one_hour_forecasts()`, and the **Alerts** tab from `alerts()`.

## Requirements

Python 3.9 or later, WeeWX 5, and the python `requests` and `dateutil` packages.  Neither
package is a WeeWX requirement, so [Installation](installation.md) covers installing them.
WeeWX 4 users: weewx-nws 4.5.7 was the last release to support WeeWX 4.
