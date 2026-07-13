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

"""Service-level tests for weewx-nws: the NWS StdService (save/dedupe/delete),
the NWSForecastVariables SearchList, and NWSPoller's request plumbing.

Run from the repo root with the WeeWX venv python:
    /home/weewx/weewx-venv/bin/python -m pytest tests

These tests stand up a real StdEngine (Simulator driver) with a real sqlite
database in a temp dir, and feed the service through the read_from_dir file
path -- no test talks to the real NWS.  HTTP behavior (304/404/sanity reject)
is tested against a fake requests.Session.
"""

import datetime
import json
import os
import sqlite3
import sys
import threading
import time

from typing import Any, Dict, Optional

os.environ['TZ'] = 'America/Los_Angeles'
time.tzset()

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'bin', 'user'))

import configobj
import pytest
import requests

import weewx
import weewx.units
from weewx.engine import StdEngine

from nws import Configuration, ForecastType, NWS, NWSForecastVariables, NWSPoller

from test_nws import load_fixture, make_alert, make_alerts_json

LATITUDE = '37.431495'
LONGITUDE = '-122.110937'

def freshen(j: Dict[str, Any], hours_from_now: int = 1) -> Dict[str, Any]:
    """Rewrite a forecast fixture's period times to lie in the future.
    fetch_records drops records whose endTime has passed, so read-back tests
    need periods that have not yet ended.  updateTime is left alone (it must
    stay in the past or saveForecastsToDB rejects the whole forecast)."""
    start = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0) \
        + datetime.timedelta(hours=hours_from_now)
    for i, period in enumerate(j['properties']['periods']):
        period['startTime'] = (start + datetime.timedelta(hours=i)).isoformat()
        period['endTime'] = (start + datetime.timedelta(hours=i+1)).isoformat()
    return j

def write_forecast_files(read_dir: str,
                         one_hour: Optional[Dict[str, Any]] = None,
                         twelve_hour: Optional[Dict[str, Any]] = None,
                         alerts: Optional[Dict[str, Any]] = None) -> None:
    for fname, j in (('ONE_HOUR', one_hour), ('TWELVE_HOUR', twelve_hour), ('ALERTS', alerts)):
        if j is not None:
            with open(os.path.join(read_dir, fname), 'w') as f:
                json.dump(j, f)

def make_config(db_file: str, read_dir: str, binding: str = 'nws_binding') -> configobj.ConfigObj:
    # Lat/long as strings, as configobj would return them from weewx.conf.
    return configobj.ConfigObj({
        'Station': {
            'station_type': 'Simulator',
            'altitude': [0, 'foot'],
            'latitude': LATITUDE,
            'longitude': LONGITUDE},
        'Simulator': {
            'driver': 'weewx.drivers.simulator',
            'mode': 'simulator'},
        'StdArchive': {
            'archive_interval': 300},
        'NWS': {
            'data_binding': binding,
            'read_from_dir': read_dir},
        'DataBindings': {
            binding: {
                'database': 'nws_sqlite',
                'manager': 'weewx.manager.Manager',
                'table_name': 'archive',
                # Production says user.nws.schema; the tests import nws.py as
                # the top-level module 'nws' (bin/user is on sys.path), and the
                # engine must not ALSO instantiate the service (the fixture
                # constructs it), hence 'nws.schema' and no data_services.
                'schema': 'nws.schema'}},
        'Databases': {
            'nws_sqlite': {
                'database_name': db_file,
                'database_type': 'SQLite'}},
        'Engine': {
            'Services': {
                'data_services': ''}},
        'DatabaseTypes': {
            'SQLite': {
                'driver': 'weedb.sqlite'}}})

@pytest.fixture
def service(tmp_path):
    """A live NWS service over a temp sqlite db, fed from files in a temp dir."""
    read_dir = str(tmp_path / 'forecasts')
    os.mkdir(read_dir)
    write_forecast_files(
        read_dir,
        one_hour    = freshen(load_fixture('one_hour.json')),
        twelve_hour = freshen(load_fixture('twelve_hour.json')),
        alerts      = make_alerts_json(make_alert()))
    db_file = str(tmp_path / 'nws.sdb')
    config = make_config(db_file, read_dir)
    engine = StdEngine(config)
    nws = NWS(engine, config)
    nws.test_read_dir = read_dir
    nws.test_db_file = db_file
    nws.test_config = config
    yield nws

