#!/usr/bin/python3
# Copyright 2020 by John A Kline <john@johnkline.com>
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
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

"""The nws extension fetches nws hourly forecasts for a station's location (as identified by lat/long].

See the README for installation and usage.
"""
import calendar
import configobj
import datetime
import json
import logging
import os
import requests
import sys
import threading
import time

from dateutil import tz
from dateutil.parser import parse

from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Dict, IO, Iterator, List, Optional

import weedb
import weewx
import weewx.units
import weeutil.weeutil

from weeutil.weeutil import timestamp_to_string
from weeutil.weeutil import to_bool
from weeutil.weeutil import to_float
from weeutil.weeutil import to_int
from weewx.engine import StdService
from weewx.cheetahgenerator import SearchList

log = logging.getLogger(__name__)

WEEWX_NWS_VERSION = "0.1"

if sys.version_info[0] < 3:
    raise weewx.UnsupportedFeature(
        "weewx-nws requires Python 3, found %s" % sys.version_info[0])

if weewx.__version__ < "4":
    raise weewx.UnsupportedFeature(
        "WeeWX 4 is required, found %s" % weewx.__version__)

# Schema for nws database (nws.sdb).
table = [
    ('dateTime',         'INTEGER NOT NULL'), # When forecast/alert was inserted.
    ('interval',         'INTEGER NOT NULL'), # Always 60 for hourly,  720 for daily, 0 for alerts
    ('usUnits',          'INTEGER NOT NULL'),
    ('generatedTime',    'INTEGER NOT NULL'), # When forecast was generated., For alerts, holds effective
    ('number',           'INTEGER NOT NULL'),
    ('name',             'STRING'),           # For alerts, holds event name (e.g., Heat Advisory)
    ('startTime',        'FLOAT NOT NULL'),   # For alerts, holds onset
    ('endTime',          'FLOAT NOT NULL'),   # For alerts, holds ends
    ('isDaytime',        'INTEGER NOT NULL'),
    ('outTemp',          'FLOAT NOT NULL'),  # Needs to be converted
    ('outTempTrend',     'STRING'),
    ('windSpeed',        'FLOAT NOT NULL'),
    ('windDir',          'FLOAT'),
    ('iconUrl',          'STRING NOT NULL'), # For alerts, holds the alert URL
    ('shortForecast',    'STRING NOT NULL'), # For alrerts, holds the headline
    ('detailedForecast', 'STRING'),          # For alerts, holds the description
    ]

schema = {
    'table'         : table,
}

class ForecastType(Enum):
    HOURLY = 1
    DAILY  = 2
    ALERTS = 3

@dataclass
class Forecast:
    interval        : int # 0 for ALERTS, 60 for HOURLY, 720 for DAILY
    usUnits         : int
    generatedTime   : int # When forecast was generated.  For alerts hold effective.
    number          : int # For alerts, numbered from 0 as parsed from the XML
    name            : Optional[str] # For alerts, holds event name (e.g., Heat Advisory)
    startTime       : float  # For alerts, holds onset
    endTime         : float  # For alerts, holds ends
    isDaytime       : int
    outTemp         : float
    outTempTrend    : Optional[str]
    windSpeed       : float
    windDir         : Optional[float]
    iconUrl         : str    # For alerts, holds the alert URL
    shortForecast   : str    # For alerts, holds the headline
    detailedForecast: Optional[str] # For alerts,hold the description

@dataclass
class Configuration:
    lock             : threading.Lock
    alerts           : List[Forecast] # Controlled by lock
    dailyForecasts   : List[Forecast] # Controlled by lock
    hourlyForecasts  : List[Forecast] # Controlled by lock
    alertsUrl        : Optional[str]  # Controlled by lock
    dailyForecastUrl : Optional[str]  # Controlled by lock
    hourlyForecastUrl: Optional[str]  # Controlled by lock
    latitude         : float          # Immutable
    longitude        : float          # Immutable
    timeout_secs     : int            # Immutable
    archive_interval : int            # Immutable
    user_agent       : str            # Immutable
    retry_wait_secs  : int            # Immutable

