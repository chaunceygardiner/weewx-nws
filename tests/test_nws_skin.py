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

import os
import re
import sys
import time
import types

from typing import Any, Dict

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

def render_skin(tmp_path,
                one_hour: Dict[str, Any],
                twelve_hour: Dict[str, Any],
                alerts: Dict[str, Any]) -> Dict[str, str]:
    """Populate an nws db from the given json, run the NWSReport through
    WeeWX's report engine, and return the three generated pages."""
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
    config['StdReport'] = {
        'SKIN_ROOT': os.path.abspath(SKINS_DIR),
        'HTML_ROOT': html_root,
        'data_binding': 'wx_binding',
        'NWSReport': {'skin': 'nws', 'enable': 'true'}}
    with weewx.manager.open_manager_with_config(config, 'wx_binding', initialize=True) as dbm:
        dbm.addRecord({'dateTime': int(time.time()), 'usUnits': weewx.US,
                       'interval': 5, 'outTemp': 72.0})

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
        assert 'Moderate severity' in page
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

    def _render(self, tmp_path, pop):
        one_hour = freshen(load_fixture('one_hour.json'))
        twelve_hour = freshen(load_fixture('twelve_hour.json'))
        for j in (one_hour, twelve_hour):
            for period in j['properties']['periods']:
                period['probabilityOfPrecipitation'] = {
                    'unitCode': 'wmoUnit:percent', 'value': pop}
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
        pages = self._render(tmp_path, None)
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
