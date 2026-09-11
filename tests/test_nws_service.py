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
import logging
import os
import sqlite3
import sys
import threading
import time

from typing import Any, Dict, Optional
from unittest import mock

os.environ['TZ'] = 'America/Los_Angeles'
time.tzset()

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'bin', 'user'))

import configobj
import pytest
import requests

import weeutil.config

import weedb
import weewx
import weewx.manager
import weewx.defaults
import weewx.units
from weewx.engine import StdEngine

import nws as nws_module
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


class TestStaleSchema:
    """A database from an older release is rebuilt, not complained about.

    6.1 relaxed NOT NULL on startTime and endTime, which leaves the column
    NAMES identical -- so the names-only check 6.0 shipped would have passed
    an old table and then failed every INSERT of an alert with no onset.  The
    check compares nullability now, and acts on what it finds.
    """

    @staticmethod
    def _create_6_0_table(db_file: str) -> None:
        """The 6.0 archive table: startTime and endTime NOT NULL."""
        columns = [(name, 'FLOAT NOT NULL' if name in ('startTime', 'endTime')
                    else spec) for name, spec in nws_module.table]
        conn = sqlite3.connect(db_file)
        try:
            conn.execute('CREATE TABLE archive (%s)'
                         % ', '.join('%s %s' % c for c in columns))
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _nullable(db_file: str, column: str) -> bool:
        conn = sqlite3.connect(db_file)
        try:
            return not [r for r in conn.execute('PRAGMA table_info(archive)')
                        if r[1] == column][0][3]
        finally:
            conn.close()

    def test_an_old_table_is_rebuilt(self, tmp_path):
        read_dir = str(tmp_path / 'forecasts')
        os.mkdir(read_dir)
        write_forecast_files(read_dir, alerts=make_alerts_json(make_alert()))
        db_file = str(tmp_path / 'nws.sdb')
        self._create_6_0_table(db_file)
        assert not self._nullable(db_file, 'startTime')

        config = make_config(db_file, read_dir)
        nws = NWS(StdEngine(config), config)
        nws.test_db_file = db_file

        assert self._nullable(db_file, 'startTime')
        assert self._nullable(db_file, 'endTime')
        # And it is usable: the whole point is that the operator does nothing.
        assert nws.cfg is not None

    def test_an_alert_with_no_onset_survives_the_round_trip(self, tmp_path):
        """The end-to-end case that had no test before, which is why the bug
        lived: intake, schema and read never met in one assertion."""
        read_dir = str(tmp_path / 'forecasts')
        os.mkdir(read_dir)
        write_forecast_files(read_dir, alerts=make_alerts_json(
            make_alert(onset=None, ends=None)))
        db_file = str(tmp_path / 'nws.sdb')
        config = make_config(db_file, read_dir)
        nws = NWS(StdEngine(config), config)
        nws.test_db_file = db_file
        populate_and_save(nws, ForecastType.ALERTS)

        rows = nws.select_forecasts(ForecastType.ALERTS)
        assert len(rows) == 1, 'an alert with no onset must still be shown'
        assert rows[0]['startTime'] is None
        assert rows[0]['endTime'] is None
        # An open-ended alert is bounded by its message expiry, and that is
        # what keeps it visible on read.
        assert rows[0]['expirationTime'] is not None

    def test_a_rebuild_that_does_not_take_says_so_once(self, tmp_path, caplog):
        """The guard against silent churn.  If the freshly created table still
        does not match what we declare, the disagreement is between this check
        and the database backend -- and without saying so, every restart would
        drop and recreate the table for ever, wiping the cache each time and
        looking like nothing at all.  sqlite is covered by the tests above;
        this exercises the branch for a backend we cannot run here.
        """
        read_dir = str(tmp_path / 'forecasts')
        os.mkdir(read_dir)
        write_forecast_files(read_dir, alerts=make_alerts_json(make_alert()))
        db_file = str(tmp_path / 'nws.sdb')
        self._create_6_0_table(db_file)
        config = make_config(db_file, read_dir)

        # A declaration no table can satisfy, so the rebuild cannot converge.
        impossible = [('dateTime', True), ('nosuchcolumn', True)]
        with mock.patch.object(NWS, 'expected_schema_pairs',
                               lambda self: impossible):
            with caplog.at_level(logging.ERROR):
                nws = NWS(StdEngine(config), config)

        assert 'still does not match this version' in caplog.text
        assert 'nosuchcolumn is missing' in caplog.text
        # And it carried on with a usable database rather than giving up.
        assert nws.cfg is not None

    def test_a_failed_recreate_does_not_take_weewxd_down(self, tmp_path, caplog):
        """At this point the table is already GONE.  A service constructor
        that raises takes weewxd with it -- StdEngine.loadServices shuts the
        started services down and re-raises -- so an unguarded recreate would
        leave the operator with no forecast table AND no WeeWX.  Failing back
        to a logged error and an inert extension is what 6.0 did in the same
        situation.
        """
        read_dir = str(tmp_path / 'forecasts')
        os.mkdir(read_dir)
        write_forecast_files(read_dir, alerts=make_alerts_json(make_alert()))
        db_file = str(tmp_path / 'nws.sdb')
        self._create_6_0_table(db_file)
        config = make_config(db_file, read_dir)
        engine = StdEngine(config)

        real = weewx.manager.DBBinder.get_manager
        seen = {'n': 0}

        def flaky(binder, data_binding='wx_binding', initialize=False):
            if data_binding == 'nws_binding':
                seen['n'] += 1
                if seen['n'] > 1:          # the re-open AFTER the drop
                    raise weedb.OperationalError('attempt to write a readonly database')
            return real(binder, data_binding=data_binding, initialize=initialize)

        with mock.patch.object(weewx.manager.DBBinder, 'get_manager', flaky):
            with caplog.at_level(logging.ERROR):
                NWS(engine, config)        # must not raise

        assert 'could not recreate it' in caplog.text
        assert 'readonly database' in caplog.text

    def test_a_current_table_is_left_alone(self, tmp_path):
        """The guard on the guard.  Rebuilding is destructive, so a false
        positive costs a user their data rather than a stray log line -- and
        the rebuild must never fire on a database that is already right."""
        read_dir = str(tmp_path / 'forecasts')
        os.mkdir(read_dir)
        write_forecast_files(read_dir, alerts=make_alerts_json(make_alert()))
        db_file = str(tmp_path / 'nws.sdb')
        config = make_config(db_file, read_dir)
        nws = NWS(StdEngine(config), config)
        nws.test_db_file = db_file
        populate_and_save(nws, ForecastType.ALERTS)
        assert db_count(nws, ForecastType.ALERTS) == 1

        # Second startup against the same, current, database.
        NWS(StdEngine(config), config)
        assert db_count(nws, ForecastType.ALERTS) == 1, 'the rows were destroyed'