class NWS(StdService):
    """Fetch NWS Forecasts"""
    def __init__(self, engine, config_dict):
        super(NWS, self).__init__(engine, config_dict)
        log.info("Service version is %s." % WEEWX_NWS_VERSION)

        self.config_dict = config_dict
        self.nws_config_dict = config_dict.get('NWS', {})
        self.engine = engine

        # If specified, get lat/long, else get it from station.
        latitude: str = self.nws_config_dict.get('latitude')
        if latitude is None:
            latitude = config_dict['Station'].get('latitude', None)
        longitude: str = self.nws_config_dict.get('longitude')
        if longitude is None:
            longitude = config_dict['Station'].get('longitude', None)
        if latitude is None or longitude is None:
            log.error("Could not determine station's latitude and longitude.")
            return
        log.info("Using latitude '%s', longitude '%s'." % (latitude, longitude))

        # get the database parameters we need to function
        self.data_binding = self.nws_config_dict.get('data_binding', 'nws_binding')

        self.dbm_dict = weewx.manager.get_manager_dict(
            self.config_dict['DataBindings'],
            self.config_dict['Databases'],
            self.data_binding)

        # [possibly] initialize the database
        dbmanager = engine.db_binder.get_manager(data_binding=self.data_binding, initialize=True)
        log.info("Using binding '%s' to database '%s'" % (self.data_binding, dbmanager.database_name))

        # Check that schema matches
        dbcol = dbmanager.connection.columnsOf(dbmanager.table_name)
        memcol = [x[0] for x in self.dbm_dict['schema']['table']]
        if dbcol != memcol:
            raise Exception('nws schema mismatch: %s != %s' % (dbcol, memcol))

        self.cfg = Configuration(
            lock              = threading.Lock(),
            dailyForecasts    = [],
            hourlyForecasts   = [],
            alerts            = [],
            dailyForecastUrl  = None,
            hourlyForecastUrl = None,
            alertsUrl         = None,
            latitude          = latitude,
            longitude         = longitude,
            timeout_secs      = to_int(self.nws_config_dict.get('timeout_secs', 5)),
            archive_interval  = int(config_dict['StdArchive']['archive_interval']),
            user_agent        = self.nws_config_dict.get('User-Agent', '(<weather-site>, <contact>)'),
            retry_wait_secs   = int(self.nws_config_dict.get('retry_wait_secs', 5)),
            )

        # At startup, attempt to get the latest forecasts.
        ts = NWS.get_archive_interval_timestamp(self.cfg.archive_interval)

        # Hourly (Never write the same archive interval twice.)
        if self.get_latest_ts(ForecastType.HOURLY) < NWS.get_archive_interval_timestamp(self.cfg.archive_interval) and NWSPoller.populate_forecast(self.cfg, ForecastType.HOURLY):
            self.saveForecastsToDB(ForecastType.HOURLY)

        # Daily (Never write the same archive interval twice.)
        if self.get_latest_ts(ForecastType.DAILY) < NWS.get_archive_interval_timestamp(self.cfg.archive_interval) and NWSPoller.populate_forecast(self.cfg, ForecastType.DAILY):
            self.saveForecastsToDB(ForecastType.DAILY)

        # Alerts (Never write the same archive interval twice.)
        if self.get_latest_ts(ForecastType.ALERTS) < NWS.get_archive_interval_timestamp(self.cfg.archive_interval) and NWSPoller.populate_forecast(self.cfg, ForecastType.ALERTS):
            self.saveForecastsToDB(ForecastType.ALERTS)

        # Start a thread to query NWS for forecasts
        nws_poller: NWSPoller = NWSPoller(self.cfg)
        t: threading.Thread = threading.Thread(target=nws_poller.poll_nws)
        t.setName('NWS')
        t.setDaemon(True)
        t.start()

        self.bind(weewx.END_ARCHIVE_PERIOD, self.end_archive_period)

    def end_archive_period(self, _event):
        """create new archive record and save them to the database"""
        self.saveForecastsToDB(ForecastType.HOURLY)
        self.saveForecastsToDB(ForecastType.DAILY)
        self.saveForecastsToDB(ForecastType.ALERTS)

    def saveForecastsToDB(self, forecast_type: ForecastType):
        if forecast_type == ForecastType.HOURLY:
            self.saveHourlyForecastsToDB()
        elif forecast_type == ForecastType.DAILY:
            self.saveDailyForecastsToDB()
        else:
            self.saveAlertsToDB()

    def saveHourlyForecastsToDB(self):
        try:
            now = int(time.time() + 0.5)
            with self.cfg.lock:
                if len(self.cfg.hourlyForecasts) != 0:
                    ts = NWS.get_archive_interval_timestamp(self.cfg.archive_interval)
                    # Never write the same archvie interval twice.
                    if self.get_latest_ts(ForecastType.HOURLY) < ts:
                        for record in self.cfg.hourlyForecasts:
                            self.save_forecast(NWS.convert_to_json(record, ts))
                        log.info('Saved %d ForecastType.HOURLY records.' % len(self.cfg.hourlyForecasts))
                    self.cfg.hourlyForecasts.clear()
                    self.delete_old_rows(ForecastType.HOURLY);
        except Exception as e:
            # Include a stack traceback in the log:
            # but eat this exception as we don't want to bring down weewx
            # because ot this extension.
            log.info('saveHourlyForedcastsToDB: %s' % e)
            weeutil.logger.log_traceback(log.critical, "    ****  ")

    def saveDailyForecastsToDB(self):
        try:
            now = int(time.time() + 0.5)
            with self.cfg.lock:
                if len(self.cfg.dailyForecasts) != 0:
                    ts = NWS.get_archive_interval_timestamp(self.cfg.archive_interval)
                    # Never write the same archvie interval twice.
                    if self.get_latest_ts(ForecastType.DAILY) < ts:
                        for record in self.cfg.dailyForecasts:
                            self.save_forecast(NWS.convert_to_json(record, ts))
                        log.info('Saved %d ForecastType.DAILY records.' % len(self.cfg.dailyForecasts))
                    self.cfg.dailyForecasts.clear()
                    self.delete_old_rows(ForecastType.DAILY);
        except Exception as e:
            # Include a stack traceback in the log:
            # but eat this exception as we don't want to bring down weewx
            # because ot this extension.
            log.info('saveDailyForedcastsToDB: %s' % e)
            weeutil.logger.log_traceback(log.critical, "    ****  ")

    def saveAlertsToDB(self):
        log.debug('saveAlertsToDB: start')
        try:
            now = int(time.time() + 0.5)
            with self.cfg.lock:
                if len(self.cfg.alerts) != 0:
                    ts = NWS.get_archive_interval_timestamp(self.cfg.archive_interval)
                    # Never write the same archvie interval twice.
                    if self.get_latest_ts(ForecastType.ALERTS) < ts:
                        for record in self.cfg.alerts:
                            self.save_forecast(NWS.convert_to_json(record, ts))
                        log.info('Saved %d ForecastType.ALERTS records.' % len(self.cfg.alerts))
                    self.cfg.alerts.clear()
                    # TODO: The last alert will ever be deleted until a new alert comes along.
                    #       This is mostly OK since the alert will not be served if it has expired.
                    #       The one problematic case is where the lat/long has changed.  In this
                    #       case, the user would have to delete the alert in the db (else, it will
                    #       be served until is expires (or an alert in the new location comes along.
                    self.delete_old_rows(ForecastType.ALERTS);
        except Exception as e:
            # Include a stack traceback in the log:
            # but eat this exception as we don't want to bring down weewx
            # because ot this extension.
            log.info('saveAlertsToDB: %s' % e)
            weeutil.logger.log_traceback(log.critical, "    ****  ")

    def delete_old_rows(self, forecast_type: ForecastType):
        try:
            dbmanager = self.engine.db_binder.get_manager(self.data_binding)
            delete = "DELETE FROM archive WHERE dateTime < (SELECT MAX(dateTime) FROM archive WHERE interval = %d) AND interval = %d" % (
                NWS.get_interval(forecast_type), NWS.get_interval(forecast_type))
            log.info('Pruning %s rows with %s.' % (forecast_type, delete))
            dbmanager.getSql(delete)
        except Exception as e:
            log.info('delete_old_rows(%s): %s failed with %s.' % (forecast_type, delete, e))

    @staticmethod
    def get_archive_interval_timestamp(archive_interval: int) -> int:
        now_ts = int(time.time() + 0.5)
        return int(now_ts / archive_interval) * archive_interval

    @staticmethod
    def convert_to_json(record, ts):
        j = {}
        j['dateTime']         = ts
        j['interval']         = record.interval
        j['usUnits']          = record.usUnits
        j['generatedTime']    = record.generatedTime
        j['number']           = record.number
        j['name']             = record.name
        j['startTime']        = record.startTime
        j['endTime']          = record.endTime
        j['isDaytime']        = record.isDaytime
        j['outTemp']          = record.outTemp
        j['outTempTrend']     = record.outTempTrend
        j['windSpeed']        = record.windSpeed
        j['windDir']          = record.windDir
        j['iconUrl']          = record.iconUrl
        j['shortForecast']    = record.shortForecast
        j['detailedForecast'] = record.detailedForecast
        return j

    @staticmethod
    def get_interval(forecast_type: ForecastType) -> int:
        if forecast_type == ForecastType.HOURLY:
            return 60
        elif forecast_type == ForecastType.DAILY:
            return 720
        # ALERTS
        return 0

    def get_latest_ts(self, forecast_type: ForecastType):
        dbmanager = self.engine.db_binder.get_manager(self.data_binding)
        select = 'SELECT MAX(dateTime) FROM archive WHERE interval = %d' % NWS.get_interval(forecast_type)
        try:
            for row in dbmanager.genSql(select):
                if row[0] != None:
                    log.debug('get_latest_ts(%s): returning %d' % (forecast_type, row[0]))
                    return row[0]
                else:
                    log.debug('get_latest_ts(%s): no rows in database, returning 0.' % forecast_type)
                    return 0
        except Exception as e:
            log.info('get_latest_type(%s): %s failed with %s.' % (forecast_type, select, e))
            return 0

    def save_forecast(self, record):
        """save data to database"""
        dbmanager = self.engine.db_binder.get_manager(self.data_binding)
        dbmanager.addRecord(record)

