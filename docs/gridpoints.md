---
title: Gridpoints
layout: default
nav_order: 8
description: How weewx-nws turns your latitude and longitude into an NWS gridpoint, the historical off-by-one bug, and the --check-grid utility that diagnoses it.
---

# Gridpoints

[weewx-nws manual](https://chaunceygardiner.github.io/weewx-nws/) ·
[weewx-nws on GitHub](https://github.com/chaunceygardiner/weewx-nws) ·
[Report an issue](https://github.com/chaunceygardiner/weewx-nws/issues)

---

NWS does not forecast for coordinates.  It divides the country into a grid — each forecast
office with its own — and forecasts for grid squares of roughly 2.5 km.  Turning your
station's latitude and longitude into the right square is NWS's job, and almost always it
does it correctly.  This page is about the times it did not.

## How the square is chosen

At startup weewx-nws asks NWS which gridpoint your coordinates belong to:

```
https://api.weather.gov/points/37.431495,-122.110937
```

NWS answers with the two URLs to poll, and those are what appear in the log:

```
INFO user.nws: request_urls: twelveHourForecastUrl: https://api.weather.gov/gridpoints/MTR/92,88/forecast
INFO user.nws: request_urls: oneHourForecastUrl: https://api.weather.gov/gridpoints/MTR/92,88/forecast/hourly
```

`MTR` is the forecast office (San Francisco Bay Area / Monterey); `92,88` is the square.

Every forecast NWS returns includes the polygon of the square it covers, and weewx-nws
checks that your coordinates fall inside it.  When they do not, it logs a warning on every
download:

```
WARNING user.nws: Lat/Long 37.431495/-122.110937 does not fall within bounds of forecast's polygon (due to NWS Bug).
```

The forecast is still used — a neighboring square's forecast is nearly always the same
weather — but if you would rather have the right square, the fix is below.

{: .note }
**As of 15 March 2023 this bug is fixed**, at least for the author's location, and has been
ever since.  If your station carries a hard-coded URL from those days, it is now the thing
making your forecast wrong: take it out.  See [Upgrading](upgrading.md#hard-coded-gridpoint-urls).

## Checking your own location

`nws.py` will check it for you, from the command line.  Run it with the python that runs
WeeWX — see [Command-line utilities](utilities.md) for the exact invocation on your kind of
install:

```
python /home/weewx/bin/user/nws.py --check-grid --latitude 37.431495 --longitude -122.110937
```

When NWS has it right, that is all it says:

```
nws computed the correct grid(92, 88) for lat/long 37.431495/-122.110937
```

When it does not, the utility searches the neighboring squares for the one that really
contains your coordinates, and prints the lines that pin it:

```
nws computed the incorrect grid(92, 88) for lat/long 37.431495/-122.110937

Add the following two lines to the [NWS] section in weewx.conf:
    twelve_hour_forecast_url = "https://api.weather.gov/gridpoints/MTR/91,87/forecast"
    one_hour_forecast_url = "https://api.weather.gov/gridpoints/MTR/91,87/forecast/hourly"
```

Add them, restart WeeWX, and the pollers use those URLs directly — the `/points` lookup is
skipped entirely:

```ini
[NWS]
    twelve_hour_forecast_url = "https://api.weather.gov/gridpoints/MTR/91,87/forecast"
    one_hour_forecast_url = "https://api.weather.gov/gridpoints/MTR/91,87/forecast/hourly"
```

{: .important }
Hard-coded URLs are a fix for a bug, not a setting.  A station that carries them is pinned
to one square for ever — including after NWS corrects its own mapping, and after the office
redraws its grid.  Re-run `--check-grid` (with the override removed) now and then, and take
the lines out when they are no longer needed.

## Alerts are not affected

Alerts are requested by point, not by gridpoint:

```
https://api.weather.gov/alerts/active?point=37.431495,-122.110937
```

so a wrong gridpoint never affects them, and hard-coded forecast URLs never affect them
either.

## If NWS has nothing for your location

Outside the areas NWS covers, `/points` answers `404` with an explanation, which weewx-nws
logs:

```
INFO user.nws: request_urls: 404, Data Unavailable For Requested Point, https://api.weather.gov/problems/InvalidPoint, Unable to provide data for requested point ...
```

There is no fix for that from this end — NWS forecasts the United States and its
territories.  Check first that `[Station]` in `weewx.conf` really holds your coordinates,
and that the longitude is negative in the western hemisphere.
