# weewx-nws — National Weather Service forecasts and alerts for WeeWX
Open source plugin for WeeWX software.

Copyright (C)2020-2026 by John A Kline (john@johnkline.com)

[![Read the manual](assets/btn-manual.svg)](https://chaunceygardiner.github.io/weewx-nws/)
[![Download weewx-nws.zip](assets/btn-download.svg)](https://github.com/chaunceygardiner/weewx-nws/releases/latest/download/weewx-nws.zip)
[![Report an issue](assets/btn-issue.svg)](https://github.com/chaunceygardiner/weewx-nws/issues)

The manual covers installation, configuration, every `$nwsforecast` tag and field, the
sample report, and troubleshooting — with search.

**This plugin requires Python 3.9 or later, WeeWX 5, and the python `requests` and
`dateutil` packages (installing them is covered below).  WeeWX 4 users: weewx-nws 4.5.7 was
the last release to support WeeWX 4.**

**If you are updating from a version earlier than 4.5.4, you MUST delete the nws database
(nws.sdb) before restarting weewx.  The database schema has changed and there is no
migration.  See [Upgrading](https://chaunceygardiner.github.io/weewx-nws/upgrading.html).**

## Description

A WeeWX extension that fetches National Weather Service forecasts and alerts for the
station's location:

* **Twelve-hour forecasts** — daytime and nighttime periods, 6.5 days out.
* **One-hour forecasts** — hourly periods, 6.5 days (156 hours) out.
* **Active alerts** — e.g., Heat Advisory, Red Flag Warning, with the full alert text.

The extension polls api.weather.gov in the background (by default, forecasts every 30
minutes and alerts every 10 minutes), saves the results to its own database (`nws.sdb`),
and makes them available to every report as `$nwsforecast` tags.

Installing it also installs a sample report (`NWSReport`) that publishes forecast and alert
pages, with weather icons, to `<HTML_ROOT>/nws/` — so forecasts appear on your site at the
first report cycle after the install, before you write a single line of template code.

![The sample report's seven-day page](https://raw.githubusercontent.com/chaunceygardiner/weewx-nws/master/docs/images/sample-report-days.png)

To see weewx-nws in action, check the forecast page at
[www.paloaltoweather.com/forecast.html](https://www.paloaltoweather.com/forecast.html) —
its **7 Day**, **Hourly** and **Alerts** tabs are driven by these tags.

## What you get

- **Four tags, no ceremony.**  `$nwsforecast.twelve_hour_forecasts()`,
  `$nwsforecast.one_hour_forecasts()`, `$nwsforecast.alerts()` and
  `$nwsforecast.alert_count()`.  Times, temperatures, wind, dewpoint, humidity and
  probability of precipitation come back as WeeWX `ValueHelper`s: `.format('%.0f')`,
  `.ordinal_compass`, `.degree_C` and `.raw` all work.
  → [Report tags](https://chaunceygardiner.github.io/weewx-nws/tags.html) ·
  [every field](https://chaunceygardiner.github.io/weewx-nws/fields.html) ·
  [recipes](https://chaunceygardiner.github.io/weewx-nws/recipes.html)

- **A sample report that works out of the box.**  A seven-day page, an hourly page and an
  alerts page, with drawn weather icons that need no request to NWS and take their colours
  from your stylesheet.
  → [The sample report](https://chaunceygardiner.github.io/weewx-nws/sample-report.html)

- **Nothing to configure to get going.**  The station's latitude and longitude come from
  `[Station]`, and NWS's own `/points` endpoint turns them into the gridpoint URLs to poll.
  The one option worth editing is `User-Agent`, which NWS's API rules ask you to set.
  → [Configuration](https://chaunceygardiner.github.io/weewx-nws/configuration.html)

- **Polite to NWS, and patient with it.**  Conditional requests, so an unchanged forecast
  costs a `304`; strict sanity checks that reject malformed json whole and log the raw
  response; and a retry ladder that backs off rather than hammers.
  → [How it works](https://chaunceygardiner.github.io/weewx-nws/how-it-works.html)

- **Alerts handled properly.**  Test, exercise, system and draft alerts ignored; superseded
  alerts dropped; expired alerts deleted; and a download of zero alerts clears the stale
  ones, so an empty list means NWS has nothing for you.

- **Diagnostics built in.**  `nws.py` runs from the command line: see exactly what NWS is
  serving your location right now, run every active US alert through the parser, check your
  gridpoint, or inspect the database.
  → [Command-line utilities](https://chaunceygardiner.github.io/weewx-nws/utilities.html)

## Installation

1. Install the prerequisites.  For a pip/venv WeeWX install, activate the virtual
   environment (the path varies by install) and use pip:

   ```
   source /home/weewx/weewx-venv/bin/activate
   pip install python-dateutil
   pip install requests
   ```

   For a Debian package install:

   ```
   sudo apt install python3-dateutil
   sudo apt install python3-requests
   ```

1. Download the [latest release from GitHub](https://github.com/chaunceygardiner/weewx-nws/releases/latest/download/weewx-nws.zip).

1. Install the nws extension.

   On a pip install `weectl` lives in the virtual environment, so
   activate it first (yours may sit elsewhere; `~/weewx-venv` is the usual
   place):

   ```
   source ~/weewx-venv/bin/activate
   weectl extension install weewx-nws.zip
   ```

   On a Debian or Red Hat package install there is no environment to
   activate and `weectl` is already on the path:

   ```
   weectl extension install weewx-nws.zip
   ```

   No `sudo`: that install put your account in the `weewx` group, which
   owns the files.  If you installed WeeWX in this same login session, log
   out and back in first so the group membership takes effect.

1. Edit `weewx.conf` and put your own site and contact address in `User-Agent`.  NWS's API
   rules ask that every request say who is making it:

   ```
   [NWS]
       User-Agent = "(my-weather-site.com, me@my-weather-site.com)"
   ```

1. Restart WeeWX.

After the next reporting cycle, the sample report appears at `<HTML_ROOT>/nws/`.  To use
the tags in a report of your own, name the search list extension in its stanza:

```
[StdReport]
    [[SeasonsReport]]
        [[[CheetahGenerator]]]
            search_list_extensions = user.nws.NWSForecastVariables
```

The manual has the full steps, including
[what the installer writes](https://chaunceygardiner.github.io/weewx-nws/installation.html),
the [configuration reference](https://chaunceygardiner.github.io/weewx-nws/configuration.html),
and what to do when
[something is not working](https://chaunceygardiner.github.io/weewx-nws/troubleshooting.html).

Upgrading from an earlier release?  See
[Upgrading](https://chaunceygardiner.github.io/weewx-nws/upgrading.html) — which release
requires deleting `nws.sdb`, and the hard-coded gridpoint URLs that are now doing harm.
The full history is in
[changes.txt](https://github.com/chaunceygardiner/weewx-nws/blob/master/changes.txt).

## Testing

There are two layers of testing, with different jobs.

The **automated test suite** (the `tests` directory) is hermetic — it never contacts NWS.
It runs the extension's parsing and validation code against saved real NWS responses and
synthetic alerts, renders the sample skin through WeeWX's report engine, and pins the
behaviors that have broken before.  Its job is catching regressions in *this extension*.
Run it from the repository root, with the python that runs WeeWX:

```
# pip install (activate WeeWX's virtual environment; pytest is a one-time install):
source /home/weewx/weewx-venv/bin/activate
pip install pytest    # first time only
python3 -m pytest tests

# Debian package install (pytest via: sudo apt install python3-pytest):
PYTHONPATH=/usr/share/weewx python3 -m pytest tests
```

The **live utilities built into nws.py** contact the real api.weather.gov.  Their job is
catching changes in *what NWS serves* — which the hermetic tests, validating assumptions
against saved responses, cannot see.  `tests/verify_cli.py` runs every one of them and
reports PASS/FAIL per option; `tests/validate_skin_html.py` renders the sample skin in both
alert states and validates the HTML with the
[Nu Html Checker](https://validator.github.io/validator/) (it needs `java` and `vnu.jar`).

```
python tests/verify_cli.py          # --skip-multigrid skips the 50-city sweep
python tests/validate_skin_html.py
```

Each utility is documented in
[Command-line utilities](https://chaunceygardiner.github.io/weewx-nws/utilities.html).

## Licensing

weewx-nws is licensed under the GNU Public License v3.
