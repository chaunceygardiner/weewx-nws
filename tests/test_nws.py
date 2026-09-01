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

"""Tests for weewx-nws.

Run from the repo root with the WeeWX venv python:
    /home/weewx/weewx-venv/bin/python -m pytest tests

The forecast fixtures in tests/fixtures/ are real (trimmed) NWS responses for
gridpoint MTR/92,88 (Palo Alto).  Alert json is built programmatically because
alert visibility depends on wall-clock time (expiration is relative to now).
No test talks to the real NWS.
"""

import datetime
import json
import logging
import os
import subprocess
import sys
import time

from typing import Any, Dict, List, Optional

os.environ['TZ'] = 'America/Los_Angeles'
time.tzset()

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'bin', 'user'))

import pytest

import weewx

from dateutil import tz
from dateutil.parser import parse

from nws import Forecast, ForecastType, NWS, NWSPoller, Point, Side

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')

UTC = {'UTC': tz.gettz('UTC')}

def load_fixture(name: str) -> Dict[str, Any]:
    with open(os.path.join(FIXTURE_DIR, name)) as f:
        return json.load(f)

@pytest.fixture
def one_hour_json() -> Dict[str, Any]:
    return load_fixture('one_hour.json')

@pytest.fixture
def twelve_hour_json() -> Dict[str, Any]:
    return load_fixture('twelve_hour.json')

def sanity_check(j: Dict[str, Any], forecast_type: ForecastType) -> Optional[str]:
    return NWSPoller.sanity_check_json(json.dumps(j), j, forecast_type)

def compose(j: Dict[str, Any], forecast_type: ForecastType) -> List[Forecast]:
    return list(NWSPoller.compose_records(j, forecast_type, '37.431495', '-122.110937'))


class TestPointInPolygon:
    # Real gridpoint polygons captured while the NWS off-by-(1,1) bug was live:
    # MTR/91,87 contains Palo Alto; MTR/92,88 (returned by /points at the time)
    # does not.
    POINT = Point(lat=37.4315, long=-122.1109)

    POLYGON_91_87 = [
        Side([Point(37.4414640, -122.1380287), Point(37.4196333, -122.1324516)]),
        Side([Point(37.4196333, -122.1324516), Point(37.4240700, -122.1048970)]),
        Side([Point(37.4240700, -122.1048970), Point(37.4459011, -122.1104687)]),
        Side([Point(37.4459011, -122.1104687), Point(37.4414640, -122.1380287)]),
        ]

    POLYGON_92_88 = [
        Side([Point(37.4677459, -122.1160977), Point(37.4459011, -122.1105197)]),
        Side([Point(37.4459011, -122.1105197), Point(37.4503181, -122.0830553)]),
        Side([Point(37.4503181, -122.0830553), Point(37.4721633, -122.0886280)]),
        Side([Point(37.4721633, -122.0886280), Point(37.4677459, -122.1160977)]),
        ]

    def test_point_inside(self):
        assert NWS.point_in_polygon(self.POINT, self.POLYGON_91_87) == True

    def test_point_outside(self):
        assert NWS.point_in_polygon(self.POINT, self.POLYGON_92_88) == False

    def test_nws_polygon_from_fixture(self, one_hour_json):
        # NWS coordinates are in long/lat order; check_latlong_against_nws_polygon
        # handles the swap.  The fixture's gridpoint covers Palo Alto (NWS fixed
        # its off-by-one for this location in March 2023).
        coordinates = one_hour_json['geometry']['coordinates']
        assert NWS.check_latlong_against_nws_polygon(37.431495, -122.110937, coordinates) == True
        assert NWS.check_latlong_against_nws_polygon(40.0, -100.0, coordinates) == False


