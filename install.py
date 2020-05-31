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

from setup import ExtensionInstaller

def loader():
    return NWSInstaller()

class NWSInstaller(ExtensionInstaller):
    def __init__(self):
        super(NWSInstaller, self).__init__(
            version="0.2",
            name='nws',
            description='Fetch NWS Hourly Forecast.',
            author="John A Kline",
            author_email="john@johnkline.com",
            data_services='user.nws.NWS',
            config={
                'NWS': {
                    'data_binding'   : 'nws_binding',
                    'days_to_keep'   : 90,
                    'poll_secs'      : 1800,
                    'retry_wait_secs': 30,
                    'timeout_secs'   : 5,
                    'User-Agent'     : '(my-weather-site.com, me@my-weather-site.com)',
                },
                'DataBindings': {
                    'nws_binding': {
                        'manager'   : 'weewx.manager.Manager',
                        'schema'    : 'user.nws.schema',
                        'table_name': 'archive',
                        'database'  : 'nws_sqlite'}},
                'Databases': {
                    'nws_sqlite': {
                        'database_name': 'nws.sdb',
                        'driver': 'weedb.sqlite'}},
            },
            files=[('bin/user', ['bin/user/nws.py']), ]
            )
