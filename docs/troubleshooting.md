---
title: Troubleshooting
layout: default
nav_order: 11
description: Diagnosing weewx-nws — no tags in a report, empty forecasts, missing alerts, what each log message means, and when to delete nws.sdb.
---

# Troubleshooting

[weewx-nws manual](https://chaunceygardiner.github.io/weewx-nws/) ·
[weewx-nws on GitHub](https://github.com/chaunceygardiner/weewx-nws) ·
[Report an issue](https://github.com/chaunceygardiner/weewx-nws/issues)

---

## Start with the log

weewx-nws is talkative.  Every download, every rejection and every save is logged under
`user.nws`, and that is where nearly every question is answered:

```
grep 'user.nws' /var/log/syslog
```

At startup you should see the version, the binding, and — unless the URLs are hard coded —
the gridpoint lookup:

```
INFO user.nws: Service version is 5.1.
INFO user.nws: Using binding 'nws_binding' to database 'nws.sdb'
INFO user.nws: request_urls: twelveHourForecastUrl: https://api.weather.gov/gridpoints/MTR/92,88/forecast
```

Then, from the poller threads, a `Downloading` line and a `Downloaded` line per type, and
at the end of each archive period a `Saved` line when a new forecast arrived.

## `$nwsforecast` prints as literal text

The report does not have the search list extension.  Add it to that report's stanza:

```ini
[StdReport]
    [[SeasonsReport]]
        [[[CheetahGenerator]]]
            search_list_extensions = user.nws.NWSForecastVariables
```

Both lines may need adding, and an existing `search_list_extensions` takes this as another
comma-separated entry rather than being replaced.  See
[Configuration](configuration.md#putting-the-tags-in-your-own-report).

## The pages are empty, or a loop produces nothing

The tags return an empty list rather than failing, so an empty page means the database has
no current forecast.  In order of likelihood:

1. **It has not saved one yet.**  Forecasts are downloaded at startup but written to the
   database at the end of the *next* archive period, and the pages are generated after
   that.  Give it two archive intervals.
2. **The downloads are failing.**  Look for `Downloaded` lines.  If they are absent, look
   for the failures — see below.
3. **The station's coordinates changed.**  Rows are stored with the latitude and longitude
   they were fetched for, and reads match on them.  Change either, and the next save prunes
   the old rows and stores new ones; between those two moments the tags return nothing.
4. **The database is elsewhere.**  Confirm with the `Using binding` line, and look at what
   is in it: [`--view-forecasts`](utilities.md#--view-forecasts) with
   `--view-criterion SUMMARY`.

## `sanity check failed`

```
INFO user.nws: request_forecast(ForecastType.ONE_HOUR): sanity check failed(https://...): ...
```

NWS returned json that does not have the shape weewx-nws requires, so it was rejected
whole rather than half-parsed into the database.  The raw response is logged with it —
that text is the evidence, so keep it.

Nearly always this is NWS having a bad few minutes, and the next poll succeeds.  If it
persists, NWS has changed something: run
[`--test-requester`](utilities.md#--test-requester) for your location to see the current
response, and please
[open an issue](https://github.com/chaunceygardiner/weewx-nws/issues) with the logged text.

## `does not fall within bounds of forecast's polygon`

```
WARNING user.nws: Lat/Long 37.431495/-122.110937 does not fall within bounds of forecast's polygon (due to NWS Bug).
```

NWS mapped your coordinates to a neighboring grid square.  The forecast is still used.
See [Gridpoints](gridpoints.md) for the check and the fix — and note that if you are seeing
this *with* hard-coded URLs in `weewx.conf`, the override is now the problem.

## `404` and `503` from NWS

```
INFO user.nws: request_forecast(ForecastType.ONE_HOUR): 503, Forecast Grid Expired, ...
INFO user.nws: request_urls: 404, Data Unavailable For Requested Point, ...
```

- **`Forecast Grid Expired`** is NWS's own grid having gone stale.  It clears without
  intervention; weewx-nws retries and goes on serving the stored forecast meanwhile.
- **`Data Unavailable For Requested Point`** means NWS does not forecast for those
  coordinates.  Check `[Station]` in `weewx.conf` — most often the longitude has lost its
  minus sign.
- **Every request failing at once** is NWS being unwell rather than your station.  Wait
  it out.  Do not shorten `poll_secs` to compensate: NWS rate-limits, and can block a
  source that asks too often — which is also why a `User-Agent` that identifies you is
  worth setting, since it gives them someone to contact instead.

## `You must delete the nws.sdb database`

```
ERROR user.nws: You must delete the nws.sdb database and restart weewx.  It contains an old schema!
```

The database was created by an older release whose schema differed, and there is no
migration.  Stop WeeWX, delete `nws.sdb` (it sits with the weather archive — commonly
`/var/lib/weewx/` on a package install, `~/weewx-data/archive/` on a pip one), and start it
again.  Nothing is lost that the next poll does not replace.  See
[Upgrading](upgrading.md).

## No alerts appear when there should be

- **Check that NWS has one for your point**, not just for your county or state:
  `https://api.weather.gov/alerts/active?point=<lat>,<long>` in a browser, or
  [`--test-requester --type ALERTS`](utilities.md#--test-requester).  An alert covering
  your area but not your coordinates does not apply.
- **The alert may be a test.**  Test, exercise, system and draft alerts are skipped, with a
  line in the log saying which: `Skipping alert with status of 'Test'`.
- **It may have been superseded.**  An alert named in a newer alert's `expiredReferences`
  is dropped: `found expired alert (skipping)`.

## An alert stays after NWS has dropped it

It should not, and mostly it does not: a download that finds no alerts clears them all.
But an alert whose message expired is deliberately kept for up to a day, because NWS
regularly lets one expire before issuing its replacement.  It goes for good once its `ends`
time has passed.  See [How it works](how-it-works.md#alerts-come-and-go).

## The wind reads `$hour.windSpeed2` on the page

A missing `$` in a template.  With `#errorCatcher Echo`, Cheetah writes the template text
into the page instead of raising, so a `$` in your generated HTML is always a template bug
— look for the placeholder it names.  See
[Wind speed comes in two parts](fields.md#wind-speed-comes-in-two-parts).

## WeeWX will not shut down

Fixed in 5.1: a SIGTERM landing inside weewx-nws's startup or save code was logged and
swallowed instead of being passed through.  If you are on an earlier release, upgrade.

## Still stuck

Run [`--test-requester`](utilities.md#--test-requester) with your station's latitude and
longitude, and
[open an issue](https://github.com/chaunceygardiner/weewx-nws/issues) with what it prints
and the `user.nws` lines from your log.