class TestComposeForecastRecords:
    def test_one_hour_field_mapping(self, one_hour_json):
        records = compose(one_hour_json, ForecastType.ONE_HOUR)
        periods = one_hour_json['properties']['periods']
        assert len(records) == len(periods)
        updateTime = parse(one_hour_json['properties']['updateTime'], tzinfos=UTC).timestamp()
        record, period = records[0], periods[0]
        assert record.interval == 60
        assert record.usUnits == weewx.US
        assert record.generatedTime == int(updateTime)
        assert record.number == period['number']
        assert record.startTime == datetime.datetime.fromisoformat(period['startTime']).timestamp()
        assert record.endTime == datetime.datetime.fromisoformat(period['endTime']).timestamp()
        assert record.isDaytime == period['isDaytime']
        assert record.outTemp == float(period['temperature'])
        assert record.outTempTrend == period['temperatureTrend']
        assert record.pop == period['probabilityOfPrecipitation']['value']
        # NWS dewpoint is celsius; the record is fahrenheit.
        assert record.dewpoint == round(period['dewpoint']['value'] * 9.0 / 5.0 + 32.0)
        assert record.outHumidity == period['relativeHumidity']['value']
        assert record.iconUrl == period['icon']
        assert record.shortForecast == period['shortForecast']
        assert record.detailedForecast == period['detailedForecast']
        # Alert-only fields are None on forecasts.
        assert record.expirationTime is None
        assert record.id is None
        assert record.instruction is None

    def test_twelve_hour_has_no_one_hour_only_fields(self, twelve_hour_json):
        records = compose(twelve_hour_json, ForecastType.TWELVE_HOUR)
        assert len(records) == len(twelve_hour_json['properties']['periods'])
        assert records[0].interval == 720
        # dewpoint/humidity are only composed for ONE_HOUR forecasts.
        assert records[0].dewpoint is None
        assert records[0].outHumidity is None

    def test_wind_speed_range_parses_into_two_speeds(self, one_hour_json):
        one_hour_json['properties']['periods'][0]['windSpeed'] = '2 to 9 mph'
        record = compose(one_hour_json, ForecastType.ONE_HOUR)[0]
        assert record.windSpeed == 2
        assert record.windSpeed2 == 9

    def test_wind_speed_single_value(self, one_hour_json):
        one_hour_json['properties']['periods'][0]['windSpeed'] = '9 mph'
        record = compose(one_hour_json, ForecastType.ONE_HOUR)[0]
        assert record.windSpeed == 9
        assert record.windSpeed2 is None

    def test_missing_wind_speed_composes_as_none(self, one_hour_json):
        # Sanity checking rejects a missing windSpeed, but compose_records must
        # still tolerate one (4.5.4).
        one_hour_json['properties']['periods'][0]['windSpeed'] = None
        record = compose(one_hour_json, ForecastType.ONE_HOUR)[0]
        assert record.windSpeed is None
        assert record.windSpeed2 is None

    def test_relative_icon_url_is_absolutized(self, one_hour_json):
        # NWS breakage observed in the wild: icon missing the scheme/host.
        one_hour_json['properties']['periods'][0]['icon'] = 'icons/land/day/bkn?size=small'
        record = compose(one_hour_json, ForecastType.ONE_HOUR)[0]
        assert record.iconUrl == 'https://api.weather.gov/icons/land/day/bkn?size=small'

    def test_metric_units(self, one_hour_json):
        one_hour_json['properties']['units'] = 'si'
        record = compose(one_hour_json, ForecastType.ONE_HOUR)[0]
        assert record.usUnits == weewx.METRIC


class TestTranslateWindDir:
    def test_all_sixteen_directions(self):
        # ENE was 77.5 through 4.5.7; fixed in 4.6.
        compass = {
            'N':   0.0, 'NNE':  22.5, 'NE':  45.0, 'ENE':  67.5,
            'E':  90.0, 'ESE': 112.5, 'SE': 135.0, 'SSE': 157.5,
            'S': 180.0, 'SSW': 202.5, 'SW': 225.0, 'WSW': 247.5,
            'W': 270.0, 'WNW': 292.5, 'NW': 315.0, 'NNW': 337.5,
            }
        for wdir_str, degrees in compass.items():
            assert NWSPoller.translate_wind_dir(wdir_str) == degrees, wdir_str

    def test_unknown_direction_is_none(self):
        assert NWSPoller.translate_wind_dir('') is None
        assert NWSPoller.translate_wind_dir(None) is None
        assert NWSPoller.translate_wind_dir('NORTH') is None


