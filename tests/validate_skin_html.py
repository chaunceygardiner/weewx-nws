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

"""Validate the sample skin's rendered HTML with the Nu Html Checker.

Renders the skin through WeeWX's report engine (reusing the render-test
harness) in two scenarios -- one with an active alert and no station archive,
one with no alerts, ranged wind speeds and a station archive behind it --
and runs vnu.jar over every generated page.  Rendering both scenarios matters:
these pages emit completely different markup depending on the day.  The alerts
page turns over entirely on whether an alert is active, so validating a live
site only checks whichever branch the weather happens to be in that day (a
one-column spacer row in the alert details table shipped in 2024 and was not
flagged until an alert was active while a warning-strict checker was
watching); and the 7 Day chart grows a seam, two labels and a second stroke
once the station has an archive to draw.

Requires java and vnu.jar (in addition to the test suite's requirements).
The jar is looked for at ~/software/vnu/vnu.jar; override with --vnu-jar or
$VNU_JAR.  Download:
    https://github.com/validator/validator/releases/download/latest/vnu.jar

Not collected by pytest (vnu.jar and java are not test-suite requirements).
Part of the pre-release checklist.  Run from the repository root with the
python that runs WeeWX -- same rules as the test suite (see the README's
"Testing" section):
    /home/weewx/weewx-venv/bin/python tests/validate_skin_html.py
    PYTHONPATH=/usr/share/weewx python3 tests/validate_skin_html.py

The rendered pages are left behind in a temp directory (printed) so a failure
can be inspected.
"""

import argparse
import glob
import os
import pathlib
import shutil
import re
import subprocess
import sys
import tempfile

from typing import List, Tuple

from test_nws import load_fixture, make_alert, make_alerts_json
from test_nws_service import freshen
from test_nws_skin import LONG_NWS_HEADLINE, archive_records, render_skin

def render_scenarios(base_dir: str) -> List[str]:
    """Render both skin scenarios under base_dir; return the html files."""
    one_hour = freshen(load_fixture('one_hour.json'))
    twelve_hour = freshen(load_fixture('twelve_hour.json'))

    with_alert = pathlib.Path(base_dir) / 'with_alert'
    with_alert.mkdir()
    render_skin(with_alert, one_hour, twelve_hour,
                make_alerts_json(make_alert(
                    parameters={'NWSheadline': [LONG_NWS_HEADLINE]})))

    ranged_one_hour = freshen(load_fixture('one_hour.json'))
    ranged_twelve_hour = freshen(load_fixture('twelve_hour.json'))
    for j in (ranged_one_hour, ranged_twelve_hour):
        for period in j['properties']['periods']:
            period['windSpeed'] = '2 to 9 mph'
    no_alert = pathlib.Path(base_dir) / 'no_alert'
    no_alert.mkdir()
    # And this one has a STATION ARCHIVE behind it, so the 7 Day chart draws
    # its observed half -- the seam, the two labels naming it and the broken
    # stroke over the outage are markup the other scenario never emits.  Same
    # argument as the alerts page: a branch nobody validates is a branch that
    # ships broken.
    render_skin(no_alert, ranged_one_hour, ranged_twelve_hour, make_alerts_json(),
                archive=archive_records(18, gap=(10, 11, 12)))

    html_files = sorted(glob.glob(os.path.join(base_dir, '*', 'public_html', 'nws', '*.html')))
    assert len(html_files) == 6, 'expected 6 rendered pages, found %d' % len(html_files)
    return html_files

# Nu's CSS backend is the W3C CSS validator, and it has never learned CONTAINER
# QUERIES: it rejects `container-type` as a property that "doesn't exist" and
# fails to parse any value containing a cqw unit.  The 7 Day chart's two seam
# chips need them -- they are HTML sized in the chart's own viewBox units, and
# 100cqw of the wrapper IS 1040 of those units, which is the one thing no other
# css mechanism can express: a percentage font-size is relative to the parent's
# font-size, and vw breaks the moment .fcwrap hits its 1240px cap.
#
# NARROW BY CONSTRUCTION, and deliberately not a list of message texts.  A
# message is excused only if the source line it points AT still contains the
# feature -- so it can excuse nothing else in the file, it cannot drift as the
# stylesheet is edited, and it disappears of its own accord on the day Nu
# learns the syntax.  Anything else the checker says about these files still
# fails the run.
#
# Container queries have been Baseline since 2023 and both engines
# tests/verify_theme.py drives render these chips correctly; production is not
# affected either way, because the check_weewx_html cron only globs *.html and
# so never reaches an external stylesheet at all.  This script checks css
# BECAUSE the cron cannot -- which is also why the exemption has to live here.
CQ_FEATURES = ('container-type', 'cqw')


