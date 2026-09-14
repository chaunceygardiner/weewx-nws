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

"""Every piece of text on the rendered sample skin, measured against the
pixels actually painted under it.

WHY PIXELS.  tests/test_nws_css.py pairs each token with the grounds somebody
wrote down, and that table can only know what it was told.  A label drawn
over an SVG band painted earlier as a SIBLING, a chip laid over a chart, a
tab whose fill changes when it is clicked -- none of those is an ancestor's
background, so no table entry or DOM walk is guaranteed to find them.  The
ground a reader sees is whatever is under the glyphs, so that is what this
measures: each page is screenshotted with every glyph made transparent, and
the pixels inside each text box ARE the ground.

HOW.  For each scenario, page, theme, width and STATE:
  1. collect every visible text node -- its box, its ink (color, or fill for
     SVG text) and the product of every ancestor's opacity;
  2. make all text transparent and take a screenshot -- of the full page, or
     of the viewport for a state the pointer holds (see measure() in DRIVER);
  3. collect again, and keep only boxes that did not move between the two
     (the alert badges are rewritten every minute by the page script);
  4. out here, group the pixels in each box (channels to the nearest 4) and
     score the ink, flattened over every ground covering at least MIN_SHARE
     of the box, against the text bar in tests/test_nws_css.py -- WCAG 4.5
     AND APCA Lc 60, with that file's arithmetic, so the two cannot disagree.
     The WORST ground is the one reported.

STATES.  A page at load is not the whole page.  Every visible <button> is
clicked in turn (the Hourly page's day tabs), each chart is hovered on both
halves (the readout, and the crosshair's past state), and a nav tab that is
not current is hovered.  The alerts page is also loaded with the browser's
clock three and a half hours ahead: alerts() never returns an ended alert,
so the Expired badge exists only in a page left open, when the page script
rewrites the badges.  Each state starts from a freshly loaded page.

TWO SCENARIOS, because the alerts page turns over entirely on the day.  One
has an alert in every state the card can draw -- in effect, open-ended,
begins later, expired, and all five severities -- plus a short station
archive so the 7 Day chart's chips appear; the other has no alerts, so the
all-clear card is measured, and a longer archive.

NOTHING IS SKIPPED QUIETLY.  A state that cannot be driven, and a box whose
largest ground covers under BUSY_SHARE of it (text on imagery, which a single
score would misdescribe), both fail the run.  A pair allowed to miss is a
named entry in EXCEPTIONS, with its reason, and an exception nothing matches
any more fails too.

WHAT IT CANNOT SEE: ::before/::after generated content, and non-text marks
(chart lines, rails), which tests/test_nws_css.py holds to the mark bar.
Chromium only: this measures the stylesheet's colors, which do not differ by
engine, and tests/verify_theme.py already drives Firefox.

Not collected by pytest -- Playwright is not a test-suite requirement.  Part
of the pre-release checklist.  Run from the repository root:

    /home/weewx/weewx-venv/bin/python tests/verify_ink.py --python ~/pwenv/bin/python

See tests/verify_theme.py's docstring for the two-interpreter setup.
"""

import argparse
import collections
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

from PIL import Image

from test_nws import iso, load_fixture, make_alert, make_alerts_json
from test_nws_service import freshen
from test_nws_skin import LONG_NWS_HEADLINE, archive_records, render_skin
from test_nws_css import BARS, wcag, apca

PAGES = ['index.html', 'hours.html', 'alerts.html']
THEMES = ['light', 'dark']
WIDTHS = [1280, 390]

MIN_SHARE = 0.08
BUSY_SHARE = 0.35

# (scenario, where, text) -> reason.  Matched on the element path and the
# start of the text, in every theme, width and state.  Empty: every piece of
# text clears the bar, and a color that passes is preferred to an entry here.
EXCEPTIONS: Dict[Tuple[str, str, str], str] = {}

