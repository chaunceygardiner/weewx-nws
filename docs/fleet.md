---
title: Sharing forecasts across a fleet
layout: default
nav_order: 9
description: read_from_dir and [[RsyncSpec]] — letting one WeeWX station fetch forecasts and alerts from NWS and the rest read them from files.
---

# Sharing forecasts across a fleet

[weewx-nws manual](https://chaunceygardiner.github.io/weewx-nws/) ·
[weewx-nws on GitHub](https://github.com/chaunceygardiner/weewx-nws) ·
[Report an issue](https://github.com/chaunceygardiner/weewx-nws/issues)

---

{: .note }
This is an advanced arrangement for one specific situation.  If you run a single station,
skip this page — the defaults are what you want.

Several WeeWX machines at **the same location** each polling NWS for the same forecast is
several times the requests for one answer.  NWS asks API clients not to do that, and can
block a source that does.  So weewx-nws can be pointed at files instead of at NWS: one
machine fetches, and copies what it got to the others, which read from disk and make no
requests at all.

Both halves are unwritten by the installer; add them by hand.

## The client half: `read_from_dir`

```ini
[NWS]
    read_from_dir = /root/forecasts
```

With this set, each poll looks in that directory for a file named for the forecast type —
`ONE_HOUR`, `TWELVE_HOUR` or `ALERTS` — holding the json NWS returned, and parses that
instead of making a request:

```
INFO user.nws: Reading ForecastType.ONE_HOUR forecasts from file: /root/forecasts/ONE_HOUR.
```

Everything downstream is unchanged: the same sanity checks, the same parsing, the same
database, the same tags.  The client also skips the startup gridpoint lookup, since it is
not going to ask NWS anything.

{: .important }
A file that is not there is not an error — the client falls back to fetching that type from
NWS itself.  That keeps a client useful before the first copy arrives, but it also means a
fleet whose copying has quietly broken goes back to polling NWS from every machine.  The
log says which of the two happened, on every poll.

## The fetching half: `[[RsyncSpec]]`

On the one machine that does contact NWS, name the clients:

```ini
[NWS]
    [[RsyncSpec]]
        enable = true
        remote_clients = client1, client2
        remote_user = root
        remote_dir = /root/forecasts
        compress = false
        log_success = false
        ssh_options = -o ConnectTimeout=1
        timeout = 1
```

| Option | Default | Effect |
|---|---|---|
| `enable` | `false` | Whether to copy anything at all. |
| `remote_clients` | — | The machines to copy to, comma separated.  Required. |
| `remote_user` | — | The user to connect as. |
| `remote_dir` | — | The directory to write into — the clients' `read_from_dir`. |
| `remote_port` | unset | A non-standard ssh port. |
| `compress` | `true` | Pass `--compress` to rsync.  These files are small and local; `false` is usually right. |
| `log_success` | `false` | Log every successful copy, not just failures. |
| `ssh_options` | `-o ConnectTimeout=1` | Passed to ssh. |
| `timeout` | `1` | Seconds before the transfer gives up. |

The copying uses WeeWX's own rsync-over-ssh helper, so it needs key-based ssh from the
fetching machine to each client, for `remote_user`, without a passphrase prompt.  A failed
copy is logged and otherwise ignored — the fetching machine's own forecasts are unaffected.

## What gets copied, and when

| Type | Copied |
|---|---|
| `ALERTS` | Immediately after every successful download |
| `ONE_HOUR`, `TWELVE_HOUR` | When a newly generated forecast is saved to the database |

Alerts travel first and fastest because they are the time-critical type: a warning is worth
nothing an hour late.  Forecasts move on the slower path — there is no point copying a
forecast that NWS answered `304` for, since the clients already have it.

## Setting one up

1. Pick the fetching machine.  Give it an ordinary weewx-nws configuration, plus
   `[[RsyncSpec]]` naming the others.
2. On each client, create `read_from_dir` and set it in `[NWS]`.  Leave everything else
   alone — the clients keep their own `nws.sdb` and generate their own reports.
3. Set up key-based ssh from the fetcher to each client.
4. Restart WeeWX everywhere, and watch the clients' logs for `Reading ... from file`.

All the machines must be at **the same location**.  Nothing enforces it: what a client
reads from the file is the forecast for the *fetcher's* coordinates, and the client stores
it under its own without complaint.  A fleet spread across a county would therefore serve
one location's forecast everywhere, silently.  That is the arrangement's one real hazard,
and the reason it is not meant for general use.

{: .note }
The copying is the one part of weewx-nws with no automated test: it shells out to rsync.
The author's own fleet exercises it continuously, which is the whole of its testing.
