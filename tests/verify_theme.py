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

In the same browsers it measures what a python render cannot see: that each
divider and control outline scores in dark what it scores in light
(LINE_PROBES), that the 7 Day chart's two chips fit where they are shown,
and that no chart's axis labels run into the rule above them or into the
readout on a phone.

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
import datetime
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile

from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_nws import iso, load_fixture, make_alert, make_alerts_json
from test_nws_css import MATCH_TOLERANCE, apca, parse
from test_nws_service import freshen
from test_nws_skin import LONG_NWS_HEADLINE, archive_records, long_one_hour, render_skin

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

# ---- the dividers and control outlines ------------------------------------
#
# In dark, each scores what it scores in light: the same APCA Lc against the
# ground it actually sits on.  tests/test_nws_css.py checks that of the
# TOKENS; this checks it of the PAGE -- the border color the browser computed
# for each element, against the background the browser computed under it --
# which is what catches a rule left pointing at the old token, or a line
# whose ground is not the one the token table assumed.
#
# (label, page, selector, border color property, ground is OUTSIDE the
# element, class to strip first, measure a TWIN).  A divider sits on its own
# element's background (a border paints over it); a control's outline is
# read against what lies outside it, not its own fill.  The strip and the
# twin make each probe land on the same state on every run: the first day
# tab is the current one, the first hour is a night row or not by the
# clock, and the 7 Day rows come from a four-period fixture, so there may be
# only one, a :first-child, which has no divider -- so it is cloned, and the
# clone, placed after it, is what a second row would be.
LINE_PROBES: List[Tuple[str, str, str, str, bool, str, bool]] = [
    ('7 Day row divider',     'index.html',  '.fc .day',         'borderTopColor',    False, '', True),
    ('7 Day column head',     'index.html',  '.fc .colhead',     'borderBottomColor', False, '', False),
    ('Right now stats rule',  'index.html',  '.fc .nowstats',    'borderLeftColor',   False, '', False),
    ('page footer rule',      'index.html',  '.fc .cfoot',       'borderTopColor',    False, '', False),
    ('page title rule',       'index.html',  '.fc .chead',       'borderBottomColor', False, '', False),
    ('nav tab outline',       'index.html',  '.nav a:not(.current)', 'borderTopColor', True, '', False),
    ('Hourly column head',    'hours.html',  '.fc .hhead',       'borderBottomColor', False, '', False),
    ('Hourly row divider',    'hours.html',  '.fc .hrow',        'borderBottomColor', False, 'nightrow', False),
    ('day tab outline',       'hours.html',  '.fc .daytab',      'borderTopColor',    True,  'on', False),
    ('alert sections rule',   'alerts.html', '.fc .asecs',       'borderTopColor',    False, '', False),
    ('alert footer rule',     'alerts.html', '.fc .ameta',       'borderTopColor',    False, '', False),
    ('response chip outline', 'alerts.html', '.fc .respchip',    'borderTopColor',    True,  '', False),
    ('begins-later badge',    'alerts.html', '.fc .badge.soon',  'borderTopColor',    True,  '', False),
]