DRIVER = r'''
import datetime, json, os, sys
from playwright.sync_api import sync_playwright

COLLECT = """() => {
  const out = [];
  const sx = window.scrollX, sy = window.scrollY;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const name = (e) => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') +
      [...e.classList].map(c => '.' + c).join('');
  let n;
  while ((n = walker.nextNode())) {
    if (!n.nodeValue.trim()) { continue; }
    const el = n.parentElement;
    if (!el || el.closest('script,style,noscript,template,title')) { continue; }
    if (!el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) { continue; }
    const cs = getComputedStyle(el);
    const svg = el instanceof SVGElement;
    const ink = svg ? cs.fill : cs.webkitTextFillColor;
    if (!ink || !/^rgb/.test(ink)) { continue; }
    let op = svg ? parseFloat(cs.fillOpacity) : 1;
    for (let e = el; e; e = e.parentElement) {
      op *= parseFloat(getComputedStyle(e).opacity);
    }
    if (op < 0.05) { continue; }
    let clip = [-1e9, -1e9, 1e9, 1e9];
    for (let e = el.parentElement; e && e !== document.documentElement; e = e.parentElement) {
      const c = getComputedStyle(e);
      if (c.overflowX !== 'visible' || c.overflowY !== 'visible') {
        const b = e.getBoundingClientRect();
        clip = [Math.max(clip[0], b.left), Math.max(clip[1], b.top),
                Math.min(clip[2], b.right), Math.min(clip[3], b.bottom)];
      }
    }
    const range = document.createRange();
    range.selectNodeContents(n);
    const rects = [];
    for (const q of range.getClientRects()) {
      const l = Math.max(q.left, clip[0]), t = Math.max(q.top, clip[1]);
      const r = Math.min(q.right, clip[2]), b = Math.min(q.bottom, clip[3]);
      if (r - l >= 2 && b - t >= 2) {
        rects.push([Math.round(l + sx), Math.round(t + sy),
                    Math.round(r + sx), Math.round(b + sy)]);
      }
    }
    if (!rects.length) { continue; }
    const path = [];
    for (let e = el; e && e !== document.body && path.length < 3; e = e.parentElement) {
      path.unshift(name(e));
    }
    out.push({where: path.join(' > '), text: n.nodeValue.trim().slice(0, 40),
              ink: ink, opacity: Math.round(op * 1000) / 1000, rects: rects});
  }
  return out;
}"""

HIDE = """
*, *::before, *::after {
  color: transparent !important;
  -webkit-text-fill-color: transparent !important;
  text-shadow: none !important;
  text-decoration-color: transparent !important;
  transition: none !important;
}
svg text, svg tspan, svg textPath {
  fill: transparent !important;
  stroke: transparent !important;
}
"""

BUTTONS = """() => [...document.querySelectorAll('button')]
  .map((b, i) => [i, b.checkVisibility(), (b.textContent || '').trim().slice(0, 30)])
  .filter(b => b[1]).map(b => [b[0], b[2]])"""

CLICK = """(i) => { const b = document.querySelectorAll('button')[i];
  if (!b || !b.checkVisibility()) { return false; } b.click(); return true; }"""

roots, out_dir = json.loads(sys.argv[1]), sys.argv[2]
pages, themes, widths = json.loads(sys.argv[3]), json.loads(sys.argv[4]), json.loads(sys.argv[5])
shots, log, problems = [], [], []

def in_view(records, dx, dy):
    """Page-coordinate boxes shifted into a viewport screenshot's pixels."""
    for r in records:
        r['rects'] = [[l - dx, t - dy, rr - dx, b - dy] for l, t, rr, b in r['rects']]
    return records

def measure(page, label, pointer=False):
    """A state held by the POINTER is shot at the viewport, never full page:
    a full-page capture resizes the viewport, the pointer leaves the chart,
    and the readout the state exists to measure is gone from the shot.  Text
    outside that viewport is the same text the load state measures whole."""
    first = page.evaluate(COLLECT)
    handle = page.add_style_tag(content=HIDE)
    page.wait_for_timeout(150)
    stem = '-'.join(str(label[k]) for k in ('scenario', 'page', 'theme', 'width', 'state'))
    stem = ''.join(c if c.isalnum() or c in '-.' else '_' for c in stem)
    path = os.path.join(out_dir, stem + '.png')
    page.screenshot(path=path, full_page=not pointer, animations='disabled')
    handle.evaluate('e => e.remove()')
    second = page.evaluate(COLLECT)
    if pointer:
        dx, dy = page.evaluate('() => [window.scrollX, window.scrollY]')
        first, second = in_view(first, dx, dy), in_view(second, dx, dy)
    shots.append({'label': label, 'png': path, 'first': first, 'second': second})
    log.append('%s %s %s %d %s: %d text' % (label['scenario'], label['page'], label['theme'],
                                           label['width'], label['state'], len(first)))

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for scenario, root in roots.items():
        for theme in themes:
            for width in widths:
                ctx = browser.new_context(viewport={'width': width, 'height': 900},
                                          color_scheme=theme)
                for name in pages:
                    url = 'file://' + root + '/' + name
                    base = {'scenario': scenario, 'page': name, 'theme': theme, 'width': width}

                    def fresh(hours_ahead=0):
                        p = ctx.new_page()
                        if hours_ahead:
                            p.clock.install(time=datetime.datetime.now()
                                            + datetime.timedelta(hours=hours_ahead))
                        p.goto(url, wait_until='load')
                        p.wait_for_timeout(300)
                        return p

                    page = fresh()
                    measure(page, dict(base, state='load'))
                    buttons = page.evaluate(BUTTONS)
                    charts = page.locator('svg.chart').count()
                    nav = page.locator('.nav a:not(.current)').count()
                    page.close()

                    drives = [('button %d: %s' % (i, t), 'click', i) for i, t in buttons]
                    for c in range(charts):
                        for frac in (0.25, 0.75):
                            drives.append(('chart %d hover at %d%%' % (c, frac * 100), 'chart', (c, frac)))
                    if nav:
                        drives.append(('nav hover', 'nav', None))
                    # The Expired badge exists only in a page left open past an
                    # alert's end: the script rewrites the badges every minute,
                    # and alerts() never returns an ended alert to render.  The
                    # Severe warning ends three hours from now.
                    if name == 'alerts.html' and scenario == 'alerts':
                        drives.append(('3.5 hours later', 'clock', 3.5))
                    if name == 'hours.html' and not buttons:
                        problems.append('%s: no day tabs to click' % base)
                    if not charts and name != 'alerts.html':
                        problems.append('%s: no chart to hover' % base)

                    for state, kind, arg in drives:
                        page = fresh(arg if kind == 'clock' else 0)
                        if kind == 'clock':
                            if not page.locator('.badge.past').count():
                                problems.append('%s %s: NOT DRIVEN (no Expired badge)' % (base, state))
                                page.close()
                                continue
                        elif kind == 'click':
                            if not page.evaluate(CLICK, arg):
                                problems.append('%s %s: NOT DRIVEN (button gone)' % (base, state))
                                page.close()
                                continue
                        elif kind == 'chart':
                            box = page.locator('svg.chart').nth(arg[0])
                            box.scroll_into_view_if_needed()
                            bb = box.bounding_box()
                            if not bb or not bb['width']:
                                problems.append('%s %s: NOT DRIVEN (chart not visible)' % (base, state))
                                page.close()
                                continue
                            page.mouse.move(bb['x'] + bb['width'] * arg[1], bb['y'] + bb['height'] * 0.6)
                            if not page.evaluate("() => [...document.querySelectorAll('.readout')]"
                                                 ".some(r => !r.hidden)"):
                                problems.append('%s %s: NOT DRIVEN (no readout appeared)' % (base, state))
                                page.close()
                                continue
                        else:
                            page.locator('.nav a:not(.current)').first.hover()
                        page.wait_for_timeout(200)
                        measure(page, dict(base, state=state), pointer=kind in ('chart', 'nav'))
                        page.close()
                ctx.close()
    browser.close()
print(json.dumps({'shots': shots, 'log': log, 'problems': problems}))
'''


