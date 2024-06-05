#!/usr/bin/python3
# Copyright 2020-2024 by John A Kline <john@johnkline.com>
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

"""The nws extension fetches nws one-hour and twelve-hour forecasts (and alertrs) for a station's location (as identified by lat/long].

See the README for installation and usage.
"""
import configobj
import datetime
import json
import logging
import os.path
import requests
import sys
import threading
import time

from dateutil import tz
from dateutil.parser import parse

from enum import Enum
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Tuple

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

WEEWX_NWS_VERSION = "3.0"

if sys.version_info[0] < 3:
    raise weewx.UnsupportedFeature(
        "weewx-nws requires Python 3, found %s" % sys.version_info[0])

if weewx.__version__ < "4":
    raise weewx.UnsupportedFeature(
        "WeeWX 4 is required, found %s" % weewx.__version__)

# Schema for nws database (nws.sdb).
table = [
    ('dateTime',         'INTEGER NOT NULL'), # When forecast/alert was inserted.
    ('interval',         'INTEGER NOT NULL'), # Always 60 for one-hour,  720 for twelve-hour, 0 for alerts
    ('latitude',         'STRING NOT NULL'),   # The latitude used to request the forecast
    ('longitude',        'STRING NOT NULL'),   # The longitude used to request the forecast
    ('usUnits',          'INTEGER NOT NULL'),
    ('generatedTime',    'INTEGER NOT NULL'), # When forecast was generated., For alerts, holds effective (issued)
    ('number',           'INTEGER NOT NULL'),
    ('name',             'STRING'),           # For alerts, holds event name (e.g., Heat Advisory)
    ('startTime',        'FLOAT NOT NULL'),   # For alerts, holds onset
    ('expirationTime',   'FLOAT'),            # For alerts, null for others.
    ('id',               'STRING'),           # For alerts, holds the id of the alert, null for others
    ('endTime',          'FLOAT NOT NULL'),   # For alerts, holds ends
    ('isDaytime',        'INTEGER NOT NULL'),
    ('outTemp',          'FLOAT NOT NULL'),  # Needs to be converted
    ('outTempTrend',     'STRING'),
    ('windSpeed',        'FLOAT NOT NULL'),
    ('windSpeed2',       'FLOAT'),
    ('windDir',          'FLOAT'),
    ('iconUrl',          'STRING NOT NULL'),
    ('shortForecast',    'STRING NOT NULL'), # For alerts, holds the headline
    ('detailedForecast', 'STRING'),          # For alerts, holds the description
    ('instruction',      'STRING'),          # For alerts only, holds instructions, null for others
    ('sent',             'FLOAT'),           # For alerts, holds the sent date, null for others.
    ('status',           'STRING'),          # For alerts, holds the status of the alert, null for others
    ('messageType',      'STRING'),          # For alerts, holds the category of the alert, null for others
    ('category',         'STRING'),          # For alerts, holds the severity of the alert, null for others
    ('severity',         'STRING'),          # For alerts, holds the messageType of the alert, null for others
    ('certainty',        'STRING'),          # For alerts, holds the certainty of the alert, null for others
    ('urgency',          'STRING'),          # For alerts, holds the urgency of the alert, null for others
    ('sender',           'STRING'),          # For alerts, holds the sender of the alert, null for others
    ('senderName',      'STRING'),           # For alerts, holds the senderName of the alert, null for others
    ]

schema = {
    'table'         : table,
}

class ForecastType(Enum):
    ONE_HOUR    = 1
    TWELVE_HOUR = 2
    ALERTS      = 3

@dataclass
class Forecast:
    interval        : int # 0 for ALERTS, 60 for ONE_HOUR, 720 for TWELVE_HOUR
    latitude        : str
    longitude       : str
    usUnits         : int
    generatedTime   : int # When forecast was generated.  For alerts hold effective.
    number          : int # For alerts, numbered from 0 as parsed from the XML
    name            : Optional[str] # For alerts, holds event name (e.g., Heat Advisory)
    startTime       : float  # For alerts, holds onset
    expirationTime  : Optional[float]  # Only for alerts, null for others.
    id              : Optional[str]    # Only for alerts, null for others.
    endTime         : float  # For alerts, holds ends
    isDaytime       : int
    outTemp         : float
    outTempTrend    : Optional[str]
    windSpeed       : float
    windSpeed2      : Optional[float]
    windDir         : Optional[float]
    iconUrl         : str
    shortForecast   : str    # For alerts, holds the headline
    detailedForecast: Optional[str] # For alerts,hold the description
    instruction     : Optional[str] # For alerts only
    sent            : Optional[float] # For alerts only
    status          : Optional[str] # For alerts only
    messageType     : Optional[str] # For alerts only
    category        : Optional[str] # For alerts only
    severity        : Optional[str] # For alerts only
    certainty       : Optional[str] # For alerts only
    urgency         : Optional[str] # For alerts only
    sender          : Optional[str] # For alerts only
    senderName      : Optional[str] # For alerts only

@dataclass
class SshConfiguration:
    enable        : bool
    remote_clients: List[str]
    remote_port   : int
    remote_user   : str
    remote_dir    : str
    compress      : bool
    log_success   : bool
    ssh_options   : List[str]
    timeout       : int

@dataclass
class Configuration:
    lock                          : threading.Lock
    alerts                        : List[Forecast]              # Controlled by lock
    signalDeleteAlerts            : bool                        # Controlled by lock
    lastModifiedAlerts            : Optional[datetime.datetime] # Controlled by lock
    twelveHourForecasts           : List[Forecast]              # Controlled by lock
    twelveHourForecastsJson       : str                         # Controlled by lock
    lastModifiedTwelveHour        : Optional[datetime.datetime] # Controlled by lock
    oneHourForecasts              : List[Forecast]              # Controlled by lock
    oneHourForecastsJson          : str                         # Controlled by lock
    lastModifiedOneHour           : Optional[datetime.datetime] # Controlled by lock
    alertsUrl                     : str                         # Immutable
    twelveHourForecastUrl         : Optional[str]               # Controlled by lock
    oneHourForecastUrl            : Optional[str]               # Controlled by lock
    hardCodedTwelveHourForecastUrl: Optional[str]               # Immutable
    hardCodedOneHourForecastUrl   : Optional[str]               # Immutable
    latitude                      : str                         # Immutable
    longitude                     : str                         # Immutable
    timeout_secs                  : int                         # Immutable
    archive_interval              : int                         # Immutable
    user_agent                    : str                         # Immutable
    poll_secs                     : int                         # Immutable
    alert_poll_secs               : int                         # Immutable
    retry_wait_secs               : int                         # Immutable
    alert_retry_wait_secs         : int                         # Immutable
    days_to_keep                  : int                         # Immutable
    read_from_dir                 : Optional[str]               # Immutable
    ssh_config                    : Optional[SshConfiguration]  # Immutable

@dataclass
class Point:
    lat : float
    long: float