class NWSPoller:
    def __init__(self, cfg: Configuration):
        self.cfg = cfg

    def poll_nws(self) -> None:
        while True:
            at_least_one_failed: bool = False
            success = NWSPoller.populate_forecast(self.cfg, ForecastType.HOURLY)
            if not success:
                at_least_one_failed = True
            success = NWSPoller.populate_forecast(self.cfg, ForecastType.DAILY)
            if not success:
                at_least_one_failed = True
            success = NWSPoller.populate_forecast(self.cfg, ForecastType.ALERTS)
            if not success:
                at_least_one_failed = True
            if at_least_one_failed:
                #TODO: Should only retry the one that failed.
                time.sleep(cfg.retry_wait_secs)
            else:
                sleep_time = NWSPoller.time_to_next_poll()
                log.debug('NWSPoller: poll_nws: Sleeping for %f seconds.' % sleep_time) 
                time.sleep(sleep_time)

    @staticmethod
    def populate_forecast(cfg, forecast_type: ForecastType) -> bool:
        log.debug('populate_forecast(%s): start' % forecast_type)
        start_time = time.time()
        j = NWSPoller.request_forecast(cfg, forecast_type)
        if j == None:
            return False
        else:
            elapsed_time = time.time() - start_time
            log.debug('Queries to NWS took %f seconds' % elapsed_time)
            with cfg.lock:
                if forecast_type == ForecastType.HOURLY:
                    cfg.hourlyForecasts.clear()
                elif forecast_type == ForecastType.DAILY:
                    cfg.dailyForecasts.clear()
                else:
                    cfg.alerts.clear()
                for record in NWSPoller.compose_records(j, forecast_type):
                    log.debug('NWSPoller: poll_nws: adding %s forecast(%s) to array.' % (forecast_type, record))
                    if forecast_type == ForecastType.HOURLY:
                        cfg.hourlyForecasts.append(record)
                    elif forecast_type == ForecastType.DAILY:
                        cfg.dailyForecasts.append(record)
                    else: # Alerts
                        cfg.alerts.append(record)
            return True

    @staticmethod
    def time_to_next_poll():
        # Poll at the top of the hour.
        time_of_next_poll = int(time.time() / 3600) * 3600 + 3600
        return time_of_next_poll - time.time()

    @staticmethod
    def request_urls(cfg):
        try:
            # Need to fetch (and cache) the forecast URLs
            url = 'https://api.weather.gov/points/%s,%s' % (cfg.latitude, cfg.longitude)
            session= requests.Session()
            headers = {'User-Agent': cfg.user_agent}
            log.debug('request_urls: headers: %s' % headers)
            log.info('Downloading URLs from %s' % url)
            response: requests.Response = session.get(url=url, headers=headers, timeout=cfg.timeout_secs)
            response.raise_for_status()
            log.debug('request_hourly_forecast: %s returned %r' % (url, response))
            if response:
                j: Dict[str, Any] = response.json()
                log.debug('id: %s' % j['id'])
                log.debug('type: %s' % j['type'])
                log.debug('geometry: %s' % j['geometry'])
                for k in j['properties']:
                    log.debug('properties key:  %s, value: %s' % (k, j['properties'][k]))
                with cfg.lock:
                    cfg.dailyForecastUrl  = j['properties']['forecast']
                    cfg.hourlyForecastUrl = j['properties']['forecastHourly']
                    cfg.alertsUrl         = 'https://api.weather.gov/alerts/active?point=%s,%s' % (cfg.latitude, cfg.longitude)
                    log.info('request_urls: Cached dailyForecastUrl: %s' % cfg.dailyForecastUrl)
                    log.info('request_urls: Cached hourlyForecastUrl: %s' % cfg.hourlyForecastUrl)
                    log.info('request_urls: Cached alertsUrl: %s' % cfg.alertsUrl)
        except Exception as e:
            log.info('request_urls: Attempt to fetch from: %s failed: %s.' % (url, e))
            weeutil.logger.log_traceback(log.critical, "    ****  ")

    @staticmethod
    def request_forecast(cfg, forecast_type: ForecastType):
        log.debug('request_forecast(%s): start' % forecast_type)
        with cfg.lock:
            if forecast_type == ForecastType.HOURLY:
                forecastUrl = cfg.hourlyForecastUrl
            elif forecast_type == ForecastType.DAILY:
                forecastUrl = cfg.dailyForecastUrl
            else:
                forecastUrl = cfg.alertsUrl
        log.debug('request_forecast(%s): forecastUrl %s' % (forecast_type, forecastUrl))
        if forecastUrl == None:
            NWSPoller.request_urls(cfg)
        else:
            log.debug('request_forecast(%s): Using cached forecastUrl: %s' % (forecast_type, forecastUrl))
        with cfg.lock:
            if forecast_type == ForecastType.HOURLY:
                forecastUrl = cfg.hourlyForecastUrl
            elif forecast_type == ForecastType.DAILY:
                forecastUrl = cfg.dailyForecastUrl
            else:
                forecastUrl = cfg.alertsUrl
        log.debug('request_forecast(%s)2: forecastUrl %s' % (forecast_type, forecastUrl))
        if forecastUrl != None:
            try:
                log.info('Downloading %s forecasts from %s.' % (forecast_type, forecastUrl))
                session= requests.Session()
                headers = {'User-Agent': cfg.user_agent}
                response: requests.Response = session.get(url=forecastUrl, headers=headers, timeout=cfg.timeout_secs)
                return response.json()
            except Exception as e:
                log.info('request_forecast(%s): Attempt to fetch from: %s failed: %s.' % (forecast_type, forecastUrl, e))
                weeutil.logger.log_traceback(log.critical, "    ****  ")
                return None
        else:
            log.info("request_forecast(%s): Couldn't get the forecast URL." % forecast_type)
            return None

    @staticmethod
    def compose_alert_records(j):
        log.debug('compose_alert_records: len(j[features]): %d' % len(j['features']))
        alertCount = 0
        for feature in j['features']:
            alert = feature['properties']
            tzinfos = {'UTC': tz.gettz("UTC")}
            effective = parse(alert['effective'], tzinfos=tzinfos).timestamp()
            onset     = parse(alert['onset'], tzinfos=tzinfos).timestamp()
            ends      = parse(alert['ends'], tzinfos=tzinfos).timestamp()
            record = Forecast(
                interval         = NWS.get_interval(ForecastType.ALERTS),
                usUnits          = 'US',                   # Dummy
                generatedTime    = int(effective),
                number           = alertCount,
                name             = alert['event'],
                startTime        = onset,
                endTime          = ends,
                isDaytime        = True,                    # Dummy
                outTemp          = 0.0,                     # Dummy
                outTempTrend     = '',                      # Dummy
                windSpeed        = 0.0,                     # Dummy
                windDir          = 0.0,                     # Dummy
                iconUrl          = '',                      # Dummy
                shortForecast    = alert['headline'],
                detailedForecast = alert['description'],
                )
            alertCount += 1
            log.debug('compose_alert_records: yielding record %s' % record)
            yield record

    @staticmethod
    def compose_records(j, forecast_type: ForecastType):
        if forecast_type == ForecastType.ALERTS:
            yield from NWSPoller.compose_alert_records(j)
            return

        # 2020-05-18T22:02:26+00:00
        tzinfos = {'UTC': tz.gettz("UTC")}
        updateTime = parse(j['properties']['updateTime'], tzinfos=tzinfos).timestamp()

        units = j['properties']['units']
        if units == 'us':
            units = 'US'
        else:
            units = 'METRIC'

        for period in j['properties']['periods']:
            windSpeedStr = period['windSpeed']
            windSpeedArray = windSpeedStr.split()
            windSpeed = to_int(windSpeedArray[0])
            windSpeedUnit = windSpeedArray[1]
            record = Forecast(
                interval         = NWS.get_interval(forecast_type),
                usUnits          = units,
                generatedTime    = int(updateTime),
                number           = period['number'],
                name             = period['name'],
                startTime        = datetime.datetime.fromisoformat(period['startTime']).timestamp(),
                endTime          = datetime.datetime.fromisoformat(period['endTime']).timestamp(),
                isDaytime        = period['isDaytime'],
                outTemp          = period['temperature'],
                outTempTrend     = period['temperatureTrend'],
                windSpeed        = windSpeed,
                windDir          = NWSPoller.translate_wind_dir(period['windDirection']),
                iconUrl          = period['icon'],
                shortForecast    = period['shortForecast'],
                detailedForecast = period['detailedForecast'])
            yield record

    @staticmethod
    def translate_wind_dir(wdir_str):
        if wdir_str == 'N':
            return 0.0
        elif wdir_str == 'NNE':
            return 22.5 
        elif wdir_str == 'NE':
            return 45.0
        elif wdir_str == 'ENE':
            return 77.5
        elif wdir_str == 'E':
            return 90.0
        elif wdir_str == 'ESE':
            return 112.5
        elif wdir_str == 'SE':
            return 135.0
        elif wdir_str == 'SSE':
            return 157.5
        elif wdir_str == 'S':
            return 180.0
        elif wdir_str == 'SSW':
            return 202.5
        elif wdir_str == 'SW':
            return 225
        elif wdir_str == 'WSW':
            return 247.5
        elif wdir_str == 'W':
            return 270
        elif wdir_str == 'WNW':
            return 292.5
        elif wdir_str == 'NW':
            return 315
        elif wdir_str == 'NNW':
            return 337.5
        else:
            return None