class TestCommandLine:
    """nws.py is documented as runnable directly -- README, docs/utilities.md.

    Nothing exercised that until 5.2, and the gap cost us: adding
    `import user.nwsicons` at module scope broke EVERY command-line option
    (run directly, sys.path[0] is bin/user, so there is no `user` package),
    and the hermetic suite stayed green throughout because it imports the
    module rather than running it.  These run the real script in a subprocess,
    which is the only way to see what a user sees.  Both options are offline.
    """

    NWS_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          '..', 'bin', 'user', 'nws.py')

    def _run(self, *args):
        # Filter PYTHONPATH; do NOT clear it.  nws.py imports weewx at module
        # scope, and on a Debian or Red Hat install weewx is reachable only
        # via PYTHONPATH (README: `PYTHONPATH=/usr/share/weewx python3 -m
        # pytest tests`).  Clearing it there kills the subprocess with
        # "No module named 'weewx'", which these tests would report as exactly
        # the "No module named 'user'" bug they exist to catch -- a false
        # positive wearing the costume of a true one.
        #
        # Drop only the entries that would make a `user` package importable,
        # since resolving nwsicons WITHOUT one is the single thing under test.
        env = dict(os.environ)
        kept = [p for p in env.get('PYTHONPATH', '').split(os.pathsep)
                if p and not os.path.isdir(os.path.join(p, 'user'))]
        if kept:
            env['PYTHONPATH'] = os.pathsep.join(kept)
        else:
            env.pop('PYTHONPATH', None)
        return subprocess.run([sys.executable, self.NWS_PY] + list(args),
                              capture_output=True, text=True, timeout=120, env=env)

    def test_help_runs(self):
        done = self._run('--help')
        assert done.returncode == 0, done.stderr
        assert 'ModuleNotFoundError' not in done.stderr
        assert '--test-requester' in done.stdout

    def test_point_in_polygon_runs(self):
        # The one utility that touches no network at all.
        done = self._run('--test-point-in-polygon')
        assert done.returncode == 0, done.stderr
        assert 'ModuleNotFoundError' not in done.stderr

