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
from typing import Any, Dict, IO, Iterator, List, Optional, Tuple

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

WEEWX_NWS_VERSION = "1.0"

if sys.version_info[0] < 3:
    raise weewx.UnsupportedFeature(
        "weewx-nws requires Python 3, found %s" % sys.version_info[0])

if weewx.__version__ < "4":
    raise weewx.UnsupportedFeature(
        "WeeWX 4 is required, found %s" % weewx.__version__)

# Schema for nws database (nws.sdb).
table = [
    ('dateTime',         'INTEGER NOT NULL'), # When forecast/alert was inserted.
    ('interval',         'INTEGER NOT NULL'), # Always 60 for hourly,  720 for twelve-hour, 0 for alerts
    ('latitude',         'STRING NOT NULL'),   # The latitude used to request the forecast
    ('longitude',        'STRING NOT NULL'),   # The longitude used to request the forecast
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
    ('iconUrl',          'STRING NOT NULL'),
    ('shortForecast',    'STRING NOT NULL'), # For alrerts, holds the headline
    ('detailedForecast', 'STRING'),          # For alerts, holds the description
    ]

schema = {
    'table'         : table,
}

class ForecastType(Enum):
    HOURLY      = 1
    TWELVE_HOUR = 2
    ALERTS      = 3

@dataclass
class Forecast:
    interval        : int # 0 for ALERTS, 60 for HOURLY, 720 for TWELVE_HOUR
    latitude        : str
    longitude       : str
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
    iconUrl         : str
    shortForecast   : str    # For alerts, holds the headline
    detailedForecast: Optional[str] # For alerts,hold the description

@dataclass
class Configuration:
    lock                 : threading.Lock
    alertsAllClear       : bool           # Controlled by lock
    alerts               : List[Forecast] # Controlled by lock
    twelveHourForecasts  : List[Forecast] # Controlled by lock
    hourlyForecasts      : List[Forecast] # Controlled by lock
    alertsUrl            : Optional[str]  # Controlled by lock
    twelveHourForecastUrl: Optional[str]  # Controlled by lock
    hourlyForecastUrl    : Optional[str]  # Controlled by lock
    latitude             : str            # Immutable
    longitude            : str            # Immutable
    timeout_secs         : int            # Immutable
    archive_interval     : int            # Immutable
    user_agent           : str            # Immutable
    poll_secs            : int            # Immutable
    retry_wait_secs      : int            # Immutable
    days_to_keep         : int            # Immutable

