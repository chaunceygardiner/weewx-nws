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

"""Render tests for the sample nws skin (skins/nws).

A FULL Cheetah render through WeeWX's report engine, against a populated nws
database -- compiling the templates is NOT sufficient: with #errorCatcher Echo,
Cheetah re-compiles each placeholder at render time, and a broken placeholder
renders as literal template text instead of raising (that is exactly how the
missing-$ windSpeed2 bug shipped in hours.html.tmpl through 4.5.7).  A '$'
surviving into the output is the tell.

Run from the repo root with the WeeWX venv python:
    /home/weewx/weewx-venv/bin/python -m pytest tests
"""

import json
import os
import re
import sys
import time
import types

from typing import Any, Dict, List, Optional, Tuple

os.environ['TZ'] = 'America/Los_Angeles'
time.tzset()

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'bin', 'user'))

import pytest

import weewx
import weewx.manager
import weewx.reportengine
import weewx.station
from weewx.engine import StdEngine

import nws as nws_module
import nwsskin as nwsskin_module
from nws import NWS, NWSPoller, ForecastType

# skin.conf names the search lists as user.nws.NWSForecastVariables and
# user.nwsskin.NWSSkin (how they are imported in an installed WeeWX).  Alias
# the already-imported modules so the report engine resolves them without a
# second copy of either.  BOTH are needed: a missing alias does not raise
# here, it makes the report engine fail to generate every page, which
# surfaces as "index.html was not generated" rather than an import error.
if 'user' not in sys.modules:
    user_pkg = types.ModuleType('user')
    user_pkg.nws = nws_module  # type: ignore[attr-defined]
    user_pkg.nwsskin = nwsskin_module  # type: ignore[attr-defined]
    sys.modules['user'] = user_pkg
    sys.modules['user.nws'] = nws_module
    sys.modules['user.nwsskin'] = nwsskin_module

from test_nws import load_fixture, make_alert, make_alerts_json
from test_nws_service import freshen, make_config, write_forecast_files

SKINS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'skins')

LONG_NWS_HEADLINE = ('HEAT ADVISORY REMAINS IN EFFECT FROM 11 AM SATURDAY TO 8 PM PDT TUESDAY '
                     'FOR INTERIOR VALLEYS AND HIGHER TERRAIN OF THE BAY AREA')

def long_one_hour(hours: int) -> Dict[str, Any]:
    """The one-hour fixture's four periods repeated to `hours` periods,
    numbered in order; freshen() then lays them end to end from an hour from
    now.  26 always holds a local noon -- where the day labels go -- two
    calendar days, and a night, whatever hour the run starts at.  The four
    periods alone hold a noon only between about 7 and 11 AM."""
    j = load_fixture('one_hour.json')
    periods = j['properties']['periods']
    j['properties']['periods'] = [dict(periods[i % len(periods)], number=i + 1)
                                  for i in range(hours)]
    return j

def archive_records(hours: int = 72, gap: Tuple[int, ...] = ()) -> List[Dict[str, Any]]:
    """Five-minute archive records for the `hours` hours before the forecast
    begins -- a station that has actually been running.

    They have to be laid out relative to the SEAM, not to midnight: freshen()
    puts the first forecast period an hour from now and observations() takes
    the seam from that period, so records placed any other way would land in
    the wrong hourly slots.  Each hour is filled from +5 to +60 minutes,
    because weewx's aggregation window is (start, stop].

    `gap` names hours, counting back from the seam, that the station recorded
    nothing in.
    """
    seam = int(time.time()) + 3600
    out = []
    for h in range(hours, 0, -1):
        if h in gap:
            continue
        slot = seam - h * 3600
        for minute in range(5, 61, 5):
            out.append({'dateTime': slot + minute * 60, 'usUnits': weewx.US,
                        'interval': 5, 'outTemp': 48.0 + (h % 12)})
    return out