class TestNonSqliteBinding:
    """weewx-nws is SQLite-only, and says so where the failure happens.

    This schema declares eighteen STRING columns and weedb emits a declared
    type verbatim (weedb.mysql has no create_table of its own), so on MySQL
    the first CREATE TABLE is a syntax error on a type MySQL does not have.
    WeeWX's own schemas never say STRING, which is why nothing else trips over
    it.  Before the check the operator got that raw syntax error -- and since
    a service constructor that raises takes weewxd with it, their whole
    station stopped rather than just this extension.
    """

    def _config(self, tmp_path, driver):
        read_dir = str(tmp_path / 'forecasts')
        os.mkdir(read_dir)
        write_forecast_files(read_dir, alerts=make_alerts_json(make_alert()))
        config = make_config(str(tmp_path / 'nws.sdb'), read_dir)
        config['DatabaseTypes']['SQLite']['driver'] = driver
        return config

    def test_a_non_sqlite_binding_is_refused_by_name(self, tmp_path, caplog):
        config = self._config(tmp_path, 'weedb.mysql')
        with caplog.at_level(logging.ERROR):
            nws = NWS(StdEngine(config), config)
        assert 'needs a SQLite database' in caplog.text
        assert 'weedb.mysql' in caplog.text
        assert 'data_binding' in caplog.text          # says what to change
        # Inert, not fatal: weewxd goes on running the station.
        assert not hasattr(nws, 'cfg')

    def test_it_does_not_reach_the_create(self, tmp_path):
        """The point of checking early: no table, no cryptic syntax error."""
        config = self._config(tmp_path, 'weedb.mysql')
        NWS(StdEngine(config), config)
        assert not os.path.exists(str(tmp_path / 'nws.sdb'))

    def test_sqlite_is_unaffected(self, tmp_path):
        config = self._config(tmp_path, 'weedb.sqlite')
        nws = NWS(StdEngine(config), config)
        assert nws.cfg is not None


