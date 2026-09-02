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

Everything weewx-nws serves lives under `$nwsforecast`.  Four tags fetch the forecast
itself:

| Tag | Returns |
|---|---|
| `$nwsforecast.twelve_hour_forecasts(max)` | The latest twelve-hour forecast: a list of periods, daytime and nighttime, about 6.5 days out |
| `$nwsforecast.one_hour_forecasts(max)` | The latest one-hour forecast: a list of hourly periods, 156 hours out |
| `$nwsforecast.alerts()` | Every active NWS alert for the station's location |
| `$nwsforecast.alert_count()` | How many of them there are |

`max` is optional on the two forecast calls: `twelve_hour_forecasts(4)` returns the first
four periods, `one_hour_forecasts(24)` the next day's worth.  Omit it to get all of them.

Four more shape that forecast into what a page actually draws — see
[Shaping the forecast](#shaping-the-forecast):

| Tag | Returns |
|---|---|
| `$nwsforecast.days(periods)` | Twelve-hour periods grouped by the calendar day each one starts in |
| `$nwsforecast.hour_days(records)` | One-hour records grouped the same way — the day tabs on an hourly page |
| `$nwsforecast.points(records)` | Hourly records as plain numbers, for chart arithmetic |
| `$nwsforecast.week_range(days)` | `(min, max)` temperature across every period on show |

And seven carry the NWS and CAP semantics that are easy to get subtly wrong — see
[Alert semantics](#alert-semantics):

| Tag | Returns |
|---|---|
| `$nwsforecast.line_label(period)` | NWS's period name, kept only where it says something the row does not |
| `$nwsforecast.ordered(alerts)` | Alerts in effect first, then most serious first |
| `$nwsforecast.is_active(alert)` | Whether that alert is in effect now |
| `$nwsforecast.alert_state(alert)` | `active`, `upcoming` or `ended` — the same question, told in full |
| `$nwsforecast.alert_window(alert)` | `(onset, finish, open_ended)` — an alert with no end leans on its expiry |
| `$nwsforecast.parse_description(desc)` | A CAP description as labeled sections, paragraphs and bullets |
| `$nwsforecast.nice_caps(text)` | Title case that survives NWS's shouted acronyms |

{: .note }
These last eleven return **data**, not markup — the one deliberate exception is
`icon()` below, which returns an `<svg>`.  They exist because they are facts about NWS's
feed rather than anybody's taste in layout, so every skin gets the same answer instead of
each re-deriving it.  How the result is *drawn* is yours.

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

They come back newest first, by the time each alert was issued — which is rarely the order
a reader wants.  `ordered()` puts the ones in effect first and then the most serious first;
see [Alert semantics](#alert-semantics).

Two of the CAP fields are worth reading before you design a page around them.
`nwsHeadline` is the upper-case banner NWS writes and **it can be missing**, in which case
`headline` is the sentence to fall back on.  And `description` and `instructions` are long,
multi-paragraph plain text with real newlines in them, which do not become markup on their
own.

{: .important }
Do not hand-convert that text.  `$nwsforecast.parse_description()` turns a description into
labeled sections, paragraphs and bullets, handling the four shapes NWS actually sends;
`$nwsforecast.nice_caps()` title-cases the shouted headline without flattening its
acronyms.  Both are covered in [Alert semantics](#alert-semantics), and the sample report
uses them.  Replacing newlines by hand — which earlier versions of this manual showed —
gets the common case and none of the others.

[Alert fields](fields.md#alert-fields) has the full field list.

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

## Icons

Each forecast period carries an `iconUrl` naming one of NWS's 34 conditions.  The extension
draws all 34 itself, day and night, so a skin can show a crisp, styleable icon instead of
hot-linking a photograph.

| Tag | Returns |
|---|---|
| `$nwsforecast.icon_sprite` | The `<symbol>` definitions.  Emit **once** per page |
| `$nwsforecast.icon(iconUrl)` | An `<svg>` for that period, ready to drop in |
| `$nwsforecast.icon(iconUrl, cls)` | The same, with `cls` in place of the default `wxi` |
| `$nwsforecast.icon_name(iconUrl)` | `(condition, is_night, known)` parsed out of the URL |

```
$nwsforecast.icon_sprite

#for $twelve_hour in $nwsforecast.twelve_hour_forecasts()
  $nwsforecast.icon($twelve_hour.iconUrl)
#end for
```

Worked examples, including what to do when NWS names a condition the extension has no
symbol for, are in [Drawn icons](recipes.md#drawn-icons).

{: .important }
Three sets of names are a contract, and will not change without a major version: the symbol
ids, `wx-<condition>-<day|night>` (for example `wx-fog-night`); the css classes on the
markup `icon()` emits — `wxi` on the `<svg>`, `wxi wxi-fallback` on the `<img>` used when a
condition has no drawn symbol, and `wxi wxi-unknown` on the empty box used when NWS itself
has no icon for a period; and the `--wx-*` custom properties that color the drawings.
Style those, and reference those ids, freely.

The icons carry no width or height of their own — sizing is the skin's job, via `.wxi`.
Every color is emitted as `var(--wx-name, #default)`, so they render exactly as shown
until you redefine something; a complete dark palette ships with the extension.  Both are
covered in [Drawn icons](recipes.md#drawn-icons).

## Shaping the forecast

NWS hands you a flat list of periods.  Almost every page wants them grouped by day, and
that grouping has a trap in it, so it is done here rather than in each skin.

`days()` groups twelve-hour periods by **the calendar day each one starts in** — not by
walking day/night pairs.  At 05:35 the feed leads with `Overnight` (01:00–06:00) followed
by `Tuesday` (06:00–18:00); a pair-walk gives `Overnight` a row of its own, so one date
appears on two consecutive rows and the leading one gets labeled "Tonight" at dawn.
Grouping by start date is also how NWS itself reads: `Tuesday Night` starts on Tuesday and
belongs to Tuesday, though it ends on Wednesday.

Each entry is a dict:

| Key | What it is |
|---|---|
| `date` | A `datetime.date` |
| `label` | `Today`, or the weekday name |
| `datestr` | `Sep 1` |
| `group` | Every period starting that day, in time order |
| `day` | The first daytime period, or `None` |
| `nights` | The non-daytime periods |
| `hi` | The daytime period's temperature, or `None` |
| `lo` | The coldest night temperature, or `None` |

```
#set $days = $nwsforecast.days($nwsforecast.twelve_hour_forecasts())
#for $d in $days[0:7]
  <h3>$d.label $d.datestr</h3>
  #for $p in $d.group
    $nwsforecast.line_label($p): $p.detailedForecast
  #end for
#end for
```

**No slicing happens in the tag.**  How many rows to draw is a judgment about your page,
so take `[0:7]` or whatever suits.  Two ends of the feed degrade, and differently: an
evening poll leads with `Tonight`, so the first date can hold only a night — `day` and
`hi` are `None` — and the last date can hold only a day, where `nights` is empty and `lo`
is `None`.  Guard both if you draw every date you are given.

`hour_days()` does the same for one-hour records, adding a `key` (`2026-09-01`) suitable
for a tab id, and `rows`.  It deliberately does **not** include chart points: call
`points()` on a day's `rows` when you want them.  `points()` unwraps the ValueHelpers into
plain numbers and drops any hour with no time or no temperature, since those cannot be
plotted at all.

`week_range()` takes the output of `days()` and returns the `(min, max)` across every
period on show, so each day's bar can be positioned against one shared scale.  With
nothing to measure it returns `(0.0, 1.0)` — that is a placeholder, not a range, so do not
caption it as one.

{: .note }
All four take the ValueHelper-wrapped records `$nwsforecast` returns, not raw database
rows.

## Alert semantics

`ordered()` sorts alerts the way a reader needs them — in effect first, then most serious
first — which is not the order the feed arrives in.  `is_active()` answers the same
question for one alert, and takes an optional instant so a page rendering a batch can pass
one `now` to every call; without that an alert can be counted in effect and then rendered
expired in the same pass.

`alert_state()` tells the whole story rather than half of it, returning `active`,
`upcoming` or `ended`.  The three are total and mutually exclusive:

| State | When |
|---|---|
| `active` | `is_active()` is true |
| `ended` | the alert's finish is known and now is past it — **whatever the onset says** |
| `upcoming` | everything else |

{: .note }
That middle rule is worth reading twice.  The obvious way to write it is "started, but not
active", and that is wrong: NWS does not always give an onset, and an alert with no onset
whose window has already closed has *ended* — but it never "started", so the obvious
spelling files it as upcoming.  Two skins wrote this classification independently and both
got it wrong, from opposite directions, which is why it lives here now.

`alert_window()` returns `(onset, finish, open_ended)`.  weewx-nws never leaves an alert's
end time empty: where NWS gave no `ends` it stores `expires`, so **the two being equal is
what an open-ended alert looks like** by the time a skin sees it.  About one alert in ten
has no end at all, so anything drawing a progress bar must not divide by a span that does
not exist.

`parse_description()` turns a CAP description into structure — a list of dicts with
`label`, `paragraphs` and `bullets`, where an empty label is unlabeled prose.  Three
quarters of real alerts are nothing but unlabeled prose, so a layout that assumes a
WHAT/WHERE/WHEN grid will be empty for most of them.

It handles the shapes the live feed actually produces.  A starred line is a **header**
when its label is shouted — `* WHAT...`, `* HEADER: text`, or `* LOCATIONS AFFECTED` alone
on its line with `- ` sub-bullets under it — and a **bullet** otherwise, which is how the
warning products list their facts (`* Until 730 PM EDT.`).  That split is the feed's own
convention, not one imposed here.  Bare uppercase labels with no asterisk are headers too
— `HAZARD...`, `SOURCE...`, `IMPACT...` — and the tropical statements' `**banner**` lines
are unwrapped.  No asterisk reaches your page, whatever a line turns out to be.

A single newline is always teletype wrapping and a blank line is always a paragraph break,
so text is reflowed; the measure is your stylesheet's business.

`nice_caps()` title-cases NWS's shouted headlines while leaving acronyms upright —
`str.title()` alone gives "11 Am Pdt".

```
#for $alert in $nwsforecast.ordered($nwsforecast.alerts())
  <h3>$alert.event</h3>
  #for $block in $nwsforecast.parse_description($alert.description)
    #if $block.label
      <h4>$block.label</h4>
    #end if
    #for $p in $block.paragraphs
      <p>$p</p>
    #end for
  #end for
#end for
```

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