def populate_and_save(nws: NWS, forecast_type: ForecastType) -> None:
    retry, success = NWSPoller.populate_forecast(nws.cfg, forecast_type)
    assert success, 'populate_forecast(%s) failed' % forecast_type
    nws.saveForecastsToDB(forecast_type)

def db_count(nws: NWS, forecast_type: ForecastType) -> int:
    conn = sqlite3.connect(nws.test_db_file)
    try:
        return conn.execute('SELECT COUNT(*) FROM archive WHERE interval = %d'
                            % NWS.get_interval(forecast_type)).fetchone()[0]
    finally:
        conn.close()


class TestServiceSaveAndReadBack:
    def test_forecasts_round_trip(self, service):
        for forecast_type, expected in ((ForecastType.ONE_HOUR, 4), (ForecastType.TWELVE_HOUR, 4)):
            populate_and_save(service, forecast_type)
            rows = service.select_forecasts(forecast_type)
            assert len(rows) == expected
        # The two types share one table but must not bleed into each other.
        one_hour = service.select_forecasts(ForecastType.ONE_HOUR)
        assert all(row['interval'] == 60 for row in one_hour)
        # sqlite gives the schema's 'STRING' columns NUMERIC affinity, so a
        # numeric-looking latitude comes back as a float (production behavior).
        assert float(one_hour[0]['latitude']) == float(LATITUDE)
        # Rows come back ordered by startTime.
        start_times = [row['startTime'] for row in one_hour]
        assert start_times == sorted(start_times)

    def test_same_forecast_never_saved_twice(self, service):
        populate_and_save(service, ForecastType.ONE_HOUR)
        count = db_count(service, ForecastType.ONE_HOUR)
        # Re-populate from the same file (same generatedTime) and save again.
        populate_and_save(service, ForecastType.ONE_HOUR)
        assert db_count(service, ForecastType.ONE_HOUR) == count

    def test_forecast_generated_in_future_rejected(self, service):
        j = freshen(load_fixture('one_hour.json'))
        j['properties']['updateTime'] = (
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=2)).isoformat()
        write_forecast_files(service.test_read_dir, one_hour=j)
        populate_and_save(service, ForecastType.ONE_HOUR)
        assert db_count(service, ForecastType.ONE_HOUR) == 0

    def test_expired_periods_not_returned(self, service):
        # Periods whose endTime has passed are stored but filtered on read.
        j = freshen(load_fixture('one_hour.json'), hours_from_now=-100)
        write_forecast_files(service.test_read_dir, one_hour=j)
        populate_and_save(service, ForecastType.ONE_HOUR)
        assert db_count(service, ForecastType.ONE_HOUR) == 4
        assert service.select_forecasts(ForecastType.ONE_HOUR) == []

    def test_end_archive_period_saves_all_three_types(self, service):
        for forecast_type in (ForecastType.ONE_HOUR, ForecastType.TWELVE_HOUR, ForecastType.ALERTS):
            retry, success = NWSPoller.populate_forecast(service.cfg, forecast_type)
            assert success
        service.end_archive_period(None)
        assert db_count(service, ForecastType.ONE_HOUR) == 4
        assert db_count(service, ForecastType.TWELVE_HOUR) == 4
        assert db_count(service, ForecastType.ALERTS) == 1