@dataclass
class Side:
    point: List[Point]

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
            # raise Exception('nws schema mismatch: %s != %s' % (dbcol, memcol))
            log.error('You must delete the nws.sdb database and restart weewx.  It contains an old schema!')
            return

        rsync_spec_dict = self.nws_config_dict.get('RsyncSpec', {})

        self.cfg = Configuration(
            lock                           = threading.Lock(),
            alerts                         = [],
            signalDeleteAlerts             = False,
            lastModifiedAlerts             = None,
            twelveHourForecasts            = [],
            twelveHourForecastsJson        = '',
            lastModifiedTwelveHour         = None,
            oneHourForecasts               = [],
            oneHourForecastsJson           = '',
            lastModifiedOneHour            = None,
            twelveHourForecastUrl          = None,
            oneHourForecastUrl             = None,
            hardCodedTwelveHourForecastUrl = self.nws_config_dict.get('twelve_hour_forecast_url', None),
            hardCodedOneHourForecastUrl    = self.nws_config_dict.get('one_hour_forecast_url', None),
            alertsUrl                      = 'https://api.weather.gov/alerts/active?point=%s,%s' % (latitude, longitude),
            latitude                       = latitude,
            longitude                      = longitude,
            timeout_secs                   = to_int(self.nws_config_dict.get('timeout_secs', 10)),
            archive_interval               = to_int(config_dict['StdArchive']['archive_interval']),
            user_agent                     = self.nws_config_dict.get('User-Agent', '(<weather-site>, <contact>)'),
            poll_secs                      = to_int(self.nws_config_dict.get('poll_secs', 1800)),
            alert_poll_secs                = to_int(self.nws_config_dict.get('alert_poll_secs', 600)),
            retry_wait_secs                = to_int(self.nws_config_dict.get('retry_wait_secs', 300)),
            alert_retry_wait_secs          = to_int(self.nws_config_dict.get('alert_retry_wait_secs', 30)),
            days_to_keep                   = to_int(self.nws_config_dict.get('days_to_keep', 90)),
            read_from_dir                  = self.nws_config_dict.get('read_from_dir', None),
            ssh_config                     = SshConfiguration(
                enable                         = to_bool(rsync_spec_dict.get('enable', False)),
                remote_clients                 = rsync_spec_dict.get('remote_clients'),
                remote_port                    = to_int(rsync_spec_dict.get('remote_port')) if rsync_spec_dict.get(
                                                 'remote_port') is not None else None,
                remote_user                    = rsync_spec_dict.get('remote_user'),
                remote_dir                     = rsync_spec_dict.get('remote_dir'),
                compress                       = to_bool(rsync_spec_dict.get('compress', True)),
                log_success                    = to_bool(rsync_spec_dict.get('log_success', False)),
                ssh_options                    = rsync_spec_dict.get('ssh_options', '-o ConnectTimeout=1'),
                timeout                        = to_int(rsync_spec_dict.get('timeout', 1)),
                ),
            )
        log.info('latitude                      : %s' % self.cfg.latitude)
        log.info('longitude                     : %s' % self.cfg.longitude)
        log.info('alertsUrl                     : %s' % self.cfg.alertsUrl)
        log.info('oneHourForecastUrl            : %s' % self.cfg.oneHourForecastUrl)
        log.info('twelveHourForecastUrl         : %s' % self.cfg.twelveHourForecastUrl)
        log.info('hardCodedOneHourForecastUrl   : %s' % self.cfg.hardCodedOneHourForecastUrl)
        log.info('hardCodedTwelveHourForecastUrl: %s' % self.cfg.hardCodedTwelveHourForecastUrl)
        log.info('timeout_secs                  : %d' % self.cfg.timeout_secs)
        log.info('archive_interval              : %d' % self.cfg.archive_interval)
        log.info('user_agent                    : %s' % self.cfg.user_agent)
        log.info('poll_secs                     : %d' % self.cfg.poll_secs)
        log.info('alert_poll_secs               : %d' % self.cfg.alert_poll_secs)
        log.info('retry_wait_secs               : %d' % self.cfg.retry_wait_secs)
        log.info('alert_retry_wait_secs         : %d' % self.cfg.alert_retry_wait_secs)
        log.info('days_to_keep                  : %d' % self.cfg.days_to_keep)
        log.info('read_from_dir                 : %s' % self.cfg.read_from_dir)
        if self.cfg.ssh_config is None:
            log.info('ssh_config                    : None')
        else:
            log.info('ssh_config(')
            log.info('enable                        : %r' % self.cfg.ssh_config.enable)
            log.info('remote_clients                : %r' % self.cfg.ssh_config.remote_clients)
            log.info('remote_port                   : %r' % (self.cfg.ssh_config.remote_port if self.cfg.ssh_config.remote_port is not None else None))
            log.info('remote_user                   : %s' % self.cfg.ssh_config.remote_user)
            log.info('remote_dir                    : %s' % self.cfg.ssh_config.remote_dir)
            log.info('compress                      : %r' % self.cfg.ssh_config.compress)
            log.info('log_success                   : %r' % self.cfg.ssh_config.log_success)
            log.info('ssh_options                   : %r' % self.cfg.ssh_config.ssh_options)
            log.info('timeout                       : %i' % self.cfg.ssh_config.timeout)
            log.info(')')

        # If the machine was just rebooted, a temporary failure in name
        # resolution is likely.  As such, try three times to get
        # request urls.
        # Skip if we're reading forecasts from files.
        if self.cfg.read_from_dir is None or self.cfg.read_from_dir == '':
            # Skip if the 1H and 12H forecast URLs are hard coded.
            if self.cfg.hardCodedTwelveHourForecastUrl is None or self.cfg.hardCodedOneHourForecastUrl is None:
                for i in range(3):
                    if NWSPoller.request_urls(self.cfg):
                        break
                    if i < 2:
                        time.sleep(5)

        # Start a thread to query NWS for 1H forecasts
        nws_1h_poller: NWSPoller = NWSPoller(self.cfg, ForecastType.ONE_HOUR)
        t_1h_forecasts: threading.Thread = threading.Thread(target=nws_1h_poller.poll_nws)
        t_1h_forecasts.setName('NWS_1h_Forecasts')
        t_1h_forecasts.setDaemon(True)
        t_1h_forecasts.start()

        # Start a thread to query NWS for 12H forecasts
        nws_12h_poller: NWSPoller = NWSPoller(self.cfg, ForecastType.TWELVE_HOUR)
        t_12h_forecasts: threading.Thread = threading.Thread(target=nws_12h_poller.poll_nws)
        t_12h_forecasts.setName('NWS_12h_Forecasts')
        t_12h_forecasts.setDaemon(True)
        t_12h_forecasts.start()

        # Start a thread to query NWS for alerts
        nws_alerts_poller: NWSPoller = NWSPoller(self.cfg, ForecastType.ALERTS)
        t_alerts: threading.Thread = threading.Thread(target=nws_alerts_poller.poll_nws)
        t_alerts.setName('NWS_Alerts')
        t_alerts.setDaemon(True)
        t_alerts.start()

        self.bind(weewx.END_ARCHIVE_PERIOD, self.end_archive_period)

    def end_archive_period(self, _event):
        """create new archive record and save them to the database"""
        log.debug('end_archive_period: saving forecasts to DB')
        self.saveForecastsToDB(ForecastType.TWELVE_HOUR)
        self.saveForecastsToDB(ForecastType.ONE_HOUR)
        self.saveForecastsToDB(ForecastType.ALERTS)

    def saveForecastsToDB(self, forecast_type: ForecastType) -> None:
        try:
            log.debug('saveForecastsToDB(%s): start' % forecast_type)
            if forecast_type == ForecastType.ALERTS:
                # Delete expired alerts.
                self.delete_expired_alerts()
            with self.cfg.lock:
                if forecast_type == ForecastType.TWELVE_HOUR:
                    bucket = self.cfg.twelveHourForecasts
                    forecast_json = self.cfg.twelveHourForecastsJson
                    forecast_filename = 'TWELVE_HOUR'
                elif forecast_type == ForecastType.ONE_HOUR:
                    bucket = self.cfg.oneHourForecasts
                    forecast_json = self.cfg.oneHourForecastsJson
                    forecast_filename = 'ONE_HOUR'
                else:       # ForecastType.ALERTS
                    bucket = self.cfg.alerts
                if len(bucket) != 0 and (forecast_type == ForecastType.TWELVE_HOUR or forecast_type == ForecastType.ONE_HOUR) and bucket[0].generatedTime > time.time():
                    log.info('Forecast %s, generated %s, ignored because the generated time is in the future.' % (forecast_type, timestamp_to_string(bucket[0].generatedTime)))
                    return
                log.debug('saveForecastsToDB(%s): bucket: %s' % (forecast_type, bucket))
                # If we successfully downloaded zero alerts, clear alerts from database before continuing.
                if forecast_type == ForecastType.ALERTS and self.cfg.signalDeleteAlerts:
                    self.delete_all_alerts()
                    self.cfg.signalDeleteAlerts = False
                if len(bucket) != 0:
                    ts = NWS.get_archive_interval_timestamp(self.cfg.archive_interval)
                    log.debug('saveForecastsToDB(%s): bucket[0].generatedTime: %s' % (forecast_type, timestamp_to_string(bucket[0].generatedTime)))
                    # Never write the same forecast twice.  This is determined by generatedTime
                    if not self.forecast_in_db(forecast_type, bucket[0].generatedTime):
                        for record in bucket:
                            self.save_forecast(NWS.convert_to_json(record, ts))
                        log.info('Saved %d %s records.' % (len(bucket), forecast_type))
                        self.delete_old_forecasts(forecast_type);
                        # If requested, scp forecast to remote clients (don't do this for alerts, the file is writen elsewhere for alerts)
                        if forecast_type != ForecastType.ALERTS and self.cfg.ssh_config is not None and self.cfg.ssh_config.enable:
                            # Write json to temp file, then scp to clients
                            local_file = '/tmp/%s' % forecast_filename
                            with open(local_file, 'w') as outfile:
                                json.dump(forecast_json, outfile)
                            remote_file = '%s/%s' % (self.cfg.ssh_config.remote_dir, forecast_filename)
                            for remote_host in self.cfg.ssh_config.remote_clients:
                                NWS.rsync_forecast(local_file, remote_file, remote_host,
                                    self.cfg.ssh_config.remote_port, self.cfg.ssh_config.timeout,
                                    self.cfg.ssh_config.remote_user, self.cfg.ssh_config.ssh_options,
                                    self.cfg.ssh_config.compress, self.cfg.ssh_config.log_success)
                    else:
                        log.debug('Forecast %s, generated %s, already exists in the database.' % (forecast_type, timestamp_to_string(bucket[0].generatedTime)))
                    bucket.clear()
        except Exception as e:
            # Include a stack traceback in the log:
            # but eat this exception as we don't want to bring down weewx
            log.error('saveForedcastsToDB(%s): %s (%s)' % (forecast_type, e, type(e)))
            weeutil.logger.log_traceback(log.error, "    ****  ")

    def forecast_in_db(self, forecast_type: ForecastType, generatedTime: int) -> bool:
        try:
            dbmanager = self.engine.db_binder.get_manager(self.data_binding)
            select = "SELECT generatedTime FROM archive WHERE interval = %d AND generatedTime = %d LIMIT 1" % (
                NWS.get_interval(forecast_type), generatedTime)
            log.debug('Checking if forecast already in db: select: %s.' % select)
            return dbmanager.getSql(select) is not None
        except Exception as e:
            log.error('forecast_in_db(%s, %d) failed with %s (%s).' % (forecast_type, generatedTime, e, type(e)))
            weeutil.logger.log_traceback(log.error, "    ****  ")
            raise Exception('forecast_in_db(%s, %d) failed with %s (%s).' % (forecast_type, generatedTime, e, type(e)))

    def delete_expired_alerts(self) -> None:
        try:
           dbmanager = self.engine.db_binder.get_manager(self.data_binding)
           # Only delete if there are actually expired alerts in the table (to avoid confusing deletes in the log).
           now_minus_one_day = time.time() - 24.0 * 60.0 * 60.0
           try:
               select = 'SELECT COUNT(dateTime) FROM archive WHERE interval = %d and expirationTime <= %f' % (NWS.get_interval(ForecastType.ALERTS), now_minus_one_day)
               log.debug('Checking if there are any expired alerts in the archive to delete: select: %s.' % select)
               row = dbmanager.getSql(select)
           except Exception as e:
               log.error('delete_expired_alerts: %s failed with %s (%s).' % (select, e, type(e)))
               weeutil.logger.log_traceback(log.error, "    ****  ")
               return
           if row[0] != 0:
               delete = 'DELETE FROM archive WHERE interval = %d and expirationTime <= %f' % (NWS.get_interval(ForecastType.ALERTS), now_minus_one_day)
               log.info('Pruning ForecastType.ALERTS')
               dbmanager.getSql(delete)
        except Exception as e:
           log.error('delete_expired_alerts: %s failed with %s (%s).' % (delete, e, type(e)))
           weeutil.logger.log_traceback(log.error, "    ****  ")

    def delete_all_alerts(self) -> None:
        try:
           dbmanager = self.engine.db_binder.get_manager(self.data_binding)
           try:
               select = 'SELECT COUNT(dateTime) FROM archive WHERE interval = %d' % NWS.get_interval(ForecastType.ALERTS)
               log.debug('Getting count of alerts: %s.' % select)
               row = dbmanager.getSql(select)
           except Exception as e:
               log.error('delete_all_alerts: %s failed with %s (%s).' % (select, e, type(e)))
               weeutil.logger.log_traceback(log.error, "    ****  ")
               return
           # If there are alerts, delete them.
           if row[0] != 0:
               delete = 'DELETE FROM archive WHERE interval = %d' % NWS.get_interval(ForecastType.ALERTS)
               log.info('Deleted %d ForecastType.ALERTS' % row[0])
               dbmanager.getSql(delete)
        except Exception as e:
           log.error('delete_all_alerts: %s failed with %s (%s).' % (delete, e, type(e)))
           weeutil.logger.log_traceback(log.error, "    ****  ")

    def delete_old_forecasts(self, forecast_type: ForecastType) -> None:
        if forecast_type == ForecastType.ALERTS:
            return    # Alerts are not deleted here; rather they are deleted each time [possibly 0] alerts are saved to the db.
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
               log.error('delete_old_forecasts(%s): %s failed with %s (%s).' % (forecast_type, delete, e, type(e)))
               weeutil.logger.log_traceback(log.error, "    ****  ")

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
    def rsync_forecast(local_file: str, remote_file: str, remote_host: str,
            remote_port: int, timeout: int, remote_user: str, ssh_options: str,
            compress: bool, log_success: bool) -> None:
        log.debug('rsync_forecast() start')
        rsync_upload = weeutil.rsyncupload.RsyncUpload(
            local_file,
            remote_file,
            server=remote_host,
            user=remote_user,
            port=str(remote_port) if remote_port is not None else None,
            ssh_options=ssh_options,
            compress=compress,
            delete=False,
            log_success=log_success,
            timeout=timeout)
        try:
            rsync_upload.run()
        except IOError as e:
            (cl, unused_ob, unused_tr) = sys.exc_info()
            log.error("rsync_forecast: Caught exception %s: %s" % (cl, e))

    @staticmethod
    def convert_to_json(record, ts) -> Dict[str, Any]:
        log.debug('convert_to_json: start')
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
        j['expirationTime']   = record.expirationTime
        j['id']               = record.id
        j['endTime']          = record.endTime
        j['isDaytime']        = record.isDaytime
        j['outTemp']          = record.outTemp
        j['outTempTrend']     = record.outTempTrend
        j['windSpeed']        = record.windSpeed
        j['windSpeed2']       = record.windSpeed2
        j['windDir']          = record.windDir
        j['iconUrl']          = record.iconUrl
        j['shortForecast']    = record.shortForecast
        j['detailedForecast'] = record.detailedForecast
        j['instruction']     = record.instruction
        j['sent']             = record.sent
        j['status']           = record.status
        j['messageType']      = record.messageType
        j['category']         = record.category
        j['severity']         = record.severity
        j['certainty']        = record.certainty
        j['urgency']          = record.urgency
        j['sender']           = record.sender
        j['senderName']       = record.senderName
        log.debug('convert_to_json: returning: %s' % j)
        return j

    @staticmethod
    def get_interval(forecast_type: ForecastType) -> int:
        if forecast_type == ForecastType.ONE_HOUR:
            return 60
        elif forecast_type == ForecastType.TWELVE_HOUR:
            return 720
        # ALERTS
        return 0

    @staticmethod
    def vectors_intersect(vec1: Side, vec2: Side) -> bool:
        d1: float;
        d2: float;
        a1: float;
        a2: float;
        b1: float;
        b2: float;
        c1: float;
        c2: float;

        # Convert vector 1 to a line (line 1) of infinite length.
        # We want the line in linear equation standard form: A*x + B*y + C = 0
        # See: http://en.wikipedia.org/wiki/Linear_equation

        #v1x1 is vec1.point[0].lat
        #v1x2 is vec1.point[1].lat
        #v1y1 is vec1.point[0].long
        #v1y2 is vec1.point[1].long
        #v2x1 is vec2.point[0].lat
        #v2x2 is vec2.point[1].lat
        #v2y1 is vec2.point[0].long
        #v2y2 is vec2.point[1].long


        a1 = vec1.point[1].long - vec1.point[0].long
        b1 = vec1.point[0].lat - vec1.point[1].lat
        c1 = (vec1.point[1].lat * vec1.point[0].long) - (vec1.point[0].lat * vec1.point[1].long)

        # Every point (x,y), that solves the equation above, is on the line,
        # every point that does not solve it, is not. The equation will have a
        # positive result if it is on one side of the line and a negative one
        # if is on the other side of it. We insert (x1,y1) and (x2,y2) of vector
        # 2 into the equation above.
        d1 = (a1 * vec2.point[0].lat) + (b1 * vec2.point[0].long) + c1
        d2 = (a1 * vec2.point[1].lat) + (b1 * vec2.point[1].long) + c1

        # If d1 and d2 both have the same sign, they are both on the same side
        # of our line 1 and in that case no intersection is possible. Careful,
        # 0 is a special case, that's why we don't test ">=" and "<=",
        # but "<" and ">".
        if d1 > 0 and d2 > 0:
            return False
        if d1 < 0 and d2 < 0:
            return False

        # The fact that vector 2 intersected the infinite line 1 above doesn't
        # mean it also intersects the vector 1. Vector 1 is only a subset of that
        # infinite line 1, so it may have intersected that line before the vector
        # started or after it ended. To know for sure, we have to repeat the
        # the same test the other way round. We start by calculating the
        # infinite line 2 in linear equation standard form.
        a2 = vec2.point[1].long - vec2.point[0].long
        b2 = vec2.point[0].lat - vec2.point[1].lat
        c2 = (vec2.point[1].lat * vec2.point[0].long) - (vec2.point[0].lat * vec2.point[1].long)

        # Calculate d1 and d2 again, this time using points of vector 1.
        d1 = (a2 * vec1.point[0].lat) + (b2 * vec1.point[0].long) + c2
        d2 = (a2 * vec1.point[1].lat) + (b2 * vec1.point[1].long) + c2

        # Again, if both have the same sign (and neither one is 0),
        # no intersection is possible.
        if d1 > 0 and d2 > 0:
            return False
        if d1 < 0 and d2 < 0:
            return False

        # If we get here, only two possibilities are left. Either the two
        # vectors intersect in exactly one point or they are collinear, which
        # means they intersect in any number of points from zero to infinite.
        if (a1 * b2) - (a2 * b1) == 0.0:
            return False # Arbitrarily return False here

        # If they are not collinear, they must intersect in exactly one point.
        return True

    @staticmethod
    def point_in_polygon(point: Point, polygon: List[Side]) -> bool:
        """ Determine if forecast returned is for the correct area (it could be off by (1,1) due to an NWS bug.
            Pass lat, long of location as well as the polygon sides that form the bounds of the forecast area
            Returns true if lat/long is within the polygon.
            See: https://stackoverflow.com/questions/217578/how-can-i-determine-whether-a-2d-point-is-within-a-polygon
        """
        # Find min/max lat/long.
        lat_min : Optional[float] = None
        lat_max : Optional[float] = None
        long_min: Optional[float] = None
        long_max: Optional[float] = None
        for side in polygon:
            if lat_min is None or side.point[0].lat < lat_min:
                lat_min = side.point[0].lat
            if  side.point[1].lat < lat_min:
                lat_min = side.point[1].lat
            if long_min is None or side.point[0].long < long_min:
                long_min = side.point[0].long
            if  side.point[1].long < long_min:
                long_min = side.point[1].long
            if lat_max is None or side.point[0].lat > lat_max:
                lat_max = side.point[0].lat
            if  side.point[1].lat > lat_max:
                lat_max = side.point[1].lat
            if long_max is None or side.point[0].long > long_max:
                long_max = side.point[0].long
            if  side.point[1].long > long_max:
                long_max = side.point[1].long
        assert lat_min is not None
        assert lat_max is not None
        assert long_min is not None
        assert long_max is not None

        # Quick check to eliminate candidates

        if point.lat < lat_min or point.lat > lat_max or point.long < long_min or point.long > long_max:
            return False

        # Specify a ray that includes point
        ray: Side = Side([
            Point(
                lat  = lat_min - 1,
                long = point.long),
            Point(
                lat  = point.lat,
                long = point.long)])

        # Test the ray against all sides
        intersections: int = 0
        for side in polygon:
            # Test if current side intersects with ray.
            if NWS.vectors_intersect(ray, side):
                intersections += 1
        return (intersections & 1) == 1

    @staticmethod
    def check_latlong_against_nws_polygon(latitude: float, longitude: float, coordinates: List[List[List[float]]]) -> bool:
        # Check if lat,long fall within the returned polygon.
        # Coordinates is an array of lat/long (array) pairs.

        point: Point = Point(latitude, longitude)

        # Construct the sides.
        sides: List[Side] = []
        prev_coordinate: Optional[Point] = None
        for coordinates_group in coordinates:
            for coordinate in coordinates_group:
                if prev_coordinate is None:
                    # NWS uses long/lat order
                    prev_coordinate = Point(coordinate[1], coordinate[0])
                else:
                    # NWS uses long/lat order
                    sides.append(Side([prev_coordinate, Point(coordinate[1], coordinate[0])]))
                    prev_coordinate = Point(coordinate[1], coordinate[0])

        return NWS.point_in_polygon(point, sides)

    def save_forecast(self, record) -> None:
        """save data to database"""
        dbmanager = self.engine.db_binder.get_manager(self.data_binding)
        dbmanager.addRecord(record)

    def select_forecasts(self, forecast_type: ForecastType, max_forecasts: int=None) -> List[Dict[str, Any]]:
        # Used for testing.
        dbmanager = self.engine.db_binder.get_manager(self.data_binding)
        return NWSForecastVariables.fetch_records(dbmanager, forecast_type, self.cfg.latitude, self.cfg.longitude, max_forecasts)

