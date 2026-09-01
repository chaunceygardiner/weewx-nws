#!/usr/bin/python3
# Copyright 2026 by John A Kline <john@johnkline.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

"""Live verification harness: run EVERY nws.py command-line option against the
real NWS API and report PASS/FAIL for each.

This complements the hermetic pytest suite, which never contacts NWS: pytest's
job is catching regressions in this extension; this harness's job is proving
every utility runs and that live NWS output still parses.  It is part of the
pre-release checklist and is NOT collected by pytest (no network in pytest).

Run it from the repository root with the python that runs WeeWX -- same rules
as the utilities themselves (see the manual's "Command-line utilities" page).
For a pip install or migrated setup.py layout, activate the virtual
environment (or name its python explicitly); for a package install, set
PYTHONPATH so weewx is importable:
    /home/weewx/weewx-venv/bin/python tests/verify_cli.py [--skip-multigrid]
    PYTHONPATH=/usr/share/weewx python3 tests/verify_cli.py [--skip-multigrid]

A full run makes ~170 requests to api.weather.gov — the 50-city sweep
dominates.  Use --skip-multigrid when iterating, and don't run the full sweep
repeatedly in quick succession: NWS throttles, and a throttled /points request
fails the sweep (rerun later; it is not a code failure).
"""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile

from typing import List, Optional, Tuple

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NWS_PY = os.path.join(REPO, 'bin', 'user', 'nws.py')

results: List[Tuple[str, str, str]] = []

def run(name: str, args: List[str], expect_re: str,
        pythonpath: Optional[str] = None, timeout: int = 240) -> None:
    env = dict(os.environ)
    if pythonpath:
        # Prepend: a package install needs its own PYTHONPATH (/usr/share/weewx)
        # to survive, or the subprocess cannot import weewx.
        env['PYTHONPATH'] = (pythonpath + os.pathsep + env['PYTHONPATH']
                             if env.get('PYTHONPATH') else pythonpath)
    try:
        proc = subprocess.run([sys.executable, NWS_PY] + args, capture_output=True,
                              text=True, timeout=timeout, env=env, cwd=REPO)
    except subprocess.TimeoutExpired:
        results.append((name, 'FAIL', 'timeout after %ds' % timeout))
        return
    out = proc.stdout + proc.stderr
    match = re.search(expect_re, out)
    if proc.returncode != 0:
        results.append((name, 'FAIL', 'rc=%d: %s' % (proc.returncode, out[-200:].strip())))
    elif match:
        results.append((name, 'PASS', match.group(0).split('\n')[0][:70]))
    else:
        results.append((name, 'FAIL', 'expected /%s/; got: %s' % (expect_re, out[-200:].strip())))

def main() -> int:
    parser = argparse.ArgumentParser(
        description='Run every nws.py command-line option against live NWS.')
    parser.add_argument('--latitude', default='37.431495',
                        help='Station latitude (default: Palo Alto).')
    parser.add_argument('--longitude', default='-122.110937',
                        help='Station longitude (default: Palo Alto).')
    parser.add_argument('--skip-multigrid', action='store_true',
                        help='Skip the 50-city sweep (~150 NWS requests).')
    options = parser.parse_args()
    lat, long = options.latitude, options.longitude

    run('--help', ['--help'], r'--check-grid')
    run('--test-point-in-polygon', ['--test-point-in-polygon'], r'Test completed\.')
    run('--check-grid', ['--check-grid', '--latitude', lat, '--longitude', long],
        r'nws computed the (correct|incorrect) grid')
    run('--test-requester ONE_HOUR',
        ['--test-requester', '--type', 'ONE_HOUR', '--latitude', lat, '--longitude', long],
        r'[1-9]\d* ForecastType\.ONE_HOUR printed\.')
    run('--test-requester TWELVE_HOUR',
        ['--test-requester', '--type', 'TWELVE_HOUR', '--latitude', lat, '--longitude', long],
        r'[1-9]\d* ForecastType\.TWELVE_HOUR printed\.')
    run('--test-requester ALERTS',
        ['--test-requester', '--type', 'ALERTS', '--latitude', lat, '--longitude', long],
        r'\d+ ForecastType\.ALERTS printed\.')
    run('--test-parse-all-alerts', ['--test-parse-all-alerts'], r'Parsed \d+ alerts\.')
    run('--test-parse-all-alerts --print-records',
        ['--test-parse-all-alerts', '--print-records'],
        r'(?s)shortForecast.*Parsed \d+ alerts\.')
    run('--test-service (with --binding)',
        ['--test-service', '--binding', 'cli_verify_binding',
         '--latitude', lat, '--longitude', long],
        r'(?s)interval.*720.*interval.*60',
        pythonpath=os.path.join(REPO, 'bin'))

    # --insert-forecast and --view-forecasts need a database with the nws schema.
    sys.path.insert(0, os.path.join(REPO, 'bin', 'user'))
    import nws as nws_module
    fixture = os.path.join(REPO, 'tests', 'fixtures', 'one_hour.json')
    with open(fixture) as f:
        period_count = len(json.load(f)['properties']['periods'])
    tmpdir = tempfile.mkdtemp(prefix='nws-verify-cli-')
    db = os.path.join(tmpdir, 'nws.sdb')
    conn = sqlite3.connect(db)
    conn.execute('CREATE TABLE archive (%s)' %
                 ', '.join('%s %s' % (column, sql_type) for column, sql_type in nws_module.table))
    conn.commit()
    conn.close()

    run('--insert-forecast',
        ['--insert-forecast', '--type', 'ONE_HOUR', '--filename', fixture,
         '--nws-database', db, '--latitude', lat, '--longitude', long],
        r'Inserted %d ForecastType\.ONE_HOUR forecasts' % period_count)
    run('--insert-forecast (dup rejected)',
        ['--insert-forecast', '--type', 'ONE_HOUR', '--filename', fixture,
         '--nws-database', db, '--latitude', lat, '--longitude', long],
        r'already in the database\.  Skipping insert\.')
    for criterion, expect in (('LATEST', r'interval\s*:?\s*60'),
                              ('ALL', r'interval\s*:?\s*60'),
                              ('SUMMARY', r'(?i)generated')):
        run('--view-forecasts %s' % criterion,
            ['--view-forecasts', '--type', 'ONE_HOUR', '--nws-database', db,
             '--view-criterion', criterion], expect)

    if options.skip_multigrid:
        results.append(('--test-multiple-gridpoints', 'SKIP', '--skip-multigrid given'))
    else:
        # Exits non-zero on any sanity-check failure or persistent fetch failure,
        # so rc=0 means every city completed.
        run('--test-multiple-gridpoints', ['--test-multiple-gridpoints'],
            r'Fetched \d+ ALERTS\.', timeout=420)

    width = max(len(name) for name, _, _ in results)
    fails = 0
    for name, status, detail in results:
        if status == 'FAIL':
            fails += 1
        print('%-*s  %-4s  %s' % (width, name, status, detail))
    print()
    print('%d PASS, %d FAIL, %d SKIP' % (
        sum(1 for _, s, _ in results if s == 'PASS'), fails,
        sum(1 for _, s, _ in results if s == 'SKIP')))
    return 1 if fails else 0

if __name__ == '__main__':
    sys.exit(main())