class TestServiceAlerts:
    def test_alert_round_trip(self, service):
        populate_and_save(service, ForecastType.ALERTS)
        rows = service.select_forecasts(ForecastType.ALERTS)
        assert len(rows) == 1
        assert rows[0]['name'] == 'Heat Advisory'
        assert rows[0]['interval'] == 0

    def test_zero_alerts_downloaded_deletes_existing(self, service):
        populate_and_save(service, ForecastType.ALERTS)
        assert db_count(service, ForecastType.ALERTS) == 1
        # NWS now reports no active alerts: the empty download must clear the db.
        write_forecast_files(service.test_read_dir, alerts=make_alerts_json())
        retry, success = NWSPoller.populate_forecast(service.cfg, ForecastType.ALERTS)
        assert success
        assert service.cfg.signalDeleteAlerts
        service.saveForecastsToDB(ForecastType.ALERTS)
        assert db_count(service, ForecastType.ALERTS) == 0

    def test_expired_alerts_pruned_on_save(self, service):
        # Insert an alert that expired more than 24 hours ago directly, then
        # drive an alerts save, which prunes expired alerts first.  (The save
        # may also legitimately write the active alert the poller has in its
        # bucket, so assert on the expired row, not on a total count.)
        expired = make_alert(id='urn:oid:2.49.0.1.840.0.expired.001.1')
        record = next(NWSPoller.compose_records(
            make_alerts_json(expired), ForecastType.ALERTS, LATITUDE, LONGITUDE))
        record.expirationTime = time.time() - 25 * 3600
        service.save_forecast(NWS.convert_to_json(record, NWS.get_archive_interval_timestamp(300)))
        assert db_count(service, ForecastType.ALERTS) == 1
        service.saveForecastsToDB(ForecastType.ALERTS)
        conn = sqlite3.connect(service.test_db_file)
        try:
            expired_left, = conn.execute(
                "SELECT COUNT(*) FROM archive WHERE interval = 0 AND id = 'urn:oid:2.49.0.1.840.0.expired.001.1'").fetchone()
            stale_left, = conn.execute(
                'SELECT COUNT(*) FROM archive WHERE interval = 0 AND expirationTime <= %f'
                % (time.time() - 24 * 3600)).fetchone()
        finally:
            conn.close()
        assert expired_left == 0
        assert stale_left == 0


class FakeGenerator:
    def __init__(self, config: configobj.ConfigObj):
        self.formatter = weewx.units.Formatter()
        self.converter = weewx.units.Converter()
        self.config_dict = config
        self.skin_dict: Dict[str, Any] = {}

class TestSearchList:
    @pytest.fixture
    def search_list(self, service):
        for forecast_type in (ForecastType.ONE_HOUR, ForecastType.TWELVE_HOUR, ForecastType.ALERTS):
            populate_and_save(service, forecast_type)
        return NWSForecastVariables(FakeGenerator(service.test_config))

    def test_extension_list(self, search_list):
        [extensions] = search_list.get_extension_list(None, None)
        assert extensions['nwsforecast'] is search_list

    def test_one_hour_forecasts_wrapped_in_value_helpers(self, search_list):
        rows = search_list.one_hour_forecasts()
        assert len(rows) == 4
        row = rows[0]
        for field in ('dateTime', 'generatedTime', 'startTime', 'endTime',
                      'outTemp', 'pop', 'dewpoint', 'outHumidity', 'windSpeed', 'windDir'):
            assert isinstance(row[field], weewx.units.ValueHelper), field
        # The wrapped value must survive the round trip (rows are ordered by
        # startTime, so row 0 is the fixture's first period).
        period = load_fixture('one_hour.json')['properties']['periods'][0]
        assert row['outTemp'].raw == float(period['temperature'])

    def test_max_forecasts_honored(self, search_list):
        assert len(search_list.one_hour_forecasts(2)) == 2
        assert len(search_list.twelve_hour_forecasts(1)) == 1

    def test_alerts_shape(self, search_list):
        [alert] = search_list.alerts()
        assert alert['event'] == 'Heat Advisory'
        assert alert['headline'].startswith('Heat Advisory issued')
        assert alert['severity'] == 'Moderate'
        for field in ('effective', 'onset', 'expires', 'ends', 'sent'):
            assert isinstance(alert[field], weewx.units.ValueHelper), field

    def test_alert_count(self, search_list):
        assert search_list.alert_count() == 1


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: Any = None, headers: Optional[Dict[str, str]] = None):
        self.status_code = status_code
        self.payload = payload
        self.headers = headers if headers is not None else {}
        self.text = json.dumps(payload) if payload is not None else ''

    def json(self) -> Any:
        if self.payload is None:
            raise json.decoder.JSONDecodeError('no payload', '', 0)
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError('%d' % self.status_code)

    def __bool__(self) -> bool:
        return self.status_code < 400

class FakeSession:
    """Stands in for requests.Session; serves a canned response and records
    the request."""
    response: FakeResponse = FakeResponse()
    requests_seen: list = []

    def get(self, url: str, headers: Dict[str, str], timeout: int) -> FakeResponse:
        FakeSession.requests_seen.append({'url': url, 'headers': headers})
        return FakeSession.response