class NWSForecastVariables(SearchList):
    def __init__(self, generator):
        SearchList.__init__(self, generator)

        self.formatter = generator.formatter
        self.converter = generator.converter

        nws_dict = generator.config_dict.get('NWS', {})
        self.binding = nws_dict.get('data_binding', 'nws_binding')

    def get_extension_list(self, timespan, db_lookup):
        return [{'nwsforecast': self}]

    def hourly_forecasts(self, max_forecasts:Optional[int]=None):
        return self.forecasts(ForecastType.HOURLY, max_forecasts)

    def daily_forecasts(self, max_forecasts:Optional[int]=None):
        return self.forecasts(ForecastType.DAILY, max_forecasts)

    def alerts(self):
        """Returns the latest alert records."""
        raw_rows = self.getLatestForecastRows(ForecastType.ALERTS)

        rows = []
        for raw_row in raw_rows:
            row = {}
            time_group = weewx.units.obs_group_dict['dateTime']
            time_units = weewx.units.USUnits[time_group]
            row['effective']   = weewx.units.ValueHelper((raw_row['generatedTime'], time_units, time_group))
            row['onset']       = weewx.units.ValueHelper((raw_row['startTime'], time_units, time_group))
            row['ends']        = weewx.units.ValueHelper((raw_row['endTime'], time_units, time_group))
            row['event']       = raw_row['name']
            row['headline']    = raw_row['shortForecast']
            row['description'] = raw_row['detailedForecast']
            rows.append(row)
        return rows

    def alert_count(self) -> int:
        return len(self.getLatestForecastRows(ForecastType.ALERTS))

    def forecasts(self, forecast_type: ForecastType, max_forecasts:Optional[int]=None):
        """Returns the latest hourly forecast records."""
        rows = self.getLatestForecastRows(forecast_type, max_forecasts)
        for row in rows:
            time_group = weewx.units.obs_group_dict['dateTime']
            time_units = weewx.units.USUnits[time_group]

            temp_group = weewx.units.obs_group_dict['outTemp']
            temp_units = weewx.units.USUnits[temp_group]

            wind_speed_group = weewx.units.obs_group_dict['windSpeed']
            wind_speed_units = weewx.units.USUnits[wind_speed_group]

            wind_dir_group = weewx.units.obs_group_dict['windDir']
            wind_dir_units = weewx.units.USUnits[wind_dir_group]

            row['dateTime'] = weewx.units.ValueHelper((row['dateTime'], time_units, time_group))
            row['generatedTime'] = weewx.units.ValueHelper((row['generatedTime'], time_units, time_group))
            row['startTime'] = weewx.units.ValueHelper((row['startTime'], time_units, time_group))
            row['endTime'] = weewx.units.ValueHelper((row['endTime'], time_units, time_group))
            row['outTemp'] = weewx.units.ValueHelper((row['outTemp'], temp_units, temp_group))
            row['windSpeed'] = weewx.units.ValueHelper((row['windSpeed'], wind_speed_units, wind_speed_group))
            row['windDir'] = weewx.units.ValueHelper((row['windDir'], wind_dir_units, wind_dir_group))
        return rows

    def getLatestForecastRows(self, forecast_type: ForecastType, max_forecasts: Optional[int]=None):
        """get the latest hourly forecast"""
        dict = weewx.manager.get_manager_dict(self.generator.config_dict['DataBindings'],
                                                  self.generator.config_dict['Databases'],self.binding)
        with weewx.manager.open_manager(dict) as dbm:
            # Latest insert date
            select = "SELECT dateTime, interval, usUnits, generatedTime, number, name, startTime, endTime, isDaytime, outTemp, outTempTrend, windSpeed, windDir, iconUrl, shortForecast, detailedForecast FROM archive WHERE dateTime = (SELECT MAX(dateTime) FROM archive WHERE interval = %d) AND interval = %d ORDER BY startTime" % (NWS.get_interval(forecast_type), NWS.get_interval(forecast_type))
            try:
                records = []
                columns = dbm.connection.columnsOf(dbm.table_name)
                forecast_count = 0
                for row in dbm.genSql(select):
                    # Only include if record hasn't expired (row[7] is endTime) and max_forecasts hasn't been exceeded.
                    if time.time() < row[7] and (max_forecasts is None or forecast_count < max_forecasts):
                        forecast_count += 1
                        record = {}
                        for i, f in enumerate(columns):
                            record[f] = row[i]
                        records.append(record)
                return records
            except Exception as e:
                log.info('%s failed with %s.' % (select, e))
        return []

    @staticmethod
    def top_of_current_hour():
        return int(time.time() / 3600) * 3600

