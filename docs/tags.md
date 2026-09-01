---
title: Report tags
layout: default
nav_order: 5
has_children: true
description: The $nwsforecast tags — twelve_hour_forecasts(), one_hour_forecasts(), alerts() and alert_count() — what each returns, in what order, and what it leaves out.
---

# Report tags

[weewx-nws manual](https://chaunceygardiner.github.io/weewx-nws/) ·
[weewx-nws on GitHub](https://github.com/chaunceygardiner/weewx-nws) ·
[Report an issue](https://github.com/chaunceygardiner/weewx-nws/issues)

---

weewx-nws serves four tags, under `$nwsforecast`:

| Tag | Returns |
|---|---|
| `$nwsforecast.twelve_hour_forecasts(max)` | The latest twelve-hour forecast: a list of periods, daytime and nighttime, about 6.5 days out |
| `$nwsforecast.one_hour_forecasts(max)` | The latest one-hour forecast: a list of hourly periods, 156 hours out |
| `$nwsforecast.alerts()` | Every active NWS alert for the station's location |
| `$nwsforecast.alert_count()` | How many of them there are |

`max` is optional on the two forecast calls: `twelve_hour_forecasts(4)` returns the first
four periods, `one_hour_forecasts(24)` the next day's worth.  Omit it to get all of them.

## Enabling the tags

The tags come from a search list extension, which each report must name:

```ini
[StdReport]
    [[SeasonsReport]]
        [[[CheetahGenerator]]]
            search_list_extensions = user.nws.NWSForecastVariables
```

The bundled sample report already has it.  A report without it renders `$nwsforecast` as
literal text.

## Forecasts

Each call returns a list of periods, in time order, from the most recently generated
forecast in the database:

```
#for $twelve_hour in $nwsforecast.twelve_hour_forecasts()
  $twelve_hour.name         ## "Tonight", "Wednesday", "Wednesday Night"...
  $twelve_hour.outTemp
  $twelve_hour.windSpeed $twelve_hour.windDir.ordinal_compass
  $twelve_hour.detailedForecast
#end for
```

```
#for $hour in $nwsforecast.one_hour_forecasts(24)
  $hour.startTime.format('%a %l %p')
  $hour.outTemp
  $hour.shortForecast
  $hour.pop
#end for
```

The two calls return the same field names, but not the same fields: one-hour periods carry
a dewpoint and a relative humidity that twelve-hour periods do not, and twelve-hour periods
carry the `name` ("Tonight") and the `detailedForecast` sentence that hourly periods leave
empty.  Every field is listed in [Forecast and alert fields](fields.md).

Four things are worth knowing about what comes back:

- **It is one forecast, not a mixture.**  NWS issues a whole forecast at a time, and every
  period of it shares a `generatedTime`.  The tag returns the periods of the newest
  `generatedTime` in the database, never a mixture of old and new.
- **Periods that have ended are dropped.**  A period whose `endTime` has passed is left
  out, so the first entry in the list is always the one in progress.  This is why an hourly
  list gets one shorter every hour and springs back to its full length when NWS issues a
  new forecast.
- **`max` counts what you get, not what NWS sent.**  It is applied after expired periods
  are dropped, so `one_hour_forecasts(24)` is the next 24 hours.
- **The list can be empty.**  Before the first successful download — and after a database
  is deleted — every call returns an empty list rather than failing.  Templates that print
  a heading before looping should check for that; the sample report's pages do.

## Alerts

`alerts()` returns every alert NWS currently has for your location — usually none:

```
#for $alert in $nwsforecast.alerts()
  $alert.event         ## "Heat Advisory", "Red Flag Warning"...
  $alert.nwsHeadline
  $alert.description
  $alert.instructions
#end for
```

They come back newest first, by the time each alert was issued.  Two of the CAP fields are
worth reading before you design a page around them: `nwsHeadline` is the upper-case banner
NWS writes for the alert and **it can be missing**, in which case `headline` is the
sentence to fall back on; and `description` and `instructions` are long, multi-paragraph
plain text with newlines in them, which need converting to markup before they read
properly.  [Recipes](recipes.md#alerts) has both patterns, and
[Alert fields](fields.md#alert-fields) has the full list.

`alert_count()` answers the same question as `len($nwsforecast.alerts())`, and is what a
banner on another page wants:

```
#set alert_count = $nwsforecast.alert_count()
#if $alert_count > 0
  <p><a href='forecast.html?tab=alerts'>$alert_count Active Alert#if $alert_count > 1 then 's' else ''#</a></p>
#end if
```

An alert stays in the list until it ends.  Alerts that NWS has replaced with a newer one
are dropped as they are parsed, alerts that have expired are deleted from the database, and
a download that finds no alerts at all clears the ones still stored — so an empty list
means NWS has nothing for you, not that nothing has been fetched.  See
[How it works](how-it-works.md#alerts-come-and-go).

{: .note }
Test, exercise, system and draft alerts never appear.  NWS issues them regularly — a
required weekly test, for instance — and weewx-nws skips them as it parses.

## Values, and formatting them

Times, temperatures, wind speeds and directions, dewpoint, humidity and probability of
precipitation come back as WeeWX `ValueHelper`s, so the helper methods a skin already uses
all work:

```
$hour.outTemp.format('%.0f')$unit.label.outTemp    ## 71°F
$hour.startTime.format('%a %l %p')                 ## Mon  4 PM
$hour.windDir.ordinal_compass                      ## WNW
$hour.pop.format('%.0f')$unit.label.pop            ## 3%
$hour.outTemp.degree_C.format('%.1f')              ## 21.7
$hour.outTemp.raw                                  ## 71.0
```

{: .important }
Print them with `.format()`, not bare.  These ValueHelpers are built without the report's
formatter, so a bare `$hour.outTemp` prints the raw number to six decimal places —
`71.000000` — and no unit label.  That is why every template in the sample skin writes
`.format('%.0f')` and appends `$unit.label.outTemp` itself.  Times are the exception: a
bare `$alert.effective` prints sensibly, as `31-Aug-2026 13:26`.

Values arrive in the units NWS served, which for US locations means °F and mph.  Nothing
converts them to the report's unit system automatically, so a skin running in metric has to
ask: `$hour.outTemp.degree_C`, `$hour.windSpeed.km_per_hour`.  `.raw` gives the plain
number for arithmetic.

The remaining fields — names, forecast text, icon URLs, the alert's CAP fields — are plain
strings, and `latitude` and `longitude` are the plain numbers the forecast was requested
for.

{: .note }
Some fields arrive as a plain `None` rather than as a ValueHelper: `windSpeed2` unless NWS
gave a range ("2 to 9 mph"), `outTempTrend` most of the time, and an alert's text fields on
a malformed alert.  Test for `None` before using those — `None.replace(...)` raises, and so
does comparing it.  Where a value *is* wrapped and empty, the ValueHelper prints `N/A` and
needs no guard.

## Reading the database

Every call reads `nws.sdb` afresh — there is no cache between calls, and the report engine
sees whatever the poller threads have saved by then.  Two consequences worth knowing:

- Calling the same tag twice in a template runs the query twice.  Assign it to a variable
  if you use it more than once.
- The pages of one report cycle can disagree slightly if a new forecast lands mid-cycle.
  In practice this is invisible: forecasts are saved at the end of an archive period, and
  reports run after that.
