---
title: Command-line utilities
layout: default
nav_order: 10
description: Running nws.py from the command line — check a gridpoint, see what NWS is serving right now, parse every active US alert, inspect the database.
---

# Command-line utilities

[weewx-nws manual](https://chaunceygardiner.github.io/weewx-nws/) ·
[weewx-nws on GitHub](https://github.com/chaunceygardiner/weewx-nws) ·
[Report an issue](https://github.com/chaunceygardiner/weewx-nws/issues)

---

`nws.py` is not only the extension: run it directly and it becomes a diagnostic tool.  Its
job is answering the question no log line can — *what is NWS actually serving for my
location right now?* — which is where a problem with this extension is usually settled.

## Running it

`nws.py` imports WeeWX, so it must run with the python that runs WeeWX.  Which command that
is depends on your install:

```
# pip install (activate WeeWX's virtual environment first):
source ~/weewx-venv/bin/activate
python ~/weewx-data/bin/user/nws.py --help

# Debian or Red Hat package install:
PYTHONPATH=/usr/share/weewx python3 /etc/weewx/bin/user/nws.py --help
```

The examples below shorten that to `bin/user/nws.py`; use whichever of the forms above
matches your install.

{: .note }
One exception: `--test-service` stands up a WeeWX engine, which imports `user.nws`, so it
also needs the directory *containing* `user` on `PYTHONPATH` — `~/weewx-data/bin` for a pip
install, and for a package install both: `PYTHONPATH=/usr/share/weewx:/etc/weewx/bin`.

## The utilities

### `--check-grid`

Check that NWS maps your latitude and longitude to a gridpoint that really contains them,
and print the `weewx.conf` lines that pin the correct one if it does not.  See
[Gridpoints](gridpoints.md).

```
python bin/user/nws.py --check-grid --latitude 38.8977 --longitude -77.0365
```

### `--test-requester`

Fetch one type of forecast for a location, parse it, and pretty print every record.  The
quickest way to see exactly what NWS is serving — and the first thing to run when a field
looks wrong on a page.  `--type` takes `ONE_HOUR`, `TWELVE_HOUR` or `ALERTS`.

```
python bin/user/nws.py --test-requester --type TWELVE_HOUR --latitude 38.8977 --longitude -77.0365
```

### `--test-parse-all-alerts`

Fetch **every** alert currently active in the United States — several hundred — and run
each through the sanity check and the parser, reporting how many parsed.  This is the
widest net there is for alert-parsing problems, and it is what to run after any change to
the alert code.  `--print-records` prints each alert as well as counting it.

```
python bin/user/nws.py --test-parse-all-alerts
```

### `--test-service`

Stand up the full NWS service as WeeWX would, against a temporary sqlite database: request
forecasts, save them, read them back.  `--binding` uses a data binding other than
`nws_binding`.

```
PYTHONPATH=/home/weewx/bin python bin/user/nws.py --test-service --latitude 38.8977 --longitude -77.0365
```

### `--test-multiple-gridpoints`

Fetch twelve-hour and one-hour forecasts for several dozen US cities — a broad sample of
NWS forecast offices, and the best way to catch a parsing assumption that only holds in one
part of the country.  It makes about 150 requests; do not run it in a loop.

```
python bin/user/nws.py --test-multiple-gridpoints
```

### `--test-point-in-polygon`

An offline self-test of the gridpoint containment check.  The only utility that does not
contact NWS.

```
python bin/user/nws.py --test-point-in-polygon
```

### `--view-forecasts`

Inspect an `nws.sdb` — read-only, and safe to run against the live database.  Requires
`--type` and `--view-criterion`:

| Criterion | Prints |
|---|---|
| `SUMMARY` | One line per forecast: inserted, generated, and the first and last period it covers |
| `LATEST` | Every record of the most recently generated forecast of that type |
| `ALL` | Every record of that type in the database |

```
python bin/user/nws.py --view-forecasts --type ONE_HOUR \
    --nws-database /home/weewx/archive/nws.sdb --view-criterion SUMMARY
```

### `--insert-forecast`

Load a forecast saved to a file (json, as NWS returned it) into an `nws.sdb` — for
reproducing a problem from a captured forecast.  Requires `--type`, `--filename`,
`--nws-database`, `--latitude` and `--longitude`; `--archive_interval` defaults to 300
seconds.

```
python bin/user/nws.py --insert-forecast --type ONE_HOUR --filename /tmp/ONE_HOUR \
    --nws-database /tmp/nws.sdb --latitude 38.8977 --longitude -77.0365
```

### `--help`

Lists every option.

## Testing a checkout

The repository carries a hermetic pytest suite — it never contacts NWS — plus one harness
that does, and two more that are offline but need something the suite does not.  Run them
from the repository root, with the same python as above:

```
python -m pytest tests              # the hermetic suite
python tests/verify_cli.py          # every utility above, against live NWS, PASS/FAIL each
python tests/validate_skin_html.py  # renders the skin; validates every page and its css
python tests/verify_theme.py        # drives the pages in a browser at both color settings
```

`verify_cli.py` is the only one that contacts NWS; it takes `--skip-multigrid` to leave out
the 50-city sweep and its ~150 requests.  `validate_skin_html.py` needs `java` and
`vnu.jar`; `verify_theme.py` needs Playwright, and is the only check that can catch a dark
theme that validates, tests clean and never actually applies.

The layers have different jobs, and both are needed: the suite catches regressions in
*this extension*, while the live utility catches changes in *what NWS serves* — which the
hermetic tests, validating our assumptions against saved responses, cannot see.
