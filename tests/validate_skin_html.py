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
harness) in two scenarios -- one with an active alert, one with no alerts and
ranged wind speeds -- and runs vnu.jar over every generated page.  Rendering
both scenarios matters: the alerts page emits completely different markup
depending on whether an alert is active, so validating a live site only checks
whichever branch the weather happens to be in that day (a one-column spacer
row in the alert details table shipped in 2024 and was not flagged until an
alert was active while a warning-strict checker was watching).

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
import subprocess
import sys
import tempfile

from typing import List, Tuple

from test_nws import load_fixture, make_alert, make_alerts_json
from test_nws_service import freshen
from test_nws_skin import LONG_NWS_HEADLINE, render_skin

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
    render_skin(no_alert, ranged_one_hour, ranged_twelve_hour, make_alerts_json())

    html_files = sorted(glob.glob(os.path.join(base_dir, '*', 'public_html', 'nws', '*.html')))
    assert len(html_files) == 6, 'expected 6 rendered pages, found %d' % len(html_files)
    return html_files

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

    # One JVM run over all six pages; attribute the checker's messages (GNU
    # format: "file:<path>":...) back to pages for the per-page report.
    proc = subprocess.run(
        ['java', '-jar', options.vnu_jar, '--Werror', '--also-check-css'] + html_files,
        capture_output=True, text=True)
    messages = proc.stdout + proc.stderr

    results: List[Tuple[str, str, str]] = []
    for html_file in html_files:
        page = os.path.join(os.path.relpath(os.path.dirname(os.path.dirname(
            os.path.dirname(html_file))), base_dir), os.path.basename(html_file))
        page_messages = [line for line in messages.splitlines() if html_file in line]
        if page_messages:
            results.append((page, 'FAIL', page_messages[0]))
        else:
            results.append((page, 'PASS', ''))

    width = max(len(name) for name, _, _ in results)
    fails = sum(1 for _, status, _ in results if status == 'FAIL')
    for name, status, detail in results:
        print('%-*s  %-4s  %s' % (width, name, status, detail))
    print()
    if proc.returncode != 0 and fails == 0:
        # Non-zero rc with no messages attributed to a page (e.g. a jar failure).
        print('FAIL: vnu.jar exited %d:' % proc.returncode)
        print(messages.strip())
        return 1
    print('%d PASS, %d FAIL' % (len(results) - fails, fails))
    return 1 if fails or proc.returncode != 0 else 0

if __name__ == '__main__':
    sys.exit(main())