# The driver runs inside the Playwright venv, which does not have WeeWX; the
# rendering happens out here, which does.  Hence two pythons and a subprocess.
DRIVER = r'''
import json, sys
from playwright.sync_api import sync_playwright
LINE = """(el, [p, outside, strip, twin]) => {
  if (twin) el = el.parentNode.insertBefore(el.cloneNode(true), el.nextSibling);
  if (strip) el.classList.remove(strip);
  const cs = getComputedStyle(el);
  let ground = null;
  for (let g = outside ? el.parentElement : el; g; g = g.parentElement) {
    const c = getComputedStyle(g).backgroundColor;
    if (c !== 'transparent' && !/^rgba\\(.*,\\s*0\\)$/.test(c)) { ground = c; break; }
  }
  return {line: cs[p], width: cs[p.replace('Color', 'Width')], ground: ground};
}"""
base, page_probes, line_probes = sys.argv[1], json.loads(sys.argv[2]), json.loads(sys.argv[3])
pages = sorted(set(page_probes) | {pr[1] for pr in line_probes})
out = {}
with sync_playwright() as pw:
    for engine in ('chromium', 'firefox'):
        browser = getattr(pw, engine).launch()
        out[engine] = {}
        for scheme in ('light', 'dark'):
            ctx = browser.new_context(color_scheme=scheme)
            readings, lines = {}, {}
            for name in pages:
                page = ctx.new_page()
                page.goto(base + name, wait_until='load')
                for label, sel, prop in page_probes.get(name, []):
                    readings[label] = page.eval_on_selector(
                        sel, '(el, p) => getComputedStyle(el)[p]', prop)
                for label, pg, sel, prop, outside, strip, twin in line_probes:
                    if pg == name:
                        lines[label] = page.eval_on_selector(
                            sel, LINE, [prop, outside, strip, twin])
                page.close()
            out[engine][scheme] = {'probes': readings, 'lines': lines}
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

# Hours of forecast rendered.  26 always reaches a local noon, where the day
# labels go, whatever hour this runs: the fixture's four periods alone drew
# one only between about 7 and 11 AM.
FORECAST_HOURS = 26

# ---- the axis labels, and the readout over them ---------------------------
#
# The day and hour labels under each chart grow with the stylesheet's type
# while the geometry above them stays put, so at a phone's size they can reach
# up into what they label.  On the Hourly page they did: at 390px the day
# labels' capitals stood a fifth of a pixel under the rain strip.  And the
# readout is sized in page pixels over a chart sized in its own units, so on
# a phone it covers most of the 7 Day plot: at 390px its bottom edge met the
# tops of the day labels under it.
#
# The top of each label's INK -- not its box, which is the font's whole em
# box and stands well above the capitals -- must sit MIN_LABEL_ROOM below the
# lowest horizontal rule of its chart (the rain strip's axis on the Hourly
# charts, the plot's floor on the 7 Day one), and a readout, with the chart
# hovered on both halves, must end that far above it.  360 and 320 as well as
# the chip widths: a narrower page shrinks the charts and not the readout, so
# the smallest phone is the binding case.
LABEL_VIEWPORTS = [1280, 880, 621, 390, 360, 320]
# Clean ground between a label's ink and what is above it, in page pixels.
# At a fifth of a pixel the Hourly labels read as touching the rain strip;
# a whole pixel is the least that reads as a gap.
MIN_LABEL_ROOM = 1.0
LABEL_PAGES = ['index.html', 'hours.html']
# The charts whose labels are the noon day names, which the render's
# forecast always reaches.  The Hourly page's day chart labels every third
# hour, and today's pane can hold fewer than three.
LABELED = ['sparkcurve', 'weekcurve']

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

LABELS = """() => {
  /* Where the INK of a label starts, in viewBox units: its baseline less the
     height its own glyphs rise, in the face the browser actually chose.  Not
     getBBox(): that is the font's whole em box, taller than the capitals,
     and the engines do not even agree on it. */
  const ctx = document.createElement('canvas').getContext('2d');
  const inkTop = t => {
    const cs = getComputedStyle(t);
    ctx.font = cs.fontStyle + ' ' + cs.fontWeight + ' ' + cs.fontSize + ' ' + cs.fontFamily;
    return t.y.baseVal[0].value - ctx.measureText(t.textContent).actualBoundingBoxAscent;
  };
  const out = [];
  document.querySelectorAll('svg.chart').forEach((svg, n) => {
    const sb = svg.getBoundingClientRect();
    if (!sb.width) return;
    let rule = null;
    svg.querySelectorAll('line.hgrid, line.axis').forEach(l => {
      if (l.y1.baseVal.value !== l.y2.baseVal.value) return;
      const y = l.y1.baseVal.value + parseFloat(getComputedStyle(l).strokeWidth) / 2;
      rule = rule === null ? y : Math.max(rule, y);
    });
    out.push({chart: n, cls: svg.getAttribute('class').split(' ')[0], rule: rule,
              k: sb.width / svg.viewBox.baseVal.width,
              labels: [...svg.querySelectorAll('text.xlab')].map(t => ({
                text: t.textContent, top: +inkTop(t).toFixed(2)}))});
  });
  return out;
}"""

READOUT = """([n, top]) => {
  const svg = document.querySelectorAll('svg.chart')[n];
  const r = svg.parentNode.querySelector('.readout');
  if (!r || r.hidden) return null;
  const b = r.getBoundingClientRect(), sb = svg.getBoundingClientRect();
  return {bottom: +b.bottom.toFixed(2), height: +b.height.toFixed(2),
          labeltop: +(sb.top + top * sb.width / svg.viewBox.baseVal.width).toFixed(2)};
}"""

base, chip_widths, label_widths = (sys.argv[1], json.loads(sys.argv[2]),
                                   json.loads(sys.argv[3]))
pages = json.loads(sys.argv[4])
out = {}
with sync_playwright() as pw:
    for engine in ('chromium', 'firefox'):
        browser = getattr(pw, engine).launch()
        out[engine] = {}
        for w in sorted(set(chip_widths) | set(label_widths), reverse=True):
            ctx = browser.new_context(viewport={'width': w, 'height': 900})
            page = ctx.new_page()
            got = {'chips': None, 'labels': {}}
            for name in pages:
                page.goto(base + name, wait_until='load')
                if name == 'index.html' and w in chip_widths:
                    got['chips'] = page.evaluate(PROBE)
                if w not in label_widths:
                    continue
                charts = page.evaluate(LABELS)
                for c in charts:
                    c['readouts'] = []
                    if not c['labels']:
                        continue
                    el = page.query_selector_all('svg.chart')[c['chart']]
                    el.scroll_into_view_if_needed()
                    box = el.bounding_box()
                    for frac in (.25, .75):
                        page.mouse.move(box['x'] + box['width'] * frac,
                                        box['y'] + box['height'] / 2)
                        c['readouts'].append(page.evaluate(
                            READOUT, [c['chart'], min(lab['top'] for lab in c['labels'])]))
                    page.mouse.move(0, 0)
                got['labels'][name] = charts
            out[engine][str(w)] = got
            ctx.close()
        browser.close()
print(json.dumps(out))
'''


