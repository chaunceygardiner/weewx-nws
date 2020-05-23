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

Installation instructions.

1. Download weewx-nws-master.zip from the https://github.com/chaunceygardiner/weewx-nws page.

2. Run the following command.

   sudo /home/weewx/bin/wee_extension --install weewx-nws-master.zip

    Note: The above command assumes a WeeWX installation of `/home/weewx`.
          Adjust the command as necessary.

3. Add NWSForecastVariables to one or more skins.  For example, to add to the Seasons skin, add:
    [StdReport]
        [[SeasonsReport]]
            [[[CheetahGenerator]]]
                search_list_extensions = user.nws.NWSForecastVariables
4.  To get at most 12 hourly forecasts (as an example).
    #for $hour in $nwsforecast.hourly_forecasts(12)
        $hour.startTime
        $hour.shortForecast
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
    ('dateTime',         'INTEGER NOT NULL'), # When forecast was inserted.
    ('interval',         'INTEGER NOT NULL'), # Always 60 (1 hr.)
    ('usUnits',          'INTEGER NOT NULL'),
    ('generatedTime',    'INTEGER NOT NULL'), # When forecast was generated.
    ('number',           'INTEGER NOT NULL'),
    ('name',             'STRING'),
    ('startTime',        'FLOAT NOT NULL'),
    ('endTime',          'FLOAT NOT NULL'),
    ('isDaytime',        'INTEGER NOT NULL'),
    ('outTemp',          'FLOAT NOT NULL'),  # Needs to be converted
    ('outTempTrend',     'STRING'),
    ('windSpeed',        'FLOAT NOT NULL'),
    ('windDir',          'FLOAT'),
    ('iconUrl',          'STRING NOT NULL'),
    ('shortForecast',    'STRING NOT NULL'),
    ('detailedForecast', 'STRING'),
    ]

schema = {
    'table'         : table,
}

@dataclass
class Forecast:
    interval        : int # Always 60 (1 hr.)
    usUnits         : int
    generatedTime   : int
    number          : int
    name            : Optional[str]
    startTime       : float
    endTime         : float
    isDaytime       : int
    outTemp         : float
    outTempTrend    : Optional[str]
    windSpeed       : float
    windDir         : Optional[float]
    iconUrl         : str
    shortForecast   : str
    detailedForecast: Optional[str]

@dataclass
class Configuration:
    lock            : threading.Lock
    forecasts       : List[Forecast] # Controlled by lock
    latitude        : float # Immutable
    longitude       : float # Immutable
    timeout_secs    : int   # Immutable
    archive_interval: int   # Immutable
    user_agent      : str

class NWS(StdService):
    """Fetch NWS Forecasts"""
    def __init__(self, engine, config_dict):
        super(NWS, self).__init__(engine, config_dict)
        log.info("Service version is %s." % WEEWX_NWS_VERSION)

        # Get latlong of station
        latitude = config_dict['Station'].get('latitude', None)
        longitude = config_dict['Station'].get('longitude', None)
        if latitude is None or longitude is None:
            log.error("Could not determine station's latitude and longitude.  Please set it under [Station] in weewx.conf.")
            return

        self.config_dict = config_dict
        self.nws_config_dict = config_dict.get('NWS', {})
        self.engine = engine

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
            lock             = threading.Lock(),
            forecasts        = [],
            latitude         = latitude,
            longitude        = longitude,
            timeout_secs     = to_int(self.nws_config_dict.get('timeout_secs', 5)),
            archive_interval = int(config_dict['StdArchive']['archive_interval']),
            user_agent       = self.nws_config_dict.get('User-Agent', '(<weather-site>, <contact>)'),
            )

        # At startup, get the latest forecast.
        if (NWSPoller.populate_forecast(self.cfg)):
            self.saveForecastsToDB()

        # Start a thread to query NWS for forecasts
        nws_poller: NWSPoller = NWSPoller(self.cfg)
        t: threading.Thread = threading.Thread(target=nws_poller.poll_nws)
        t.setName('NWS')
        t.setDaemon(True)
        t.start()

        self.bind(weewx.END_ARCHIVE_PERIOD, self.end_archive_period)

    def end_archive_period(self, _event):
        """create new archive record and save them to the database"""
        self.saveForecastsToDB()

    def saveForecastsToDB(self):
        try:
            now = int(time.time() + 0.5)
            with self.cfg.lock:
                if len(self.cfg.forecasts) != 0:
                    now_ts = int(time.time() + 0.5)
                    ts = int(now_ts / self.cfg.archive_interval) * self.cfg.archive_interval
                    for record in self.cfg.forecasts:
                        self.save_forecast(NWS.convert_to_json(record, ts))
                    self.cfg.forecasts.clear()
                    self.deleteOldRows();
        except Exception as e:
            # Include a stack traceback in the log:
            # but eat this exception as we don't want to bring down weewx
            # because ot this extension.
            weeutil.logger.log_traceback(log.critical, "    ****  ")

    def deleteOldRows(self):
        try:
            dbmanager = self.engine.db_binder.get_manager(self.data_binding)
            delete = "DELETE FROM ARCHIVE where dateTime < (SELECT MAX(dateTime) from archive)"
            dbmanager.getSql(delete)
        except weedb.DatabaseError as e:
            log.info('%s failed with %s.' % (delete, e))

    @staticmethod
    def convert_to_json(record, ts):
        j = {}
        j['dateTime']         = ts
        j['interval']         = record.interval
        j['usUnits']          = record.usUnits
        j['generatedTime']    = record.generatedTime
        j['number']           = record.number
        if record.name:
            j['name']         = record.name
        j['startTime']        = record.startTime
        j['endTime']          = record.endTime
        j['isDaytime']        = record.isDaytime
        j['outTemp']          = record.outTemp
        if record.outTempTrend:
            j['outTempTrend'] = record.outTempTrend
        j['windSpeed']        = record.windSpeed
        if record.windDir:
            j['windDir']      = record.windDir
        j['iconUrl']          = record.iconUrl
        j['shortForecast']    = record.shortForecast
        if record.detailedForecast:
            j['detailedForecast'] = record.detailedForecast
        return j

    def save_forecast(self, record):
        """save data to database"""
        dbmanager = self.engine.db_binder.get_manager(self.data_binding)
        dbmanager.addRecord(record)