def render(base: str) -> Dict[str, str]:
    """Both scenarios under base; returns {scenario: html root}."""
    now = datetime.datetime.now(datetime.timezone.utc)
    hours = lambda h: iso(now + datetime.timedelta(hours=h))  # noqa: E731
    alerts = make_alerts_json(
        # In effect, with an end, and the long headline that wraps.
        make_alert(id='urn:ink.severe', severity='Severe', event='Excessive Heat Warning',
                   parameters={'NWSheadline': [LONG_NWS_HEADLINE]}),
        # In effect with no onset and no end, as some real alerts are: the
        # window falls back to the message's own times.
        make_alert(id='urn:ink.extreme', severity='Extreme', event='Hurricane Warning',
                   onset=None, ends=None),
        # Begins later: the warn badge.
        make_alert(id='urn:ink.moderate', severity='Moderate', event='Wind Advisory',
                   onset=hours(5), ends=hours(9), expires=hours(9)),
        # The fourth severity.  An ENDED alert cannot be rendered at all --
        # alerts() drops it -- so the Expired badge is reached in the
        # browser instead: see the 'clock' state in DRIVER.
        make_alert(id='urn:ink.minor', severity='Minor', event='Beach Hazards Statement'),
        # No severity, and no end: the unknown chip, and a bar running to the
        # message's expiry with a faint "(expires)".
        make_alert(id='urn:ink.unknown', severity='Unknown', event='Special Weather Statement',
                   ends=None),
        # An end before the start: no bar, both times.
        make_alert(id='urn:ink.backwards', severity='Minor', event='Small Craft Advisory',
                   onset=hours(5), ends=hours(4), expires=hours(6)))
    roots = {}
    for scenario, alert_json, archive in (
            ('alerts', alerts, archive_records(4)),
            ('quiet', make_alerts_json(), archive_records(18, gap=(10, 11, 12)))):
        path = pathlib.Path(base) / scenario
        path.mkdir()
        render_skin(path, freshen(load_fixture('one_hour.json')),
                    freshen(load_fixture('twelve_hour.json')), alert_json, archive=archive)
        roots[scenario] = str(path / 'public_html' / 'nws')
    return roots


