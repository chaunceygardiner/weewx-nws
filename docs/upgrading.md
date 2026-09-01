---
title: Upgrading
layout: default
nav_order: 4
description: What existing weewx-nws stations need to know — when to delete nws.sdb, why weewx.conf is never rewritten, the WeeWX 5 requirement, and the hard-coded gridpoint URLs to remove.
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

The database schema has changed several times, and **there is no migration**.  Deleting the
database is the whole of the fix, and it costs nothing: the next poll refills it, and
nothing but old forecasts is lost.

| Coming from | Action |
|---|---|
| 4.5.4 or later | Nothing to do |
| Earlier than 4.5.4 | Delete `nws.sdb` after installing, before restarting WeeWX |

If you skip it, weewx-nws logs this at startup and then does nothing at all — no
polling, no saving, no tags.  WeeWX itself carries on:

```
ERROR user.nws: You must delete the nws.sdb database and restart weewx.  It contains an old schema!
```

The database sits with the weather archive, in the directory `SQLITE_ROOT` names under
`[DatabaseTypes]` in `weewx.conf` — `/var/lib/weewx` on a package install,
`~/weewx-data/archive` on a pip one:

```
rm /var/lib/weewx/nws.sdb
```

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
