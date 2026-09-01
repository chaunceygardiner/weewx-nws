---
title: Recipes
layout: default
parent: Report tags
nav_order: 2
description: Copy-and-paste Cheetah snippets for WeeWX skins — a seven-day forecast, an hourly strip, an alert banner, the full alert page, and local weather icons.
---

# Recipes

[weewx-nws manual](https://chaunceygardiner.github.io/weewx-nws/) ·
[weewx-nws on GitHub](https://github.com/chaunceygardiner/weewx-nws) ·
[Report an issue](https://github.com/chaunceygardiner/weewx-nws/issues)

---

Snippets to paste into a skin of your own.  Each assumes the report names the search list
extension — see [Configuration](configuration.md#putting-the-tags-in-your-own-report) — and
each follows the patterns [the sample report](sample-report.md) uses, whose three pages are
rendered and checked on every release.

{: .note }
`#errorCatcher Echo` at the top of a template is what the sample skin uses.  It keeps a
report from dying on one bad placeholder — but it also means a typo renders as literal
template text rather than raising.  A `$` in your generated HTML is the tell.

## A seven-day forecast

Twelve-hour periods, each with an icon, the temperature, the wind and NWS's own sentence:

```
#for $twelve_hour in $nwsforecast.twelve_hour_forecasts()
<div class="forecast-period">
  <img src='$twelve_hour.iconUrl' alt='$twelve_hour.shortForecast'>
  <h3>$twelve_hour.name</h3>
  <p>$twelve_hour.outTemp.format('%.0f')$unit.label.outTemp</p>
  #if $twelve_hour.windSpeed2 is None
  <p>$twelve_hour.windSpeed.format('%.0f')$unit.label.windSpeed $twelve_hour.windDir.ordinal_compass</p>
  #else
  <p>$twelve_hour.windSpeed.format('%.0f') to $twelve_hour.windSpeed2.format('%.0f')$unit.label.windSpeed $twelve_hour.windDir.ordinal_compass</p>
  #end if
  <p>$twelve_hour.detailedForecast</p>
</div>
#end for
```

`twelve_hour_forecasts()` with no argument returns every period NWS sent — 14 of them,
covering about 6.5 days — beginning with the one in progress.  Pass a number to shorten
it: `twelve_hour_forecasts(4)` is the next two days.

## Saying when the forecast was made

Every period of one forecast shares its `generatedTime`, so take it from whichever period
you happen to be holding:

```
#set $generated_at = ''
#for $twelve_hour in $nwsforecast.twelve_hour_forecasts()
  #set $generated_at = $twelve_hour.generatedTime
  ...
#end for
#if $generated_at != ''
<p class="generated">Forecast generated $generated_at.</p>
#end if
```

The `#if` matters: before the first download there are no periods, and the paragraph would
otherwise print an empty date.

## An hourly strip

The next seven hours across the top of a page — time, icon, temperature, chance of rain:

```
#set $hours = $nwsforecast.one_hour_forecasts(7)
<table>
  <tr>
  #for $hour in $hours
    <td>$hour.startTime.format('%l %p')</td>
  #end for
  </tr>
  <tr>
  #for $hour in $hours
    <td><img src='$hour.iconUrl' alt='$hour.shortForecast'></td>
  #end for
  </tr>
  <tr>
  #for $hour in $hours
    <td>$hour.outTemp.format('%.0f')$unit.label.outTemp<br>
        $hour.shortForecast<br>
        PoP: $hour.pop.format('%.0f')$unit.label.pop</td>
  #end for
  </tr>
</table>
```

Expired hours are already gone, so the first column is always the hour in progress.

Note the `#set`: a strip like this reads the list three times, once per row, and each call
to the tag is a fresh database query.  Assigning it once is worth it.  (The sample skin
predates this advice and calls the tag three times.)

## An alert banner on another page

The cheapest way to put "2 Active Alerts" at the top of a page that is not the alerts page:

```
#set $alert_count = $nwsforecast.alert_count()
#if $alert_count > 0
<p class="alert-banner">
  <a href='alerts.html'>$alert_count Active Alert#if $alert_count > 1 then 's' else ''#</a>
</p>
#end if
```

## Alerts

An alerts page has to handle four things: a missing `nwsHeadline`, multi-paragraph text,
fields that can be `None` on a malformed alert, and the common case of no alerts at all.

```
#set $alert_count = 0
#for $alert in $nwsforecast.alerts()
#set $alert_count += 1
  ## nwsHeadline is the banner NWS writes, but it is not always there.
  #if $alert.nwsHeadline is not None
    #set $headline = $alert.nwsHeadline
  #else
    #set $headline = $alert.headline
  #end if
  <h2>$headline</h2>
  <p>$alert.event, issued $alert.effective</p>
  <p>Severity: $alert.severity · Certainty: $alert.certainty · Urgency: $alert.urgency</p>

  ## description and instructions are plain text with newlines in them.
  #try
    #set $desc = $alert.description.replace('\n\n', '<br/><br/>')
    #set $desc = $desc.replace('\n', ' ')
  #except
    ## A malformed alert can leave description as None.
    #set $desc = $alert.description
  #end try
  <p>$desc</p>

  #if $alert.instructions is not None
  <p><em>Instructions</em><br>$alert.instructions</p>
  #end if

  <p>In effect $alert.onset to $alert.ends.  Issued by $alert.senderName.</p>
#end for
#if $alert_count == 0
  <p><em>No active National Weather Service alerts for this location.</em></p>
#end if
```

{: .important }
Do not iterate `alerts()` twice to count them first — each call re-reads the database.
Count as you loop, as above, or call `alert_count()`.

## Bigger or smaller icons

NWS's icon URLs carry the size as a query parameter, so a template can ask for another one
by rewriting the URL it was given:

```
#set $icon = $hour.iconUrl
#set $icon = $icon.replace('?size=small', '?size=medium')
#set $icon = $icon.replace(',0?', '?')
<img src='$icon' alt='$hour.shortForecast'>
```

One-hour forecasts arrive with `?size=small`, twelve-hour with `?size=medium`; `large` is
the third size NWS serves.

The third line handles the other thing NWS puts in these URLs: hourly icons can carry a
precipitation chance — `.../rain_showers,20?size=small` — and dropping a chance of zero
tidies the URL.  Both replacements are what the sample skin's hourly page does.

## Serving the icons yourself

The extension ships NWS's icon set — three sizes, day and night, 34 conditions — so a site
can serve them from its own web root rather than hot-linking api.weather.gov.  They land
beside the sample report's pages, at `<HTML_ROOT>/nws/nws_icons/<size>/<day|night>/<name>`,
with no file extension (they are PNGs).

Mapping an `iconUrl` to one of them means reading the path NWS gives, which has more shapes
than it first appears:

```
https://api.weather.gov/icons/land/night/bkn?size=medium         plain
https://api.weather.gov/icons/land/day/rain_showers,20?size=small  with a precipitation chance
https://api.weather.gov/icons/land/night/sct/fog?size=medium        two conditions
https://api.weather.gov/icons/land/day/tsra_hi,20/rain,20?size=medium  both at once
```

Taking the day-or-night segment and the first condition, with any chance suffix trimmed,
handles all four:

```
#set $path = $twelve_hour.iconUrl.split('?')[0]
#set $segments = $path.split('/icons/land/')[-1].split('/')
#set $day_night = $segments[0]
#set $condition = $segments[1].split(',')[0]
<img src='nws_icons/medium/$day_night/$condition' alt='$twelve_hour.shortForecast'>
```

The 34 condition names, and what each one means, are in
[Icons](sample-report.md#icons).
