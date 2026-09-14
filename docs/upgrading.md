---
title: Upgrading
layout: default
nav_order: 4
description: What existing weewx-nws stations need to know — the database rebuilds itself, why weewx.conf is never rewritten, the WeeWX 5 requirement, and the hard-coded gridpoint URLs to remove.
---

# Upgrading

[weewx-nws manual](https://chaunceygardiner.github.io/weewx-nws/) ·
[weewx-nws on GitHub](https://github.com/chaunceygardiner/weewx-nws) ·
[Report an issue](https://github.com/chaunceygardiner/weewx-nws/issues)

---

Upgrading is the same command as installing — `weectl extension install weewx-nws.zip`
replaces the files in place.  See [Installation](installation.md).  Four things are worth
checking before you restart.

## Do you need to delete `nws.sdb`?

**No — not since 6.1.**  The database schema has changed several times over the extension's
life and there is no migration, but weewx-nws now notices an old one at startup and rebuilds
the table itself:

```
INFO user.nws: The nws database has an old schema (startTime is NOT NULL and should be nullable, endTime is NOT NULL and should be nullable); rebuilding it.
INFO user.nws: Rebuilt archive with the current schema.  The next poll of each forecast type will repopulate it.
```

Nothing is lost that the next poll does not replace.  The database holds the current
forecast and the current alerts; no page ever reads a row older than that, and the three
pollers refill it within seconds of a restart.

Before 6.1 this was your job.  weewx-nws logged `You must delete the nws.sdb database and
restart weewx` and then did nothing at all — no polling, no saving, no tags — until you
deleted the file by hand.

{: .note }
If you are upgrading *to* 6.1 from any earlier release, there is still nothing to do: 6.1's
own startup does the rebuild.  Should the drop ever fail — a permissions problem, say — it
says so and names the database, and deleting it by hand remains the fallback.

## WeeWX 5 and Python 3.9

Since **5.0**, weewx-nws requires WeeWX 5 and Python 3.9 or later.  **4.5.7 was the last
release to support WeeWX 4**, and it remains available on the
[releases page](https://github.com/chaunceygardiner/weewx-nws/releases) for stations still
on WeeWX 4.

## Hard-coded gridpoint URLs

If `weewx.conf` carries `twelve_hour_forecast_url` and `one_hour_forecast_url`, they were
added to work around an NWS bug that mapped a location to the wrong grid square.

**That bug was fixed on 15 March 2023.**  The override outlives the problem it solved, and
a pinned square goes on being used after NWS corrects its mapping or redraws its grid.
Take the two lines out, restart, and check the log: if the warning about the forecast's
polygon does not return, they were doing nothing but harm.  If it does return, put them
back — after confirming the numbers with
[`--check-grid`](gridpoints.md#checking-your-own-location), which may now name a different
square.

## `weewx.conf` is never rewritten

An upgrade adds nothing to `weewx.conf` and changes nothing already in it.  Two
consequences:

- **New options do not appear.**  A station installed years ago has whatever `[NWS]` looked
  like then.  Where the [configuration reference](configuration.md) shows an option your
  file does not have, add it by hand.
- **Old values keep governing.**  Options the installer now writes commented out — so that
  the extension's own default governs — are still live on a station that received them
  live, pinned to whatever the value was that day.  `timeout_secs` shipped as 5 for years,
  and `alert_poll_secs` and `alert_retry_wait_secs` did not exist before 2.3.  Comment out
  or delete a line to hand the choice back to the extension.

## Notable changes for existing stations

**6.1.2** — alerts keep three more fields NWS sends: `areaDesc`, the areas an alert covers;
`response`, CAP's recommended action; and `parameters`, NWS's own parameters for the alert.
See [Alert fields](fields.md#alert-fields).  It is a schema change, and there is nothing to
do: the database rebuilds itself on the first start, as described above.

**6.1** — three things.

**If you print these tags in a skin of your own, delete any `$unit.label.…` you append
after `.format()`.**  Until 6.1 the tags carried no formatter, so `.format('%.0f')` gave a
bare `71` and every example here told you to add the label yourself; it now gives `71°F`,
and the old idiom prints `71°F°F`.  For a range, suppress the first label instead of the
second: `$hour.windSpeed.format('%.0f', add_label=False) to $hour.windSpeed2.format('%.0f')`.
The sample skin never used that idiom, so an unmodified `NWSReport` needs nothing.

The `$nwsforecast` tags now return values in **your report's own units**.  Until 6.1 they
came back in the units NWS served — °F and mph — whatever `[Units]` said, so a report set
to metric printed a Fahrenheit number beside a °C label.  If you run in US units nothing
changes.  If you run in metric, your pages are now right, and a skin that worked around the
old behavior needs attention: asking explicitly (`$hour.outTemp.degree_C`) is still
correct and harmless, but a hard-coded °F label, or your own arithmetic on `.raw`, will now
convert twice.

The sample report's seven-day page now draws two weeks of temperature: the week your
station recorded, read from your own weather archive, then the week NWS forecasts.  Nothing
to configure.  A station with a short archive gets a short observed half and one with no
archive gets the forecast week alone, so there is nothing to do on an upgrade beyond the
usual: reinstalling overwrites `skins/nws/`, so copy anything you customized first.

**6.0** — the sample report was rebuilt.  The three pages are responsive, they follow your
reader's light or dark setting, and they carry charts, day tabs and severity-colored
alert cards.  Nothing you have written against the tags changes: the tag surface only
gained methods.  Two things to know if you had customized the skin.  First, reinstalling
overwrites `skins/nws/` as it always has, so copy anything you want to keep before
upgrading — see [Making it your own](sample-report.md#making-it-your-own).  Second, the
skin gained `css/nws.css` and `scripts/nws.js` and lost `style.inc`; `weectl` copies the
new files but does not remove the old one, so a stale `skins/nws/style.inc` may be left
behind.  Nothing references it and it is harmless; delete it if you like a tidy skin
directory.

**5.1** — WeeWX could fail to shut down when the SIGTERM that stops weewxd landed while the
main thread was inside weewx-nws's startup or end-of-archive-period code.  Those paths now
pass the shutdown through.

**5.0** — WeeWX 5 and Python 3.9 required.  Two fixes worth knowing: `windDir` for ENE had
been reported as 77.5 degrees and is now 67.5, and a ranged wind speed ("2 to 9 mph") had
been rendering as literal template text on the sample report's hourly page.  The standalone
`check_grid.py` — which needed matplotlib — was folded into `nws.py` as
[`--check-grid`](gridpoints.md#checking-your-own-location) and removed.

**4.5 through 4.5.7** — a run of releases spent finding the line between rejecting NWS's
genuinely malformed json and tolerating its merely odd json.  4.5 added the sanity checks;
4.5.4 relaxed them (and changed the schema — see above); 4.5.6 tightened them again; 4.5.7
made room for the null `temperatureTrend` NWS turned out to send, and started logging the
raw response with every rejection.  That last part is why a rejection today leaves evidence
in the log rather than a mystery.

**4.3** — Exercise, system and draft alerts are ignored, as test alerts already were.

**4.1** — `nwsHeadline` added to alerts (schema change).

**2.3** — Alerts got their own polling and retry intervals (`alert_poll_secs`,
`alert_retry_wait_secs`).

The full history is in
[changes.txt](https://github.com/chaunceygardiner/weewx-nws/blob/master/changes.txt).