def pretty_print(record):
    print('interval        : %d' % record.interval)
    print('usUnits         : %s' % record.usUnits)
    print('generatedTime   : %s' % timestamp_to_string(record.generatedTime))
    print('number          : %d' % record.number)
    print('name            : %s' % record.name)
    print('startTime       : %s' % timestamp_to_string(record.startTime))
    print('endTime         : %s' % timestamp_to_string(record.endTime))
    print('isDaytime       : %d' % record.isDaytime)
    print('outTemp         : %f' % record.outTemp)
    print('outTempTrend    : %s' % record.outTempTrend)
    print('windSpeed       : %f' % record.windSpeed)
    print('windDir         : %f' % record.windDir)
    print('iconUrl         : %s' % record.iconUrl)
    print('shortForecast   : %s' % record.shortForecast)
    print('detailedForecast: %s' % record.detailedForecast)

if __name__ == '__main__':
    cfg = Configuration(
        lock              = threading.Lock(),
        alerts            = [],
        dailyForecasts    = [],
        hourlyForecasts   = [],
        alertsUrl         = None,
        dailyForecastUrl  = None,
        hourlyForecastUrl = None,
        latitude          = 37.431495,
        longitude         = -122.110937,
        timeout_secs      = 5,
        archive_interval  = 300,
        user_agent        = '(weewx-nws test run, weewx-nws-developer)',
        retry_wait_secs   = 5,
        )

    j = NWSPoller.request_forecast(cfg, ForecastType.HOURLY)
    for record in NWSPoller.compose_records(j, ForecastType.HOURLY):
        pretty_print(record)
        print('------------------------')

    j = NWSPoller.request_forecast(cfg, ForecastType.DAILY)
    for record in NWSPoller.compose_records(j, ForecastType.DAILY):
        pretty_print(record)
        print('------------------------')

    j = NWSPoller.request_forecast(cfg, ForecastType.ALERTS)
    for record in NWSPoller.compose_records(j, ForecastType.ALERTS):
        pretty_print(record)
        print('------------------------')
