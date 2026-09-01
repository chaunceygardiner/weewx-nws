---
title: Configuration
layout: default
nav_order: 3
description: Every weewx-nws option in one place — the [NWS] section of weewx.conf, the data binding and database, the NWSReport stanza, and the search list extension that puts the tags in a report.
---

# Configuration

[weewx-nws manual](https://chaunceygardiner.github.io/weewx-nws/) ·
[weewx-nws on GitHub](https://github.com/chaunceygardiner/weewx-nws) ·
[Report an issue](https://github.com/chaunceygardiner/weewx-nws/issues)

---

Every option this extension reads, in one place.  All of it lives in `weewx.conf`, in four
places — the installer writes the first three:

| Group | Governs | Lives in |
|---|---|---|
| [`[NWS]`](#the-nws-section) | What is fetched, how often, and who it says it is | `weewx.conf`, top level |
| [`[[nws_binding]]`, `[[nws_sqlite]]`](#the-database) | Where the forecasts are kept | `[DataBindings]` and `[Databases]` |
| [`[[NWSReport]]`](#the-sample-reports-stanza) | The bundled sample report | `weewx.conf`, under `[StdReport]` |
| [`search_list_extensions`](#putting-the-tags-in-your-own-report) | Which of your reports get the `$nwsforecast` tags | Each report's `[[[CheetahGenerator]]]` |

## The `[NWS]` section

The installer writes this section with a comment above every option (elided here):

```ini
[NWS]
    data_binding = nws_binding
    #days_to_keep = 9
    #poll_secs = 1800
    #alert_poll_secs = 600
    #retry_wait_secs = 300
    #alert_retry_wait_secs = 30
    #timeout_secs = 10
    User-Agent = "(my-weather-site.com, me@my-weather-site.com)"
```

An option that merely selects a default is written **commented out**, with the default
shown.  Nothing is lost: with the line commented, the value in force is the extension's own
— so if a later release picks a better default, your station follows it.  Uncomment one to
pin your station to a value of your own.  `data_binding` is live because it names the
database this extension writes to, which is structure rather than a tunable; `User-Agent`
is live because it is the one option you must edit.

{: .important }
Upgrading never rewrites `weewx.conf`, so what your station carries depends on when it was
installed.  Go by what your own file shows: where a line reads `#poll_secs = 1800`,
uncomment it and change the number; where it reads `poll_secs = 1800`, simply change the
number; and where there is no such line at all, add one.

### Options the installer writes

| Option | Default | Effect |
|---|---|---|
| `data_binding` | `nws_binding` | The data binding naming the forecast database.  The installer seeds the matching `[[nws_binding]]` and `[[nws_sqlite]]` entries; there is no reason to change any of it. |
| `days_to_keep` | `9` | Days of old forecasts to keep.  `0` keeps them for ever.  Pruning happens when a new forecast is saved.  Alerts are not affected — they are deleted when they expire.  A large number slows things down. |
| `poll_secs` | `1800` | Seconds between forecast requests (twelve-hour and one-hour).  Polls align to the wall clock, so 1800 polls on the hour and the half hour. |
| `alert_poll_secs` | `600` | Seconds between alert requests.  Alerts are polled more often than forecasts because they are time critical. |
| `retry_wait_secs` | `300` | Seconds to wait before trying forecasts again once NWS looks to be down.  Transient failures are retried first, seconds apart; see [How it works](how-it-works.md#when-nws-does-not-answer). |
| `alert_retry_wait_secs` | `30` | The same, for alerts. |
| `timeout_secs` | `10` | Seconds before an HTTP request to NWS times out. |
| `User-Agent` | placeholder | Contact information sent on every request.  NWS's API rules ask that it identify your site and give a contact address.  **This is the one option that must be edited.** |

### Options you add by hand

None of these is written by the installer.  Add the ones you need.

| Option | Default | Effect |
|---|---|---|
| `latitude`, `longitude` | from `[Station]` | Override the station's location.  Best practice is *not* to set these; see below. |
| `twelve_hour_forecast_url` | resolved from NWS | Hard code the twelve-hour gridpoint URL.  Only needed when NWS maps your location to the wrong gridpoint — see [Gridpoints](gridpoints.md). |
| `one_hour_forecast_url` | resolved from NWS | The same, for one-hour forecasts. |
| `read_from_dir` | unset | Read forecasts from files instead of contacting NWS.  For a fleet of stations at one location — see [Sharing forecasts across a fleet](fleet.md). |
| `[[RsyncSpec]]` | disabled | The other half of `read_from_dir`: copy each downloaded batch to the fleet's clients.  See [Sharing forecasts across a fleet](fleet.md). |

### User-Agent

NWS asks that API clients identify themselves, so that it can contact whoever is making the
requests.  Put your own site and an address that reaches you:

```ini
[NWS]
    User-Agent = "(my-weather-site.com, me@my-weather-site.com)"
```

The placeholder works — NWS does not reject it — but a station that leaves it in place is
anonymous to NWS, and NWS's rules ask otherwise.

### Latitude and longitude

By default the station's location comes from `[Station]` in `weewx.conf`, which is where
WeeWX already keeps it.  Leave it there.  If you must forecast for somewhere other than the
station's own coordinates, `[NWS]` overrides them:

```ini
[NWS]
    latitude = 37.431495     # Best practice is not to set latitude here.
    longitude = -122.110937  # Best practice is not to set longitude here.
```

Both are used verbatim in the URLs weewx-nws builds, and both are stored on every row it
saves — which is also how it recognizes rows belonging to some other location and prunes
them.  Change either one and the existing rows stop matching, so the database repopulates
from the next poll.

### Keeping fewer days

```ini
[NWS]
    #days_to_keep = 9
```

Nine days is enough to look back over the past week's forecasts.  Reports only ever read
the *latest* forecast, so a bigger number buys history, not accuracy — and it slows queries
down.  Set it to `0` to keep everything for ever.

## The database

weewx-nws keeps its forecasts in `nws.sdb`, a sqlite database of its own, next to the
weather archive.  The installer writes both halves:

```ini
[DataBindings]
    [[nws_binding]]
        manager = weewx.manager.Manager
        schema = user.nws.schema
        table_name = archive
        database = nws_sqlite

[Databases]
    [[nws_sqlite]]
        database_name = nws.sdb
        driver = weedb.sqlite
```

{: .note }
`weectl` rewrites `driver = weedb.sqlite` to `database_type = SQLite` as it merges the
stanza in.  Both say the same thing; the second is WeeWX 5's spelling.

One table, `archive`, holds all three record types, told apart by the `interval` column:
`60` for one-hour forecasts, `720` for twelve-hour, `0` for alerts.  Several columns carry
different things for alerts than for forecasts — `shortForecast` holds an alert's headline,
for instance.  [Forecast and alert fields](fields.md) is the map; the schema comments in
`bin/user/nws.py` are the authority.

{: .important }
The schema has changed over the extension's life and there is no migration.  When it
changes, weewx-nws logs an error naming the fix — `You must delete the nws.sdb database and
restart weewx` — and does nothing else until you do.  Nothing is lost that the next poll
does not replace.  See [Upgrading](upgrading.md).

## The sample report's stanza

```ini
[StdReport]
    [[NWSReport]]
        HTML_ROOT = public_html/nws
        enable = true
        skin = nws
```

`HTML_ROOT` is a path relative to `WEEWX_ROOT`.  The installer supplies just `nws`, and
`weectl` prepends your station's own `HTML_ROOT` as it merges the stanza in — so a station
publishing to `public_html` ends up with `public_html/nws`, a subdirectory of the site.
Set `enable = false` to stop generating the pages; the tags go on working, since they are
served by the extension rather than by the report.  See
[The sample report](sample-report.md).

## Putting the tags in your own report

The `$nwsforecast` tags are a search list extension.  Name it in the stanza of each report
that should have them:

```ini
[StdReport]
    [[SeasonsReport]]
        [[[CheetahGenerator]]]
            search_list_extensions = user.nws.NWSForecastVariables
```

Both lines may need adding.  If the report already names other extensions, add this one to
the list, comma separated.  See [Report tags](tags.md).
