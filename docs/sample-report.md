---
title: The sample report
layout: default
nav_order: 6
description: The NWSReport installed with weewx-nws — a seven-day page, an hourly page and an alerts page, plus the bundled NWS weather icons.
---

# The sample report

[weewx-nws manual](https://chaunceygardiner.github.io/weewx-nws/) ·
[weewx-nws on GitHub](https://github.com/chaunceygardiner/weewx-nws) ·
[Report an issue](https://github.com/chaunceygardiner/weewx-nws/issues)

---

Installing weewx-nws installs a report as well as the tags.  It publishes three pages to
`<HTML_ROOT>/nws/` and needs no configuration: forecasts appear on your site at the first
report cycle after the install.  It is meant to be useful as it stands and to be read as
worked examples — every page below is rendered and checked on every release.

## The seven-day page

`index.html` — the twelve-hour forecast: daytime and nighttime periods, about 6.5 days of
them, each with NWS's icon, the period's temperature, the wind, and NWS's own sentence.
The line at the foot says when NWS generated the forecast.

![The sample report's seven-day page](images/sample-report-days.png)

## The hourly page

`hours.html` — the one-hour forecast.  A strip across the top gives the next seven hours at
a glance; below it, every hour NWS sent (156 of them, 6.5 days) with temperature, wind,
probability of precipitation, dewpoint and relative humidity.

![The sample report's hourly page](images/sample-report-hours.png)

## The alerts page

`alerts.html` — every active NWS alert for the station's location, most recently issued
first: the headline, the alert's own text and instructions, and the CAP fields underneath.

![The sample report's alerts page, with a Heat Advisory in effect](images/sample-report-alerts.png)

Most of the time there are no alerts, and the page says so:

```
No active National Weather Service alerts for this location.
```

{: .note }
The two states are entirely different markup, which is worth knowing if you edit the page:
a change tested on a quiet day has not been tested at all on the branch that matters.  The
repository's `tests/validate_skin_html.py` renders both.

## What is installed, and where

| File | What it is |
|---|---|
| `skins/nws/index.html.tmpl` | The seven-day page |
| `skins/nws/hours.html.tmpl` | The hourly page |
| `skins/nws/alerts.html.tmpl` | The alerts page |
| `skins/nws/menubar.inc` | The three-tab navigation bar shared by all three |
| `skins/nws/style.inc` | The stylesheet for that bar |
| `skins/nws/skin.conf` | The skin's own configuration |

`skin.conf` names the search list extension and generates the three pages:

```ini
[CheetahGenerator]
    search_list_extensions = user.nws.NWSForecastVariables
    [[ToDate]]
        [[[days]]]
            template = index.html.tmpl
        [[[hours]]]
            template = hours.html.tmpl
        [[[alerts]]]
            template = alerts.html.tmpl
```

The report itself is a stanza in `weewx.conf`:

```ini
[StdReport]
    [[NWSReport]]
        HTML_ROOT = public_html/nws
        enable = true
        skin = nws
```

`weectl` writes that `HTML_ROOT` by prepending your station's own — the installer supplies
just `nws` — so the pages land in a subdirectory of the site rather than on top of it.
Set `enable = false` to stop generating the pages.  The `$nwsforecast` tags go on working:
they are served by the extension, not by this report.

## Making it your own

Edit the templates in place if you like — they are ordinary Cheetah — but remember that
reinstalling the extension overwrites them.  For anything you intend to keep, copy the
skin to a name of your own and point a new report stanza at it:

```
cp -r <SKIN_ROOT>/nws <SKIN_ROOT>/myforecast
```

```ini
[StdReport]
    [[MyForecastReport]]
        HTML_ROOT = forecast
        enable = true
        skin = myforecast
```

[Recipes](recipes.md) has the pieces on their own, ready to paste into a skin you already
have.

## Icons

Since 5.2 the sample report **draws** its icons.  The extension carries a drawn SVG symbol
for all 34 NWS conditions, day and night; the seven-day and hourly pages emit
`$nwsforecast.icon_sprite` once and then call `$nwsforecast.icon()` per period, so the
pages make no request to api.weather.gov at all and the icons stay crisp at any size.
`skins/nws/style.inc` sizes them at 86 px — what NWS's `?size=medium` raster measured — so
the pages lay out as they always did.  See [Drawn icons](recipes.md#drawn-icons) for the
tags, the colour properties and the dark palette.

(Through 5.1 the pages hot-linked NWS's hosted images, and the extension separately bundled
NWS's icon set as PNG files that nothing referenced.  Both are gone in 5.2.)

The condition names, which are the last path segment of an NWS icon URL:

| Name | Condition | Name | Condition |
|---|---|---|---|
| `skc` | Fair/clear | `sleet` | Sleet |
| `few` | A few clouds | `rain` | Rain |
| `sct` | Partly cloudy | `rain_showers` | Rain showers (high cloud cover) |
| `bkn` | Mostly cloudy | `rain_showers_hi` | Rain showers (low cloud cover) |
| `ovc` | Overcast | `tsra` | Thunderstorm (high cloud cover) |
| `wind_skc` | Fair/clear and windy | `tsra_sct` | Thunderstorm (medium cloud cover) |
| `wind_few` | A few clouds and windy | `tsra_hi` | Thunderstorm (low cloud cover) |
| `wind_sct` | Partly cloudy and windy | `tornado` | Tornado |
| `wind_bkn` | Mostly cloudy and windy | `hurricane` | Hurricane conditions |
| `wind_ovc` | Overcast and windy | `tropical_storm` | Tropical storm conditions |
| `snow` | Snow | `dust` | Dust |
| `rain_snow` | Rain/snow | `smoke` | Smoke |
| `rain_sleet` | Rain/sleet | `haze` | Haze |
| `snow_sleet` | Snow/sleet | `hot` | Hot |
| `fzra` | Freezing rain | `cold` | Cold |
| `rain_fzra` | Rain/freezing rain | `blizzard` | Blizzard |
| `snow_fzra` | Freezing rain/snow | `fog` | Fog/mist |

An icon URL can name a precipitation chance (`rain_showers,20`) and can name two conditions
at once (`.../day/tsra_hi,20/rain,20`).  Both resolve to the first condition for the
purpose of picking a file.
