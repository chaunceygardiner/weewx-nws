---
title: Installation
layout: default
nav_order: 2
description: Installing weewx-nws — the requests and dateutil prerequisites, installing the extension with weectl, setting User-Agent, and confirming it took.
---

# Installation

[weewx-nws manual](https://chaunceygardiner.github.io/weewx-nws/) ·
[weewx-nws on GitHub](https://github.com/chaunceygardiner/weewx-nws) ·
[Report an issue](https://github.com/chaunceygardiner/weewx-nws/issues)

---

weewx-nws requires Python 3.9 or later, WeeWX 5, and the python
[requests](https://requests.readthedocs.io/) and
[dateutil](https://dateutil.readthedocs.io/) packages.  Neither is a WeeWX requirement
(WeeWX 5.4 needs neither), which is why they are installed here.

{: .important }
Upgrading from a release earlier than 4.5.4?  The database schema has changed since then,
and there is no migration: delete `nws.sdb` before restarting WeeWX.  See
[Upgrading](upgrading.md).

## 1. Install the prerequisites

On a pip install, activate WeeWX's virtual environment first (the path varies by install;
`/home/weewx/weewx-venv` and `~/weewx-venv` are the usual ones):

```
source /home/weewx/weewx-venv/bin/activate
pip install python-dateutil
pip install requests
```

On a Debian or Red Hat package install, WeeWX runs in the system python, so install the
system packages.  On Debian:

```
sudo apt install python3-dateutil
sudo apt install python3-requests
```

## 2. Download the extension

Download
[weewx-nws.zip](https://github.com/chaunceygardiner/weewx-nws/releases/latest/download/weewx-nws.zip)
from the [releases page](https://github.com/chaunceygardiner/weewx-nws/releases).

## 3. Install it

On a pip install `weectl` lives in the virtual environment, so activate it first (yours may
sit elsewhere; `~/weewx-venv` is the usual place):

```
source ~/weewx-venv/bin/activate
weectl extension install weewx-nws.zip
```

On a Debian or Red Hat package install there is no environment to activate and `weectl` is
already on the path:

```
weectl extension install weewx-nws.zip
```

No `sudo`: that install put your account in the `weewx` group, which owns the files.  If
you installed WeeWX in this same login session, log out and back in first so the group
membership takes effect.

The install adds `user.nws.NWS` to `data_services` and writes four sections into
`weewx.conf`: `[NWS]` itself, the `[[nws_binding]]` data binding, the `[[nws_sqlite]]`
database, and an `[[NWSReport]]` report stanza for the sample report.  Every option in
`[NWS]` arrives with a comment saying what it does — see
[Configuration](configuration.md).

## 4. Set User-Agent

NWS's API rules ask that every request identify who is making it.  The installer writes a
placeholder; edit `weewx.conf` and put your own site and contact address in its place:

```ini
[NWS]
    User-Agent = "(my-weather-site.com, me@my-weather-site.com)"
```

This is the one option that needs editing.  Everything else has a working default.

## 5. Restart WeeWX

```
sudo systemctl restart weewx
```

## 6. Confirm it took

The extension announces itself in the log at startup.  These are the lines to look for:

```
INFO user.nws: Service version is 6.0.
INFO user.nws: Using binding 'nws_binding' to database 'nws.sdb'
INFO user.nws: request_urls: twelveHourForecastUrl: https://api.weather.gov/gridpoints/MTR/92,88/forecast
INFO user.nws: request_urls: oneHourForecastUrl: https://api.weather.gov/gridpoints/MTR/92,88/forecast/hourly
INFO user.nws: Downloaded 156 ForecastType.ONE_HOUR records generated at ...
INFO user.nws: Saved 156 ForecastType.ONE_HOUR records.
```

The `Downloaded` lines come from the poller threads, which fetch immediately at startup;
the `Saved` lines come at the end of the next archive period.  After the report cycle that
follows, the sample report appears at `<HTML_ROOT>/nws/` — a seven-day page, an hourly page and
an alerts page.  See [The sample report](sample-report.md).

{: .note }
The gridpoint URLs above are resolved from your latitude and longitude through NWS's
`/points` endpoint.  If NWS maps your location to the wrong gridpoint, the log says so —
see [Gridpoints](gridpoints.md).

## 7. Add the tags to your own reports

The sample report has the tags already.  To use them in another report — the Seasons skin,
say, or a skin of your own — name the search list extension in that report's stanza:

```ini
[StdReport]
    [[SeasonsReport]]
        [[[CheetahGenerator]]]
            search_list_extensions = user.nws.NWSForecastVariables
```

Both the `[[[CheetahGenerator]]]` line and the `search_list_extensions` line may need
adding.  Then see [Report tags](tags.md) and [Recipes](recipes.md).

## Uninstalling

```
weectl extension uninstall nws
```

(Activate the virtual environment first on a pip install.)  This removes the extension's
files and the sections it added to `weewx.conf`.  The database, `nws.sdb`, is left where it
is; delete it by hand if you want it gone.
