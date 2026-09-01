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
`ValueHelper`: format it with `.format('%.0f')`, convert it with `.degree_C` or
`.km_per_hour`, take the plain number with `.raw`, and expect `N/A` when the value is
`None`.  Print one bare and you get the raw number to six decimal places, so don't — see
[Values, and formatting them](tags.md#values-and-formatting-them).  Everything else is a
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
| `usUnits` | int | ● | ● | The unit system NWS served, as WeeWX's constant. |

The alert-only fields — `id`, `expirationTime`, `instruction`, `sent`, `status`,
`messageType`, `category`, `severity`, `certainty`, `urgency`, `sender`, `senderName`,
`nwsHeadline` — are present on a forecast period too, always `None`.

### Wind speed comes in two parts

NWS sends wind speed as text: `"9 mph"`, or `"2 to 9 mph"` when it is forecasting a range.
weewx-nws parses both into numbers — a single figure fills `windSpeed` and leaves
`windSpeed2` as `None`; a range fills both.  So every template that prints wind has to
handle the two cases:

```
#if $hour.windSpeed2 is None
  $hour.windSpeed.format('%.0f')$unit.label.windSpeed $hour.windDir.ordinal_compass
#else
  $hour.windSpeed.format('%.0f') to $hour.windSpeed2.format('%.0f')$unit.label.windSpeed $hour.windDir.ordinal_compass
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
| `onset` | VH time | When the conditions begin. |
| `ends` | VH time | When they end.  An alert whose `ends` has passed is not returned. |
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
paragraph.  Turning the blank lines into breaks is the minimum:

```
#try
  #set $desc = $alert.description.replace('\n\n', '<br/>')
  #set $desc = $desc.replace('\n', ' ')
#except
  ## A malformed alert can leave description as None.
  #set $desc = $alert.description
#end try
```

The `#try` matters: malformed alerts reach the tags with `None` in fields that are normally
strings, and `None.replace(...)` raises.  [Recipes](recipes.md#alerts) has the fuller
pattern the sample report uses.
