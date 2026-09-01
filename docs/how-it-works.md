---
title: How it works
layout: default
nav_order: 7
description: What weewx-nws does between report cycles — three poller threads, wall-clock polling, conditional requests, sanity checks, and how forecasts and alerts reach and leave the database.
---

# How it works

[weewx-nws manual](https://chaunceygardiner.github.io/weewx-nws/) ·
[weewx-nws on GitHub](https://github.com/chaunceygardiner/weewx-nws) ·
[Report an issue](https://github.com/chaunceygardiner/weewx-nws/issues)

---

Nothing about weewx-nws needs understanding to use it.  This page is for reading the log,
judging what an option will do, and knowing what to expect when NWS misbehaves.

## Three threads, three schedules

At startup the extension resolves your station's gridpoint (below), then starts three
daemon threads — one for twelve-hour forecasts, one for one-hour forecasts, one for alerts.
Each polls on its own schedule, independently of WeeWX's archive and report cycles:

| Thread | Every | Option |
|---|---|---|
| Twelve-hour forecasts | 30 minutes | `poll_secs` |
| One-hour forecasts | 30 minutes | `poll_secs` |
| Alerts | 10 minutes | `alert_poll_secs` |

Polls align to the wall clock rather than to startup: with the default 1800 seconds, a
forecast poll happens on the hour and on the half hour, whenever WeeWX was started.  All
three threads poll once immediately at startup, so a restart does not wait for the next
slot.

Each poll writes a line to the log:

```
INFO user.nws: Downloading ForecastType.TWELVE_HOUR forecasts from https://api.weather.gov/gridpoints/MTR/92,88/forecast.
INFO user.nws: Downloaded 14 ForecastType.TWELVE_HOUR records generated at 2026-08-31 13:26:54 PDT (1788208014)
```

## Finding your gridpoint

NWS does not forecast for arbitrary coordinates; it forecasts for a grid, and each
forecast office has its own.  At startup weewx-nws sends your latitude and longitude to
`https://api.weather.gov/points/<lat>,<long>`, and NWS answers with the two URLs to poll:

```
INFO user.nws: request_urls: twelveHourForecastUrl: https://api.weather.gov/gridpoints/MTR/92,88/forecast
INFO user.nws: request_urls: oneHourForecastUrl: https://api.weather.gov/gridpoints/MTR/92,88/forecast/hourly
```

This is tried three times, five seconds apart, because a machine that has only just booted
often cannot resolve a name yet.  It is skipped entirely when the URLs are hard coded, or
when `read_from_dir` is set.  Alerts do not need it: they are requested by point.

Every forecast NWS returns carries the polygon of the grid square it is for, and weewx-nws
checks that your coordinates actually fall inside it.  When they do not, the log says so —
see [Gridpoints](gridpoints.md).

## What one poll does

1. **Ask, conditionally.**  Each request carries the `Last-Modified` value of the previous
   answer as an `If-Modified-Since` header.  If the forecast has not been reissued, NWS
   answers `304 Not Modified` and there is nothing to do:

   ```
   INFO user.nws: ForecastType.ONE_HOUR: Skipping since not modified since Mon, 31 Aug 2026 22:00:00 UTC
   ```

   This is the common case.  A forecast is generated a few times a day; polling every half
   hour mostly costs a `304`.

2. **Sanity check the json.**  NWS does send malformed responses.  Every field weewx-nws
   reads is checked for presence and type before anything is parsed, and a response that
   fails is rejected whole — logged, with the raw response text, and not saved:

   ```
   INFO user.nws: request_forecast(ForecastType.ONE_HOUR): sanity check failed(...): ...
   ```

   Where the line falls between strict and lenient is the product of several releases
   of argument with NWS's output, and it is finer than it looks: a null
   `temperatureTrend` is accepted, and so is a null *value* inside an hourly period's
   `dewpoint` or `relativeHumidity` — but a `dewpoint` or `relativeHumidity` entry that
   is missing altogether is rejected, as is a missing or null `windSpeed`, a wind speed
   in anything but mph, and NWS's occasional `unknown` icon.

3. **Parse, and hold in memory.**  Parsing turns NWS's text into the fields a report reads
   — the wind speed text into one or two numbers, the compass point into degrees, times
   into timestamps.  The result is held in memory; nothing is written to the database yet.

## When NWS does not answer

Failures — a timeout, a 404, a 503, a response that fails its sanity check — go through a
two-stage retry rather than either giving up or hammering:

1. Up to **four attempts, five seconds apart**.  This clears the transient case.
2. If all four fail, up to **three waits of `retry_wait_secs`** (300 seconds for forecasts,
   30 for alerts, so alerts recover fast), retrying after each.
3. If it is still failing, weewx-nws stops until the next scheduled poll.

Nothing is lost meanwhile: the database keeps the last good forecast, and reports go on
serving it.

{: .note }
NWS's `404` and `503` answers carry a json explanation, and weewx-nws logs it rather than
just the status code — "Data Unavailable For Requested Point", "Forecast Grid Expired",
"The resource you requested is currently unavailable".  The middle one is NWS's own grid
having gone stale, and it clears on its own.

## Getting into the database

The poller threads never write to the database.  Saving happens on WeeWX's
`END_ARCHIVE_PERIOD` event — the same moment an archive record is written — on the main
thread, and it applies four rules:

- **The same forecast is never written twice.**  A forecast is identified by its
  `generatedTime`; if that one is already stored, the save is skipped.
- **A forecast generated in the future is rejected.**  NWS has served these, and they would
  otherwise shadow the real forecast for ever.
- **Old rows are pruned.**  After a new forecast is saved, rows older than `days_to_keep`
  (nine days by default) go, as do any rows belonging to a different latitude and longitude
  — which is what makes moving a station tidy up after itself.
- **The forecast is saved whole.**  All 14 twelve-hour periods, or all 156 hourly ones, are
  written as one batch of rows sharing a `generatedTime`.

```
INFO user.nws: Saved 156 ForecastType.ONE_HOUR records.
INFO user.nws: Pruning ForecastType.ONE_HOUR rows older than 2026-08-22 16:30:00 PDT (1787441400).
```

## Alerts come and go

Alerts follow different rules, because they are not a forecast that gets reissued but a set
that changes:

- **Superseded alerts are dropped as they are parsed.**  A new alert names the ones it
  replaces (`expiredReferences`), and those never reach the database.
- **Test, exercise, system and draft alerts are skipped**, with a line in the log saying
  which and why.  NWS issues them regularly.
- **Expired alerts are deleted** before each save — but not the moment they expire.  NWS
  routinely lets an alert message expire before issuing its replacement, so weewx-nws
  tolerates a lapsed `expires` for a day before deleting the row.  Reports are stricter
  than the database: an alert whose `ends` time has passed stops being returned to them
  straight away, whether or not its row has gone yet.
- **A download of zero alerts clears the table.**  This is how the all-clear reaches your
  pages: NWS reporting nothing is treated as "there is nothing", not as "no news".

```
INFO user.nws: Downloaded 0 ForecastType.ALERTS records.
INFO user.nws: Deleted 1 ForecastType.ALERTS
```

## Getting out again

Reports read the database directly, through the `$nwsforecast` tags — one query per call,
no cache.  The query asks for the rows of the newest forecast for this location, in time
order, and drops periods that have already ended.  So a page always shows the latest
forecast NWS has issued, beginning with the period in progress.

If the database is momentarily locked — sqlite, two threads — the read is retried twice, a
second apart, before it gives up and returns an empty list.  A report that renders no
forecast for one cycle is the worst case; nothing is lost.

## Shutting down

WeeWX stops weewxd by raising an exception inside whatever the main thread is doing, which
includes weewx-nws's own startup and save paths.  Those paths pass a shutdown through
rather than logging it and carrying on — which is what 5.1 fixed, after a SIGTERM landing
in the wrong place could leave weewx unable to stop.  The three poller threads are daemon
threads and end with the process.