def make_cfg(**overrides: Any) -> Configuration:
    values: Dict[str, Any] = dict(
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
        alertsUrl             = 'https://api.weather.gov/alerts/active?point=%s,%s' % (LATITUDE, LONGITUDE),
        twelveHourForecastUrl = 'https://api.weather.gov/gridpoints/MTR/92,88/forecast',
        oneHourForecastUrl    = 'https://api.weather.gov/gridpoints/MTR/92,88/forecast/hourly',
        hardCodedTwelveHourForecastUrl = None,
        hardCodedOneHourForecastUrl = None,
        latitude              = LATITUDE,
        longitude             = LONGITUDE,
        timeout_secs          = 5,
        archive_interval      = 300,
        user_agent            = '(weewx-nws test run, weewx-nws-developer)',
        poll_secs             = 1800,
        alert_poll_secs       = 600,
        retry_wait_secs       = 300,
        alert_retry_wait_secs = 30,
        days_to_keep          = 90,
        read_from_dir         = None,
        ssh_config            = None,
        )
    values.update(overrides)
    return Configuration(**values)

@pytest.fixture
def fake_session(monkeypatch):
    FakeSession.response = FakeResponse()
    FakeSession.requests_seen = []
    monkeypatch.setattr(requests, 'Session', FakeSession)
    return FakeSession

class TestRequestForecast:
    def test_success(self, fake_session):
        fake_session.response = FakeResponse(200, load_fixture('one_hour.json'))
        cfg = make_cfg()
        retry, j = NWSPoller.request_forecast(cfg, ForecastType.ONE_HOUR)
        assert retry == True and j is not None
        assert fake_session.requests_seen[0]['url'] == cfg.oneHourForecastUrl
        # A successful response primes If-Modified-Since for the next request.
        assert cfg.lastModifiedOneHour is not None
        NWSPoller.request_forecast(cfg, ForecastType.ONE_HOUR)
        assert 'If-Modified-Since' in fake_session.requests_seen[1]['headers']

    def test_not_modified_means_no_retry(self, fake_session):
        cfg = make_cfg(lastModifiedOneHour=datetime.datetime.now(datetime.timezone.utc))
        fake_session.response = FakeResponse(304)
        retry, j = NWSPoller.request_forecast(cfg, ForecastType.ONE_HOUR)
        assert (retry, j) == (False, None)

    def test_404_means_retry(self, fake_session):
        fake_session.response = FakeResponse(404, {
            'title': 'Data Unavailable For Requested Point', 'status': 404,
            'type': 'https://api.weather.gov/problems/InvalidPoint',
            'detail': 'Unable to provide data', 'correlationId': 'x', 'instance': 'y'})
        retry, j = NWSPoller.request_forecast(make_cfg(), ForecastType.TWELVE_HOUR)
        assert (retry, j) == (True, None)

    def test_sanity_check_rejection_means_retry(self, fake_session):
        bad = load_fixture('one_hour.json')
        del bad['properties']['updateTime']
        fake_session.response = FakeResponse(200, bad)
        retry, j = NWSPoller.request_forecast(make_cfg(), ForecastType.ONE_HOUR)
        assert (retry, j) == (True, None)

    def test_hard_coded_url_wins(self, fake_session):
        hard_coded = 'https://api.weather.gov/gridpoints/MTR/91,87/forecast/hourly'
        fake_session.response = FakeResponse(200, load_fixture('one_hour.json'))
        cfg = make_cfg(hardCodedOneHourForecastUrl=hard_coded)
        NWSPoller.request_forecast(cfg, ForecastType.ONE_HOUR)
        assert fake_session.requests_seen[0]['url'] == hard_coded