class NWSPoller:
    def __init__(self, cfg: Configuration, forecast_type: ForecastType):
        self.cfg             = cfg
        self.forecast_type   = forecast_type
        self.poll_secs       = cfg.alert_poll_secs if forecast_type == ForecastType.ALERTS else cfg.poll_secs
        self.retry_wait_secs = cfg.alert_retry_wait_secs if forecast_type == ForecastType.ALERTS else cfg.retry_wait_secs

    def poll_nws(self) -> None:
        on_retry      : bool = False
        on_retry_count: int  = 0
        failed        : bool = False
        while True:
            try:
                if not on_retry or failed:
                    for i in range(4):
                        retry, success = NWSPoller.populate_forecast(self.cfg, self.forecast_type)
                        if success or not retry:
                            break
                        else:
                            if i < 3:
                                log.info('Retrying %s request in 5s.' % self.forecast_type)
                                time.sleep(5)
                    if success or not retry:
                        failed = False
                    else:
                        failed = True
                if failed:
                    log.error('Retrying %s request in %d s.' % (self.forecast_type, self.retry_wait_secs))
                    if on_retry_count < 3:
                        on_retry_count += 1
                        on_retry = True
                        # TODO: Perhaps back off on retries.
                        time.sleep(self.retry_wait_secs)
                    else:
                        # We've retried enough, wait until next poll period.
                        on_retry = False
                        on_retry_count = 0
                        sleep_time = NWSPoller.time_to_next_poll(self.poll_secs)
                        log.debug('poll_nws: Sleeping for %f seconds.' % sleep_time)
                        time.sleep(sleep_time)
                else:
                    on_retry = False
                    on_retry_count = 0
                    sleep_time = NWSPoller.time_to_next_poll(self.poll_secs)
                    log.debug('poll_nws: Sleeping for %f seconds.' % sleep_time)
                    time.sleep(sleep_time)
            except Exception as e:
                log.error('poll_nws(%s): Encountered exception. Retrying in %d seconds. exception: %s (%s)' % (self.forecast_type, self.retry_wait_secs, e, type(e)))
                weeutil.logger.log_traceback(log.error, "    ****  ")
                time.sleep(self.cfg.retry_wait_secs)

    @staticmethod
    def populate_forecast(cfg, forecast_type: ForecastType) -> Tuple[bool, bool]: # returns retry, success booleans
        log.debug('populate_forecast(%s): start' % forecast_type)
        start_time = time.time()
        retry, j = NWSPoller.request_forecast(cfg, forecast_type)
        if j == None:
            return retry, False # Retry will be False if forecast has not been modified
        else:
            elapsed_time = time.time() - start_time
            log.debug('Queries to NWS took %f seconds' % elapsed_time)
            with cfg.lock:
                if forecast_type == ForecastType.ONE_HOUR:
                    cfg.oneHourForecasts.clear()
                    cfg.oneHourForecastsJson = j
                elif forecast_type == ForecastType.TWELVE_HOUR:
                    cfg.twelveHourForecasts.clear()
                    cfg.twelveHourForecastsJson = j
                else:
                    cfg.alerts.clear()
                try:
                    record_count: int = 0
                    generatedTime: Optional[int] = None
                    for record in NWSPoller.compose_records(j, forecast_type, cfg.latitude, cfg.longitude):
                        record_count += 1
                        generatedTime = record.generatedTime
                        log.debug('NWSPoller: poll_nws: adding %s forecast(%s) to array.' % (forecast_type, record))
                        if forecast_type == ForecastType.ONE_HOUR:
                            cfg.oneHourForecasts.append(record)
                        elif forecast_type == ForecastType.TWELVE_HOUR:
                            cfg.twelveHourForecasts.append(record)
                        else: # Alerts
                            cfg.alerts.append(record)
                except KeyError as e:
                    log.error("populate_forecast(%s): Could not compose forecast record.  Key: '%s' missing in returned forecast." % (forecast_type, e))
                    return True, False  # retry since unsuccessful
                # Signal to delete all alerts if 0 alerts were downloaded
                if forecast_type == ForecastType.ALERTS:
                    if record_count == 0:
                        cfg.signalDeleteAlerts = True
                    else:
                        cfg.signalDeleteAlerts = False
            if record_count == 0:
                log.info('Downloaded 0 %s records.' % forecast_type)
            else:
                log.info('Downloaded %d %s records generated at %s' % (record_count, forecast_type, timestamp_to_string(generatedTime)))
            # scp alerts to remote clients (skip lock as the ssh parameters are immutable)
            if forecast_type == ForecastType.ALERTS and cfg.ssh_config is not None and cfg.ssh_config.enable:
                # Write json to temp file, then scp to clients
                local_file = '/tmp/ALERTS'
                with open(local_file, 'w') as outfile:
                    json.dump(j, outfile)
                remote_file = '%s/ALERTS' % cfg.ssh_config.remote_dir
                for remote_host in cfg.ssh_config.remote_clients:
                    NWS.rsync_forecast(local_file, remote_file, remote_host,
                        cfg.ssh_config.remote_port, cfg.ssh_config.timeout,
                        cfg.ssh_config.remote_user, cfg.ssh_config.ssh_options,
                        cfg.ssh_config.compress, cfg.ssh_config.log_success)
            return False, True # no-need to retry as successful

    @staticmethod
    def time_to_next_poll(poll_secs: int) -> float:
        time_of_next_poll = int(time.time() / poll_secs) * poll_secs + poll_secs
        return time_of_next_poll - time.time()

    @staticmethod
    def log_404_and_503(caller: str, url: str, response: requests.Response) -> None:
        #{
        #    "correlationId": "ac04ca11-ce4d-464e-8cef-602497b10aa1",
        #    "title": "Data Unavailable For Requested Point",
        #    "type": "https://api.weather.gov/problems/InvalidPoint",
        #    "status": 404,
        #    "detail": "Unable to provide data for requested point -20.9512,55.3085",
        #    "instance": "https://api.weather.gov/requests/ac04ca11-ce4d-464e-8cef-602497b10aa1"
        #}
        #{
        #    "correlationId": "ba8277d6-de87-41fd-9ce5-dfb1868c1ced",
        #    "title": "Forecast Grid Expired",
        #    "type": "https://api.weather.gov/problems/ForecastGridExpired",
        #    "status": 503,
        #    "detail": "The requested forecast grid was issued 2020-06-09T11:01:35+00:00 and has expired.",
        #    "instance": "https://api.weather.gov/requests/ba8277d6-de87-41fd-9ce5-dfb1868c1ced"
        #}
        # correlation_id: 574b53f3-6f15-4a17-9008-08627ceb80f0
        # title         : Unavailable Resource
        # type          : https://api.weather.gov/problems/UnavailableWebService
        # status        : 503
        # detail        : The resource you requested is currently unavailable.  Please try again later.
        # instance      : https://api.weather.gov/requests/574b53f3-6f15-4a17-9008-08627ceb80f0
        try:
            d = response.json()
            correlation_id: str = d.get('correlationId')
            title: str = d.get('title')
            type_str: str = d.get('type')
            status: str = d.get('status')
            detail: str = d.get('detail')
            instance: str = d.get('instance')
            if title is not None:
                log.info('%s: %s, %s, %s, %s, %s, %s' % (caller, status, title, type_str, detail, instance, correlation_id))
            else:
                log.info('%s: %d error for url: %s' % (caller, response.status_code, url))
        except json.decoder.JSONDecodeError:
            # Couldn't get any further information about 404 or 503 errors.  That's OK.
            log.info('%s: %d error for url: %s.' % (caller, response.status_code, url))

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
            if response.status_code == 404 or response.status_code == 503:
                NWSPoller.log_404_and_503('request_urls', url, response)
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
                    cfg.oneHourForecastUrl    = j['properties']['forecastHourly']
                    log.info('request_urls: twelveHourForecastUrl: %s' % cfg.twelveHourForecastUrl)
                    log.info('request_urls: oneHourForecastUrl: %s' % cfg.oneHourForecastUrl)
                return True
            else:
                return False
        except requests.exceptions.RequestException as e:
            log.info('request_urls: Attempt to fetch from: %s failed: %s (%s).' % (url, e, type(e)))
            return False
        except Exception as e:
            # Unexpected exceptions need a stack track to diagnose.
            log.error('request_urls: Attempt to fetch from: %s failed: %s (%s).' % (url, e, type(e)))
            weeutil.logger.log_traceback(log.error, "    ****  ")
            return False

    @staticmethod
    def request_forecast(cfg, forecast_type: ForecastType)->Tuple[bool, Optional[Dict[str, Any]]]: # retry, json
        log.debug('request_forecast(%s): start' % forecast_type)
        with cfg.lock:
            if forecast_type == ForecastType.ONE_HOUR:
                if cfg.read_from_dir is not None and os.path.exists('%s/ONE_HOUR' % cfg.read_from_dir):
                    log.info('Reading %s forecasts from file: %s/ONE_HOUR.' % (forecast_type, cfg.read_from_dir))
                    f = open('%s/ONE_HOUR' % cfg.read_from_dir)
                    one_hour_contents: str = f.read()
                    return False, json.loads(one_hour_contents)
                if cfg.hardCodedOneHourForecastUrl is not None:
                    forecastUrl = cfg.hardCodedOneHourForecastUrl
                else:
                    forecastUrl = cfg.oneHourForecastUrl
            elif forecast_type == ForecastType.TWELVE_HOUR:
                if cfg.read_from_dir is not None and os.path.exists('%s/TWELVE_HOUR' % cfg.read_from_dir):
                    log.info('Reading %s forecasts from file: %s/TWELVE_HOUR.' % (forecast_type, cfg.read_from_dir))
                    f = open('%s/TWELVE_HOUR' % cfg.read_from_dir)
                    twelve_hour_contents: str = f.read()
                    return False, json.loads(twelve_hour_contents)
                if cfg.hardCodedTwelveHourForecastUrl is not None:
                    forecastUrl = cfg.hardCodedTwelveHourForecastUrl
                else:
                    forecastUrl = cfg.twelveHourForecastUrl
            else:
                if cfg.read_from_dir is not None and os.path.exists('%s/ALERTS' % cfg.read_from_dir):
                    log.info('Reading ForecastType.ALERTS forecasts from file: %s/ALERTS.' % cfg.read_from_dir)
                    f = open('%s/ALERTS' % cfg.read_from_dir)
                    alerts_contents: str = f.read()
                    return False, json.loads(alerts_contents)
                forecastUrl = cfg.alertsUrl
        log.debug('request_forecast(%s): forecastUrl %s' % (forecast_type, forecastUrl))
        if forecastUrl == None:
            if not NWSPoller.request_urls(cfg):
                log.info('request_forecast(%s): skipping attempt since request_urls was unsuccessful.' % forecast_type)
                return True, None
            else:
                # We now have filled in the urls.  It must be either 1H or 12H (and not hardcoded).
                with cfg.lock:
                    if forecast_type == ForecastType.ONE_HOUR:
                        forecastUrl = cfg.oneHourForecastUrl
                    elif forecast_type == ForecastType.TWELVE_HOUR:
                        forecastUrl = cfg.twelveHourForecastUrl
        log.debug('request_forecast(%s): forecastUrl %s' % (forecast_type, forecastUrl))
        try:
            log.info('Downloading %s forecasts from %s.' % (forecast_type, forecastUrl))
            session= requests.Session()
            headers = {'User-Agent': cfg.user_agent}
            with cfg.lock:
                if forecast_type == ForecastType.ONE_HOUR:
                    lastModified = cfg.lastModifiedOneHour
                elif forecast_type == ForecastType.TWELVE_HOUR:
                    lastModified = cfg.lastModifiedTwelveHour
                else: # ALERT
                    lastModified = cfg.lastModifiedAlerts
            if lastModified is not None:
                lastModifiedStr = lastModified.strftime('%a, %d %b %Y %H:%M:%S %Z')
                headers['If-Modified-Since'] = lastModifiedStr
            # Work around NWS caching issue.
            headers['Feature-Flags'] =  '%f' % time.time()
            log.info('%s: calling requests.Response with %r' % (forecast_type, headers))
            response: requests.Response = session.get(url=forecastUrl, headers=headers, timeout=cfg.timeout_secs)
            log.debug('response: %s' % response)
            if response.status_code == 404 or response.status_code == 503:
                NWSPoller.log_404_and_503('request_forecast(%s)' % forecast_type, forecastUrl, response)
                return True, None
            if response.status_code == 304: # 304 (Not Modified)
                log.info('%s: Skipping since not modified since %s' % (forecast_type, lastModifiedStr))
                return False, None
            response.raise_for_status()
            if response:
                j = response.json()
                log.debug('request_forecast(%s): response.headers: %r' % (forecast_type, response.headers))
                last_mod = None
                tzinfos = {'UTC': tz.gettz("UTC")}
                if 'Last-Modified' in response.headers:
                    last_mod = parse(response.headers['Last-Modified'], tzinfos=tzinfos)
                    log.debug('%s: last_mod retrieved from Last-Modified header: %s' % (forecast_type, last_mod.strftime('%a, %d %b %Y %H:%M:%S %Z')))
                elif 'properties' in j and 'updateTime' in j['properties']:
                    # Use updateTime for last-modified.
                    last_mod = parse(j['properties']['updateTime'], tzinfos=tzinfos)
                    log.debug('%s: last_mod retrieved from updateTime: %s' % (forecast_type, last_mod.strftime('%a, %d %b %Y %H:%M:%S %Z')))
                if last_mod is not None and last_mod <= datetime.datetime.now(datetime.timezone.utc):
                    with cfg.lock:
                        if forecast_type == ForecastType.ONE_HOUR:
                            cfg.lastModifiedOneHour = last_mod
                        elif forecast_type == ForecastType.TWELVE_HOUR:
                            cfg.lastModifiedTwelveHour = last_mod
                        else: # ALERT
                            cfg.lastModifiedAlerts = last_mod
                return True, j
            else:
                log.debug('returning None')
                return True, None
        except requests.exceptions.RequestException as e:
            log.error('request_forecast(%s): Attempt to fetch from: %s failed: %s (%s).' % (forecast_type, forecastUrl, e, type(e)))
            return True, None
        except json.decoder.JSONDecodeError as e:
            log.error('request_forecast(%s): Could not convert response to json: %s, error: %s (%s).' % (forecast_type, response, e, type(e)))
            return True, None
        except Exception as e:
            # Unexpected exceptions need a stack track to diagnose.
            log.error('request_forecast(%s): Attempt to fetch from: %s failed: %s (%s).' % (forecast_type, forecastUrl, e, type(e)))
            weeutil.logger.log_traceback(log.error, "    ****  ")
            return True, None

    @staticmethod
    def compose_alert_records(j, latitude: str, longitude: str) -> Iterator[Forecast]:
        log.debug('compose_alert_records: len(j[features]): %d' % len(j['features']))
        alertCount = 0
        # Collect expired ids up front so that these alerts can be discarded, rather than yielded
        # to the caller.
        expired_ids = set()
        for feature in j['features']:
            try:
                alert = feature['properties']
                # Keep track of ids in expiredReferences in alert[parameters].
                if 'expiredReferences' in alert['parameters']:
                    for expiredRef in alert['parameters']['expiredReferences']:
                        split_text = expiredRef.split(',')
                        for segment in split_text:
                            if segment.startswith("urn:oid"):
                                expired_ids.add(segment)
            except Exception as e:
                log.info('unable to collect expired alert ids due to malformed alert (skipping): %s, %s' % (feature, e))
        # Now go through the alerts again to yield the unexpired alerts.
        for feature in j['features']:
            try:
                alert = feature['properties']
                tzinfos = {'UTC': tz.gettz("UTC")}
                if alert is None or 'effective' not in alert or 'expires' not in alert or 'onset' not in alert or 'ends' not in alert:
                    log.info('malformed alert (skipping): %s' % alert)
                    continue
                id        = alert['id']
                effective = parse(alert['effective'], tzinfos=tzinfos).timestamp()
                expires   = parse(alert['expires'], tzinfos=tzinfos).timestamp()
                onset     = parse(alert['onset'], tzinfos=tzinfos).timestamp()
                if alert['ends'] is not None:
                    ends      = parse(alert['ends'], tzinfos=tzinfos).timestamp()
                else:
                    # Sometimes alert['ends'] is None, use expires instead.
                    ends      = parse(alert['expires'], tzinfos=tzinfos).timestamp()
                if id in expired_ids:
                    log.info('found expired alert (skipping): %s' % id)
                elif expires <= (time.time() - 24.0 * 60.0 * 60.0):  # Don't be so quick to stop showing expired alerts.  NWS doesn't reissue them quickly enough.
                    log.info('alert is past expiration time of %s (skipping): %s' % (timestamp_to_string(expires), alert['id']))
                elif alert['status'] == 'Test':
                    log.info("Skipping alert with status of 'Test': ID: %s, Headline: %s" % (alert['id'], alert['headline']))
                else:
                    record = Forecast(
                        interval         = NWS.get_interval(ForecastType.ALERTS),
                        latitude         = latitude,
                        longitude        = longitude,
                        usUnits          = weewx.US,                # Dummy
                        generatedTime    = int(effective),
                        number           = alertCount,
                        name             = alert['event'],
                        startTime        = onset,
                        expirationTime   = expires,
                        id               = id,
                        endTime          = ends,
                        isDaytime        = True,                    # Dummy
                        outTemp          = 0.0,                     # Dummy
                        outTempTrend     = '',                      # Dummy
                        windSpeed        = 0.0,                     # Dummy
                        windSpeed2       = None,                    # Dummy
                        windDir          = None,                    # Dummy
                        iconUrl          = '',                      # Dummy
                        shortForecast    = alert['headline'],
                        detailedForecast = alert['description'],
                        instruction      = alert['instruction'],
                        sent             = parse(alert['sent'], tzinfos=tzinfos).timestamp(),
                        status           = alert['status'],
                        messageType      = alert['messageType'],
                        category         = alert['category'],
                        severity         = alert['severity'],
                        certainty        = alert['certainty'],
                        urgency          = alert['urgency'],
                        sender           = alert['sender'],
                        senderName       = alert['senderName'],
                        )
                    alertCount += 1
                    log.debug('compose_alert_records: yielding record %s' % record)
                    yield record
            except Exception as e:
                log.info('malformed alert (skipping): %s, %s' % (feature, e))

    @staticmethod
    def compose_records(j, forecast_type: ForecastType, latitude: str, longitude: str) -> Iterator[Forecast]:
        if forecast_type == ForecastType.ALERTS:
            yield from NWSPoller.compose_alert_records(j, latitude, longitude)
            return

        if not NWS.check_latlong_against_nws_polygon(float(latitude), float(longitude), j['geometry']['coordinates']):
            log.warning("Lat/Long %s/%s does not fall within bounds of forecast's polygon (due to NWS Bug)." % (latitude, longitude))

        # 2020-05-18T22:02:26+00:00
        log.debug('compose_records(%s): updateTime: %s' % (forecast_type, j['properties']['updateTime']))
        tzinfos = {'UTC': tz.gettz("UTC")}
        updateTime = parse(j['properties']['updateTime'], tzinfos=tzinfos).timestamp()
        log.debug('compose_records(%s): updateTime: %s' % (forecast_type, timestamp_to_string(updateTime)))

        units = j['properties']['units']
        if units == 'us':
            units = weewx.US
        else:
            units = weewx.METRIC

        for period in j['properties']['periods']:
            windSpeedStr = period['windSpeed']
            windSpeedArray = windSpeedStr.split()
            windSpeed = to_int(windSpeedArray[0])
            if len(windSpeedArray) == 2:
                windSpeed2 = None
                windSpeedUnit = windSpeedArray[1]
            else:
                windSpeed2 = to_int(windSpeedArray[2])
                windSpeedUnit = windSpeedArray[3]
            if windSpeedUnit != "mph":
                log.info('compose_records(%s): expecting windspeed to be in MPH but found %s, please file an issue on github.' % (forecast_type, windSpeedUnit))
            record = Forecast(
                interval         = NWS.get_interval(forecast_type),
                latitude         = latitude,
                longitude        = longitude,
                usUnits          = units,
                generatedTime    = int(updateTime),
                number           = period['number'],
                name             = period['name'],
                startTime        = datetime.datetime.fromisoformat(period['startTime']).timestamp(),
                expirationTime   = None,
                id               = None,
                endTime          = datetime.datetime.fromisoformat(period['endTime']).timestamp(),
                isDaytime        = period['isDaytime'],
                outTemp          = to_float(period['temperature']),
                outTempTrend     = period['temperatureTrend'],
                windSpeed        = windSpeed,
                windSpeed2       = windSpeed2,
                windDir          = NWSPoller.translate_wind_dir(period['windDirection']),
                iconUrl          = period['icon'],
                shortForecast    = period['shortForecast'],
                detailedForecast = period['detailedForecast'],
                instruction      = None,
                sent             = None,
                status           = None,
                messageType      = None,
                category         = None,
                severity         = None,
                certainty        = None,
                urgency          = None,
                sender           = None,
                senderName       = None)
            yield record

    @staticmethod
    def translate_wind_dir(wdir_str) -> Optional[float]:
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

    def get_extension_list(self, timespan, db_lookup) -> List[Dict[str, 'NWSForecastVariables']]:
        return [{'nwsforecast': self}]

    def one_hour_forecasts(self, max_forecasts:Optional[int]=None) -> List[Dict[str, Any]]:
        return self.forecasts(ForecastType.ONE_HOUR, max_forecasts)

    def twelve_hour_forecasts(self, max_forecasts:Optional[int]=None) -> List[Dict[str, Any]]:
        return self.forecasts(ForecastType.TWELVE_HOUR, max_forecasts)

    def alerts(self) -> List[Dict[str, Any]]:
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
            row['expires']     = weewx.units.ValueHelper((raw_row['expirationTime'], time_units, time_group))
            row['id']          = raw_row['id']
            row['ends']        = weewx.units.ValueHelper((raw_row['endTime'], time_units, time_group))
            row['event']       = raw_row['name']
            row['headline']    = raw_row['shortForecast']
            row['description'] = raw_row['detailedForecast']
            row['instructions'] = raw_row['instruction']
            row['sent']        = weewx.units.ValueHelper((raw_row['sent'], time_units, time_group))
            row['status']      = raw_row['status']
            row['messageType'] = raw_row['messageType']
            row['category']    = raw_row['category']
            row['severity']    = raw_row['severity']
            row['certainty']   = raw_row['certainty']
            row['urgency']     = raw_row['urgency']
            row['sender']      = raw_row['sender']
            row['senderName']  = raw_row['senderName']
            rows.append(row)
        return rows

    def alert_count(self) -> int:
        return len(self.getLatestForecastRows(ForecastType.ALERTS))

    def forecasts(self, forecast_type: ForecastType, max_forecasts:Optional[int]=None) -> List[Dict[str, Any]]:
        """Returns the latest forecast records of the given type."""
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
            if row['expirationTime'] is not None:
                row['expirationTime'] = weewx.units.ValueHelper((row['expirationTime'], time_units, time_group))
            row['endTime'] = weewx.units.ValueHelper((row['endTime'], time_units, time_group))
            row['outTemp'] = weewx.units.ValueHelper((row['outTemp'], temp_units, temp_group))
            row['windSpeed'] = weewx.units.ValueHelper((row['windSpeed'], wind_speed_units, wind_speed_group))
            if row['windSpeed2'] is not None:
                row['windSpeed2'] = weewx.units.ValueHelper((row['windSpeed2'], wind_speed_units, wind_speed_group))
            row['windDir'] = weewx.units.ValueHelper((row['windDir'], wind_dir_units, wind_dir_group))
            if row['sent'] is not None:
                row['sent'] = weewx.units.ValueHelper((row['sent'], time_units, time_group))
        return rows

    def getLatestForecastRows(self, forecast_type: ForecastType, max_forecasts: Optional[int]=None) -> List[Dict[str, Any]]:
        """get the latest forecast of the specified type"""
        try:
            dict = weewx.manager.get_manager_dict(self.generator.config_dict['DataBindings'],
                                                  self.generator.config_dict['Databases'],self.binding)
            with weewx.manager.open_manager(dict) as dbm:
                return NWSForecastVariables.fetch_records(dbm, forecast_type, self.latitude, self.longitude, max_forecasts)
        except Exception as e:
            log.error('getLatestForecastRows: %s (%s)' % (e, type(e)))
            weeutil.logger.log_traceback(log.error, "    ****  ")
            return []

    @staticmethod
    def fetch_records(dbm: weewx.manager.Manager, forecast_type: ForecastType, latitude, longitude, max_forecasts: int=None) -> List[Dict[str, Any]]:
        for i in range(3):
            try:
                return NWSForecastVariables.fetch_records_internal(dbm, forecast_type, latitude, longitude, max_forecasts)
            except Exception as e:
                # Datbase locked exception has been observed.  If first try, print info and sleep 1s.
                if i < 2:
                    log.info('fetch_records failed with %s (%s), retrying.' % (e, type(e)))
                    time.sleep(1)
                else:
                    log.error('Fetch records failed with %s (%s).' % (e, type(e)))
                    weeutil.logger.log_traceback(log.error, "    ****  ")
        return []

    @staticmethod
    def fetch_records_internal(dbm: weewx.manager.Manager, forecast_type: ForecastType, latitude, longitude, max_forecasts: int=None) -> List[Dict[str, Any]]:
        # Fetch last records inserted for this forecast_type
        # This is tricky.  Sometimes, servers return older forecasts (i.e., generated at a time older than the latest generated).
        # As such, we'd like to select only the records that match MAX(generatedTime).  Alas, if we do that, when multiple alerts are
        # in effect, only the effective alert with the latest generated time will be shown.  As such:
        # for forecasts:
        #     select where generatedTime = MAX(generatedTime)
        #     order by start time
        # for alerts:
        #     select where dateTime = MAX(dateTime)
        #     order by issued date (generatedTime in db, effective to the user)
        if forecast_type == ForecastType.ALERTS:
            time_select_phrase = "dateTime = (SELECT MAX(dateTime)"
            order_by_clause = "ORDER BY generatedTime desc"
        else:
            time_select_phrase = "generatedTime = (SELECT MAX(generatedTime)"
            order_by_clause = "ORDER BY startTime"
        select = "SELECT dateTime, interval, latitude, longitude, usUnits, generatedTime, number, name, startTime, expirationTime, id, endTime, isDaytime, outTemp, outTempTrend, windSpeed, windSpeed2, windDir, iconUrl, shortForecast, detailedForecast, instruction, sent, status, messageType, category, severity, certainty, urgency, sender, senderName FROM archive WHERE %s FROM archive WHERE interval = %d AND latitude = %s AND longitude = %s) AND interval = %d AND latitude = %s AND longitude = %s %s" % (time_select_phrase, NWS.get_interval(forecast_type), latitude, longitude, NWS.get_interval(forecast_type), latitude, longitude, order_by_clause)
        records = []
        forecast_count = 0
        for row in dbm.genSql(select):
            EXP_TIME = 9
            END_TIME = 11
            # Only include if record hasn't expired (row[END_TIME] is endTime) and, for alerts, expiration_time has not been hit) and max_forecasts hasn't been exceeded.
            # Don't be so strict with expiration time.  NWS likes to have alerts expire without issuing new ones in time.
            if time.time() < row[END_TIME] and (row[EXP_TIME] is None or row[EXP_TIME] > (time.time() - 24.0 * 60.0 * 60.0)) and (max_forecasts is None or forecast_count < max_forecasts):
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
                record['expirationTime'] = row[9]
                record['id'] = row[10]
                record['endTime'] = row[11]
                record['isDaytime'] = row[12]
                record['outTemp'] = row[13]
                record['outTempTrend'] = row[14]
                record['windSpeed'] = row[15]
                record['windSpeed2'] = row[16]
                record['windDir'] = row[17]
                record['iconUrl'] = row[18]
                record['shortForecast'] = row[19]
                record['detailedForecast'] = row[20]
                record['instruction'] = row[21]
                record['sent'] = row[22]
                record['status'] = row[23]
                record['messageType'] = row[24]
                record['category'] = row[25]
                record['severity'] = row[26]
                record['certainty'] = row[27]
                record['urgency'] = row[28]
                record['sender'] = row[29]
                record['senderName'] = row[30]

                records.append(record)
        return records