class NWS(StdService):
    """Fetch NWS Forecasts"""
    def __init__(self, engine, config_dict):
        super(NWS, self).__init__(engine, config_dict)
        log.info("Service version is %s." % WEEWX_NWS_VERSION)

        self.config_dict = config_dict
        self.nws_config_dict = config_dict.get('NWS', {})
        self.engine = engine

        latitude, longitude = NWS.get_lat_long(self.config_dict)
        if latitude is None or longitude is None:
            log.error("Could not determine station's latitude and longitude.")
            return

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
            lock                  = threading.Lock(),
            alertsAllClear        = False,
            alerts                = [],
            twelveHourForecasts   = [],
            hourlyForecasts       = [],
            twelveHourForecastUrl = None,
            hourlyForecastUrl     = None,
            alertsUrl             = None,
            latitude              = latitude,
            longitude             = longitude,
            timeout_secs          = to_int(self.nws_config_dict.get('timeout_secs', 5)),
            archive_interval      = to_int(config_dict['StdArchive']['archive_interval']),
            user_agent            = self.nws_config_dict.get('User-Agent', '(<weather-site>, <contact>)'),
            poll_secs             = to_int(self.nws_config_dict.get('poll_secs', 1800)),
            retry_wait_secs       = to_int(self.nws_config_dict.get('retry_wait_secs', 30)),
            days_to_keep          = to_int(self.nws_config_dict.get('days_to_keep', 90)),
            )
        log.info('latitude        : %s' % self.cfg.latitude)
        log.info('longitude       : %s' % self.cfg.longitude)
        log.info('timeout_secs    : %d' % self.cfg.timeout_secs)
        log.info('archive_interval: %d' % self.cfg.archive_interval)
        log.info('user_agent      : %s' % self.cfg.user_agent)
        log.info('poll_secs       : %d' % self.cfg.poll_secs)
        log.info('retry_wait_secs : %d' % self.cfg.retry_wait_secs)
        log.info('days_to_keep    : %d' % self.cfg.days_to_keep)

        # If the machine was just rebooted, a temporary failure in name
        # resolution is likely.  As such, try three times to get
        # request urls.
        for i in range(3):
            if NWSPoller.request_urls(self.cfg):
                break
            if i < 2:
                time.sleep(5)

        # At startup, attempt to get the latest forecasts.
        if NWSPoller.populate_forecast(self.cfg, ForecastType.TWELVE_HOUR):
            self.saveForecastsToDB(ForecastType.TWELVE_HOUR)
        if NWSPoller.populate_forecast(self.cfg, ForecastType.HOURLY):
            self.saveForecastsToDB(ForecastType.HOURLY)
        if NWSPoller.populate_forecast(self.cfg, ForecastType.ALERTS):
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
        self.saveForecastsToDB(ForecastType.TWELVE_HOUR)
        self.saveForecastsToDB(ForecastType.HOURLY)
        self.saveForecastsToDB(ForecastType.ALERTS)

    def saveForecastsToDB(self, forecast_type: ForecastType):
        try:
            now = int(time.time() + 0.5)
            with self.cfg.lock:
                if forecast_type == ForecastType.TWELVE_HOUR:
                    bucket = self.cfg.twelveHourForecasts
                elif forecast_type == ForecastType.HOURLY:
                    bucket = self.cfg.hourlyForecasts
                else:       # ForecastType.ALERTS
                    bucket = self.cfg.alerts
                if len(bucket) != 0:
                    ts = NWS.get_archive_interval_timestamp(self.cfg.archive_interval)
                    # Never write the same forecast twice.  This is determined by generatedTime
                    if not self.forecast_in_db(forecast_type, bucket[0].generatedTime):
                        for record in bucket:
                            self.save_forecast(NWS.convert_to_json(record, ts))
                        log.info('Saved %d %s records.' % (len(bucket), forecast_type))
                        self.delete_old_forecasts(forecast_type);
                    else:
                        log.debug('Forecast %s, generated %s, already exists in the database.' % (forecast_type, timestamp_to_string(bucket[0].generatedTime)))
                    bucket.clear()
                elif forecast_type == ForecastType.ALERTS and self.cfg.alertsAllClear:
                    # No alert records and all clear has been signaled (no alerts returned).
                    # delete all alerts and reset all clear
                    self.cfg.alertsAllClear = False
                    self.delete_all_alerts()
        except Exception as e:
            # Include a stack traceback in the log:
            # but eat this exception as we don't want to bring down weewx
            log.error('saveForedcastsToDB(%s): %s' % (forecast_type, e))
            weeutil.logger.log_traceback(log.critical, "    ****  ")

    def forecast_in_db(self, forecast_type: ForecastType, generatedTime: int):
        try:
            dbmanager = self.engine.db_binder.get_manager(self.data_binding)
            select = "SELECT generatedTime FROM archive WHERE interval = %d AND generatedTime = %d LIMIT 1" % (
                NWS.get_interval(forecast_type), generatedTime)
            log.debug('Checking if forecast already in db: select: %s.' % select)
            return dbmanager.getSql(select) is not None
        except Exception as e:
            log.error('forecast_in_db(%s, %d) failed with %s.' % (forecast_type, generatedTime, e))
            weeutil.logger.log_traceback(log.critical, "    ****  ")

    def delete_all_alerts(self):
        try:
           dbmanager = self.engine.db_binder.get_manager(self.data_binding)
           # Only delete if there are actually alerts in the table (to avoid confusing deletes in the log).
           try:
               select = 'SELECT COUNT(dateTime) FROM archive WHERE interval = %d' % NWS.get_interval(ForecastType.ALERTS)
               log.debug('Checking if there are any alerts in the archive to delete: select: %s.' % select)
               row = dbmanager.getSql(select)
           except Exception as e:
               log.error('delete_all_alerts: %s failed with %s.' % (select, e))
               weeutil.logger.log_traceback(log.critical, "    ****  ")
               return
           if row[0] != 0:
               delete = "DELETE FROM archive WHERE interval = %d" % NWS.get_interval(ForecastType.ALERTS)
               log.info('Pruning ForecastType.ALERTS')
               dbmanager.getSql(delete)
        except Exception as e:
           log.error('delete_all_alerts: %s failed with %s.' % (delete, e))
           weeutil.logger.log_traceback(log.critical, "    ****  ")

    def delete_old_forecasts(self, forecast_type: ForecastType):
        if forecast_type == ForecastType.ALERTS:
            return    # Alerts are not deleted here; rather they are deleted on cfg.alertsAllClear
        if self.cfg.days_to_keep == 0:
            log.info('days_to_keep set to zero, the database will not be pruned.')
        else:
            try:
               n_days_ago: int = int(time.time() - self.cfg.days_to_keep * 24 * 3600)
               dbmanager = self.engine.db_binder.get_manager(self.data_binding)
               delete = "DELETE FROM archive WHERE (interval = %d AND dateTime < %d) OR latitude != %s OR longitude != %s" % (
                   NWS.get_interval(forecast_type), n_days_ago, self.cfg.latitude, self.cfg.longitude)
               log.info('Pruning %s rows older than %s.' % (forecast_type, timestamp_to_string(n_days_ago)))
               dbmanager.getSql(delete)
            except Exception as e:
               log.error('delete_old_forecasts(%s): %s failed with %s.' % (forecast_type, delete, e))
               weeutil.logger.log_traceback(log.critical, "    ****  ")

    @staticmethod
    def get_lat_long(config_dict) -> Tuple[str, str]:
        # If specified, get lat/long, else get it from station.
        nws_config_dict = config_dict.get('NWS', {})
        latitude: str = nws_config_dict.get('latitude')
        if latitude is None:
            latitude = config_dict['Station'].get('latitude', None)
        longitude: str = nws_config_dict.get('longitude')
        if longitude is None:
            longitude = config_dict['Station'].get('longitude', None)
        return (latitude, longitude)

    @staticmethod
    def get_archive_interval_timestamp(archive_interval: int) -> int:
        now_ts = int(time.time() + 0.5)
        return int(now_ts / archive_interval) * archive_interval

    @staticmethod
    def convert_to_json(record, ts):
        j = {}
        j['dateTime']         = ts
        j['interval']         = record.interval
        j['latitude']         = record.latitude
        j['longitude']        = record.longitude
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
        elif forecast_type == ForecastType.TWELVE_HOUR:
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
            log.error('get_latest_type(%s): %s failed with %s.' % (forecast_type, select, e))
            weeutil.logger.log_traceback(log.critical, "    ****  ")
            return 0

    def save_forecast(self, record):
        """save data to database"""
        dbmanager = self.engine.db_binder.get_manager(self.data_binding)
        dbmanager.addRecord(record)

    def select_forecasts(self, forecast_type: ForecastType, max_forecasts: int=None) -> List[Dict[str, Any]]:
        # Used for testing.
        dbmanager = self.engine.db_binder.get_manager(self.data_binding)
        return NWSForecastVariables.fetch_records(dbmanager, forecast_type, self.cfg.latitude, self.cfg.longitude, max_forecasts)

