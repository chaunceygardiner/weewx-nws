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

from setup import ExtensionInstaller

def loader():
    return NWSInstaller()

class NWSInstaller(ExtensionInstaller):
    def __init__(self):
        super(NWSInstaller, self).__init__(
            version="4.1",
            name='nws',
            description='Fetch NWS Hourly Forecast.',
            author="John A Kline",
            author_email="john@johnkline.com",
            data_services='user.nws.NWS',
            config={
                'NWS': {
                    'data_binding'         : 'nws_binding',
                    'days_to_keep'         : 9,
                    'poll_secs'            : 1800,
                    'alert_poll_secs'      : 600,
                    'retry_wait_secs'      : 300,
                    'alert_retry_wait_secs': 30,
                    'timeout_secs'         : 10,
                    'User-Agent'           : '(my-weather-site.com, me@my-weather-site.com)',
                },
                'DataBindings': {
                    'nws_binding': {
                        'manager'   : 'weewx.manager.Manager',
                        'schema'    : 'user.nws.schema',
                        'table_name': 'archive',
                        'database'  : 'nws_sqlite'
                    }
                },
                'Databases': {
                    'nws_sqlite': {
                        'database_name': 'nws.sdb',
                        'driver': 'weedb.sqlite'
                    }
                },
                'StdReport': {
                    'NWSReport': {
                        'HTML_ROOT':'nws',
                        'enable': 'true',
                        'skin':'nws',
                    },
                },
            },
            files=[
                ('bin/user', ['bin/user/nws.py']),
                ('skins/nws', [
                    'skins/nws/forecast_alerts.inc',
                    'skins/nws/forecast_days.inc',
                    'skins/nws/forecast_hours.inc',
                    'skins/nws/index.html.tmpl',
                    'skins/nws/skin.conf',
                    'skins/nws/icons/large/night/dust',
                    'skins/nws/icons/large/night/sleet',
                    'skins/nws/icons/large/night/fog',
                    'skins/nws/icons/large/night/cold',
                    'skins/nws/icons/large/night/hot',
                    'skins/nws/icons/large/night/rain_showers',
                    'skins/nws/icons/large/night/wind_bkn',
                    'skins/nws/icons/large/night/smoke',
                    'skins/nws/icons/large/night/wind_skc',
                    'skins/nws/icons/large/night/skc',
                    'skins/nws/icons/large/night/tsra',
                    'skins/nws/icons/large/night/rain',
                    'skins/nws/icons/large/night/snow',
                    'skins/nws/icons/large/night/sct',
                    'skins/nws/icons/large/night/tsra_sct',
                    'skins/nws/icons/large/night/ovc',
                    'skins/nws/icons/large/night/rain_sleet',
                    'skins/nws/icons/large/night/rain_snow',
                    'skins/nws/icons/large/night/tropical_storm',
                    'skins/nws/icons/large/night/fzra',
                    'skins/nws/icons/large/night/haze',
                    'skins/nws/icons/large/night/few',
                    'skins/nws/icons/large/night/snow_sleet',
                    'skins/nws/icons/large/night/rain_fzra',
                    'skins/nws/icons/large/night/tornado',
                    'skins/nws/icons/large/night/tsra_hi',
                    'skins/nws/icons/large/night/wind_ovc',
                    'skins/nws/icons/large/night/blizzard',
                    'skins/nws/icons/large/night/snow_fzra',
                    'skins/nws/icons/large/night/hurricane',
                    'skins/nws/icons/large/night/rain_showers_hi',
                    'skins/nws/icons/large/night/wind_few',
                    'skins/nws/icons/large/night/bkn',
                    'skins/nws/icons/large/night/wind_sct',
                    'skins/nws/icons/large/day/dust',
                    'skins/nws/icons/large/day/sleet',
                    'skins/nws/icons/large/day/fog',
                    'skins/nws/icons/large/day/cold',
                    'skins/nws/icons/large/day/hot',
                    'skins/nws/icons/large/day/rain_showers',
                    'skins/nws/icons/large/day/wind_bkn',
                    'skins/nws/icons/large/day/smoke',
                    'skins/nws/icons/large/day/wind_skc',
                    'skins/nws/icons/large/day/skc',
                    'skins/nws/icons/large/day/tsra',
                    'skins/nws/icons/large/day/rain',
                    'skins/nws/icons/large/day/snow',
                    'skins/nws/icons/large/day/sct',
                    'skins/nws/icons/large/day/tsra_sct',
                    'skins/nws/icons/large/day/ovc',
                    'skins/nws/icons/large/day/rain_sleet',
                    'skins/nws/icons/large/day/rain_snow',
                    'skins/nws/icons/large/day/tropical_storm',
                    'skins/nws/icons/large/day/fzra',
                    'skins/nws/icons/large/day/haze',
                    'skins/nws/icons/large/day/few',
                    'skins/nws/icons/large/day/snow_sleet',
                    'skins/nws/icons/large/day/rain_fzra',
                    'skins/nws/icons/large/day/tornado',
                    'skins/nws/icons/large/day/tsra_hi',
                    'skins/nws/icons/large/day/wind_ovc',
                    'skins/nws/icons/large/day/blizzard',
                    'skins/nws/icons/large/day/snow_fzra',
                    'skins/nws/icons/large/day/hurricane',
                    'skins/nws/icons/large/day/rain_showers_hi',
                    'skins/nws/icons/large/day/wind_few',
                    'skins/nws/icons/large/day/bkn',
                    'skins/nws/icons/large/day/wind_sct',
                    'skins/nws/icons/small/night/dust',
                    'skins/nws/icons/small/night/sleet',
                    'skins/nws/icons/small/night/fog',
                    'skins/nws/icons/small/night/cold',
                    'skins/nws/icons/small/night/hot',
                    'skins/nws/icons/small/night/rain_showers',
                    'skins/nws/icons/small/night/wind_bkn',
                    'skins/nws/icons/small/night/smoke',
                    'skins/nws/icons/small/night/wind_skc',
                    'skins/nws/icons/small/night/skc',
                    'skins/nws/icons/small/night/tsra',
                    'skins/nws/icons/small/night/rain',
                    'skins/nws/icons/small/night/snow',
                    'skins/nws/icons/small/night/sct',
                    'skins/nws/icons/small/night/tsra_sct',
                    'skins/nws/icons/small/night/ovc',
                    'skins/nws/icons/small/night/rain_sleet',
                    'skins/nws/icons/small/night/rain_snow',
                    'skins/nws/icons/small/night/tropical_storm',
                    'skins/nws/icons/small/night/fzra',
                    'skins/nws/icons/small/night/haze',
                    'skins/nws/icons/small/night/few',
                    'skins/nws/icons/small/night/snow_sleet',
                    'skins/nws/icons/small/night/rain_fzra',
                    'skins/nws/icons/small/night/tornado',
                    'skins/nws/icons/small/night/tsra_hi',
                    'skins/nws/icons/small/night/wind_ovc',
                    'skins/nws/icons/small/night/blizzard',
                    'skins/nws/icons/small/night/snow_fzra',
                    'skins/nws/icons/small/night/hurricane',
                    'skins/nws/icons/small/night/rain_showers_hi',
                    'skins/nws/icons/small/night/wind_few',
                    'skins/nws/icons/small/night/bkn',
                    'skins/nws/icons/small/night/wind_sct',
                    'skins/nws/icons/small/day/dust',
                    'skins/nws/icons/small/day/sleet',
                    'skins/nws/icons/small/day/fog',
                    'skins/nws/icons/small/day/cold',
                    'skins/nws/icons/small/day/hot',
                    'skins/nws/icons/small/day/rain_showers',
                    'skins/nws/icons/small/day/wind_bkn',
                    'skins/nws/icons/small/day/smoke',
                    'skins/nws/icons/small/day/wind_skc',
                    'skins/nws/icons/small/day/skc',
                    'skins/nws/icons/small/day/tsra',
                    'skins/nws/icons/small/day/rain',
                    'skins/nws/icons/small/day/snow',
                    'skins/nws/icons/small/day/sct',
                    'skins/nws/icons/small/day/tsra_sct',
                    'skins/nws/icons/small/day/ovc',
                    'skins/nws/icons/small/day/rain_sleet',
                    'skins/nws/icons/small/day/rain_snow',
                    'skins/nws/icons/small/day/tropical_storm',
                    'skins/nws/icons/small/day/fzra',
                    'skins/nws/icons/small/day/haze',
                    'skins/nws/icons/small/day/few',
                    'skins/nws/icons/small/day/snow_sleet',
                    'skins/nws/icons/small/day/rain_fzra',
                    'skins/nws/icons/small/day/tornado',
                    'skins/nws/icons/small/day/tsra_hi',
                    'skins/nws/icons/small/day/wind_ovc',
                    'skins/nws/icons/small/day/blizzard',
                    'skins/nws/icons/small/day/snow_fzra',
                    'skins/nws/icons/small/day/hurricane',
                    'skins/nws/icons/small/day/rain_showers_hi',
                    'skins/nws/icons/small/day/wind_few',
                    'skins/nws/icons/small/day/bkn',
                    'skins/nws/icons/small/day/wind_sct',
                    'skins/nws/icons/medium/night/dust',
                    'skins/nws/icons/medium/night/sleet',
                    'skins/nws/icons/medium/night/fog',
                    'skins/nws/icons/medium/night/cold',
                    'skins/nws/icons/medium/night/hot',
                    'skins/nws/icons/medium/night/rain_showers',
                    'skins/nws/icons/medium/night/wind_bkn',
                    'skins/nws/icons/medium/night/smoke',
                    'skins/nws/icons/medium/night/wind_skc',
                    'skins/nws/icons/medium/night/skc',
                    'skins/nws/icons/medium/night/tsra',
                    'skins/nws/icons/medium/night/rain',
                    'skins/nws/icons/medium/night/snow',
                    'skins/nws/icons/medium/night/sct',
                    'skins/nws/icons/medium/night/tsra_sct',
                    'skins/nws/icons/medium/night/ovc',
                    'skins/nws/icons/medium/night/rain_sleet',
                    'skins/nws/icons/medium/night/rain_snow',
                    'skins/nws/icons/medium/night/tropical_storm',
                    'skins/nws/icons/medium/night/fzra',
                    'skins/nws/icons/medium/night/haze',
                    'skins/nws/icons/medium/night/few',
                    'skins/nws/icons/medium/night/snow_sleet',
                    'skins/nws/icons/medium/night/rain_fzra',
                    'skins/nws/icons/medium/night/tornado',
                    'skins/nws/icons/medium/night/tsra_hi',
                    'skins/nws/icons/medium/night/wind_ovc',
                    'skins/nws/icons/medium/night/blizzard',
                    'skins/nws/icons/medium/night/snow_fzra',
                    'skins/nws/icons/medium/night/hurricane',
                    'skins/nws/icons/medium/night/rain_showers_hi',
                    'skins/nws/icons/medium/night/wind_few',
                    'skins/nws/icons/medium/night/bkn',
                    'skins/nws/icons/medium/night/wind_sct',
                    'skins/nws/icons/medium/day/dust',
                    'skins/nws/icons/medium/day/sleet',
                    'skins/nws/icons/medium/day/fog',
                    'skins/nws/icons/medium/day/cold',
                    'skins/nws/icons/medium/day/hot',
                    'skins/nws/icons/medium/day/rain_showers',
                    'skins/nws/icons/medium/day/wind_bkn',
                    'skins/nws/icons/medium/day/smoke',
                    'skins/nws/icons/medium/day/wind_skc',
                    'skins/nws/icons/medium/day/skc',
                    'skins/nws/icons/medium/day/tsra',
                    'skins/nws/icons/medium/day/rain',
                    'skins/nws/icons/medium/day/snow',
                    'skins/nws/icons/medium/day/sct',
                    'skins/nws/icons/medium/day/tsra_sct',
                    'skins/nws/icons/medium/day/ovc',
                    'skins/nws/icons/medium/day/rain_sleet',
                    'skins/nws/icons/medium/day/rain_snow',
                    'skins/nws/icons/medium/day/tropical_storm',
                    'skins/nws/icons/medium/day/fzra',
                    'skins/nws/icons/medium/day/haze',
                    'skins/nws/icons/medium/day/few',
                    'skins/nws/icons/medium/day/snow_sleet',
                    'skins/nws/icons/medium/day/rain_fzra',
                    'skins/nws/icons/medium/day/tornado',
                    'skins/nws/icons/medium/day/tsra_hi',
                    'skins/nws/icons/medium/day/wind_ovc',
                    'skins/nws/icons/medium/day/blizzard',
                    'skins/nws/icons/medium/day/snow_fzra',
                    'skins/nws/icons/medium/day/hurricane',
                    'skins/nws/icons/medium/day/rain_showers_hi',
                    'skins/nws/icons/medium/day/wind_few',
                    'skins/nws/icons/medium/day/bkn',
                    'skins/nws/icons/medium/day/wind_sct',
                ]),
            ]
        )