def run_geometry(python: str, html_root: str, driver_dir: str) -> Optional[Dict[str, Any]]:
    """Run CHIP_DRIVER; its readings, or None if the driver failed."""
    driver = os.path.join(driver_dir, 'chip_driver.py')
    with open(driver, 'w') as f:
        f.write(CHIP_DRIVER)
    proc = subprocess.run(
        [python, driver, 'file://' + html_root + '/', json.dumps(CHIP_VIEWPORTS),
         json.dumps(LABEL_VIEWPORTS), json.dumps(LABEL_PAGES)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        print('\nFAIL: the geometry driver exited %d:' % proc.returncode)
        print((proc.stderr or proc.stdout).strip()[-2000:])
        return None
    readings: Dict[str, Any] = json.loads(proc.stdout)
    return readings


def measure_labels(readings: Dict[str, Any]) -> int:
    """Report the axis labels and the readout.  Returns the number of
    failures."""
    print('\nthe axis labels\' ink, in px clear of the rule above it and of a'
          ' hovered readout (at least %.1f)' % MIN_LABEL_ROOM)
    fails = 0
    for engine in sorted(readings):
        for width in LABEL_VIEWPORTS:
            for page in LABEL_PAGES:
                for c in readings[engine][str(width)]['labels'][page]:
                    bad = []
                    if not c['labels']:
                        if c['cls'] in LABELED:
                            bad.append('no labels drawn')
                        else:
                            continue
                    if c['labels'] and c['rule'] is None:
                        bad.append('no horizontal rule to measure from')
                        c['labels'] = []
                    # Page pixels for both, which is what a reader sees.
                    clear = ((min(lab['top'] for lab in c['labels']) - c['rule']) * c['k']
                             if c['labels'] else 0.0)
                    if c['labels'] and clear < MIN_LABEL_ROOM:
                        bad.append('a label\'s ink is %.1fpx under the rule' % clear)
                    shown = [r for r in c['readouts'] if r]
                    if c['labels'] and not shown:
                        bad.append('no readout appeared on hover')
                    room = min((r['labeltop'] - r['bottom'] for r in shown), default=0.0)
                    if shown and room < MIN_LABEL_ROOM:
                        bad.append('the readout overlaps a label\'s ink by %.1fpx' % -room
                                   if room < 0 else
                                   'the readout stops %.1fpx above a label\'s ink' % room)
                    print('  %-9s %4dpx  %-11s %-10s labels %5.1fpx clear, readout %5.1fpx clear  %s'
                          % (engine, width, page, c['cls'], clear, room,
                             '  '.join(bad) or 'ok'))
                    fails += bool(bad)
    return fails


def measure_chips(readings: Dict[str, Any]) -> int:
    """Report the chips.  Returns the number of failures."""
    print('\nthe 7 Day chart\'s seam chips, measured in viewBox units')

    fails, widest = 0, 0.0
    for engine in sorted(readings):
        for width in CHIP_VIEWPORTS:
            # A chip the stylesheet has hidden still MATCHES the selector;
            # what it has is a zero box.  Reading that as a 0-wide chip would
            # report it as clipped and outside the band, which is the opposite
            # of what it is.
            chips = [c for c in readings[engine][str(width)]['chips'] if c['width']]
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

def check_lines(results: Dict[str, Any]) -> int:
    """Score LINE_PROBES from the driver's readings.  Returns the number of
    failures."""
    def lc(reading: Dict[str, str]) -> float:
        return abs(apca(parse(reading['line'])[:3], parse(reading['ground'])[:3]))
    print('\nthe dividers and control outlines, APCA Lc on their own ground'
          ' (dark must be within %.1f of light)' % MATCH_TOLERANCE)
    fails = 0
    for engine in sorted(results):
        light, dark = results[engine]['light']['lines'], results[engine]['dark']['lines']
        for label, *_ in LINE_PROBES:
            bad = [r for r in (light[label], dark[label])
                   if r['width'] in ('0px', '') or not r['ground']]
            if bad:
                print('  %-9s %-22s no line drawn, or no ground under it: %r'
                      % (engine, label, bad))
                fails += 1
                continue
            want, got = lc(light[label]), lc(dark[label])
            ok = abs(got - want) <= MATCH_TOLERANCE
            print('  %-9s %-22s light %5.1f  dark %5.1f  %s'
                  % (engine, label, want, got, 'ok' if ok else '<-- does not match light'))
            fails += not ok
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

    now = datetime.datetime.now(datetime.timezone.utc)
    later = lambda h: now + datetime.timedelta(hours=h)  # noqa: E731
    base = tempfile.mkdtemp(prefix='nws-theme-')
    print('Rendering the sample skin to %s (kept for inspection).' % base)
    render_skin(pathlib.Path(base),
                freshen(long_one_hour(FORECAST_HOURS)),
                freshen(load_fixture('twelve_hour.json')),
                make_alerts_json(
                    make_alert(parameters={'NWSheadline': [LONG_NWS_HEADLINE]}),
                    # Begins later: the one badge with an outline.
                    make_alert(id='urn:theme.later', severity='Minor', event='Wind Advisory',
                               onset=iso(later(5)), ends=iso(later(9)),
                               expires=iso(later(9)))),
                # AS MANY HOURS AS THE FORECAST, and the match is
                # load-bearing.  The chart needs an archive at all for its
                # observed half to exist -- no probe can reach a mark the
                # page never emits -- but the two chips are shown only when
                # BOTH halves are at least NWSSkin.CHIP_ROOM wide.  More
                # archive than forecast pushes the seam right until the
                # forecast side has nowhere to put a chip, and the pair goes;
                # less pushes it left.  Equal halves put the seam in the
                # middle, which is also the widest the chips ever have to be
                # measured at.
                archive=archive_records(FORECAST_HOURS))
    html_root = os.path.join(base, 'public_html', 'nws')
    for name in set(PAGE_PROBES) | {pr[1] for pr in LINE_PROBES}:
        assert os.path.isfile(os.path.join(html_root, name)), name

    driver = os.path.join(base, 'driver.py')
    with open(driver, 'w') as f:
        f.write(DRIVER)
    proc = subprocess.run(
        [options.python, driver, 'file://' + html_root + '/',
         json.dumps(PAGE_PROBES), json.dumps(LINE_PROBES)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        print('FAIL: the browser driver exited %d:' % proc.returncode)
        print((proc.stderr or proc.stdout).strip()[-2000:])
        return 1
    results: Dict[str, Any] = json.loads(proc.stdout)

    fails = 0
    for engine in sorted(results):
        print('\n%s' % engine)
        light, dark = results[engine]['light']['probes'], results[engine]['dark']['probes']
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
    fails += check_lines(results)
    geometry = run_geometry(options.python, html_root, base)
    if geometry is None:
        return 1
    fails += measure_chips(geometry)
    fails += measure_labels(geometry)
    return 1 if fails else 0

if __name__ == '__main__':
    sys.exit(main())