class TestRequestUrls:
    def test_success_fills_urls(self, fake_session):
        fake_session.response = FakeResponse(200, {
            'id': 'x', 'type': 'Feature', 'geometry': {},
            'properties': {
                'forecast': 'https://api.weather.gov/gridpoints/MTR/92,88/forecast',
                'forecastHourly': 'https://api.weather.gov/gridpoints/MTR/92,88/forecast/hourly'}})
        cfg = make_cfg(twelveHourForecastUrl=None, oneHourForecastUrl=None)
        assert NWSPoller.request_urls(cfg) == True
        assert cfg.twelveHourForecastUrl == 'https://api.weather.gov/gridpoints/MTR/92,88/forecast'
        assert cfg.oneHourForecastUrl == 'https://api.weather.gov/gridpoints/MTR/92,88/forecast/hourly'

    def test_404_returns_false(self, fake_session):
        fake_session.response = FakeResponse(404, {'title': 'Data Unavailable', 'status': 404})
        assert NWSPoller.request_urls(make_cfg()) == False

    # weewxd stops by raising Terminate (recognized by name -- weewxd runs as
    # __main__ so the class can't be imported) from its SIGTERM handler inside
    # whatever the main thread is executing.  request_urls runs on the main
    # thread at engine startup: its broad handler must re-raise Terminate...
    def test_terminate_escapes(self, monkeypatch):
        class Terminate(Exception):
            pass
        class TerminatingSession:
            def get(self, url: str, headers: Dict[str, str], timeout: int) -> FakeResponse:
                raise Terminate()
        monkeypatch.setattr(requests, 'Session', TerminatingSession)
        with pytest.raises(Terminate):
            NWSPoller.request_urls(make_cfg())

    # ...while an ordinary unexpected exception is still swallowed (logged,
    # returns False) so a transient failure can't bring down weewx.
    def test_ordinary_exception_still_swallowed(self, monkeypatch):
        class FailingSession:
            def get(self, url: str, headers: Dict[str, str], timeout: int) -> FakeResponse:
                raise ValueError('boom')
        monkeypatch.setattr(requests, 'Session', FailingSession)
        assert NWSPoller.request_urls(make_cfg()) == False


class TestFetchRecordsRetry:
    # weewxd writes while reports read, and sqlite 'database is locked' has
    # been observed; fetch_records retries 3 times, one second apart.
    def test_retries_after_locked_database(self, monkeypatch):
        calls = []
        def flaky(dbm, forecast_type, latitude, longitude, max_forecasts=None):
            calls.append(1)
            if len(calls) < 2:
                raise Exception('database is locked')
            return [{'ok': True}]
        monkeypatch.setattr(NWSForecastVariables, 'fetch_records_internal', staticmethod(flaky))
        monkeypatch.setattr(time, 'sleep', lambda secs: None)
        rows = NWSForecastVariables.fetch_records(None, ForecastType.ONE_HOUR, LATITUDE, LONGITUDE)
        assert rows == [{'ok': True}]
        assert len(calls) == 2

    def test_gives_up_after_three_tries(self, monkeypatch):
        calls = []
        def always_locked(dbm, forecast_type, latitude, longitude, max_forecasts=None):
            calls.append(1)
            raise Exception('database is locked')
        monkeypatch.setattr(NWSForecastVariables, 'fetch_records_internal', staticmethod(always_locked))
        monkeypatch.setattr(time, 'sleep', lambda secs: None)
        rows = NWSForecastVariables.fetch_records(None, ForecastType.ONE_HOUR, LATITUDE, LONGITUDE)
        assert rows == []
        assert len(calls) == 3


class TestSmallUtilities:
    def test_get_lat_long_from_station(self):
        config = configobj.ConfigObj({'Station': {'latitude': LATITUDE, 'longitude': LONGITUDE}})
        assert NWS.get_lat_long(config) == (LATITUDE, LONGITUDE)

    def test_get_lat_long_nws_override_wins(self):
        config = configobj.ConfigObj({
            'Station': {'latitude': LATITUDE, 'longitude': LONGITUDE},
            'NWS': {'latitude': '1.0', 'longitude': '2.0'}})
        assert NWS.get_lat_long(config) == ('1.0', '2.0')

    def test_time_to_next_poll_aligns_to_wall_clock(self):
        for poll_secs in (300, 600, 1800):
            sleep_time = NWSPoller.time_to_next_poll(poll_secs)
            assert 0 < sleep_time <= poll_secs
            assert (time.time() + sleep_time) % poll_secs < 0.1

    def test_get_archive_interval_timestamp(self):
        ts = NWS.get_archive_interval_timestamp(300)
        assert ts % 300 == 0
        assert time.time() - 300 <= ts <= time.time() + 0.5

    def test_convert_to_json_round_trips_every_field(self):
        record = next(NWSPoller.compose_records(
            make_alerts_json(make_alert()), ForecastType.ALERTS, LATITUDE, LONGITUDE))
        j = NWS.convert_to_json(record, 1234567890)
        assert j['dateTime'] == 1234567890
        # Every schema column except dateTime comes from the Forecast record.
        from nws import table
        for column, _ in table:
            assert column in j, column
        assert j['name'] == record.name
        assert j['severity'] == record.severity