class TestReadFromDir:
    """Fleet mode reads forecasts from a directory instead of from NWS, and
    since 6.1 they get the same sanity check a reply from NWS gets.

    They did not through 6.0, and the difference grew teeth once compose began
    refusing a non-US forecast outright: populate_forecast clears the bucket
    BEFORE composing and catches only KeyError, so anything else raised there
    unwound to poll_nws's broad handler -- an empty bucket and a stack trace
    naming nothing, every retry_wait_secs, for as long as the file sat there.
    """

    def test_a_non_us_file_is_rejected_rather_than_raising(self, service):
        j = freshen(load_fixture('one_hour.json'))
        j['properties']['units'] = 'si'
        write_forecast_files(service.test_read_dir, one_hour=j)
        retry, success = NWSPoller.populate_forecast(
            service.cfg, ForecastType.ONE_HOUR)
        assert retry is True and success is False

    def test_a_malformed_file_is_rejected_rather_than_raising(self, service):
        """json.loads raises JSONDecodeError, which IS a ValueError, so this
        had the same shape as the case above."""
        with open(os.path.join(service.test_read_dir, 'ONE_HOUR'), 'w') as f:
            f.write('{ this is not json')
        retry, success = NWSPoller.populate_forecast(
            service.cfg, ForecastType.ONE_HOUR)
        assert retry is True and success is False

    def test_a_good_file_still_loads(self, service):
        """The other half: the check must not reject what fleet mode actually
        ships, which is a verbatim copy of a reply NWS already served."""
        write_forecast_files(service.test_read_dir,
                             one_hour=freshen(load_fixture('one_hour.json')))
        retry, success = NWSPoller.populate_forecast(
            service.cfg, ForecastType.ONE_HOUR)
        assert success is True
        assert len(service.cfg.oneHourForecasts) == 4


class FakeGenerator:
    """Stands in for the report generator.  `converter` is the load-bearing
    part: the tags build their ValueHelpers with it, so it is what decides
    which units a report gets."""
    def __init__(self, config: configobj.ConfigObj, group_units=None,
                 real_formatter: bool = False):
        # A bare Formatter() has empty format and label dicts.  `real_formatter`
        # builds the one an actual report would have -- WeeWX's own defaults --
        # which is what decides whether .format() labels the value.
        if real_formatter:
            skin = weeutil.config.deep_copy(weewx.defaults.defaults)
            skin['Units']['Groups'].update(
                weewx.units.std_groups[weewx.METRIC if group_units else weewx.US])
            self.formatter = weewx.units.Formatter.fromSkinDict(skin)
        else:
            self.formatter = weewx.units.Formatter()
        self.converter = weewx.units.Converter(group_units or weewx.units.USUnits)
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

    def test_values_come_back_in_the_reports_units(self, service):
        """The tags build their ValueHelpers with the report's converter, so a
        report set to metric gets Celsius and km/h.

        Through 6.0 they were built with no converter at all, and a
        ValueHelper converts once, at construction, and never again -- so
        every value came back in the units NWS served whatever [Units] said,
        and neither .raw nor .format() could rescue a metric skin.
        """
        for forecast_type in (ForecastType.ONE_HOUR, ForecastType.TWELVE_HOUR):
            populate_and_save(service, forecast_type)
        us = NWSForecastVariables(FakeGenerator(service.test_config))
        metric = NWSForecastVariables(
            FakeGenerator(service.test_config, weewx.units.MetricUnits))
        f_row, c_row = us.one_hour_forecasts()[0], metric.one_hour_forecasts()[0]
        assert round(f_row['outTemp'].raw) == 76          # the fixture's first hour
        assert round(c_row['outTemp'].raw) == 24          # ... in Celsius
        assert round(f_row['windSpeed'].raw) == 2         # mph
        assert round(c_row['windSpeed'].raw) == 3         # km/h
        # A percentage is a percentage in both.
        assert f_row['pop'].raw == c_row['pop'].raw

    def test_format_supplies_the_unit_label(self, service):
        """The tags now carry the report's formatter, so .format() labels the
        value the way $current.outTemp does.

        This is the half of the 6.1 change that asks something of existing
        skins: until 6.1 .format('%.0f') returned a bare '71' and the manual
        told readers to append $unit.label.outTemp themselves, which now
        prints '71degF degF'.  The documentation was rewritten around this
        behavior, so it is pinned here.
        """
        populate_and_save(service, ForecastType.ONE_HOUR)
        us = NWSForecastVariables(
            FakeGenerator(service.test_config, real_formatter=True))
        metric = NWSForecastVariables(
            FakeGenerator(service.test_config, weewx.units.MetricUnits,
                          real_formatter=True))
        assert us.one_hour_forecasts()[0]['outTemp'].format('%.0f') == '76\u00b0F'
        assert metric.one_hour_forecasts()[0]['outTemp'].format('%.0f') == '24\u00b0C'
        # And the documented way to write a range: suppress the FIRST label.
        speed = us.one_hour_forecasts()[0]['windSpeed']
        assert speed.format('%.0f', add_label=False) == '2'
        assert speed.format('%.0f') == '2 mph'

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