def render_skin(tmp_path,
                one_hour: Dict[str, Any],
                twelve_hour: Dict[str, Any],
                alerts: Dict[str, Any],
                archive: Optional[List[Dict[str, Any]]] = None,
                units: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Populate an nws db from the given json, run the NWSReport through
    WeeWX's report engine, and return the three generated pages.

    `archive` is the station's OWN weather archive, which the 7 Day chart's
    observed week is read from.  `units` is a {unit group: unit} mapping for
    the report's own [Units][[Groups]] -- how a reader asks these pages for
    Celsius.
    """
    read_dir = str(tmp_path / 'forecasts')
    os.mkdir(read_dir)
    write_forecast_files(read_dir, one_hour=one_hour, twelve_hour=twelve_hour, alerts=alerts)
    db_file = str(tmp_path / 'nws.sdb')
    config = make_config(db_file, read_dir)
    engine = StdEngine(config)
    service = NWS(engine, config)
    for forecast_type in (ForecastType.ONE_HOUR, ForecastType.TWELVE_HOUR, ForecastType.ALERTS):
        retry, success = NWSPoller.populate_forecast(service.cfg, forecast_type)
        assert success
        service.saveForecastsToDB(forecast_type)

    # The report engine needs a weather archive with at least one record (it
    # dates the report from the archive's lastGoodStamp).
    config['DataBindings']['wx_binding'] = {
        'database'  : 'wx_sqlite',
        'manager'   : 'weewx.manager.Manager',
        'table_name': 'archive',
        'schema'    : 'weewx.schemas.wview_extended.schema'}
    config['Databases']['wx_sqlite'] = {
        'database_name': str(tmp_path / 'wx.sdb'),
        'database_type': 'SQLite'}
    html_root = str(tmp_path / 'public_html' / 'nws')
    config['WEEWX_ROOT'] = str(tmp_path)
    report: Dict[str, Any] = {'skin': 'nws', 'enable': 'true'}
    if units:
        report['Units'] = {'Groups': dict(units)}
    config['StdReport'] = {
        'SKIN_ROOT': os.path.abspath(SKINS_DIR),
        'HTML_ROOT': html_root,
        'data_binding': 'wx_binding',
        'NWSReport': report}
    with weewx.manager.open_manager_with_config(config, 'wx_binding', initialize=True) as dbm:
        # The default is ONE record, and it is deliberately older than the
        # chart's observed window: the report engine needs an archive with
        # something in it to date the report from at all, and this way the
        # default pages are the no-observed-week case -- which is what a
        # fresh install renders, and a state worth having under test.
        dbm.addRecord(archive if archive is not None
                      else [{'dateTime': int(time.time()) - 200 * 3600,
                             'usUnits': weewx.US, 'interval': 5, 'outTemp': 72.0}])

    stn_info = weewx.station.StationInfo(**config['Station'])
    report_engine = weewx.reportengine.StdReportEngine(config, stn_info, first_run=True)
    report_engine.run()  # synchronously, not as a thread

    pages = {}
    for page in ('index.html', 'hours.html', 'alerts.html'):
        path = os.path.join(html_root, page)
        assert os.path.exists(path), '%s was not generated' % page
        with open(path) as f:
            pages[page] = f.read()
    return pages

def assert_fully_rendered(page: str, name: str) -> None:
    # Under #errorCatcher Echo a failed placeholder survives as literal '$...'.
    # No template ships a literal '$', so any '$' in the output is a bug.
    assert '$' not in page, '%s contains an unrendered placeholder: ...%s...' % (
        name, page[max(0, page.find('$')-60):page.find('$')+60])

@pytest.fixture(scope='module')
def pages(tmp_path_factory):
    """The three pages, rendered from the standard fixtures: single wind
    speeds, one active alert with a long NWSheadline (exercises the headline
    wrapping loops)."""
    tmp_path = tmp_path_factory.mktemp('skin')
    return render_skin(
        tmp_path,
        one_hour    = freshen(load_fixture('one_hour.json')),
        twelve_hour = freshen(load_fixture('twelve_hour.json')),
        alerts      = make_alerts_json(make_alert(
            parameters={'NWSheadline': [LONG_NWS_HEADLINE]})))

@pytest.fixture(scope='module')
def pages_with_archive(tmp_path_factory):
    """The same pages for a station that has been RUNNING for three days,
    with one three-hour outage in the middle of them.  The 7 Day chart then
    carries the week the station recorded as well as the week NWS forecasts,
    which is a different code path from the fresh-install pages above."""
    return render_skin(
        tmp_path_factory.mktemp('skin_archive'),
        one_hour    = freshen(load_fixture('one_hour.json')),
        twelve_hour = freshen(load_fixture('twelve_hour.json')),
        alerts      = make_alerts_json(make_alert()),
        # 18 hours, not a week: the one_hour fixture is trimmed to four
        # periods, so a week of archive would push the seam so far right that
        # the forecast half has nowhere to put a chip.  The shape of a full
        # fortnight is pinned in tests/test_nwsskin.py, which needs no
        # database to draw one.
        archive     = archive_records(18, gap=(10, 11, 12)))


@pytest.fixture(scope='module')
def pages_with_chips(tmp_path_factory):
    """The same pages again, with the archive and the forecast the SAME
    length, which is the only shape that puts the 7 Day chart's two seam
    chips on a page rendered from the trimmed fixtures.

    It earns a third render because the chips are the one part of that chart
    that is not SVG: NWSSkin returns them as markup after the </svg>, and
    only a real render proves the template places them inside the wrapper
    that positions them.  Four hours, because the one_hour fixture is four
    periods -- more archive than forecast pushes the seam right until the
    forecast chip has nowhere to sit, which is exactly what the fixture above
    demonstrates.
    """
    return render_skin(
        tmp_path_factory.mktemp('skin_chips'),
        one_hour    = freshen(load_fixture('one_hour.json')),
        twelve_hour = freshen(load_fixture('twelve_hour.json')),
        alerts      = make_alerts_json(make_alert()),
        archive     = archive_records(4))


class TestObservedWeek:
    """The 7 Day chart's observed half, rendered from a real archive through
    the report engine -- which is the only place the search list, the database
    read, the unit conversion and the template all meet."""

    def test_the_page_still_renders_whole(self, pages_with_archive):
        for name, page in pages_with_archive.items():
            assert_fully_rendered(page, name)

    def test_the_chart_carries_the_week_the_station_recorded(self, pages_with_archive):
        page = pages_with_archive['index.html']
        assert 'class="aline"' in page
        assert 'class="seam"' in page
        assert 'Temperature, recorded and forecast' in page

    def test_the_caption_counts_the_hours_that_were_actually_drawn(self, pages_with_archive):
        """Eighteen hours of archive draw eighteen hours, so the caption says
        so.  A fixed "the week this station recorded" was the identical claim
        to a chip fixed at seven days, on the identical half -- and below the
        width the chips need, this line is the only thing naming the halves at
        all, which is where the wrong number survived longest."""
        assert 'The past 18 hours this station recorded' in pages_with_archive['index.html']

    def test_the_seam_chips_reach_the_page_outside_the_svg(self, pages_with_chips):
        """The one part of the chart that is not SVG.  NWSSkin returns the
        chips as markup after the </svg>, and the template has to place them
        inside the wrapper that positions them -- which nothing short of a
        render can show.  They are markup so the browser can size a filled box
        around words whose length, type size and face all vary, and so a
        screen reader can reach them at all: role="img" hides every <text>
        inside the chart."""
        page = pages_with_chips['index.html']
        legend = re.search(r'<div class="seamlegend"[^>]*>(.*?)</div>', page)
        assert legend, 'the chips did not reach the page'
        assert 'PAST 4 HOURS ACTUAL' in legend.group(1)
        assert 'FORECASTED TEMPERATURES' in legend.group(1)
        # Inside the positioning wrapper, and after the chart it names.
        # Counted FROM the wrapper: the first </svg> on the page closes the
        # icon sprite, hundreds of lines above this.
        wrap = page.index('<div class="sparkwrap chartwrap">')
        assert wrap < page.index('</svg>', wrap) < page.index('seamlegend', wrap)

    def test_a_short_history_gets_the_seam_without_the_chips(self, pages_with_archive):
        """BOTH CHIPS OR NEITHER: a matched pair centered on the rule cannot
        be dropped one at a time, because one alone would straddle the rule it
        is meant to stand beside.  Here the forecast half is the narrow one."""
        assert 'seamlegend' not in pages_with_archive['index.html']

    def test_an_outage_leaves_a_hole_rather_than_a_confident_line(self, pages_with_archive):
        """Three hours the station recorded nothing in.  A single stroke
        across them would be a claim about weather nobody measured."""
        d = re.search(r'<path d="([^"]*)" class="aline"/>',
                      pages_with_archive['index.html']).group(1)
        assert d.count('M') == 2

    def test_the_observed_hours_are_marked_for_the_readout(self, pages_with_archive):
        """A measurement and a prediction must not be reported in the same
        words, so the crosshair is told which is which."""
        spec = json.loads(re.search(r"data-chart='([^']*)'",
                                    pages_with_archive['index.html']).group(1))
        observed = [p for p in spec['p'] if p.get('o')]
        # Every hour, INCLUDING the three the station missed: the crosshair
        # turns a pointer position into an index, so an hour that lost its
        # place would put every later reading on the wrong hour.
        assert len(observed) == 18
        assert [p['T'] is None for p in observed] == [i in (6, 7, 8)
                                                      for i in range(18)]

    def test_a_fresh_install_gets_the_forecast_week_alone(self, pages):
        """An empty archive is what the sample report most often meets: it is
        frequently the first page a new user sees."""
        page = pages['index.html']
        assert 'class="aline"' not in page
        assert 'class="seam"' not in page
        assert 'viewBox="0 0 1040 138"' in page
        assert 'The week&rsquo;s temperature' in page
        assert 'Temperature, recorded and forecast' not in page


METRIC_GROUPS = {'group_temperature': 'degree_C', 'group_speed': 'km_per_hour'}


@pytest.fixture(scope='module')
def metric_pages(tmp_path_factory):
    """The pages of a station whose report asks for Celsius, with a US
    archive behind it -- the combination that has to convert BOTH halves of
    the 7 Day chart, from two different starting points."""
    return render_skin(
        tmp_path_factory.mktemp('skin_metric'),
        one_hour    = freshen(load_fixture('one_hour.json')),
        twelve_hour = freshen(load_fixture('twelve_hour.json')),
        alerts      = make_alerts_json(make_alert()),
        archive     = archive_records(18, gap=(10, 11, 12)),
        units       = METRIC_GROUPS)


class TestReportUnits:
    """A report set to Celsius must get Celsius.

    Through 6.0 it did not, and no test could see it: nws.py built its
    ValueHelpers with no converter, and a ValueHelper converts once at
    construction and never again -- so every number on these pages was
    Fahrenheit whatever [Units] said, and the wind carried a km/h LABEL on an
    mph number.  It has to be checked through a real render, because the
    defect was in how the tag layer and the report's own unit settings meet.
    """

    def test_the_page_still_renders_whole(self, metric_pages):
        for name, page in metric_pages.items():
            assert_fully_rendered(page, name)

    def test_the_forecast_half_is_celsius(self, metric_pages):
        """The fixture's four hours are 76-81F, which is 24-27C."""
        spec = json.loads(re.search(r"data-chart='([^']*)'",
                                    metric_pages['index.html']).group(1))
        forecast = [p['T'] for p in spec['p'] if not p.get('o')]
        assert forecast == [24, 26, 27, 27]

    def test_the_observed_half_is_celsius_too(self, metric_pages):
        """A US archive on a metric report: the two halves start in different
        units and must arrive in the same one, or they would be drawn on one
        axis in two scales."""
        spec = json.loads(re.search(r"data-chart='([^']*)'",
                                    metric_pages['index.html']).group(1))
        observed = [p['T'] for p in spec['p'] if p.get('o') and p['T'] is not None]
        # archive_records() lays down 48-59F, which is 9-15C.
        assert observed and all(5 <= t <= 18 for t in observed), observed

    def test_the_same_report_in_us_units_is_unchanged(self, pages_with_archive):
        """The other half of the claim: nothing moves for a US station."""
        spec = json.loads(re.search(r"data-chart='([^']*)'",
                                    pages_with_archive['index.html']).group(1))
        assert [p['T'] for p in spec['p'] if not p.get('o')] == [76, 78, 80, 81]

    def test_the_wind_number_and_its_label_agree(self, metric_pages, pages_with_archive):
        """The plainest tell that the numbers were never converted:
        $unit.label.windSpeed follows the report's units even when the value
        does not, so through 6.0 an unconverted speed printed an mph number
        wearing a km/h label.

        The twelve-hour fixture's periods are "5 mph" and "1 to 7 mph", so a
        metric report must read 8 km/h and 2-11 km/h -- not 5 and 1-7 with the
        units changed underneath them.
        """
        metric, us = metric_pages['index.html'], pages_with_archive['index.html']
        assert '<span class="w">8 km/h</span>' in metric
        assert '<span class="w">2&ndash;11 km/h</span>' in metric
        assert '<span class="w">5 mph</span>' in us
        assert '<span class="w">1&ndash;7 mph</span>' in us

    def test_the_day_rows_are_celsius(self, metric_pages):
        """Not just the chart: the low-to-high bars read .raw as well."""
        page = metric_pages['index.html']
        highs = [int(v) for v in re.findall(r'<span class="hi">(\d+)&deg;</span>', page)]
        assert highs and all(-10 < h < 45 for h in highs), highs


class TestRenderedPages:
    def test_no_unrendered_placeholders(self, pages):
        for name, page in pages.items():
            assert_fully_rendered(page, name)

    def test_index_page(self, pages):
        page = pages['index.html']
        period = load_fixture('twelve_hour.json')['properties']['periods'][0]
        assert period['name'] in page                    # e.g. 'This Afternoon'
        assert period['detailedForecast'] in page
        assert 'forecast issued' in page
        assert 'class="current"' in page                 # nav marks the page
        assert 'Right now' in page and 'The week ahead' in page

    def test_hours_page(self, pages):
        page = pages['hours.html']
        period = load_fixture('one_hour.json')['properties']['periods'][0]
        assert period['shortForecast'] in page           # e.g. 'Mostly Cloudy'
        assert 'hourly forecast issued' in page
        assert 'Next 12 hours' in page and 'Every hour' in page

    def test_alerts_page(self, pages):
        page = pages['alerts.html']
        # The headline is title-cased, with the acronyms kept upright -- NWS
        # shouts it, and str.title() alone would give "11 Am Pdt".
        assert 'Heat Advisory Remains In Effect' in page
        assert '11 AM Saturday' in page and '8 PM PDT Tuesday' in page
        assert 'HEAT ADVISORY REMAINS IN EFFECT' not in page
        assert 'Heat Advisory issued July 12' in page    # sub-headline
        # Named in the chip beside the event, not buried in the footer.
        assert '<span class="sevchip">Moderate</span>' in page
        assert 'severity' not in page
        assert 'Drink plenty of fluids.' in page         # instructions
        assert 'What to do' in page                      # the callout
        assert 'No alerts in effect' not in page

    def test_every_page_has_one_h1_and_its_own_title(self, pages):
        """Through 5.2 all three pages carried an identical <title>NWS
        Forecast</title> and no body heading at all, so a tab or a bookmark
        could not tell them apart."""
        titles = set()
        for name, page in pages.items():
            found = re.findall(r'<title>(.*?)</title>', page)
            assert len(found) == 1, name
            titles.add(found[0])
            assert page.count('<h1') == 1, name
        assert len(titles) == 3, titles

    def test_headings_do_not_skip_a_level(self, pages):
        """The Nu checker enforces this, and an alert card's own heading is
        the easy one to get wrong: h1 page title, h2 for every section."""
        for name, page in pages.items():
            levels = [int(m) for m in re.findall(r'<h([1-6])[ >]', page)]
            assert levels and levels[0] == 1, name
            for a, b in zip(levels, levels[1:]):
                assert b - a <= 1, '%s: h%d follows h%d' % (name, b, a)

    def test_every_section_carries_a_heading(self, pages):
        """A house rule the validator enforces: a <section> with no h2-h6 is
        an untitled region."""
        for name, page in pages.items():
            for body in re.findall(r'<section\b[^>]*>(.*?)</section>', page, re.S):
                assert re.search(r'<h[2-6][ >]', body), name

    def test_the_nav_marks_exactly_one_current_page(self, pages):
        for name, page in pages.items():
            assert page.count('class="current"') == 1, name

    def test_no_page_reloads_itself(self, pages):
        """Settled for this skin: the sample must not impose an auto-reload
        on everyone who copies it."""
        for name, page in pages.items():
            assert 'http-equiv="refresh"' not in page, name
            assert 'location.reload' not in page, name

class TestDrawnIcons:
    """Since 5.2 the sample skin draws its icons instead of hot-linking NWS.

    Worth pinning here rather than only in test_nwsicons.py: that module tests
    the markup a function returns, this one tests that the templates actually
    CALL it.  Under #errorCatcher Echo a mistyped tag renders as literal text
    and a page full of prose still 'renders', so a passing render proves
    nothing about the icons on its own.
    """

    def test_sprite_is_emitted_once_on_each_icon_page(self, pages):
        for name in ('index.html', 'hours.html'):
            page = pages[name]
            # Exactly one sprite: a second would redefine all 68 ids.
            assert page.count('<symbol id="wx-') == 68, name
            assert page.count('id="wx-skc-day"') == 1, name

    def test_alerts_page_carries_no_sprite(self, pages):
        # It has no icons, so 60k of symbol definitions would be dead weight.
        assert '<symbol id="wx-' not in pages['alerts.html']

    def test_periods_reference_drawn_symbols(self, pages):
        for name in ('index.html', 'hours.html'):
            page = pages[name]
            uses = re.findall(r'<use href="#(wx-[a-z_]+-(?:day|night))"/>', page)
            assert uses, '%s references no drawn symbol' % name
            # Every <use> must point at a symbol the same page defines, or it
            # draws nothing at all -- silently, with no console error.
            for symbol_id in set(uses):
                assert 'id="%s"' % symbol_id in page, '%s: dangling %s' % (
                    name, symbol_id)

    def test_pages_no_longer_hot_link_nws(self, pages):
        # The whole point of the drawn set: no third-party request per period,
        # and nothing that breaks when NWS moves its icon URLs again.
        for name in ('index.html', 'hours.html'):
            assert 'api.weather.gov' not in pages[name], name

    def test_colors_arrive_as_overridable_tokens(self, pages):
        # A skin must be able to theme these; if the fills ever revert to bare
        # hex, weewx-nws 6.0's light/dark/auto has nothing to hold on to.
        page = pages['index.html']
        assert 'var(--wx-sun, #F2B705)' in page
        assert 'var(--wx-cloud-2, #9AA5B4)' in page
        assert 'var(--wx-eye, transparent)' in page
        assert not re.search(r'<(?:circle|path|rect|line)[^>]*fill="#[0-9A-Fa-f]', page)

class TestRenderedVariants:
    def test_ranged_wind_and_no_alerts(self, tmp_path):
        """Ranged wind speeds ('2 to 9 mph') exercise the windSpeed2 branch on
        both forecast pages (the missing-$ bug that shipped through 4.5.7),
        and an empty alert feed must render the no-alerts message."""
        one_hour = freshen(load_fixture('one_hour.json'))
        twelve_hour = freshen(load_fixture('twelve_hour.json'))
        for j in (one_hour, twelve_hour):
            for period in j['properties']['periods']:
                period['windSpeed'] = '2 to 9 mph'
        pages = render_skin(tmp_path, one_hour, twelve_hour, make_alerts_json())
        for name, page in pages.items():
            assert_fully_rendered(page, name)
        assert '2&ndash;9 mph' in pages['index.html']
        assert '2&ndash;9 mph' in pages['hours.html']
        # The pre-fix bug rendered the literal text 'hour.windSpeed2.format'.
        assert 'windSpeed2' not in pages['hours.html']
        assert 'No alerts in effect' in pages['alerts.html']
        assert 'class="alert ' not in pages['alerts.html']

    def test_nws_unknown_icon_renders_an_empty_box(self, tmp_path):
        """End to end for the path 5.2 opened up.

        Through 5.1 an `unknown` icon failed the whole reply in
        sanity_check_forecast_json, so no such record ever reached a template
        and this could not be exercised at all.  Now the period stores, and
        the page must show an empty icon box -- NOT an <img> at
        api.weather.gov, which answers 400 for that URL.
        """
        one_hour = freshen(load_fixture('one_hour.json'))
        twelve_hour = freshen(load_fixture('twelve_hour.json'))
        for period in one_hour['properties']['periods']:
            period['icon'] = \
                'https://api.weather.gov/icons/land/night/unknown?size=medium'
        pages = render_skin(tmp_path, one_hour, twelve_hour, make_alerts_json())
        for name, page in pages.items():
            assert_fully_rendered(page, name)
        hours = pages['hours.html']
        assert 'wxi-unknown' in hours
        assert 'api.weather.gov' not in hours
        assert '<use href="#wx-unknown' not in hours   # no such symbol exists
        # The 12-hour page is unaffected: its periods still draw normally.
        assert '<use href="#wx-' in pages['index.html']

class TestEndedAlertsAreNotRendered:
    """An alert whose end has passed never reaches a generated page.

    fetch_records_internal drops it as it builds the rows, so
    $nwsforecast.alerts() cannot return one.  Pinned here because both this
    skin and a sibling had written comments claiming the opposite, and the
    claim shapes where you look for the alerts page's staleness: it is in the
    clock, not in the feed.
    """

    def test_an_alert_whose_window_has_closed_is_not_on_the_page(self, tmp_path):
        import datetime
        from test_nws import iso
        now = datetime.datetime.now(datetime.timezone.utc)
        ended = make_alert(id='urn:oid:ended.1', event='Ended Warning',
                           onset=iso(now - datetime.timedelta(hours=3)),
                           ends=iso(now - datetime.timedelta(hours=1)),
                           expires=iso(now - datetime.timedelta(hours=1)))
        live = make_alert(id='urn:oid:live.1', event='Live Warning')
        pages = render_skin(tmp_path,
                            freshen(load_fixture('one_hour.json')),
                            freshen(load_fixture('twelve_hour.json')),
                            make_alerts_json(ended, live))
        page = pages['alerts.html']
        assert 'Live Warning' in page
        assert 'Ended Warning' not in page
        assert page.count('<section class="alert') == 1
        assert 'in effect' in page


class TestDayTabsAndCharts:
    """What the 6.0 pages added: tabbed days and drawn charts.

    Both are rendered by python and placed by the template, so a passing
    render says nothing about them on its own -- under #errorCatcher Echo a
    mistyped tag is silently literal text.
    """

    def test_the_hourly_page_has_a_tab_and_a_pane_for_every_day(self, pages):
        page = pages['hours.html']
        tabs = re.findall(r'<button type="button" class="daytab[^"]*" data-day="([0-9-]+)"', page)
        panes = re.findall(r'<div class="daypane[^"]*" data-day="([0-9-]+)"', page)
        assert tabs and tabs == panes

    def test_exactly_one_tab_and_one_pane_start_selected(self, pages):
        """With javascript off the page must still show one day, not all of
        them stacked and not none."""
        page = pages['hours.html']
        assert page.count('class="daytab on"') == 1
        panes = re.findall(r'<div class="daypane( off)?"', page)
        assert panes.count('') == 1

    def test_the_charts_carry_their_points_for_the_crosshair(self, pages):
        assert 'class="sparkcurve chart"' in pages['index.html']
        assert "data-chart='" in pages['index.html']
        assert 'class="daycurve chart"' in pages['hours.html']

    def test_the_alerts_page_draws_no_chart(self, pages):
        assert 'class="chart"' not in pages['alerts.html']

    def test_no_chart_bakes_a_color_into_the_page(self, pages):
        """The dark theme is pure CSS; a hex in the markup would not follow
        it."""
        for name in ('index.html', 'hours.html'):
            assert not re.search(r'class="(?:tline|dline|parea|night|hgrid)"[^>]*'
                                 r'(?:fill|stroke)="#', pages[name]), name


class TestPopThreshold:
    """Chance of rain is blank below 15%, weather.gov's own threshold -- and
    an ABSENT value must not look the same as a suppressed one."""

    _KEEP = object()

    def _render(self, tmp_path, pop, hourly_pop=_KEEP):
        """`hourly_pop` defaults to `pop`, and is given separately only for
        the absent case: sanity_check_forecast_json REQUIRES a chance of rain
        on an hourly period and not on a twelve-hour one, because that is how
        NWS sends them.  A fixture with neither is a state the feed cannot
        produce, and since 6.1 the read_from_dir path checks it the same way
        the network path always did."""
        one_hour = freshen(load_fixture('one_hour.json'))
        twelve_hour = freshen(load_fixture('twelve_hour.json'))
        hourly = pop if hourly_pop is self._KEEP else hourly_pop
        for j, value in ((one_hour, hourly), (twelve_hour, pop)):
            for period in j['properties']['periods']:
                period['probabilityOfPrecipitation'] = {
                    'unitCode': 'wmoUnit:percent', 'value': value}
        return render_skin(tmp_path, one_hour, twelve_hour, make_alerts_json())

    def test_a_low_chance_shows_no_droplet(self, tmp_path):
        pages = self._render(tmp_path, 5)
        for name in ('index.html', 'hours.html'):
            assert 'class="drop"' not in pages[name], name
            assert_fully_rendered(pages[name], name)

    def test_a_real_chance_shows_one(self, tmp_path):
        pages = self._render(tmp_path, 60)
        for name in ('index.html', 'hours.html'):
            assert 'class="drop"' in pages[name], name
            assert '60%' in pages[name], name

    def test_an_absent_chance_is_an_em_dash_not_a_blank(self, tmp_path):
        """A twelve-hour period may carry no chance of rain -- and index.html
        is the twelve-hour page, which is where the em-dash shows."""
        pages = self._render(tmp_path, None, hourly_pop=10)
        assert 'pop-na' in pages['index.html']


class TestCopiedAssets:
    """The stylesheet and the script are copied by CopyGenerator, not
    rendered.  A skin file that install.py does not list, or that skin.conf
    does not copy, leaves the pages unstyled with no error anywhere."""

    def test_the_stylesheet_and_script_reach_the_html_root(self, tmp_path):
        render_skin(tmp_path,
                    freshen(load_fixture('one_hour.json')),
                    freshen(load_fixture('twelve_hour.json')),
                    make_alerts_json())
        html_root = tmp_path / 'public_html' / 'nws'
        for rel in ('css/nws.css', 'scripts/nws.js'):
            assert (html_root / rel).exists(), rel
            assert (html_root / rel).stat().st_size > 0, rel

    def test_every_page_links_both(self, pages):
        for name, page in pages.items():
            assert 'href="css/nws.css"' in page, name
            assert 'src="scripts/nws.js"' in page, name
