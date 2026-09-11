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
from test_nws_skin import LONG_NWS_HEADLINE, archive_records, render_skin

# After the test modules, which are what put bin/user on the path.
from nwsskin import NWSSkin

# (label, css selector, computed property).  Two of each kind: a ground, text,
# a filled chip whose text color INVERTS between themes, and the drawn icons --
# plus the 7 Day chart's two seam chips, which are the only marks on these
# pages carrying --fc-hi and --fc-muted as FILLS, where a theme that did not
# reach them would leave a forecast-red box on a dark card.
PROBES: List[Tuple[str, str, str]] = [
    ('page background',      'body',                 'backgroundColor'),
    ('card background',      'section.now',          'backgroundColor'),
    ('body text',            '.fc .prose',           'color'),
    ('page title',           'h1.ctitle',            'color'),
    ('current tab fill',     '.nav a.current',       'backgroundColor'),
    ('current tab text',     '.nav a.current',       'color'),
    ('chart chip: recorded', '.seamchip.obs',        'backgroundColor'),
    ('chart chip: forecast', '.seamchip.fcast',      'backgroundColor'),
    ('icon: sun disc',       '#wx-skc-day circle',   'fill'),
    ('icon: overcast back',  '#wx-ovc-day g rect',   'fill'),
]

# Probes that live on a page other than index.html.  The severity chip is on
# an alert card, and it is exactly what this file exists for: a NEW colored
# mark, whose color is the only thing distinguishing one severity from
# another now that the word is beside it.
PAGE_PROBES: Dict[str, List[Tuple[str, str, str]]] = {
    'index.html': PROBES,
    'alerts.html': [('alert severity chip', '.alert .sevchip', 'color'),
                    ('alert severity rail', '.alert',          'borderLeftColor')],
}

# The driver runs inside the Playwright venv, which does not have WeeWX; the
# rendering happens out here, which does.  Hence two pythons and a subprocess.
DRIVER = r'''
import json, sys
from playwright.sync_api import sync_playwright
base, page_probes = sys.argv[1], json.loads(sys.argv[2])
out = {}
with sync_playwright() as pw:
    for engine in ('chromium', 'firefox'):
        browser = getattr(pw, engine).launch()
        out[engine] = {}
        for scheme in ('light', 'dark'):
            ctx = browser.new_context(color_scheme=scheme)
            readings = {}
            for name, probes in page_probes.items():
                page = ctx.new_page()
                page.goto(base + name, wait_until='load')
                for label, sel, prop in probes:
                    readings[label] = page.eval_on_selector(
                        sel, '(el, p) => getComputedStyle(el)[p]', prop)
                page.close()
            out[engine][scheme] = readings
            ctx.close()
        browser.close()
print(json.dumps(out))
'''

# ---- the chips, measured where they are actually drawn --------------------
#
# WHY THIS IS A MEASUREMENT.  The chips name the halves of the 7 Day chart and
# they are markup rather than SVG <text> precisely so that nothing has to
# compute how wide a filled box around those words comes out: the browser
# sizes them.  What NWSSkin DOES decide is whether there is room for the pair
# at all (CHIP_ROOM), and that is arithmetic against a width no python can
# see.  So this asks the browser where the ink went.
#
# FOUR WIDTHS, because the stylesheet gives the chips three sizes as the page
# narrows -- 13 viewBox units, 18 below 880px and 21 below 620px -- and the
# narrowest page is always the binding case: css scales this type in the same
# units the geometry is written in.  621 is here as well as 390 and 880 to
# catch each switch on the wide side of itself.  Both engines, because they do
# not agree about text metrics, and whatever face this machine substitutes for
# Open Sans, which the skin names and does not load.
#
# It fails if a pair that was SHOWN does not fit between the plot's edge and
# the seam rule -- the one thing CHIP_ROOM exists to prevent -- and if any
# chip came out wider than CHIP_WIDTH, which is how that constant is stopped
# from going stale.
CHIP_VIEWPORTS = [1280, 880, 621, 390]

# Room to spare, in viewBox units, before a chip is called clipped.  Not zero:
# a chip whose edge lands exactly on the plot edge is one rounding away from
# crossing it.
MIN_CLEARANCE = 1.0

CHIP_DRIVER = r'''
import json, sys
from playwright.sync_api import sync_playwright

PROBE = """() => {
  const out = [];
  document.querySelectorAll('.seamlegend').forEach(leg => {
    const wrap = leg.parentNode;
    const svg = wrap.querySelector('svg.chart');
    if (!svg) return;
    const box = svg.getBoundingClientRect();
    if (!box.width) return;
    /* viewBox units per css pixel, so everything below is in the units the
       python geometry is written in. */
    const k = svg.viewBox.baseVal.width / box.width;
    const seam = svg.querySelector('.seam');
    if (!seam) return;
    let spec;
    try { spec = JSON.parse(svg.getAttribute('data-chart')); } catch (e) { return; }
    leg.querySelectorAll('.seamchip').forEach(chip => {
      const r = chip.getBoundingClientRect();
      out.push({
        text: chip.textContent,
        obs: chip.classList.contains('obs'),
        left: +((r.left - box.left) * k).toFixed(2),
        right: +((r.right - box.left) * k).toFixed(2),
        width: +(r.width * k).toFixed(2),
        top: +((r.top - box.top) * k).toFixed(2),
        bottom: +((r.bottom - box.top) * k).toFixed(2),
        seam: +(seam.x1.baseVal.value).toFixed(2),
        x0: spec.x0, x1: spec.x1, y0: spec.y0,
        fontpx: +getComputedStyle(chip).fontSize.replace('px', ''),
        unit: +(1 / k).toFixed(4)
      });
    });
  });
  return out;
}"""

base, widths = sys.argv[1], json.loads(sys.argv[2])
out = {}
with sync_playwright() as pw:
    for engine in ('chromium', 'firefox'):
        browser = getattr(pw, engine).launch()
        out[engine] = {}
        for w in widths:
            ctx = browser.new_context(viewport={'width': w, 'height': 900})
            page = ctx.new_page()
            page.goto(base + 'index.html', wait_until='load')
            out[engine][str(w)] = page.evaluate(PROBE)
            ctx.close()
        browser.close()
print(json.dumps(out))
'''