def excused(path: str, message: str) -> bool:
    """True for a checker message pointing at a container-query declaration."""
    if not any(f in message for f in ('Parse Error', 'container-type')):
        return False
    where = re.search(r'":(\d+)\.\d+-', message)
    if not where:
        return False
    try:
        with open(path, encoding='utf-8') as f:
            line = f.readlines()[int(where.group(1)) - 1]
    except (OSError, IndexError):
        return False
    return any(f in line for f in CQ_FEATURES)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render the sample skin and validate it with the Nu Html Checker.")
    parser.add_argument('--vnu-jar',
                        default=os.environ.get(
                            'VNU_JAR', os.path.expanduser('~/software/vnu/vnu.jar')),
                        help='Path to vnu.jar (default: $VNU_JAR or ~/software/vnu/vnu.jar).')
    options = parser.parse_args()

    if shutil.which('java') is None:
        print('FAIL: java not found on PATH (vnu.jar needs a java runtime).')
        return 1
    if not os.path.isfile(options.vnu_jar):
        print('FAIL: %s not found.  Download the Nu Html Checker jar from' % options.vnu_jar)
        print('  https://github.com/validator/validator/releases/download/latest/vnu.jar')
        print('or point --vnu-jar (or $VNU_JAR) at an existing copy.')
        return 1

    base_dir = tempfile.mkdtemp(prefix='nws-skin-html-')
    print('Rendering the sample skin to %s (kept for inspection).' % base_dir)
    html_files = render_scenarios(base_dir)

    # The skin's stylesheet is checked TOO, and it has to be asked for
    # separately: --also-check-css only reaches css embedded in the html, and
    # the production check_weewx_html cron only globs *.html -- so an external
    # stylesheet is otherwise never validated anywhere.
    css_files = sorted(set(
        os.path.join(os.path.dirname(f), 'css', 'nws.css') for f in html_files))
    css_files = [f for f in css_files if os.path.isfile(f)]
    if not css_files:
        print('FAIL: the skin rendered no css/nws.css to validate.')
        return 1

    # One JVM run over every page; attribute the checker's messages (GNU
    # format: "file:<path>":...) back to files for the per-file report.
    proc = subprocess.run(
        ['java', '-jar', options.vnu_jar, '--Werror', '--also-check-css'] + html_files,
        capture_output=True, text=True)
    css_proc = subprocess.run(
        ['java', '-jar', options.vnu_jar, '--Werror', '--css'] + css_files,
        capture_output=True, text=True)
    messages = proc.stdout + proc.stderr + css_proc.stdout + css_proc.stderr

    results: List[Tuple[str, str, str]] = []
    attributed, n_excused = set(), 0
    for html_file in html_files + css_files:
        # Relative to base_dir, so a css file under public_html/nws/css is
        # named unambiguously rather than being folded onto a page's name.
        page = os.path.relpath(html_file, base_dir)
        mine = [line for line in messages.splitlines() if html_file in line]
        attributed.update(mine)
        page_messages = [line for line in mine if not excused(html_file, line)]
        n_excused += len(mine) - len(page_messages)
        if page_messages:
            results.append((page, 'FAIL', page_messages[0]))
        else:
            results.append((page, 'PASS', ''))
    # ANYTHING THE CHECKER SAID ABOUT NO FILE WE ENUMERATED.  This is the only
    # place a jar that died partway through the list can show up: the files it
    # reached report clean, `fails` is 0, and without this the run would print
    # 8 PASS and return 0 for files that were never opened.  It is also why
    # `excused` may not be counted as "every line vnu printed" -- a JVM notice
    # on stderr would have been tallied as a forgiven container-query error.
    orphans = [ln for ln in messages.splitlines()
               if ln.strip() and ln not in attributed]

    width = max(len(name) for name, _, _ in results)
    fails = sum(1 for _, status, _ in results if status == 'FAIL')
    for name, status, detail in results:
        print('%-*s  %-4s  %s' % (width, name, status, detail))
    print()
    # vnu's own exit status still has to be looked at -- but it can no longer
    # BE the verdict, because the checker exits 1 for the container-query
    # declarations `excused` is there to forgive.  What replaces it is the
    # orphan list: a non-zero rc is a failure whenever vnu said anything about
    # something other than the files we enumerated, which covers both a jar
    # that would not start (nothing at all) and one that died partway through
    # (a stack trace, after some files reported clean).
    rc = proc.returncode or css_proc.returncode
    if rc != 0 and (orphans or not messages.strip()):
        print('FAIL: vnu.jar exited %d with %d message(s) about no file we '
              'asked it to check:' % (rc, len(orphans)))
        print('\n'.join(orphans[:20]) if orphans else '(no output at all)')
        return 1
    if n_excused:
        print('%d message(s) excused: Nu\'s css backend does not know container '
              'queries.  See CQ_FEATURES.' % n_excused)
    print('%d PASS, %d FAIL' % (len(results) - fails, fails))
    return 1 if fails else 0

if __name__ == '__main__':
    sys.exit(main())