class NWSPoller:
    def __init__(self, cfg: Configuration):
        self.cfg = cfg

    def poll_nws(self) -> None:
        while True:
            success = NWSPoller.populate_forecast(self.cfg)
            if success:
                sleep_time = NWSPoller.time_to_next_poll()
                log.debug('NWSPoller: poll_nws: Sleeping for %f seconds.' % sleep_time) 
                time.sleep(sleep_time)
            else:
                time.sleep(10)

    @staticmethod
    def populate_forecast(cfg) -> bool:
        start_time = time.time()
        j = NWSPoller.request_forecast(cfg)
        if j == None:
            return False
        else:
            elapsed_time = time.time() - start_time
            log.debug('Queries to NWS took %f seconds' % elapsed_time)
            with cfg.lock:
                cfg.forecasts.clear()
                for record in NWSPoller.compose_records(j):
                    log.debug('NWSPoller: poll_nws: adding forecast(%s)' % record)
                    cfg.forecasts.append(record)
            return True

    @staticmethod
    def time_to_next_poll():
        # Poll at the top of the hour.
        time_of_next_poll = int(time.time() / 3600) * 3600 + 3600
        return time_of_next_poll - time.time()

    @staticmethod
    def request_forecast(cfg):
        try:
            url = 'https://api.weather.gov/points/%s,%s' % (cfg.latitude, cfg.longitude)
            session= requests.Session()
            headers = {'User-Agent': cfg.user_agent}
            log.debug('request_forecast: headers: %s' % headers)
            response: requests.Response = session.get(url=url, headers=headers, timeout=cfg.timeout_secs)
            response.raise_for_status()
            log.debug('request_forecast: %s returned %r' % (url, response))
            if response:
                j: Dict[str, Any] = response.json()
                log.debug('id: %s' % j['id'])
                log.debug('type: %s' % j['type'])
                log.debug('geometry: %s' % j['geometry'])
                for k in j['properties']:
                    log.debug('properties key:  %s, value: %s' % (k, j['properties'][k]))
                hourlyForecastUrl = j['properties']['forecastHourly']
                log.debug('hourlyForecastUrl: %s' % hourlyForecastUrl)
                response2: requests.Response = session.get(url=hourlyForecastUrl, timeout=cfg.timeout_secs)
                return response2.json()
            else:
                log.info('request_forecast: Fetch from: %s did not succeeed: %r.' % (url, response))
                return None
        except Exception as e:
            log.info('request_forecast: Attempt to fetch from: %s failed: %s.' % (url, e))
            return None

    @staticmethod
    def compose_records(j):
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
                interval         = 60,
                usUnits          = units,
                generatedTime    = updateTime,
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
        elif wdir_str == 'NE':
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

    def hourly_forecasts(self, max_forecasts=100):
        """Returns the latest hourly forecast records."""
        rows = self.getLatestHourlyForecastRows(max_forecasts)
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

    def getLatestHourlyForecastRows(self, max_forecasts):
        """get the latest hourly forecast"""
        dict = weewx.manager.get_manager_dict(self.generator.config_dict['DataBindings'],
                                                  self.generator.config_dict['Databases'],self.binding)
        with weewx.manager.open_manager(dict) as dbm:
            # Latest insert date
            select = "SELECT dateTime, interval, usUnits, generatedTime, number, name, startTime, endTime, isDaytime, outTemp, outTempTrend, windSpeed, windDir, iconUrl, shortForecast, detailedForecast FROM archive where dateTime = (SELECT MAX(dateTime) from archive) ORDER BY startTime LIMIT %d" % max_forecasts
            try:
                records = []
                columns = dbm.connection.columnsOf(dbm.table_name)
                for row in dbm.genSql(select):
                    record = {}
                    for i, f in enumerate(columns):
                        record[f] = row[i]
                    records.append(record)
                return records
            except weedb.DatabaseError as e:
                log.info('%s failed with %s.' % (select, e))
        return []

def pretty_print(record):
    print('interval        : %d' % record.interval)
    print('usUnits         : %s' % record.usUnits)
    print('generatedTime   : %s' % timestamp_to_string(record.generatedTime))
    print('number          : %d' % record.number)
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
        lock          = threading.Lock(),
        forecasts    = [],
        latitude     = 37.431495,
        longitude    = -122.110937,
        timeout_secs = 5,
        archive_interval = 300,
        user_agent = '(weewx-nws test run, weewx-nws-developer)',
        )
    j = NWSPoller.request_forecast(cfg)
    for record in NWSPoller.compose_records(j):
        print('NWSPoller: poll_nws: adding forecast(%s)' % record)

    for record in NWSPoller.compose_records(j):
        pretty_print(record)
        print('------------------------')

    for record in NWSPoller.compose_records(j):
        print(NWS.convert_to_json(record, 0))