def parse_css_rgb(css: str) -> Tuple[Tuple[int, int, int], float]:
    parts = css[css.index('(') + 1:css.index(')')].replace('/', ',').split(',')
    vals = [float(v) for v in parts if v.strip()]
    alpha = vals[3] if len(vals) > 3 else 1.0
    r, g, b = (int(round(v)) for v in vals[:3])
    return (r, g, b), alpha


def score(record: Dict[str, Any], img: Image.Image) -> Optional[Dict[str, Any]]:
    """The worst ground under record's boxes, or None if it covers nothing."""
    ink, alpha = parse_css_rgb(record['ink'])
    alpha *= record['opacity']
    tallies: Dict[Tuple[int, ...], List[Any]] = {}
    total = 0
    for l, t, r, b in record['rects']:
        l, t, r, b = max(l, 0), max(t, 0), min(r, img.width), min(b, img.height)
        if r - l < 1 or b - t < 1:
            continue
        box = img.crop((l, t, r, b))
        colors: List[Tuple[int, Any]] = box.getcolors(box.width * box.height) or []
        for count, color in colors:
            px = tuple(color[:3])
            slot = tallies.setdefault(tuple((c + 2) // 4 * 4 for c in px), [0, px])
            slot[0] += count
            total += count
    if not total:
        return None
    ranked = sorted(tallies.values(), key=lambda v: -v[0])
    wcag_bar, apca_bar = BARS['text']
    worst: Optional[Dict[str, Any]] = None
    for count, px in ranked:
        share = count / total
        if share < MIN_SHARE:
            break
        seen = tuple(i * alpha + g * (1 - alpha) for i, g in zip(ink, px))
        w, a = wcag(seen, px), abs(apca(seen, px))
        ok = w + 1e-9 >= wcag_bar and a >= apca_bar
        # EVERY ground is judged, and a failing one is the one reported.  The
        # two measures do not rank grounds alike, so "the ground with the
        # lowest Lc" can pass both bars while another ground under the same
        # text misses WCAG.
        if (worst is None or (worst['ok'] and not ok)
                or (worst['ok'] == ok and a < worst['apca'])):
            worst = {'ground': '#%02x%02x%02x' % px, 'share': round(share, 2),
                     'wcag': round(w, 2), 'apca': round(a, 1), 'ok': ok}
    assert worst is not None
    worst['top_share'] = round(ranked[0][0] / total, 2)
    worst['busy'] = worst['top_share'] < BUSY_SHARE
    return worst


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
              '$PLAYWRIGHT_PYTHON.  See tests/verify_theme.py\'s docstring.')
        return 1

    base = tempfile.mkdtemp(prefix='nws-ink-')
    print('Rendering the sample skin to %s (kept, with the text-hidden screenshots).' % base)
    roots = render(base)
    for root in roots.values():
        for name in PAGES:
            assert os.path.isfile(os.path.join(root, name)), (root, name)
    alerts_page = open(os.path.join(roots['alerts'], 'alerts.html')).read()
    for cls in ('badge on', 'badge soon', '<i>(expires)</i>', '<i>(effective)</i>',
                '<span class="aw-t">&ndash; ', 'sev-extreme',
                'sev-severe', 'sev-moderate', 'sev-minor'):
        # A state the render never produced is a state nothing measured.
        if cls not in alerts_page:
            print('FAIL: the alerts scenario rendered no %r' % cls)
            return 1

    shots_dir = os.path.join(base, 'shots')
    os.mkdir(shots_dir)
    driver = os.path.join(base, 'driver.py')
    with open(driver, 'w') as f:
        f.write(DRIVER)
    proc = subprocess.run(
        [options.python, driver, json.dumps(roots), shots_dir,
         json.dumps(PAGES), json.dumps(THEMES), json.dumps(WIDTHS)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        print('FAIL: the browser driver exited %d:' % proc.returncode)
        print((proc.stderr or proc.stdout).strip()[-2000:])
        return 1
    run = json.loads(proc.stdout)

    measured = 0
    moved: collections.Counter = collections.Counter()
    fails: List[str] = []
    busy: List[str] = []
    used = set()
    for shot in run['shots']:
        label = shot['label']
        img = Image.open(shot['png']).convert('RGB')
        still = collections.Counter((r['where'], json.dumps(r['rects'])) for r in shot['second'])
        for rec in shot['first']:
            key = (rec['where'], json.dumps(rec['rects']))
            if still[key] <= 0:
                moved[(label['page'], rec['where'])] += 1
                continue
            still[key] -= 1
            got = score(rec, img)
            if got is None:
                continue
            measured += 1
            where = '%s %s %s %dpx %s | %s "%s"' % (
                label['scenario'], label['page'], label['theme'], label['width'],
                label['state'], rec['where'], rec['text'])
            exempt = next((k for k in EXCEPTIONS
                           if k[0] == label['scenario'] and k[1] == rec['where']
                           and rec['text'].startswith(k[2])), None)
            if exempt:
                used.add(exempt)
                continue
            if got['busy']:
                busy.append('%s: largest ground covers %d%%' % (where, got['top_share'] * 100))
            elif not got['ok']:
                fails.append('%s: %s on %s, WCAG %.2f, APCA Lc %.1f'
                             % (where, rec['ink'], got['ground'], got['wcag'], got['apca']))

    for line in run['log']:
        print('  ' + line)
    print()
    # The same pair recurs in every state that shows it; say each once.
    for line in sorted(set(fails)):
        print('FAIL ' + line)
    for line in sorted(set(busy)):
        print('BUSY ' + line)
    for line in run['problems']:
        print('PROBLEM ' + line)
    stale = sorted(set(EXCEPTIONS) - used)
    for k in stale:
        print('STALE EXCEPTION %r: nothing it names was measured' % (k,))
    # Said by name, so a whole kind of text that never holds still is seen
    # sitting the run out rather than hiding in a count.
    for (page, where), n in sorted(moved.items()):
        print('MOVED, not scored, %d time(s): %s | %s' % (n, page, where))
    print('\n%d text boxes measured in %d states (%d moved between the two collections '
          'and were not scored): %d failing, %d busy, %d problem(s), %d stale exception(s)'
          % (measured, len(run['shots']), sum(moved.values()), len(set(fails)),
             len(set(busy)), len(run['problems']), len(stale)))
    return 1 if (fails or busy or run['problems'] or stale) else 0


if __name__ == '__main__':
    sys.exit(main())