class TestSanityCheckForecast:
    def test_valid_one_hour_passes(self, one_hour_json):
        assert sanity_check(one_hour_json, ForecastType.ONE_HOUR) is None

    def test_valid_twelve_hour_passes(self, twelve_hour_json):
        assert sanity_check(twelve_hour_json, ForecastType.TWELVE_HOUR) is None

    def test_null_temperature_trend_allowed(self, one_hour_json):
        # 4.5.7: NWS sends temperatureTrend = null.
        one_hour_json['properties']['periods'][0]['temperatureTrend'] = None
        assert sanity_check(one_hour_json, ForecastType.ONE_HOUR) is None

    def test_missing_geometry_rejected(self, one_hour_json):
        # compose_forecast_records needs geometry for the polygon check; the
        # sanity check must reject its absence (with the raw response logged)
        # rather than leaving it to blow up at compose time.
        del one_hour_json['geometry']
        err = sanity_check(one_hour_json, ForecastType.ONE_HOUR)
        assert err is not None and 'geometry' in err

    def test_null_geometry_rejected(self, one_hour_json):
        one_hour_json['geometry'] = None
        assert sanity_check(one_hour_json, ForecastType.ONE_HOUR) is not None

    def test_non_list_geometry_coordinates_rejected(self, one_hour_json):
        one_hour_json['geometry']['coordinates'] = 'bogus'
        err = sanity_check(one_hour_json, ForecastType.ONE_HOUR)
        assert err is not None and 'coordinates' in err

    def test_missing_update_time_rejected(self, one_hour_json):
        del one_hour_json['properties']['updateTime']
        err = sanity_check(one_hour_json, ForecastType.ONE_HOUR)
        assert err is not None and 'updateTime' in err

    def test_unparseable_update_time_rejected(self, one_hour_json):
        one_hour_json['properties']['updateTime'] = 'not-a-date'
        assert sanity_check(one_hour_json, ForecastType.ONE_HOUR) is not None

    def test_periods_not_a_list_rejected(self, one_hour_json):
        one_hour_json['properties']['periods'] = 'bogus'
        err = sanity_check(one_hour_json, ForecastType.ONE_HOUR)
        assert err is not None and 'periods' in err

    def test_null_wind_speed_rejected(self, one_hour_json):
        # 4.5.6: return to strict checking.
        one_hour_json['properties']['periods'][0]['windSpeed'] = None
        err = sanity_check(one_hour_json, ForecastType.ONE_HOUR)
        assert err is not None and 'windSpeed' in err

    def test_non_mph_wind_speed_rejected(self, one_hour_json):
        one_hour_json['properties']['periods'][0]['windSpeed'] = '15 km/h'
        assert sanity_check(one_hour_json, ForecastType.ONE_HOUR) is not None

    def test_unknown_icon_no_longer_discards_the_forecast(self, caplog):
        """Since 5.2 an `unknown` icon keeps its period instead of failing
        the whole reply.

        NWS really does send `.../land/night/unknown?size=medium`.  Rejecting
        on it threw away an entire forecast -- up to 156 periods -- over one
        missing glyph, and the site served the previous forecast until NWS
        sent a clean one.  The period is good data apart from the icon, and
        the report tags now render it as an empty icon box rather than
        hot-linking a URL api.weather.gov answers 400 for.
        """
        j = load_fixture('one_hour.json')
        j['properties']['periods'][0]['icon'] = \
            'https://api.weather.gov/icons/land/night/unknown?size=medium'
        with caplog.at_level(logging.INFO):
            assert sanity_check(j, ForecastType.ONE_HOUR) is None
        # The operator still has to hear about it -- once for the reply,
        # naming the count, not once per period.
        lines = [r for r in caplog.records if 'unknown' in r.getMessage()]
        assert len(lines) == 1, [r.getMessage() for r in lines]
        assert '1 of %d periods' % len(j['properties']['periods']) \
            in lines[0].getMessage()

    def test_several_unknown_icons_are_logged_once_for_the_reply(self, caplog):
        # A pathological reply could carry one per period; that many identical
        # lines is how a real signal gets ignored.
        j = load_fixture('one_hour.json')
        for period in j['properties']['periods']:
            period['icon'] = \
                'https://api.weather.gov/icons/land/night/unknown?size=medium'
        with caplog.at_level(logging.INFO):
            assert sanity_check(j, ForecastType.ONE_HOUR) is None
        lines = [r for r in caplog.records if 'unknown' in r.getMessage()]
        assert len(lines) == 1, [r.getMessage() for r in lines]

    def test_null_dewpoint_value_allowed(self, one_hour_json):
        # The dewpoint entry must exist, but its value may be null (4.5.4/4.5.6
        # compromise).
        one_hour_json['properties']['periods'][0]['dewpoint'] = {'unitCode': 'wmoUnit:degC', 'value': None}
        assert sanity_check(one_hour_json, ForecastType.ONE_HOUR) is None

    def test_null_dewpoint_entry_rejected(self, one_hour_json):
        one_hour_json['properties']['periods'][0]['dewpoint'] = None
        err = sanity_check(one_hour_json, ForecastType.ONE_HOUR)
        assert err is not None and 'dewpoint' in err

    def test_null_relative_humidity_entry_rejected(self, one_hour_json):
        one_hour_json['properties']['periods'][0]['relativeHumidity'] = None
        err = sanity_check(one_hour_json, ForecastType.ONE_HOUR)
        assert err is not None and 'relativeHumidity' in err

    def test_null_pop_value_rejected_for_one_hour(self, one_hour_json):
        one_hour_json['properties']['periods'][0]['probabilityOfPrecipitation']['value'] = None
        assert sanity_check(one_hour_json, ForecastType.ONE_HOUR) is not None


def iso(dt: datetime.datetime) -> str:
    return dt.replace(microsecond=0).isoformat()

