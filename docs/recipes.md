---
title: Recipes
layout: default
parent: Report tags
nav_order: 2
description: Copy-and-paste Cheetah snippets for WeeWX skins — a seven-day forecast, an hourly strip, an alert banner, the full alert page, and drawn weather icons.
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

{: .note }
This is for a skin that hot-links NWS's hosted photographs.  If you use the extension's
own [drawn icons](#drawn-icons) — as the sample report does since 5.2 — size them with css
instead (`.wxi { width: 34px; height: 34px; }`) and ignore this section.

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
tidies the URL.  (The sample skin's hourly page did exactly this through 5.1; it draws its
icons now.)

## Drawn icons

Since 5.2 the extension draws all 34 NWS conditions itself, day and night, as SVG.  Drawn
icons stay crisp at any size, take their colours from your stylesheet, and avoid the split
"X then Y" pictures NWS produces for a two-condition period, which read as glitches at the
size a forecast table uses.

Two tags.  Emit the sprite **once** per page — it holds the symbol definitions everything
else points at — then call `icon()` per period:

```
$nwsforecast.icon_sprite

#for $twelve_hour in $nwsforecast.twelve_hour_forecasts()
  $nwsforecast.icon($twelve_hour.iconUrl)
  $twelve_hour.name: $twelve_hour.shortForecast
#end for
```

`icon()` returns a complete element, so size and colour it from your own stylesheet:

```css
.wxi { width: 34px; height: 34px; }
```

An optional second argument replaces the class, if one page wants bigger icons than
another:

```
$nwsforecast.icon($twelve_hour.iconUrl, 'wxi wxi-big')
```

{: .note }
The sprite must appear somewhere in the page, but it need not come first — an SVG `<use>`
resolves against a symbol defined anywhere in the document, so the end of `<body>` works
just as well as the top.

### Colouring them

Every fill is emitted as `var(--wx-name, #default)`, so the built-in colours are simply
the defaults.  Define nothing and you get exactly the icons shown above; define one and
the icons follow your stylesheet:

```css
@media (prefers-color-scheme: dark) {
  :root {
    --wx-cloud:   #525963;
    --wx-cloud-2: #85909E;
    --wx-cloud-3: #B0BCCB;
    --wx-moon:    #A1AAB8;
    --wx-rain:    #7FBFFF;
  }
}
```

You do not have to choose those values yourself — a complete, checked dark palette ships
with the extension.  See [A dark palette](#a-dark-palette) below.

The twenty colour properties, and what each paints by default:

| Property | Default | Paints |
|---|---|---|
| `--wx-sun` | `#F2B705` | the sun's disc |
| `--wx-sunray` | `#E0A800` | the sun's rays |
| `--wx-moon` | `#8A93A0` | the crescent moon |
| `--wx-cloud` | `#C3CBD6` | cloud ramp, step 1 |
| `--wx-cloud-2` | `#9AA5B4` | cloud ramp, step 2 |
| `--wx-cloud-3` | `#7E8998` | cloud ramp, step 3 |
| `--wx-rain` | `#2F6EA8` | raindrops |
| `--wx-snow` | `#6FA8D8` | snowflakes |
| `--wx-sleet` | `#4A7FB5` | sleet pellets |
| `--wx-bolt` | `#E0A800` | the lightning bolt |
| `--wx-fog` | `#8B93A0` | fog and haze bands |
| `--wx-wind` | `#6E7B8B` | wind lines |
| `--wx-hot` | `#C0392B` | the "hot" thermometer |
| `--wx-cold` | `#2F6EA8` | the "cold" thermometer |
| `--wx-dust` | `#B08A50` | blowing dust |
| `--wx-smoke` | `#8B93A0` | smoke |
| `--wx-swirl` | `#6E7B8B` | funnel step 1; hurricane and tropical-storm bands |
| `--wx-swirl-2` | `#8B95A2` | funnel step 2 |
| `--wx-swirl-3` | `#A5ADB7` | funnel step 3 |
| `--wx-eye` | `transparent` | fills a cyclone's eye, if you want it painted |

And two opacities, for the places where translucency — not tone — is the intent:

| Property | Default | Controls |
|---|---|---|
| `--wx-op-band` | `.66` | how much fainter a tropical storm is than a hurricane |
| `--wx-op-tube` | `.28` | the thermometer's tube behind the mercury |

### About the ramps

`--wx-cloud`, `-2` and `-3` are **three steps of one ramp**, not three different
clouds.  Two overlapping cloud shapes in the same grey merge into one blob, so a stacked
symbol paints its back cloud a step along from its front; that gap is the entire reason
`bkn` and `ovc` are distinguishable at 34 px.

They are numbered rather than named because neither obvious name would be true.  Step 2 is
the **back** cloud in `bkn` and the **front** cloud in `ovc`, so they cannot be named for
depth; and a dark theme inverts the ramp — step 3 holds the *lightest* value there — so
they cannot be named for tone either.  `--wx-swirl`, `-2` and `-3` are the same idea for
the tornado's funnel, which fades toward the ground on a light page and therefore darkens
toward the ground on a dark one.

{: .important }
Keep the steps in order and keep a visible gap between them.  Setting all three of a ramp
to one value is the one change that reliably breaks these icons: `few`, `sct`, `bkn` and
`ovc` collapse into flat silhouettes that a reader cannot tell apart at forecast-table
size.

Because a custom property set on the `<svg>` itself inherits through `<use>`, one page can
carry differently-coloured instances — set the properties on a container to theme just
that part of the page.

### A dark palette

Choosing twenty values that keep the ramps legible on a dark ground is real work, so it is
done for you.  `bin/user/nwsicons.py` carries a `DARK` palette chosen against a `#111834`
card and checked at small sizes, and `dark_css()` emits it as a rule:

```
:root {
  --wx-sun: #F2B704;
  --wx-sunray: #E1A904;
  --wx-moon: #A1AAB8;
  --wx-cloud: #525963;
  --wx-cloud-2: #85909E;
  --wx-cloud-3: #B0BCCB;
  --wx-rain: #7FBFFF;
  --wx-snow: #659ECD;
  --wx-sleet: #8DC4FE;
  --wx-bolt: #E1A904;
  --wx-fog: #A2AAB7;
  --wx-wind: #C5D3E5;
  --wx-hot: #FF7361;
  --wx-cold: #7FBFFF;
  --wx-dust: #CAA369;
  --wx-smoke: #A2AAB7;
  --wx-swirl: #C5D3E5;
  --wx-swirl-2: #9DA8B5;
  --wx-swirl-3: #7B838C;
  --wx-eye: transparent;
  --wx-op-band: .74;
  --wx-op-tube: .38;
}
```

Paste it into a `@media (prefers-color-scheme: dark)` block, or into your own
`.theme-dark` class.

It is derived rather than hand-picked.  Each colour keeps its hue and chroma — heat stays
red, the sun stays gold — and only its lightness moves, chosen so that the palette
reproduces the *relative* prominence the light set already has: how far each colour stands
from the page it is drawn on, compared with the others.

{: .important }
The cloud ramp therefore **inverts**: on a dark ground `--wx-cloud` is the *darkest* step
and `--wx-cloud-3` the lightest.  That is deliberate, not a transcription error.  In light
mode the back cloud is the more prominent of the two, so on a dark ground it has to be the
lighter one.  Keep the order as written; swapping it back flattens `bkn` and `ovc`.

{: .note }
`--wx-eye` needs no dark value.  A cyclone's eye is left unpainted, so whatever is behind
the icon shows through and it is correct on every background — see below.

### If you would rather draw your own

`icon_name()` hands back what the extension parsed out of the URL, so a skin can pick its
own artwork without re-implementing the parsing:

```
#set $condition, $is_night, $known = $nwsforecast.icon_name($twelve_hour.iconUrl)
<img src='my_icons/${condition}.png' alt='$twelve_hour.shortForecast'>
```

{: .warning }
Note the braces.  `$condition.png` would make Cheetah look for a `png` attribute *on the
condition* and fail with `NotFound: cannot find 'png'`; `${condition}.png` is what you
want.



That matters because these URLs have more shapes than they first appear:

```
https://api.weather.gov/icons/land/night/bkn?size=medium               plain
https://api.weather.gov/icons/land/day/rain_showers,20?size=small      with a precipitation chance
https://api.weather.gov/icons/land/night/sct/fog?size=medium           two conditions
https://api.weather.gov/icons/land/day/tsra_hi,20/rain,20?size=medium  both at once
```

`icon_name()` handles all four: it strips any `,NN` chance suffix, and for a two-condition
URL it returns the **first** condition — the period's own `shortForecast` already says
"Patchy Fog then Mostly Sunny", so the icon need not.

### The cyclone's eye

`hurricane` and `tropical_storm` are drawn as two spiral bands around a hollow centre.  The
centre is simply not painted, so the page shows through it, and the eye is right on a white
page, a tinted card or a dark theme without your setting anything.

(Through an early 5.2 draft it was a white disc, which was invisible on white and a white
blob everywhere else.  `--wx-eye` remains, defaulting to `transparent`, for a skin that
wants the eye filled rather than open.)

### When NWS adds a condition

`known` is `False` when NWS names a condition this release has no symbol for.  `icon()`
then falls back to NWS's own hosted image, so the reader still sees the right weather, and
the extension logs the name once per weewxd run:

```
nwsicons: no drawn icon for condition 'volcanic_ash' (https://...); using NWS's own image.
```

That `<img>` carries `class="wxi wxi-fallback"`, so your `.wxi` sizing already applies to
it; add `object-fit: contain` if your box is not square.

Coverage is complete as of this release — the drawn set and the conditions NWS publishes
match exactly, and a test holds them together — so that line means NWS has *added* one.
Please report it.

### When NWS has no icon at all

Separately, NWS sometimes gives a period the icon name `unknown`, meaning it has nothing
for that period.  `api.weather.gov` answers **400** for that URL, so linking it would give
your reader a broken image rather than the weather.  `icon()` renders an empty box instead:

```html
<svg class="wxi wxi-unknown" viewBox="0 0 32 32" role="img" aria-label="forecast icon unavailable"></svg>
```

It is the same size as a drawn icon, so the row keeps its alignment.  Style `.wxi-unknown`
if you would rather it showed something — the sample skin gives it a faint dashed outline,
so a reader can tell "no icon" from a layout bug.

A **blank or missing `iconUrl` gets the same box**, for the same reason: it means "no
icon", not "clear sky".  This matters most for alerts, which carry no icon at all — every
alert record stores an empty `iconUrl` — so `$nwsforecast.icon($alert.iconUrl)` gives you
the empty box rather than a sun over a tornado warning.  `icon_name()` answers
`('unknown', False, False)` for a blank URL, and nothing is logged: a blank URL on an
alert is normal, and a line per alert would be noise.

This is a live path, not a backstop.  Through 5.1 weewx-nws failed the whole reply when
any period carried `unknown`, so no such period ever reached a template — at the cost of
discarding an entire forecast, up to 156 periods, over one missing glyph.  Since 5.2 the
period is kept, and the log records the count once per poll:

```
ForecastType.ONE_HOUR: 3 of 156 periods carry NWS's `unknown` icon; storing them
(they render with an empty icon box).
```

### Bundled photographs

Through 5.1 the extension shipped NWS's own images as PNG files, copied into the report's
`HTML_ROOT`.  Nothing ever referenced them and they were removed in 5.2.  If you were
serving them from your own web root, either keep a copy or switch to the drawn icons above.
