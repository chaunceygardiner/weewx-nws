---
title: Forecast and alert fields
layout: default
parent: Report tags
nav_order: 1
description: Every field a weewx-nws forecast period and alert carries — what it holds, what type it is, which forecast types fill it in, and which can be None.
---

# Forecast and alert fields

[weewx-nws manual](https://chaunceygardiner.github.io/weewx-nws/) ·
[weewx-nws on GitHub](https://github.com/chaunceygardiner/weewx-nws) ·
[Report an issue](https://github.com/chaunceygardiner/weewx-nws/issues)

---

What every field holds, and what type it comes back as.  **VH** marks a WeeWX
`ValueHelper`, carrying the value in **your report's own units**: print it bare for your
skin's own format and label, shape it with `.format('%.0f')` (which labels it too), convert
it to something else with `.degree_C` or `.km_per_hour`, take the plain number with `.raw`,
and expect `N/A` when the value is `None`.  See
[Values, and formatting them](tags.md#values-and-formatting-them) — and if you are
upgrading from 6.0, the note there about deleting `$unit.label.…`.  Everything else is a
plain string or number.

## Forecast fields

Returned by `$nwsforecast.twelve_hour_forecasts()` and `$nwsforecast.one_hour_forecasts()`.
Both return the same field names; the **12H** and **1H** columns say which forecast type
actually fills each one in.

| Field | Type | 12H | 1H | What it is |
|---|---|:-:|:-:|---|
| `generatedTime` | VH time | ● | ● | When NWS generated this forecast.  Every period of one forecast shares it. |
| `number` | int | ● | ● | The period's position in the forecast, counting from 1. |
| `name` | string | ● | — | "This Afternoon", "Tonight", "Wednesday Night".  An empty string on one-hour periods. |
| `startTime` | VH time | ● | ● | When the period begins. |
| `endTime` | VH time | ● | ● | When it ends.  A period whose `endTime` has passed is not returned. |
| `isDaytime` | int | ● | ● | 1 for a daytime period, 0 for a nighttime one. |
| `outTemp` | VH temperature | ● | ● | The forecast temperature: the period's high or low for twelve-hour, the hour's temperature for one-hour. |
| `outTempTrend` | string or `None` | ● | ● | "rising" or "falling" when NWS says so, `None` far more often than not. |
| `pop` | VH percent | ● | ● | Probability of precipitation. |
| `dewpoint` | VH temperature | — | ● | Dewpoint.  Empty on twelve-hour periods, where it prints `N/A`. |
| `outHumidity` | VH percent | — | ● | Relative humidity.  Empty on twelve-hour periods, where it prints `N/A`. |
| `windSpeed` | VH speed | ● | ● | Wind speed — the lower bound when NWS gives a range. |
| `windSpeed2` | VH speed or `None` | ● | ● | The upper bound of a ranged wind speed, `None` when NWS gave a single figure.  See below. |
| `windDir` | VH direction | ● | ● | Wind direction in degrees, from NWS's compass point.  `.ordinal_compass` prints it back as "WNW". |
| `iconUrl` | string | ● | ● | The URL of NWS's weather icon for the period.  See [Icons](sample-report.md#icons). |
| `shortForecast` | string | ● | ● | "Mostly Cloudy", "Slight Chance Rain Showers". |
| `detailedForecast` | string | ● | — | The full sentence: "Partly sunny, with a high near 87.  North northwest wind 1 to 7 mph."  An empty string on one-hour periods. |
| `latitude`, `longitude` | number | ● | ● | The point the forecast was requested for. |
| `dateTime` | VH time | ● | ● | When this row was written to the database. |
| `interval` | int | ● | ● | 720 for twelve-hour, 60 for one-hour.  How the shared table tells the types apart. |
| `usUnits` | int | ● | ● | The unit system the row is stored in, as WeeWX's constant.  Always `1` (US) — a reply that says otherwise is rejected rather than stored.  The `ValueHelper` fields above are converted to your report's units regardless. |

The alert-only fields — `id`, `expirationTime`, `instruction`, `sent`, `status`,
`messageType`, `category`, `severity`, `certainty`, `urgency`, `sender`, `senderName`,
`nwsHeadline`, `areaDesc`, `response`, `parameters` — are present on a forecast period
too, always `None`.

### Wind speed comes in two parts

NWS sends wind speed as text: `"9 mph"`, or `"2 to 9 mph"` when it is forecasting a range.
weewx-nws parses both into numbers — a single figure fills `windSpeed` and leaves
`windSpeed2` as `None`; a range fills both.  So every template that prints wind has to
handle the two cases:

```
#if $hour.windSpeed2 is None
  $hour.windSpeed.format('%.0f') $hour.windDir.ordinal_compass
#else
  $hour.windSpeed.format('%.0f', add_label=False) to $hour.windSpeed2.format('%.0f') $hour.windDir.ordinal_compass
#end if
```

{: .important }
Note the `$` on `$hour.windSpeed2` in the `#if`.  With `#errorCatcher Echo`, a missing `$`
does not raise — Cheetah writes the template text into the page instead.  That is exactly
how a broken wind line shipped in the sample skin through 4.5.7.

### Wind direction

NWS gives a compass point, and weewx-nws turns it into degrees: `N` is 0, `NNE` 22.5, `NE`
45, and so on around.  An unrecognized value becomes `None`.  `.ordinal_compass` turns the
degrees back into a compass point for display, and any skin's own compass labels — a
translated skin's included — apply.

## Alert fields

Returned by `$nwsforecast.alerts()`.  These are the CAP fields NWS publishes, renamed where
weewx-nws's names read better.

| Field | Type | What it is |
|---|---|---|
| `event` | string | The alert's name: "Heat Advisory", "Red Flag Warning", "Tornado Warning". |
| `nwsHeadline` | string or `None` | The upper-case banner NWS writes: "HEAT ADVISORY IN EFFECT FROM 1 PM TUESDAY TO 7 PM CDT THURSDAY".  **Can be missing** — fall back to `headline`. |
| `headline` | string | The sentence form: "Heat Advisory issued August 31 at 12:12PM CDT until September 3 at 7:00PM CDT by NWS Lincoln IL". |
| `description` | string | The body of the alert — What / Where / When / Impacts, several paragraphs, newline separated. |
| `instructions` | string or `None` | What to do about it: "Drink plenty of fluids, stay in an air-conditioned room...". |
| `effective` | VH time | When the alert was issued. |
| `onset` | VH time, `.raw` may be `None` | When the conditions begin.  **NWS does not always say**, and since 6.1 that is stored as nothing rather than faked; [`alert_window()`](tags.md#alert-semantics) falls back to `effective`.  The tag is still a ValueHelper — test `.raw is None`, not the tag. |
| `ends` | VH time, `.raw` may be `None` | When they end, and likewise empty when NWS gave no end — about one alert in ten.  An alert whose end has passed is not returned; an open-ended one is bounded by `expires` instead. |
| `expires` | VH time | When the alert message itself expires — usually well before `ends`, because NWS re-issues. |
| `sent` | VH time | When NWS sent this message. |
| `severity` | string | Extreme, Severe, Moderate, Minor, Unknown. |
| `certainty` | string | Observed, Likely, Possible, Unlikely, Unknown. |
| `urgency` | string | Immediate, Expected, Future, Past, Unknown. |
| `status` | string | Actual, for everything you will see.  Test, Exercise, System and Draft alerts are skipped. |
| `messageType` | string | Alert, Update or Cancel. |
| `category` | string | Met for weather; Geo, Safety, Fire and the rest of CAP's list exist. |
| `sender` | string | `w-nws.webmaster@noaa.gov`. |
| `senderName` | string | The issuing office: "NWS San Francisco CA". |
| `areaDesc` | string or `None` | The areas the alert covers, as NWS lists them, separated by semicolons: "Presque Isle; Alpena; Alcona".  Most alerts name one; a marine alert can name dozens of zones.  Since 6.1.2. |
| `response` | string or `None` | CAP's recommended action, one word: Shelter, Evacuate, Prepare, Execute, Avoid, Monitor, Assess, AllClear or None.  Since 6.1.2. |
| `parameters` | dict | NWS's own parameters for the alert, each value a list: `VTEC`, `NWSheadline`, and on some storm warnings `maxWindGust`, `maxHailSize` and the like.  Stored whole, so what NWS adds later is here too.  Empty when none were stored.  Since 6.1.2. |
| `id` | string | NWS's identifier for the alert, e.g. `urn:oid:2.49.0.1.840.0.b46a...001.1`. |
| `latitude`, `longitude` | number | The point the alerts were requested for. |

{: .note }
`expires` versus `ends`: NWS expires an alert *message* long before the weather it warns
about is over, and issues a fresh message in its place.  weewx-nws keeps an alert until it
`ends`, tolerating a lapsed `expires` for a day, because NWS is not always prompt with the
replacement.  See [How it works](how-it-works.md#alerts-come-and-go).

### Text fields need work before they render

`description` and `instructions` are plain text with real newlines in them — paragraphs
separated by blank lines.  Dropped into HTML as they stand they collapse into one run-on
paragraph.

Use `$nwsforecast.parse_description()` rather than converting them by hand.  It returns the
description as labeled sections, paragraphs and bullets, and it handles all four shapes NWS
sends — starred headers, bare `HAZARD.../SOURCE.../IMPACT...` labels, starred lines that
are really bullets, and the free prose that three quarters of alerts are entirely.  It also
takes `None` without raising, which a malformed alert really does produce.

```
#for $block in $nwsforecast.parse_description($alert.description)
  #if $block.label
    <h4>$block.label</h4>
  #end if
  #for $p in $block.paragraphs
    <p>$p</p>
  #end for
#end for
```

`instructions` is a single block of prose rather than a structured field; splitting it on
blank lines is enough.  See [Alert semantics](tags.md#alert-semantics) and
[Recipes](recipes.md#alerts).