def make_alert(**overrides) -> Dict[str, Any]:
    """An active Heat Advisory in NWS CAP shape; override fields per test."""
    now = datetime.datetime.now(datetime.timezone.utc)
    properties: Dict[str, Any] = {
        'id'          : 'urn:oid:2.49.0.1.840.0.deadbeef.001.1',
        'status'      : 'Actual',
        'messageType' : 'Alert',
        'category'    : 'Met',
        'severity'    : 'Moderate',
        'certainty'   : 'Likely',
        'urgency'     : 'Expected',
        'event'       : 'Heat Advisory',
        'headline'    : 'Heat Advisory issued July 12',
        'description' : 'Temperatures up to 105 expected.',
        'instruction' : 'Drink plenty of fluids.',
        'sender'      : 'w-nws.webmaster@noaa.gov',
        'senderName'  : 'NWS San Francisco CA',
        'sent'        : iso(now - datetime.timedelta(hours=1)),
        'effective'   : iso(now - datetime.timedelta(hours=1)),
        'onset'       : iso(now - datetime.timedelta(hours=1)),
        'expires'     : iso(now + datetime.timedelta(hours=3)),
        'ends'        : iso(now + datetime.timedelta(hours=3)),
        'parameters'  : {},
        }
    properties.update(overrides)
    return {'properties': properties}

def make_alerts_json(*features: Dict[str, Any]) -> Dict[str, Any]:
    return {'features': list(features)}

def compose_alerts(j: Dict[str, Any]) -> List[Forecast]:
    return compose(j, ForecastType.ALERTS)


class TestSanityCheckAlerts:
    def test_valid_alert_passes(self):
        j = make_alerts_json(make_alert())
        assert sanity_check(j, ForecastType.ALERTS) is None

    def test_zero_alerts_passes(self):
        assert sanity_check(make_alerts_json(), ForecastType.ALERTS) is None

    def test_features_not_a_list_rejected(self):
        err = sanity_check({'features': None}, ForecastType.ALERTS)
        assert err is not None and 'features' in err

    def test_missing_headline_rejected(self):
        alert = make_alert()
        del alert['properties']['headline']
        err = sanity_check(make_alerts_json(alert), ForecastType.ALERTS)
        assert err is not None and 'headline' in err

    def test_null_instruction_allowed(self):
        j = make_alerts_json(make_alert(instruction=None))
        assert sanity_check(j, ForecastType.ALERTS) is None

    def test_null_ends_allowed(self):
        j = make_alerts_json(make_alert(ends=None))
        assert sanity_check(j, ForecastType.ALERTS) is None

    def test_test_alert_skips_field_checks(self):
        # Test/Exercise/System/Draft alerts are skipped before field validation,
        # so a malformed one must not fail the whole batch.
        j = make_alerts_json({'properties': {'status': 'Test'}})
        assert sanity_check(j, ForecastType.ALERTS) is None