class NWSPoller:
    def __init__(self, cfg: Configuration):
        self.cfg = cfg

    def poll_nws(self) -> None:
        on_retry          : bool = False
        twelve_hour_failed: bool = False
        hourly_failed     : bool = False
        alerts_failed     : bool = False
        while True:
            try:
                if not on_retry or twelve_hour_failed:
                    success = NWSPoller.populate_forecast(self.cfg, ForecastType.TWELVE_HOUR)
                    if success:
                        twelve_hour_failed = False
                    else:
                        twelve_hour_failed = True
                if not on_retry or hourly_failed:
                    success = NWSPoller.populate_forecast(self.cfg, ForecastType.HOURLY)
                    if success:
                        hourly_failed = False
                    else:
                        hourly_failed = True
                if not on_retry or alerts_failed:
                    success = NWSPoller.populate_forecast(self.cfg, ForecastType.ALERTS)
                    if success:
                        alerts_failed = False
                    else:
                        alerts_failed = True
                if twelve_hour_failed or hourly_failed or alerts_failed:
                    if twelve_hour_failed:
                        log.error('poll_nws: ForecastType.TWELVE_HOUR request failed.  Will retry in %d seconds.' % self.cfg.retry_wait_secs)
                    if hourly_failed:
                        log.error('poll_nws: ForecastType.HOURLY request failed.  Will retry in %d seconds.' % self.cfg.retry_wait_secs)
                    if alerts_failed:
                        log.error('poll_nws: ForecastType.ALERTS request failed.  Will retry in %d seconds.' % self.cfg.retry_wait_secs)
                    on_retry = True
                    # TODO: Perhaps back off on retries.
                    time.sleep(self.cfg.retry_wait_secs)
                else:
                    on_retry = False
                    sleep_time = NWSPoller.time_to_next_poll(self.cfg.poll_secs)
                    log.debug('poll_nws: Sleeping for %f seconds.' % sleep_time)
                    time.sleep(sleep_time)
            except Exception as e:
                log.error('poll_nws: Encountered exception. Retrying in %d seconds. exception: %s' % (self.cfg.retry_wait_secs, e))
                time.sleep(self.cfg.retry_wait_secs)

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
                elif forecast_type == ForecastType.TWELVE_HOUR:
                    cfg.twelveHourForecasts.clear()
                else:
                    cfg.alerts.clear()
                    cfg.alertsAllClear = True    # Will be set to False below if there are any alerts present
                for record in NWSPoller.compose_records(j, forecast_type, cfg.latitude, cfg.longitude):
                    log.debug('NWSPoller: poll_nws: adding %s forecast(%s) to array.' % (forecast_type, record))
                    if forecast_type == ForecastType.HOURLY:
                        cfg.hourlyForecasts.append(record)
                    elif forecast_type == ForecastType.TWELVE_HOUR:
                        cfg.twelveHourForecasts.append(record)
                    else: # Alerts
                        cfg.alerts.append(record)
                        cfg.alertsAllClear = False    # Alerts will not be deleted from db since there is an active alert.
            return True

    @staticmethod
    def time_to_next_poll(poll_secs: int):
        time_of_next_poll = int(time.time() / poll_secs) * poll_secs + poll_secs
        return time_of_next_poll - time.time()

    @staticmethod
    def request_urls(cfg) -> bool:
        try:
            # Need to fetch (and cache) the forecast URLs
            url = 'https://api.weather.gov/points/%s,%s' % (cfg.latitude, cfg.longitude)
            session= requests.Session()
            headers = {'User-Agent': cfg.user_agent}
            log.debug('request_urls: headers: %s' % headers)
            log.info('Downloading URLs from %s' % url)
            response: requests.Response = session.get(url=url, headers=headers, timeout=cfg.timeout_secs)
            if response.status_code == 404:
                #{
                #    "correlationId": "ac04ca11-ce4d-464e-8cef-602497b10aa1",
                #    "title": "Data Unavailable For Requested Point",
                #    "type": "https://api.weather.gov/problems/InvalidPoint",
                #    "status": 404,
                #    "detail": "Unable to provide data for requested point -20.9512,55.3085",
                #    "instance": "https://api.weather.gov/requests/ac04ca11-ce4d-464e-8cef-602497b10aa1"
                #}
                d = response.json()
                correlationId: str = d.get('correlationId')
                title: str = d.get('title')
                type_str: str = d.get('type')
                status: str = d.get('status')
                detail: str = d.get('detail')
                instance: str = d.get('instance')
                if title is not None:
                    log.info(correlationId)
                    log.info(title)
                    log.info(type_str)
                    log.info(status)
                    log.info(detail)
                    log.info(instance)
                else:
                    log.info('404 error for url: %s' % url)
                return False
            response.raise_for_status()
            log.debug('request_urls: %s returned %r' % (url, response))
            if response:
                j: Dict[str, Any] = response.json()
                log.debug('id: %s' % j['id'])
                log.debug('type: %s' % j['type'])
                log.debug('geometry: %s' % j['geometry'])
                for k in j['properties']:
                    log.debug('properties key:  %s, value: %s' % (k, j['properties'][k]))
                with cfg.lock:
                    cfg.twelveHourForecastUrl = j['properties']['forecast']
                    cfg.hourlyForecastUrl     = j['properties']['forecastHourly']
                    cfg.alertsUrl             = 'https://api.weather.gov/alerts/active?point=%s,%s' % (cfg.latitude, cfg.longitude)
                    log.info('request_urls: Cached twelveHourForecastUrl: %s' % cfg.twelveHourForecastUrl)
                    log.info('request_urls: Cached hourlyForecastUrl: %s' % cfg.hourlyForecastUrl)
                    log.info('request_urls: Cached alertsUrl: %s' % cfg.alertsUrl)
                return True
            else:
                return False
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            log.info('request_urls: Attempt to fetch from: %s failed: %s.' % (url, e))
            return False
        except Exception as e:
            # Unexpected exceptions need a stack track to diagnose.
            log.error('request_urls: Attempt to fetch from: %s failed: %s.' % (url, e))
            weeutil.logger.log_traceback(log.critical, "    ****  ")
            return False

    @staticmethod
    def request_forecast(cfg, forecast_type: ForecastType):
        log.debug('request_forecast(%s): start' % forecast_type)
        with cfg.lock:
            if forecast_type == ForecastType.HOURLY:
                forecastUrl = cfg.hourlyForecastUrl
            elif forecast_type == ForecastType.TWELVE_HOUR:
                forecastUrl = cfg.twelveHourForecastUrl
            else:
                forecastUrl = cfg.alertsUrl
        log.debug('request_forecast(%s): forecastUrl %s' % (forecast_type, forecastUrl))
        if forecastUrl == None:
            if not NWSPoller.request_urls(cfg):
                log.info('request_forecast(%s): skipping attempt since request_urls was unsuccessful.' % forecast_type)
                return None
        with cfg.lock:
            if forecast_type == ForecastType.HOURLY:
                forecastUrl = cfg.hourlyForecastUrl
            elif forecast_type == ForecastType.TWELVE_HOUR:
                forecastUrl = cfg.twelveHourForecastUrl
            else:
                forecastUrl = cfg.alertsUrl
        log.debug('request_forecast(%s): forecastUrl %s' % (forecast_type, forecastUrl))
        try:
            log.info('Downloading %s forecasts from %s.' % (forecast_type, forecastUrl))
            session= requests.Session()
            headers = {'User-Agent': cfg.user_agent}
            response: requests.Response = session.get(url=forecastUrl, headers=headers, timeout=cfg.timeout_secs)
            return response.json()
        except requests.exceptions.Timeout as e:
            log.error('request_forecast(%s): Attempt to fetch from: %s failed: %s.' % (forecast_type, forecastUrl, e))
            return None
        except Exception as e:
            # Unexpected exceptions need a stack track to diagnose.
            log.error('request_forecast(%s): Attempt to fetch from: %s failed: %s.' % (forecast_type, forecastUrl, e))
            weeutil.logger.log_traceback(log.critical, "    ****  ")
            return None

    @staticmethod
    def compose_alert_records(j, latitude: str, longitude: str):
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
                latitude         = latitude,
                longitude        = longitude,
                usUnits          = weewx.US,                # Dummy
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
    def compose_records(j, forecast_type: ForecastType, latitude: str, longitude: str):
        if forecast_type == ForecastType.ALERTS:
            yield from NWSPoller.compose_alert_records(j, latitude, longitude)
            return

        # 2020-05-18T22:02:26+00:00
        tzinfos = {'UTC': tz.gettz("UTC")}
        updateTime = parse(j['properties']['updateTime'], tzinfos=tzinfos).timestamp()

        units = j['properties']['units']
        if units == 'us':
            units = weewx.US
        else:
            units = weewx.METRIC

        for period in j['properties']['periods']:
            windSpeedStr = period['windSpeed']
            windSpeedArray = windSpeedStr.split()
            windSpeed = to_int(windSpeedArray[0])
            windSpeedUnit = windSpeedArray[1]
            record = Forecast(
                interval         = NWS.get_interval(forecast_type),
                latitude         = latitude,
                longitude        = longitude,
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

        self.latitude, self.longitude = NWS.get_lat_long(generator.config_dict)

    def get_extension_list(self, timespan, db_lookup):
        return [{'nwsforecast': self}]

    def hourly_forecasts(self, max_forecasts:Optional[int]=None):
        return self.forecasts(ForecastType.HOURLY, max_forecasts)

    def twelve_hour_forecasts(self, max_forecasts:Optional[int]=None):
        return self.forecasts(ForecastType.TWELVE_HOUR, max_forecasts)

    def alerts(self):
        """Returns the latest alert records."""
        raw_rows = self.getLatestForecastRows(ForecastType.ALERTS)

        rows = []
        for raw_row in raw_rows:
            row = {}
            time_group = weewx.units.obs_group_dict['dateTime']
            time_units = weewx.units.USUnits[time_group]
            row['latitude']    = raw_row['latitude']
            row['longitude']   = raw_row['longitude']
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

    def getLatestForecastRows(self, forecast_type: ForecastType, max_forecasts: Optional[int]=None) -> List[Dict[str, Any]]:
        """get the latest hourly forecast"""
        try:
            dict = weewx.manager.get_manager_dict(self.generator.config_dict['DataBindings'],
                                                  self.generator.config_dict['Databases'],self.binding)
            with weewx.manager.open_manager(dict) as dbm:
                return NWSForecastVariables.fetch_records(dbm, forecast_type, self.latitude, self.longitude, max_forecasts)
        except Exception as e:
            log.error('getLatestForecastRows: %s' % e)
            weeutil.logger.log_traceback(log.critical, "    ****  ")
            return []

    @staticmethod
    def fetch_records(dbm: weewx.manager.Manager, forecast_type: ForecastType, latitude, longitude, max_forecasts: int=None) -> List[Dict[str, Any]]:
        # Fetch last records inserted for this forecast_type
        select = "SELECT dateTime, interval, latitude, longitude, usUnits, generatedTime, number, name, startTime, endTime, isDaytime, outTemp, outTempTrend, windSpeed, windDir, iconUrl, shortForecast, detailedForecast FROM archive WHERE dateTime = (SELECT MAX(dateTime) FROM archive WHERE interval = %d AND latitude = %s AND longitude = %s) AND interval = %d AND latitude = %s AND longitude = %s ORDER BY startTime" % (NWS.get_interval(forecast_type), latitude, longitude, NWS.get_interval(forecast_type), latitude, longitude)
        try:
            records = []
            forecast_count = 0
            for row in dbm.genSql(select):
                END_TIME = 9
                # Only include if record hasn't expired (row[END_TIME] is endTime) and max_forecasts hasn't been exceeded.
                if time.time() < row[END_TIME] and (max_forecasts is None or forecast_count < max_forecasts):
                    forecast_count += 1
                    record = {}

                    record['dateTime'] = row[0]
                    record['interval'] = row[1]
                    record['latitude'] = row[2]
                    record['longitude'] = row[3]
                    record['usUnits'] = row[4]
                    record['generatedTime'] = row[5]
                    record['number'] = row[6]
                    record['name'] = row[7]
                    record['startTime'] = row[8]
                    record['endTime'] = row[9]
                    record['isDaytime'] = row[10]
                    record['outTemp'] = row[11]
                    record['outTempTrend'] = row[12]
                    record['windSpeed'] = row[13]
                    record['windDir'] = row[14]
                    record['iconUrl'] = row[15]
                    record['shortForecast'] = row[16]
                    record['detailedForecast'] = row[17]

                    records.append(record)
            return records
        except Exception as e:
            log.error('%s failed with %s.' % (select, e))
            weeutil.logger.log_traceback(log.critical, "    ****  ")
            return []

if __name__ == '__main__':
    usage = """%prog [options] [--help]"""

    import weeutil.logger

    def main():
        import optparse
        import weecfg

        parser = optparse.OptionParser(usage=usage)
        parser.add_option('--binding', dest="binding", metavar="BINDING",
                          default='nws_binding',
                          help="The data binding to use. Default is 'nws_binding'.")
        parser.add_option('--test-requester', dest='testreq', action='store_true',
                          help='Test the forecast requester.  Requires specify --type, --latitude, --longitude.')
        parser.add_option('--type', dest='ty',
                          help='ALERTS|TWELVE_HOUR|HOURLY')
        parser.add_option('--nws-database', dest='db',
                          help='Location of nws.sdb file (only works with sqlite3).')
        parser.add_option('--test-service', dest='testserv', action='store_true',
                          help='Test the NWS service.  Requires --latitude and --longitude.')
        parser.add_option('--latitude', type='float', dest='lat',
                          help='The latitude to use when testing the service.')
        parser.add_option('--longitude', type='float', dest='long',
                          help='The longitude to use when testing the service.')
        parser.add_option('--view-criterion', dest='view_criterion',
                          help='ALL|LATEST|SUMMARY')
        parser.add_option('--view-forecasts', dest='view', action='store_true',
                          help='View forecast records.  Must specify --nws-database, --type and --view-criterion.')
        (options, args) = parser.parse_args()

        weeutil.logger.setup('nws', {})

        if options.testreq:
            forecast_type = decode_forecast_type(options.ty)
            if forecast_type == None:
                parser.error('--type must be one of: ALERTS|TWELVE_HOUR|HOURLY')
            if not options.lat or not options.long:
                parser.error('--test-service requires --latitude and --longitude arguments')
            test_requester(forecast_type, options.lat, options.long)

        if options.testserv:
            if not options.lat or not options.long:
                parser.error('--test-service requires --latitude and --longitude arguments')
            test_service(options.lat, options.long)

        if options.view:
            if not options.db:
                parser.error('--test-requester requires --nws-database argument')

            forecast_type = decode_forecast_type(options.ty)
            if forecast_type == None:
                parser.error('--type must be one of: ALERTS|TWELVE_HOUR|HOURLY')

            criterion = decode_criterion(options.view_criterion)
            if criterion == None:
                parser.error('--vew-criterion must be one of: ALL|LATEST|SUMMARY')

            view_sqlite_database(options.db, forecast_type, criterion)

    def decode_forecast_type(ty: str) -> Optional[ForecastType]:
        if ty.upper() == 'ALERTS':
            return ForecastType.ALERTS
        elif ty.upper() == 'TWELVE_HOUR':
            return ForecastType.TWELVE_HOUR
        elif ty.upper() == 'HOURLY':
            return ForecastType.HOURLY
        else:
            return None

    class Criterion(Enum):
        ALL     = 1
        LATEST  = 2
        SUMMARY = 3

    def decode_criterion(cr: str) -> Optional[Criterion]:
        if cr.upper() == 'ALL':
            return Criterion.ALL
        elif cr.upper() == 'LATEST':
            return Criterion.LATEST
        elif cr.upper() == 'SUMMARY':
            return Criterion.SUMMARY
        else:
            return None

    def test_requester(forecast_type: ForecastType, lat: float, long: float) -> None:
        cfg = Configuration(
            lock                  = threading.Lock(),
            alertsAllClear        = False,
            alerts                = [],
            twelveHourForecasts   = [],
            hourlyForecasts       = [],
            alertsUrl             = None,
            twelveHourForecastUrl = None,
            hourlyForecastUrl     = None,
            latitude              = str(lat),
            longitude             = str(long),
            timeout_secs          = 5,
            archive_interval      = 300,
            user_agent            = '(weewx-nws test run, weewx-nws-developer)',
            poll_secs             = 3600,
            retry_wait_secs       = 30,
            days_to_keep          = 90,
            )

        j = NWSPoller.request_forecast(cfg, forecast_type)
        for forecast in NWSPoller.compose_records(j, forecast_type, cfg.latitude, cfg.longitude):
            pretty_print_forecast(forecast)
            print('------------------------')

    def test_service(lat: float, long: float):
        from weewx.engine import StdEngine
        from tempfile import NamedTemporaryFile

        with NamedTemporaryFile() as temp_file:
            config = configobj.ConfigObj({
                'Station': {
                    'station_type': 'Simulator',
                    'altitude' : [0, 'foot'],
                    'latitude' : lat,
                    'longitude': long},
                'Simulator': {
                    'driver': 'weewx.drivers.simulator',
                    'mode': 'simulator'},
                'StdArchive': {
                    'archive_interval': 300},
                'NWS': {
                    'binding': 'nws_binding'},
                'DataBindings': {
                    'nws_binding': {
                        'database': 'nws_sqlite',
                        'manager': 'weewx.manager.Manager',
                        'table_name': 'archive',
                        'schema': 'user.nws.schema'}},
                'Databases': {
                    'nws_sqlite': {
                        'database_name': temp_file.name,
                        'database_type': 'SQLite'}},
                'Engine': {
                    'Services': {
                        'data_services': 'user.nws.NWS'}},
                'DatabaseTypes': {
                    'SQLite': {
                        'driver': 'weedb.sqlite'}}})
            engine = StdEngine(config)
            nws = NWS(engine, config)
            for record in nws.select_forecasts(ForecastType.TWELVE_HOUR):
                pretty_print_record(record)
                print('------------------------')
            for record in nws.select_forecasts(ForecastType.HOURLY):
                pretty_print_record(record)
                print('------------------------')
            for record in nws.select_forecasts(ForecastType.ALERTS):
                pretty_print_record(record)
                print('------------------------')

    def view_sqlite_database(dbfile: str, forecast_type: ForecastType, criterion: Criterion):
        try:
            import sqlite3
        except:
            print('Could not import sqlite3.')
            return
        conn = sqlite3.connect(dbfile)
        if criterion == Criterion.ALL or criterion == Criterion.LATEST:
            print_sqlite_records(conn, dbfile, forecast_type, criterion)
        else:   # SUMMMARY
            print_sqlite_summary(conn, dbfile, forecast_type)

    def print_sqlite_records(conn, dbfile: str, forecast_type: ForecastType, criterion: Criterion):
        if criterion == Criterion.ALL:
            select = "SELECT dateTime, interval, latitude, longitude, usUnits, generatedTime, number, name, startTime, endTime, isDaytime, outTemp, outTempTrend, windSpeed, windDir, iconUrl, shortForecast, detailedForecast FROM archive WHERE interval = %d ORDER BY dateTime, number" % NWS.get_interval(forecast_type)
        elif criterion == Criterion.LATEST:
            select = "SELECT dateTime, interval, latitude, longitude, usUnits, generatedTime, number, name, startTime, endTime, isDaytime, outTemp, outTempTrend, windSpeed, windDir, iconUrl, shortForecast, detailedForecast FROM archive WHERE interval = %d AND dateTime = (SELECT MAX(dateTime) FROM archive WHERE interval = %d) ORDER BY number" % (NWS.get_interval(forecast_type), NWS.get_interval(forecast_type))

        for row in conn.execute(select):
            record = {}
            record['dateTime'] = row[0]
            record['interval'] = row[1]
            record['latitude'] = row[2]
            record['longitude'] = row[3]
            record['usUnits'] = row[4]
            record['generatedTime'] = row[5]
            record['number'] = row[6]
            record['name'] = row[7]
            record['startTime'] = row[8]
            record['endTime'] = row[9]
            record['isDaytime'] = row[10]
            record['outTemp'] = row[11]
            record['outTempTrend'] = row[12]
            record['windSpeed'] = row[13]
            record['windDir'] = row[14]
            record['iconUrl'] = row[15]
            record['shortForecast'] = row[16]
            record['detailedForecast'] = row[17]
            pretty_print_record(record)
            print('------------------------')

    def print_sqlite_summary(conn, dbfile: str, forecast_type: ForecastType):
        select = "SELECT dateTime, MAX(generatedTime), MIN(startTime), MAX(endTime) FROM archive WHERE interval = %d GROUP BY dateTime ORDER BY dateTime" % NWS.get_interval(forecast_type)

        # 2020-05-28 14:00:00 PDT (1590699600)
        print('%s %s %s %s' % ('Inserted'.ljust(36), 'Generated'.ljust(36), 'Start'.ljust(36), 'End'))
        for row in conn.execute(select):
            print('%s %s %s %s' % (timestamp_to_string(row[0]), timestamp_to_string(row[1]), timestamp_to_string(row[2]), timestamp_to_string(row[3])))

    def pretty_print_forecast(forecast):
        print('interval        : %d' % forecast.interval)
        print('latitude        : %s' % forecast.latitude)
        print('longitude       : %s' % forecast.longitude)
        print('usUnits         : %d' % forecast.usUnits)
        print('generatedTime   : %s' % timestamp_to_string(forecast.generatedTime))
        print('number          : %d' % forecast.number)
        print('name            : %s' % forecast.name)
        print('startTime       : %s' % timestamp_to_string(forecast.startTime))
        print('endTime         : %s' % timestamp_to_string(forecast.endTime))
        print('isDaytime       : %d' % forecast.isDaytime)
        print('outTemp         : %f' % forecast.outTemp)
        print('outTempTrend    : %s' % forecast.outTempTrend)
        print('windSpeed       : %f' % forecast.windSpeed)
        print('windDir         : %f' % forecast.windDir)
        print('iconUrl         : %s' % forecast.iconUrl)
        print('shortForecast   : %s' % forecast.shortForecast)
        print('detailedForecast: %s' % forecast.detailedForecast)

    def pretty_print_record(record):
        print('dateTime        : %s' % timestamp_to_string(record['dateTime']))
        print('interval        : %d' % record['interval'])
        print('latitude        : %s' % record['latitude'])
        print('longitude       : %s' % record['longitude'])
        print('usUnits         : %d' % record['usUnits'])
        print('gneratedTime    : %s' % timestamp_to_string(record['generatedTime']))
        print('number          : %d' % record['number'])
        print('name            : %s' % record['name'])
        print('startTime       : %s' % timestamp_to_string(record['startTime']))
        print('endTime         : %s' % timestamp_to_string(record['endTime']))
        print('isDayTime       : %d' % record['isDaytime'])
        print('outTemp         : %f' % record['outTemp'])
        print('outTempTrend    : %s' % record['outTempTrend'])
        print('windSpeed       : %f' % record['windSpeed'])
        print('windDir         : %f' % record['windDir'])
        print('iconUrl         : %s' % record['iconUrl'])
        print('shortForecast   : %s' % record['shortForecast'])
        print('detailedForecast: %s' % record['detailedForecast'])

    main()