def measure_chips(python: str, html_root: str, driver_dir: str) -> int:
    """Run CHIP_DRIVER and report.  Returns the number of failures."""
    driver = os.path.join(driver_dir, 'chip_driver.py')
    with open(driver, 'w') as f:
        f.write(CHIP_DRIVER)
    proc = subprocess.run(
        [python, driver, 'file://' + html_root + '/', json.dumps(CHIP_VIEWPORTS)],
        capture_output=True, text=True)
    print('\nthe 7 Day chart\'s seam chips, measured in viewBox units')
    if proc.returncode != 0:
        print('  FAIL: the browser driver exited %d:' % proc.returncode)
        print((proc.stderr or proc.stdout).strip()[-2000:])
        return 1
    readings = json.loads(proc.stdout)

    fails, widest = 0, 0.0
    for engine in sorted(readings):
        for width in CHIP_VIEWPORTS:
            # A chip the stylesheet has hidden still MATCHES the selector;
            # what it has is a zero box.  Reading that as a 0-wide chip would
            # report it as clipped and outside the band, which is the opposite
            # of what it is.
            chips = [c for c in readings[engine][str(width)] if c['width']]
            if not chips:
                # Never the right answer at any of these widths: the pair is
                # shown at every page width, and only a short ARCHIVE takes it
                # away.  Nothing measured means a selector stopped matching.
                print('  %-9s %4dpx  no chips drawn  <-- expected a pair'
                      % (engine, width))
                fails += 1
                continue
            for c in chips:
                widest = max(widest, c['width'])
                # The gap between the chip and the edge of the plot on its own
                # side.  That is what CHIP_ROOM was asked to guarantee.
                room = (c['left'] - c['x0']) if c['obs'] else (c['x1'] - c['right'])
                bad = []
                if room < MIN_CLEARANCE:
                    bad.append('clipped: %.1f from the plot edge' % room)
                if c['width'] > NWSSkin.CHIP_WIDTH:
                    bad.append('wider than CHIP_WIDTH (%d)' % NWSSkin.CHIP_WIDTH)
                # The band was cut to hold it; the stylesheet centers it there.
                if c['top'] < 0 or c['bottom'] > c['y0']:
                    bad.append('outside the band (0..%d)' % c['y0'])
                print('  %-9s %4dpx  %-24s %6.1f wide at %4.1f units,'
                      ' %5.1f clear of the plot edge  %s'
                      % (engine, width, c['text'], c['width'], c['unit'],
                         room, '  '.join(bad) or 'ok'))
                fails += bool(bad)
    print('  widest chip seen: %.1f units.  CHIP_WIDTH is %d.'
          % (widest, NWSSkin.CHIP_WIDTH))
    return fails

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
                    parameters={'NWSheadline': [LONG_NWS_HEADLINE]})),
                # FOUR hours, and the number is load-bearing.  The chart
                # needs an archive at all for its observed half to exist --
                # no probe can reach a mark the page never emits -- but the
                # two chips are shown only when BOTH halves are at least
                # NWSSkin.CHIP_ROOM wide, and the one_hour fixture is trimmed
                # to four periods.  More archive than forecast pushes the
                # seam right until the forecast side has nowhere to put a
                # chip, and the pair goes.  Four each side puts the seam in
                # the middle, which is also the widest the chips ever have to
                # be measured at.
                archive=archive_records(4))
    html_root = os.path.join(base, 'public_html', 'nws')
    for name in PAGE_PROBES:
        assert os.path.isfile(os.path.join(html_root, name)), name

    driver = os.path.join(base, 'driver.py')
    with open(driver, 'w') as f:
        f.write(DRIVER)
    proc = subprocess.run(
        [options.python, driver, 'file://' + html_root + '/',
         json.dumps(PAGE_PROBES)],
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
        for label, _sel, _prop in [pr for prs in PAGE_PROBES.values() for pr in prs]:
            same = light[label] == dark[label]
            # Every probe is a color the two palettes define differently.  If
            # one comes back identical the theme did not reach it -- which is
            # precisely the failure static checks cannot see.
            print('  %-20s %-22s %-22s %s'
                  % (label, light[label], dark[label],
                     'IDENTICAL <-- theme did not apply' if same else 'ok'))
            fails += same
    print('\n%d probe(s) unchanged across the two settings' % fails)
    fails += measure_chips(options.python, html_root, base)
    return 1 if fails else 0

if __name__ == '__main__':
    sys.exit(main())
