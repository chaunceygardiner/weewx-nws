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

"""Drive the rendered sample skin in a real browser at both OS color
settings and read the computed colors back out.

WHY THIS EXISTS.  tests/test_nws_css.py proves the two palettes are correct
ARITHMETIC -- contrast, ladder, prominence -- and vnu proves the stylesheet
parses.  Neither can tell you the theme actually SWITCHES.  A dark block that
never applies passes both: a typo in the media query, a selector the cascade
outranks, a token defined too late.  The page would simply stay light and
every check would still be green.

It also covers the one thing about the drawn icons nobody could reason their
way to: the --wx-* overrides live on :root and the shapes that consume them
are inside a <symbol>, reached through <use>.  Whether a custom property
crosses that boundary is a question about browsers, not about our css.  (It
does, in both engines.)

Chromium AND Firefox, because the two diverge on exactly the kind of thing
this checks; a pass in one is not a pass.

Not collected by pytest -- Playwright is not a test-suite requirement.  Part
of the pre-release checklist.  Run from the repository root:

    /home/weewx/weewx-venv/bin/python tests/verify_theme.py

The rendering needs WeeWX and the driving needs Playwright, and those are
rarely the same interpreter.  If the python running this has Playwright, it
drives the browsers itself; otherwise point --python (or $PLAYWRIGHT_PYTHON)
at one that does:

    python3 -m venv ~/pwenv
    ~/pwenv/bin/pip install playwright
    ~/pwenv/bin/python -m playwright install chromium firefox
    ... tests/verify_theme.py --python ~/pwenv/bin/python

The browser builds land in ~/.cache/ms-playwright, which is per-user and
shared by every project -- whatever one downloads, the others drive.
"""

import argparse
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile

from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_nws import load_fixture, make_alert, make_alerts_json
from test_nws_service import freshen
from test_nws_skin import LONG_NWS_HEADLINE, render_skin

# (label, css selector, computed property).  Two of each kind: a ground, text,
# a filled chip whose text color INVERTS between themes, and the drawn icons.
PROBES: List[Tuple[str, str, str]] = [
    ('page background',      'body',                 'backgroundColor'),
    ('card background',      'section.now',          'backgroundColor'),
    ('body text',            '.fc .prose',           'color'),
    ('page title',           'h1.ctitle',            'color'),
    ('current tab fill',     '.nav a.current',       'backgroundColor'),
    ('current tab text',     '.nav a.current',       'color'),
    ('icon: sun disc',       '#wx-skc-day circle',   'fill'),
    ('icon: overcast back',  '#wx-ovc-day g rect',   'fill'),
]

# The driver runs inside the Playwright venv, which does not have WeeWX; the
# rendering happens out here, which does.  Hence two pythons and a subprocess.
DRIVER = r'''
import json, sys
from playwright.sync_api import sync_playwright
url, probes = sys.argv[1], json.loads(sys.argv[2])
out = {}
with sync_playwright() as pw:
    for engine in ('chromium', 'firefox'):
        browser = getattr(pw, engine).launch()
        out[engine] = {}
        for scheme in ('light', 'dark'):
            ctx = browser.new_context(color_scheme=scheme)
            page = ctx.new_page()
            page.goto(url, wait_until='load')
            out[engine][scheme] = {
                label: page.eval_on_selector(sel, '(el, p) => getComputedStyle(el)[p]', prop)
                for label, sel, prop in probes}
            ctx.close()
        browser.close()
print(json.dumps(out))
'''

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', default=os.environ.get('PLAYWRIGHT_PYTHON'),
                        help='python that has playwright installed; only '
                             'needed if this one does not (default: '
                             '$PLAYWRIGHT_PYTHON)')
    options = parser.parse_args()
    if not options.python and importlib.util.find_spec('playwright'):
        options.python = sys.executable
    if not options.python or not os.path.isfile(options.python):
        print('FAIL: no python with playwright.  Pass --python, or set '
              '$PLAYWRIGHT_PYTHON.  See this file\'s docstring.')
        return 1

    base = tempfile.mkdtemp(prefix='nws-theme-')
    print('Rendering the sample skin to %s (kept for inspection).' % base)
    render_skin(pathlib.Path(base),
                freshen(load_fixture('one_hour.json')),
                freshen(load_fixture('twelve_hour.json')),
                make_alerts_json(make_alert(
                    parameters={'NWSheadline': [LONG_NWS_HEADLINE]})))
    page = os.path.join(base, 'public_html', 'nws', 'index.html')
    assert os.path.isfile(page), page

    driver = os.path.join(base, 'driver.py')
    with open(driver, 'w') as f:
        f.write(DRIVER)
    proc = subprocess.run(
        [options.python, driver, 'file://' + page, json.dumps(PROBES)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        print('FAIL: the browser driver exited %d:' % proc.returncode)
        print((proc.stderr or proc.stdout).strip()[-2000:])
        return 1
    results: Dict[str, Dict[str, Dict[str, str]]] = json.loads(proc.stdout)

    fails = 0
    for engine in sorted(results):
        print('\n%s' % engine)
        light, dark = results[engine]['light'], results[engine]['dark']
        for label, _sel, _prop in PROBES:
            same = light[label] == dark[label]
            # Every probe is a color the two palettes define differently.  If
            # one comes back identical the theme did not reach it -- which is
            # precisely the failure static checks cannot see.
            print('  %-20s %-22s %-22s %s'
                  % (label, light[label], dark[label],
                     'IDENTICAL <-- theme did not apply' if same else 'ok'))
            fails += same
    print('\n%d probe(s) unchanged across the two settings' % fails)
    return 1 if fails else 0

if __name__ == '__main__':
    sys.exit(main())
