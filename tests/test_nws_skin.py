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
from nws import NWS, NWSPoller, ForecastType

# skin.conf names the search list as user.nws.NWSForecastVariables (how it is
# imported in an installed WeeWX).  Alias the already-imported module so the
# report engine resolves it without a second copy of the module.
if 'user' not in sys.modules:
    user_pkg = types.ModuleType('user')
    user_pkg.nws = nws_module  # type: ignore[attr-defined]
    sys.modules['user'] = user_pkg
    sys.modules['user.nws'] = nws_module

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
        assert 'Forecast generated' in page
        assert 'class="active"' in page                  # menubar highlights the tab

    def test_hours_page(self, pages):
        page = pages['hours.html']
        period = load_fixture('one_hour.json')['properties']['periods'][0]
        assert period['shortForecast'] in page           # e.g. 'Mostly Cloudy'
        assert 'PoP:' in page
        assert '?size=medium' in page                    # small icons upsized
        assert 'Forecast generated' in page

    def test_alerts_page(self, pages):
        page = pages['alerts.html']
        # The long NWSheadline exercises the line-wrapping loops; the wrapped
        # title must come through (with <br> breaks), plus the CAP details.
        assert 'HEAT ADVISORY REMAINS IN EFFECT' in page
        assert 'Heat Advisory issued July 12' in page    # sub-headline
        assert 'Moderate' in page                        # severity
        assert 'Drink plenty of fluids.' in page         # instructions
        assert 'No active National Weather Service alerts' not in page

    def test_icons_copied(self, pages, tmp_path_factory):
        # CopyGenerator copy_once must ship the icon tree next to the pages.
        html_root = os.path.join(str(tmp_path_factory.getbasetemp()), 'skin0', 'public_html', 'nws')
        assert os.path.exists(os.path.join(html_root, 'nws_icons', 'medium', 'day', 'skc'))

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
        assert '2 to 9' in pages['index.html']
        assert '2 to 9' in pages['hours.html']
        # The pre-fix bug rendered the literal text 'hour.windSpeed2.format'.
        assert 'windSpeed2' not in pages['hours.html']
        assert 'No active National Weather Service alerts' in pages['alerts.html']