if __name__ == '__main__':
    usage = """%prog [options] [--help]"""

    import weeutil.logger

    def main():
        import optparse

        parser = optparse.OptionParser(usage=usage)
        parser.add_option('--binding', dest="binding", metavar="BINDING",
                          default='nws_binding',
                          help="The data binding to use. Default is 'nws_binding'.")
        parser.add_option('--test-point-in-polygon', dest='testpointinpolygon', action='store_true',
                          help='Test the point in polygon function.')
        parser.add_option('--test-requester', dest='testreq', action='store_true',
                          help='Test the forecast requester.  Requires specify --type, --latitude, --longitude.')
        parser.add_option('--type', dest='ty',
                          help='ALERTS|TWELVE_HOUR|ONE_HOUR')
        parser.add_option('--nws-database', dest='db',
                          help='Location of nws.sdb file (only works with sqlite3).')
        parser.add_option('--insert-forecast', dest='manually_insert_forecast', action='store_true',
                          help='Manually insert a forecast from a file.  Requires --nws-database, --type, --filename, --latitude, --longitude and --archive-interval')
        parser.add_option('--test-service', dest='testserv', action='store_true',
                          help='Test the NWS service.  Requires --latitude and --longitude.')
        parser.add_option('--latitude', type='float', dest='lat',
                          help='The latitude of the station.')
        parser.add_option('--longitude', type='float', dest='long',
                          help='The longitude of the station.')
        parser.add_option('--archive_interval', type='int', dest='arcint',
                          default=300,
                          help='The archive interval.')
        parser.add_option('--view-criterion', dest='view_criterion',
                          help='ALL|LATEST|SUMMARY')
        parser.add_option('--view-forecasts', dest='view', action='store_true',
                          help='View forecast records.  Must specify --nws-database, --type and --view-criterion.')
        parser.add_option('--filename', type='str', dest='fname',
                          help='The filename from which to read the forecast.')
        (options, args) = parser.parse_args()

        weeutil.logger.setup('nws', {})

        if options.manually_insert_forecast:
            if not options.ty:
                parser.error('--insert-forecast requires --type argument')
            forecast_type = decode_forecast_type(options.ty)
            if forecast_type == None:
                parser.error('--type must be one of: ALERTS|TWELVE_HOUR|ONE_HOUR')
            if not options.fname:
                parser.error('--insert-forecast requires --filename argument')
            if not options.db:
                parser.error('--insert-forecast requires --nws-database argument')
            if not options.lat or not options.long:
                parser.error('--test-service requires --latitude and --longitude arguments')
            manually_insert_forecast(forecast_type, options.fname, options.db, options.lat, options.long, options.arcint)

        if options.testpointinpolygon:
            test_point_in_polygon()

        if options.testreq:
            forecast_type = decode_forecast_type(options.ty)
            if forecast_type == None:
                parser.error('--type must be one of: ALERTS|TWELVE_HOUR|ONE_HOUR')
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
                parser.error('--type must be one of: ALERTS|TWELVE_HOUR|ONE_HOUR')

            criterion = decode_criterion(options.view_criterion)
            if criterion == None:
                parser.error('--vew-criterion must be one of: ALL|LATEST|SUMMARY')

            view_sqlite_database(options.db, forecast_type, criterion)

    def decode_forecast_type(ty: str) -> Optional[ForecastType]:
        if ty.upper() == 'ALERTS':
            return ForecastType.ALERTS
        elif ty.upper() == 'TWELVE_HOUR':
            return ForecastType.TWELVE_HOUR
        elif ty.upper() == 'ONE_HOUR':
            return ForecastType.ONE_HOUR
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

    def manually_insert_forecast(forecast_type: ForecastType, fname: str, dbfile: str, latitude: float, longitude: float, arcint) -> None:
        f = open(fname)
        contents: str = f.read()
        j = json.loads(contents)
        try:
            import sqlite3
        except:
            print('Could not import sqlite3.')
            return
        ts = NWS.get_archive_interval_timestamp(arcint)
        conn = sqlite3.connect(dbfile)
        # Check to see if forecast already in DB
        tzinfos = {'UTC': tz.gettz("UTC")}
        generatedTime = int(parse(j['properties']['updateTime'], tzinfos=tzinfos).timestamp())
        if (forecast_type == ForecastType.TWELVE_HOUR or forecast_type == ForecastType.ONE_HOUR) and generatedTime > time.time():
            print('%s forecast generated at %s is in the future!  Skipping insert.' % (forecast_type, timestamp_to_string(generatedTime)))
            return
        select = "SELECT COUNT(*) FROM archive WHERE interval = %d AND generatedTime = %d LIMIT 1" % (
            NWS.get_interval(forecast_type), generatedTime)
        existing_count: int = 0
        for row in conn.execute(select):
            existing_count = row[0]
        if existing_count > 0:
            print('%s forecast generated at %s is already in the database.  Skipping insert.' % (forecast_type, timestamp_to_string(generatedTime)))
            return
        cursor = conn.cursor()
        count: int = 0
        for record in NWSPoller.compose_records(j, forecast_type, str(latitude), str(longitude)):
            json_record = NWS.convert_to_json(record, ts)
            insert_statement = compose_insert_statement(json_record)
            cursor.execute(insert_statement)
            count += 1
        conn.commit()
        cursor.close()
        print('Inserted %d %s forecasts generated at %s.' % (count, forecast_type, timestamp_to_string(generatedTime)))

    def compose_insert_statement(json_record) -> str:
        # We need ordering so columns matches values
        columns = []
        values = []
        for key in json_record:
            if json_record[key] is not None:
                columns.append(key)
                # String values need quotes
                string_columns = ['latitude', 'longitude', 'name', 'outTempTrend', 'iconUrl', 'shortForecast', 'detailedForecast' ]
                if key in string_columns:
                    values.append('"%s"' % json_record[key])
                else:
                    values.append(str(json_record[key]))
        return 'INSERT INTO archive (%s) VALUES(%s)' % (','.join(columns), ','.join(values))

    def test_requester(forecast_type: ForecastType, lat: float, long: float) -> None:
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
            alertsUrl             = 'https://api.weather.gov/alerts/active?point=str(lat),str(long)',
            twelveHourForecastUrl = None,
            oneHourForecastUrl    = None,
            hardCodedTwelveHourForecastUrl = None,
            hardCodedOneHourForecastUrl = None,
            latitude              = str(lat),
            longitude             = str(long),
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

        _, j = NWSPoller.request_forecast(cfg, forecast_type)
        if j is not None:
            for forecast in NWSPoller.compose_records(j, forecast_type, cfg.latitude, cfg.longitude):
                pretty_print_forecast(forecast)
                print('------------------------')
        else:
            print('request_forecast returned None.')

    def test_point_in_polygon() -> None:
        point = Point(
            lat  = 37.4315,
            long = -122.1109)

        polygon_91_87: List[Side] = [
            Side([
                Point(
                    lat = 37.441464000000003,
                    long  = -122.13802870000001),
                Point(
                    lat = 37.419633300000001,
                    long  = -122.13245160000001)]),

            Side([
                Point(
                    lat = 37.419633300000001,
                    long  = -122.13245160000001),
                Point(
                    lat = 37.42407,
                    long  = -122.10489700000001)]),

            Side([
                Point(
                    lat = 37.42407,
                    long  = -122.10489700000001),
                Point(
                    lat = 37.4459011,
                    long  = -122.11046870000001)]),

            Side([
                Point(
                    lat = 37.4459011,
                    long  = -122.11046870000001),
                Point(
                    lat = 37.441464000000003,
                    long  = -122.13802870000001)])
            ]

        polygon_92_88: List[Side] = [
            Side([
                Point(
                    lat = 37.467745899999997,
                    long  = -122.1160977),
                Point(
                    lat = 37.4459011,
                    long  = -122.1105197)]),

            Side([
                Point(
                    lat = 37.4459011,
                    long  = -122.1105197),
                Point(
                    lat = 37.450318099999997,
                    long  = -122.0830553)]),

            Side([
                Point(
                    lat = 37.450318099999997,
                    long  = -122.0830553),
                Point(
                    lat = 37.472163299999998,
                    long  = -122.088628)]),

            Side([
                Point(
                    lat = 37.472163299999998,
                    long  = -122.088628),
                Point(
                    lat = 37.467745899999997,
                    long  = -122.1160977)])
            ]

        assert NWS.point_in_polygon(point, polygon_91_87) == True
        assert NWS.point_in_polygon(point, polygon_92_88) == False

    def test_service(lat: float, long: float) -> None:
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

            _, rc = NWSPoller.populate_forecast(nws.cfg, ForecastType.TWELVE_HOUR)
            if rc:
                nws.saveForecastsToDB(ForecastType.TWELVE_HOUR)
            _, rc = NWSPoller.populate_forecast(nws.cfg, ForecastType.ONE_HOUR)
            if rc:
                nws.saveForecastsToDB(ForecastType.ONE_HOUR)
            _, rc = NWSPoller.populate_forecast(nws.cfg, ForecastType.ALERTS)
            if rc:
                nws.saveForecastsToDB(ForecastType.ALERTS)

            for record in nws.select_forecasts(ForecastType.TWELVE_HOUR):
                pretty_print_record(record, ForecastType.TWELVE_HOUR)
                print('------------------------')
            for record in nws.select_forecasts(ForecastType.ONE_HOUR):
                pretty_print_record(record, ForecastType.ONE_HOUR)
                print('------------------------')
            for record in nws.select_forecasts(ForecastType.ALERTS):
                pretty_print_record(record, ForecastType.ALERTS)
                print('------------------------')

    def view_sqlite_database(dbfile: str, forecast_type: ForecastType, criterion: Criterion) -> None:
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

    def print_sqlite_records(conn, dbfile: str, forecast_type: ForecastType, criterion: Criterion) -> None:
        if criterion == Criterion.ALL:
            select = "SELECT dateTime, interval, latitude, longitude, usUnits, generatedTime, number, name, startTime, expirationTime, id, endTime, isDaytime, outTemp, outTempTrend, windSpeed, windSpeed2, windDir, iconUrl, shortForecast, detailedForecast, instruction, sent, status, messageType, category, severity, certainty, urgency, sender, senderName FROM archive WHERE interval = %d ORDER BY generatedTime, number" % NWS.get_interval(forecast_type)
        elif criterion == Criterion.LATEST:
            select = "SELECT dateTime, interval, latitude, longitude, usUnits, generatedTime, number, name, startTime, expirationTime, id, endTime, isDaytime, outTemp, outTempTrend, windSpeed, windSpeed2, windDir, iconUrl, shortForecast, detailedForecast, instruction, sent, status, messageType, category, severity, certainty, urgency, sender, senderName FROM archive WHERE interval = %d AND generatedTime = (SELECT MAX(generatedTime) FROM archive WHERE interval = %d) ORDER BY number" % (NWS.get_interval(forecast_type), NWS.get_interval(forecast_type))

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
            record['expirationTime'] = row[9]
            record['id'] = row[10]
            record['endTime'] = row[11]
            record['isDaytime'] = row[12]
            record['outTemp'] = row[13]
            record['outTempTrend'] = row[14]
            record['windSpeed'] = row[15]
            record['windSpeed2'] = row[16]
            record['windDir'] = row[17]
            record['iconUrl'] = row[18]
            record['shortForecast'] = row[19]
            record['detailedForecast'] = row[20]
            record['instruction'] = row[21]
            record['sent'] = row[22]
            record['status'] = row[23]
            record['messageType'] = row[24]
            record['category'] = row[25]
            record['severity'] = row[26]
            record['certainty'] = row[27]
            record['urgency'] = row[28]
            record['sender'] = row[29]
            record['senderName'] = row[30]
            pretty_print_record(record, forecast_type)
            print('------------------------')

    def print_sqlite_summary(conn, dbfile: str, forecast_type: ForecastType) -> None:
        select = "SELECT dateTime, MAX(generatedTime), MIN(startTime), MAX(endTime) FROM archive WHERE interval = %d GROUP BY dateTime ORDER BY generatedTime" % NWS.get_interval(forecast_type)

        # 2020-05-28 14:00:00 PDT (1590699600)
        print('%s %s %s %s' % ('Inserted'.ljust(36), 'Generated'.ljust(36), 'Start'.ljust(36), 'End'))
        for row in conn.execute(select):
            print('%s %s %s %s' % (timestamp_to_string(row[0]), timestamp_to_string(row[1]), timestamp_to_string(row[2]), timestamp_to_string(row[3])))

    def pretty_print_forecast(forecast) -> None:
        print('interval        : %d' % forecast.interval)
        print('latitude        : %s' % forecast.latitude)
        print('longitude       : %s' % forecast.longitude)
        print('usUnits         : %d' % forecast.usUnits)
        print('generatedTime   : %s' % timestamp_to_string(forecast.generatedTime))
        print('number          : %d' % forecast.number)
        print('name            : %s' % forecast.name)
        print('startTime       : %s' % timestamp_to_string(forecast.startTime))
        if forecast.expirationTime is not None:
            print('expirationTime  : %s' % timestamp_to_string(forecast.expirationTime))
        if forecast.id is not None:
            print('id              : %s' % forecast.id)
        print('endTime         : %s' % timestamp_to_string(forecast.endTime))
        print('isDaytime       : %d' % forecast.isDaytime)
        print('outTemp         : %f' % forecast.outTemp)
        print('outTempTrend    : %s' % forecast.outTempTrend)
        print('windSpeed       : %f' % forecast.windSpeed)
        print('windSpeed2      : %f' % forecast.windSpeed2)
        print('windDir         : %f' % forecast.windDir)
        print('iconUrl         : %s' % forecast.iconUrl)
        print('shortForecast   : %s' % forecast.shortForecast)
        print('detailedForecast: %s' % forecast.detailedForecast)
        if forecast.instruction is not None:
            print('instruction     : %s' % forecast.instruction)
        if forecast.sent is not None:
            print('sent            : %s' % timestamp_to_string(forecast.sent))
        if forecast.status is not None:
            print('status          : %s' % forecast.status)
        if forecast.messageType is not None:
            print('messasgeType    : %s' % forecast.messasgeType)
        if forecast.category is not None:
            print('category        : %s' % forecast.category)
        if forecast.severity is not None:
            print('severity        : %s' % forecast.severity)
        if forecast.certainty is not None:
            print('certainty       : %s' % forecast.certainty)
        if forecast.urgency is not None:
            print('urgency         : %s' % forecast.urgency)
        if forecast.sender is not None:
            print('sender          : %s' % forecast.sender)
        if forecast.senderName is not None:
            print('senderName      : %s' % forecast.senderName)

    def pretty_print_record(record, forecast_type) -> None:
        if forecast_type == ForecastType.ONE_HOUR or forecast_type == ForecastType.TWELVE_HOUR:
            print('dateTime        : %s' % timestamp_to_string(record['dateTime']))
            print('interval        : %d' % record['interval'])
            print('latitude        : %s' % record['latitude'])
            print('longitude       : %s' % record['longitude'])
            print('usUnits         : %d' % record['usUnits'])
            print('generatedTime   : %s' % timestamp_to_string(record['generatedTime']))
            print('number          : %d' % record['number'])
            print('name            : %s' % record['name'])
            print('startTime       : %s' % timestamp_to_string(record['startTime']))
            if record['expirationTime'] is not None:
                print('expirationTime  : %s' % timestamp_to_string(record['expirationTime']))
            if record['id'] is not None:
                print('id              : %s' % record['id'])
            print('endTime         : %s' % timestamp_to_string(record['endTime']))
            print('isDaytime       : %d' % record['isDaytime'])
            print('outTemp         : %f' % record['outTemp'])
            print('outTempTrend    : %s' % record['outTempTrend'])
            print('windSpeed       : %f' % record['windSpeed'])
            print('windSpeed2      : %f' % record['windSpeed2'])
            print('windDir         : %f' % record['windDir'])
            print('iconUrl         : %s' % record['iconUrl'])
            print('shortForecast   : %s' % record['shortForecast'])
            print('detailedForecast: %s' % record['detailedForecast'])
            if record['instruction'] is not None:
                print('instruction     : %s' % record['instruction'])
            if record['sent'] is not None:
                print('sent            : %s' % timestamp_to_string(record['sent']))
            if record['status'] is not None:
                print('status          : %s' % record['status'])
            if record['messageType'] is not None:
                print('messageType     : %s' % record['messageType'])
            if record['category'] is not None:
                print('category        : %s' % record['category'])
            if record['severity'] is not None:
                print('severity        : %s' % record['severity'])
            if record['certainty'] is not None:
                print('certainty       : %s' % record['certainty'])
            if record['urgency'] is not None:
                print('urgency         : %s' % record['urgency'])
            if record['sender'] is not None:
                print('sender          : %s' % record['sender'])
            if record['senderName'] is not None:
                print('senderName      : %s' % record['senderName'])
        else: # ForecastType.ALERTS
            print('dateTime        : %s' % timestamp_to_string(record['dateTime']))
            print('Headline        : %s' % record['shortForecast'])
            print('Issued          : %s' % timestamp_to_string(record['generatedTime']))
            print('Onset           : %s' % timestamp_to_string(record['startTime']))
            print('Ends            : %s' % timestamp_to_string(record['endTime']))
            if record['status'] is not None:
                print('Status          : %s' % record['status'])
            if record['severity'] is not None:
                print('Severity        : %s' % record['severity'])
            if record['certainty'] is not None:
                print('certainty       : %s' % record['certainty'])
            print('Description     : %s' % record['detailedForecast'])
            if record['instruction'] is not None:
                print('Instructions    : %s' % record['instruction'])
            if record['id'] is not None:
                print('ID              : %s' % record['id'])
            print('Event           : %s' % record['name'])
            if record['expirationTime'] is not None:
                print('Expires         : %s' % timestamp_to_string(record['expirationTime']))
            if record['sent'] is not None:
                print('Sent            : %s' % timestamp_to_string(record['sent']))
            if record['messageType'] is not None:
                print('Message         : %s' % record['messageType'])
            if record['category'] is not None:
                print('Category        : %s' % record['category'])
            if record['urgency'] is not None:
                print('Urgency         : %s' % record['urgency'])
            if record['sender'] is not None:
                print('Sender          : %s' % record['sender'])
            if record['senderName'] is not None:
                print('Sender Name     : %s' % record['senderName'])

    main()