class TestComposeAlertRecords:
    def test_active_alert_composes(self):
        alert = make_alert()
        records = compose_alerts(make_alerts_json(alert))
        assert len(records) == 1
        record = records[0]
        properties = alert['properties']
        assert record.interval == 0
        assert record.name == properties['event']
        assert record.shortForecast == properties['headline']
        assert record.detailedForecast == properties['description']
        assert record.instruction == properties['instruction']
        assert record.id == properties['id']
        assert record.generatedTime == int(parse(properties['effective'], tzinfos=UTC).timestamp())
        assert record.startTime == parse(properties['onset'], tzinfos=UTC).timestamp()
        assert record.expirationTime == parse(properties['expires'], tzinfos=UTC).timestamp()
        assert record.endTime == parse(properties['ends'], tzinfos=UTC).timestamp()
        assert record.severity == properties['severity']
        assert record.certainty == properties['certainty']
        assert record.urgency == properties['urgency']
        assert record.senderName == properties['senderName']

    def test_non_actual_statuses_skipped(self):
        for status in ('Test', 'Exercise', 'System', 'Draft'):
            j = make_alerts_json(make_alert(status=status))
            assert compose_alerts(j) == [], 'status %s should be skipped' % status

    def test_null_ends_falls_back_to_expires(self):
        alert = make_alert(ends=None)
        record = compose_alerts(make_alerts_json(alert))[0]
        assert record.endTime == parse(alert['properties']['expires'], tzinfos=UTC).timestamp()

    def test_recently_expired_alert_still_shown(self):
        # Alerts are kept for 24 hours past expiration because NWS is slow to
        # reissue them.
        now = datetime.datetime.now(datetime.timezone.utc)
        j = make_alerts_json(make_alert(
            expires = iso(now - datetime.timedelta(hours=1)),
            ends    = iso(now - datetime.timedelta(hours=1))))
        assert len(compose_alerts(j)) == 1

    def test_long_expired_alert_skipped(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        j = make_alerts_json(make_alert(
            expires = iso(now - datetime.timedelta(hours=25)),
            ends    = iso(now - datetime.timedelta(hours=25))))
        assert compose_alerts(j) == []

    def test_expired_references_skipped(self):
        # An alert whose id appears in another alert's expiredReferences must
        # not be yielded.
        old = make_alert(id='urn:oid:2.49.0.1.840.0.deadbeef.001.1')
        new = make_alert(
            id         = 'urn:oid:2.49.0.1.840.0.deadbeef.002.1',
            parameters = {'expiredReferences': ['w-nws.webmaster@noaa.gov,urn:oid:2.49.0.1.840.0.deadbeef.001.1,2026-07-12T00:00:00-00:00']})
        records = compose_alerts(make_alerts_json(old, new))
        assert [r.id for r in records] == ['urn:oid:2.49.0.1.840.0.deadbeef.002.1']

    def test_malformed_alert_does_not_kill_batch(self):
        j = make_alerts_json({'properties': None}, make_alert())
        records = compose_alerts(j)
        assert len(records) == 1

    def test_nws_headline_parameter(self):
        j = make_alerts_json(make_alert(
            parameters = {'NWSheadline': ['HEAT ADVISORY IN EFFECT UNTIL 8 PM']}))
        record = compose_alerts(j)[0]
        assert record.nwsHeadline == 'HEAT ADVISORY IN EFFECT UNTIL 8 PM'


class TestEndToEndParse:
    def test_request_forecast_path_via_read_from_dir(self, one_hour_json, twelve_hour_json, tmp_path):
        """Drive request_forecast's read_from_dir file path (the fleet/client
        mode) end to end: file -> json -> sanity check -> composed records."""
        import threading
        from nws import Configuration
        (tmp_path / 'ONE_HOUR').write_text(json.dumps(one_hour_json))
        (tmp_path / 'TWELVE_HOUR').write_text(json.dumps(twelve_hour_json))
        cfg = Configuration(
            lock                  = threading.Lock(),
            alerts                = [],
            signalDeleteAlerts    = False,
            lastModifiedAlerts    = None,
            twelveHourForecasts   = [],
            twelveHourForecastsJson = '',
            lastModifiedTwelveHour = None,
            oneHourForecasts      = [],
            oneHourForecastsJson  = '',
            lastModifiedOneHour   = None,
            alertsUrl             = 'unused',
            twelveHourForecastUrl = None,
            oneHourForecastUrl    = None,
            hardCodedTwelveHourForecastUrl = None,
            hardCodedOneHourForecastUrl = None,
            latitude              = '37.431495',
            longitude             = '-122.110937',
            timeout_secs          = 5,
            archive_interval      = 300,
            user_agent            = '(weewx-nws test run, weewx-nws-developer)',
            poll_secs             = 1800,
            alert_poll_secs       = 600,
            retry_wait_secs       = 300,
            alert_retry_wait_secs = 30,
            days_to_keep          = 90,
            read_from_dir         = str(tmp_path),
            ssh_config            = None,
            )
        for forecast_type in (ForecastType.ONE_HOUR, ForecastType.TWELVE_HOUR):
            retry, j = NWSPoller.request_forecast(cfg, forecast_type)
            assert retry == False
            assert j is not None
            assert sanity_check(j, forecast_type) is None
            assert len(compose(j, forecast_type)) == 4
