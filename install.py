# Copyright 2020-2026 by John A Kline <john@johnkline.com>
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

from io import StringIO

import configobj

from setup import ExtensionInstaller

# The stanza a fresh install writes into weewx.conf, as text rather than a
# dict so that ConfigObj carries its comments into the user's file.  An
# option that only selects a default is written commented out, so that the
# extension's own fallback -- and a better one in some later release -- goes
# on governing; weectl fills in absent keys only and never rewrites a value
# that is already there, so a value written live here would pin the station
# to it for ever.
#
# Live in [NWS]: data_binding and User-Agent.  The rest -- days_to_keep, the
# poll/retry seconds and timeout_secs -- are written commented out.
#
# ORDER MATTERS: ConfigObj attaches a comment block to the NEXT key, and
# conditional_merge transfers a key's comments only when it CREATES that
# key.  [NWS] is followed by [DataBindings], which every real weewx.conf
# already has, so a comment block left last in [NWS] is not misplaced -- it
# is dropped without trace.  Hence User-Agent last in [NWS], and the prose
# for the other sections on the subsection weectl creates.
CONFIG = """
[NWS]
    # This section configures the weewx-nws extension.  See the README.md
    # for details.
    #
    # An option shown commented out is one the extension supplies itself.
    # Leave it commented and the extension's own value governs, including a
    # better one a later release might bring.  Uncomment it to pin this
    # station to the value written here.

    # The data binding used for the forecast database.  The install also
    # seeds the matching nws_binding and nws_sqlite entries under
    # [DataBindings] and [Databases]; there is no reason to change any of it.
    data_binding = nws_binding

    # Days of old forecasts to keep in the database (0 keeps them for ever).
    # Expired alerts are always deleted, whatever this is set to.  Keeping a
    # large number of days slows things down.
    #days_to_keep = 9

    # Seconds between requests for forecasts (twelve-hour and one-hour).
    # Polls align to the wall clock: 1800 polls on the hour and half hour.
    #poll_secs = 1800

    # Seconds between requests for alerts.  Alerts are polled more often
    # than forecasts because they are time critical.
    #alert_poll_secs = 600

    # Seconds to wait before trying NWS again after repeated failures.  A
    # transient failure is first retried a few times seconds apart; these
    # govern the wait once NWS looks to be down.
    #retry_wait_secs = 300
    #alert_retry_wait_secs = 30

    # Seconds before a request to NWS times out.
    #timeout_secs = 10

    # PLACEHOLDER -- replace with your own weather site and contact address.
    # NWS's API rules ask that every request say who is making it, and this
    # is sent as the User-Agent header on all of them.  It is the one option
    # in this section that must be edited.
    User-Agent = "(my-weather-site.com, me@my-weather-site.com)"

[DataBindings]
    [[nws_binding]]
        # weewx-nws keeps its forecasts and alerts in a database of its own
        # (nws.sdb), separate from the weather archive.
        manager = weewx.manager.Manager
        schema = user.nws.schema
        table_name = archive
        database = nws_sqlite

[Databases]
    [[nws_sqlite]]
        # The database named by nws_binding above.  It lands in the same
        # directory as the weather archive.
        database_name = nws.sdb
        driver = weedb.sqlite

[StdReport]
    [[NWSReport]]
        # The "NWSReport" uses the "nws" skin, which showcases the extension:
        # a twelve-hour forecast page, a one-hour forecast page and an alerts
        # page.  Files are placed in a dedicated subdirectory.
        HTML_ROOT = nws
        enable = true
        skin = nws
"""

nws_dict = configobj.ConfigObj(StringIO(CONFIG), encoding='utf-8')

def loader():
    return NWSInstaller()

class NWSInstaller(ExtensionInstaller):
    def __init__(self):
        super(NWSInstaller, self).__init__(
            version="5.1",
            name='nws',
            description='Fetch NWS Hourly Forecast.',
            author="John A Kline",
            author_email="john@johnkline.com",
            data_services='user.nws.NWS',
            config=nws_dict,
            files=[
                ('bin/user', ['bin/user/nws.py']),
                ('skins/nws', [
                    'skins/nws/alerts.html.tmpl',
                    'skins/nws/hours.html.tmpl',
                    'skins/nws/index.html.tmpl',
                    'skins/nws/menubar.inc',
                    'skins/nws/skin.conf',
                    'skins/nws/style.inc',
                    'skins/nws/nws_icons/large/night/dust',
                    'skins/nws/nws_icons/large/night/sleet',
                    'skins/nws/nws_icons/large/night/fog',
                    'skins/nws/nws_icons/large/night/cold',
                    'skins/nws/nws_icons/large/night/hot',
                    'skins/nws/nws_icons/large/night/rain_showers',
                    'skins/nws/nws_icons/large/night/wind_bkn',
                    'skins/nws/nws_icons/large/night/smoke',
                    'skins/nws/nws_icons/large/night/wind_skc',
                    'skins/nws/nws_icons/large/night/skc',
                    'skins/nws/nws_icons/large/night/tsra',
                    'skins/nws/nws_icons/large/night/rain',
                    'skins/nws/nws_icons/large/night/snow',
                    'skins/nws/nws_icons/large/night/sct',
                    'skins/nws/nws_icons/large/night/tsra_sct',
                    'skins/nws/nws_icons/large/night/ovc',
                    'skins/nws/nws_icons/large/night/rain_sleet',
                    'skins/nws/nws_icons/large/night/rain_snow',
                    'skins/nws/nws_icons/large/night/tropical_storm',
                    'skins/nws/nws_icons/large/night/fzra',
                    'skins/nws/nws_icons/large/night/haze',
                    'skins/nws/nws_icons/large/night/few',
                    'skins/nws/nws_icons/large/night/snow_sleet',
                    'skins/nws/nws_icons/large/night/rain_fzra',
                    'skins/nws/nws_icons/large/night/tornado',
                    'skins/nws/nws_icons/large/night/tsra_hi',
                    'skins/nws/nws_icons/large/night/wind_ovc',
                    'skins/nws/nws_icons/large/night/blizzard',
                    'skins/nws/nws_icons/large/night/snow_fzra',
                    'skins/nws/nws_icons/large/night/hurricane',
                    'skins/nws/nws_icons/large/night/rain_showers_hi',
                    'skins/nws/nws_icons/large/night/wind_few',
                    'skins/nws/nws_icons/large/night/bkn',
                    'skins/nws/nws_icons/large/night/wind_sct',
                    'skins/nws/nws_icons/large/day/dust',
                    'skins/nws/nws_icons/large/day/sleet',
                    'skins/nws/nws_icons/large/day/fog',
                    'skins/nws/nws_icons/large/day/cold',
                    'skins/nws/nws_icons/large/day/hot',
                    'skins/nws/nws_icons/large/day/rain_showers',
                    'skins/nws/nws_icons/large/day/wind_bkn',
                    'skins/nws/nws_icons/large/day/smoke',
                    'skins/nws/nws_icons/large/day/wind_skc',
                    'skins/nws/nws_icons/large/day/skc',
                    'skins/nws/nws_icons/large/day/tsra',
                    'skins/nws/nws_icons/large/day/rain',
                    'skins/nws/nws_icons/large/day/snow',
                    'skins/nws/nws_icons/large/day/sct',
                    'skins/nws/nws_icons/large/day/tsra_sct',
                    'skins/nws/nws_icons/large/day/ovc',
                    'skins/nws/nws_icons/large/day/rain_sleet',
                    'skins/nws/nws_icons/large/day/rain_snow',
                    'skins/nws/nws_icons/large/day/tropical_storm',
                    'skins/nws/nws_icons/large/day/fzra',
                    'skins/nws/nws_icons/large/day/haze',
                    'skins/nws/nws_icons/large/day/few',
                    'skins/nws/nws_icons/large/day/snow_sleet',
                    'skins/nws/nws_icons/large/day/rain_fzra',
                    'skins/nws/nws_icons/large/day/tornado',
                    'skins/nws/nws_icons/large/day/tsra_hi',
                    'skins/nws/nws_icons/large/day/wind_ovc',
                    'skins/nws/nws_icons/large/day/blizzard',
                    'skins/nws/nws_icons/large/day/snow_fzra',
                    'skins/nws/nws_icons/large/day/hurricane',
                    'skins/nws/nws_icons/large/day/rain_showers_hi',
                    'skins/nws/nws_icons/large/day/wind_few',
                    'skins/nws/nws_icons/large/day/bkn',
                    'skins/nws/nws_icons/large/day/wind_sct',
                    'skins/nws/nws_icons/small/night/dust',
                    'skins/nws/nws_icons/small/night/sleet',
                    'skins/nws/nws_icons/small/night/fog',
                    'skins/nws/nws_icons/small/night/cold',
                    'skins/nws/nws_icons/small/night/hot',
                    'skins/nws/nws_icons/small/night/rain_showers',
                    'skins/nws/nws_icons/small/night/wind_bkn',
                    'skins/nws/nws_icons/small/night/smoke',
                    'skins/nws/nws_icons/small/night/wind_skc',
                    'skins/nws/nws_icons/small/night/skc',
                    'skins/nws/nws_icons/small/night/tsra',
                    'skins/nws/nws_icons/small/night/rain',
                    'skins/nws/nws_icons/small/night/snow',
                    'skins/nws/nws_icons/small/night/sct',
                    'skins/nws/nws_icons/small/night/tsra_sct',
                    'skins/nws/nws_icons/small/night/ovc',
                    'skins/nws/nws_icons/small/night/rain_sleet',
                    'skins/nws/nws_icons/small/night/rain_snow',
                    'skins/nws/nws_icons/small/night/tropical_storm',
                    'skins/nws/nws_icons/small/night/fzra',
                    'skins/nws/nws_icons/small/night/haze',
                    'skins/nws/nws_icons/small/night/few',
                    'skins/nws/nws_icons/small/night/snow_sleet',
                    'skins/nws/nws_icons/small/night/rain_fzra',
                    'skins/nws/nws_icons/small/night/tornado',
                    'skins/nws/nws_icons/small/night/tsra_hi',
                    'skins/nws/nws_icons/small/night/wind_ovc',
                    'skins/nws/nws_icons/small/night/blizzard',
                    'skins/nws/nws_icons/small/night/snow_fzra',
                    'skins/nws/nws_icons/small/night/hurricane',
                    'skins/nws/nws_icons/small/night/rain_showers_hi',
                    'skins/nws/nws_icons/small/night/wind_few',
                    'skins/nws/nws_icons/small/night/bkn',
                    'skins/nws/nws_icons/small/night/wind_sct',
                    'skins/nws/nws_icons/small/day/dust',
                    'skins/nws/nws_icons/small/day/sleet',
                    'skins/nws/nws_icons/small/day/fog',
                    'skins/nws/nws_icons/small/day/cold',
                    'skins/nws/nws_icons/small/day/hot',
                    'skins/nws/nws_icons/small/day/rain_showers',
                    'skins/nws/nws_icons/small/day/wind_bkn',
                    'skins/nws/nws_icons/small/day/smoke',
                    'skins/nws/nws_icons/small/day/wind_skc',
                    'skins/nws/nws_icons/small/day/skc',
                    'skins/nws/nws_icons/small/day/tsra',
                    'skins/nws/nws_icons/small/day/rain',
                    'skins/nws/nws_icons/small/day/snow',
                    'skins/nws/nws_icons/small/day/sct',
                    'skins/nws/nws_icons/small/day/tsra_sct',
                    'skins/nws/nws_icons/small/day/ovc',
                    'skins/nws/nws_icons/small/day/rain_sleet',
                    'skins/nws/nws_icons/small/day/rain_snow',
                    'skins/nws/nws_icons/small/day/tropical_storm',
                    'skins/nws/nws_icons/small/day/fzra',
                    'skins/nws/nws_icons/small/day/haze',
                    'skins/nws/nws_icons/small/day/few',
                    'skins/nws/nws_icons/small/day/snow_sleet',
                    'skins/nws/nws_icons/small/day/rain_fzra',
                    'skins/nws/nws_icons/small/day/tornado',
                    'skins/nws/nws_icons/small/day/tsra_hi',
                    'skins/nws/nws_icons/small/day/wind_ovc',
                    'skins/nws/nws_icons/small/day/blizzard',
                    'skins/nws/nws_icons/small/day/snow_fzra',
                    'skins/nws/nws_icons/small/day/hurricane',
                    'skins/nws/nws_icons/small/day/rain_showers_hi',
                    'skins/nws/nws_icons/small/day/wind_few',
                    'skins/nws/nws_icons/small/day/bkn',
                    'skins/nws/nws_icons/small/day/wind_sct',
                    'skins/nws/nws_icons/medium/night/dust',
                    'skins/nws/nws_icons/medium/night/sleet',
                    'skins/nws/nws_icons/medium/night/fog',
                    'skins/nws/nws_icons/medium/night/cold',
                    'skins/nws/nws_icons/medium/night/hot',
                    'skins/nws/nws_icons/medium/night/rain_showers',
                    'skins/nws/nws_icons/medium/night/wind_bkn',
                    'skins/nws/nws_icons/medium/night/smoke',
                    'skins/nws/nws_icons/medium/night/wind_skc',
                    'skins/nws/nws_icons/medium/night/skc',
                    'skins/nws/nws_icons/medium/night/tsra',
                    'skins/nws/nws_icons/medium/night/rain',
                    'skins/nws/nws_icons/medium/night/snow',
                    'skins/nws/nws_icons/medium/night/sct',
                    'skins/nws/nws_icons/medium/night/tsra_sct',
                    'skins/nws/nws_icons/medium/night/ovc',
                    'skins/nws/nws_icons/medium/night/rain_sleet',
                    'skins/nws/nws_icons/medium/night/rain_snow',
                    'skins/nws/nws_icons/medium/night/tropical_storm',
                    'skins/nws/nws_icons/medium/night/fzra',
                    'skins/nws/nws_icons/medium/night/haze',
                    'skins/nws/nws_icons/medium/night/few',
                    'skins/nws/nws_icons/medium/night/snow_sleet',
                    'skins/nws/nws_icons/medium/night/rain_fzra',
                    'skins/nws/nws_icons/medium/night/tornado',
                    'skins/nws/nws_icons/medium/night/tsra_hi',
                    'skins/nws/nws_icons/medium/night/wind_ovc',
                    'skins/nws/nws_icons/medium/night/blizzard',
                    'skins/nws/nws_icons/medium/night/snow_fzra',
                    'skins/nws/nws_icons/medium/night/hurricane',
                    'skins/nws/nws_icons/medium/night/rain_showers_hi',
                    'skins/nws/nws_icons/medium/night/wind_few',
                    'skins/nws/nws_icons/medium/night/bkn',
                    'skins/nws/nws_icons/medium/night/wind_sct',
                    'skins/nws/nws_icons/medium/day/dust',
                    'skins/nws/nws_icons/medium/day/sleet',
                    'skins/nws/nws_icons/medium/day/fog',
                    'skins/nws/nws_icons/medium/day/cold',
                    'skins/nws/nws_icons/medium/day/hot',
                    'skins/nws/nws_icons/medium/day/rain_showers',
                    'skins/nws/nws_icons/medium/day/wind_bkn',
                    'skins/nws/nws_icons/medium/day/smoke',
                    'skins/nws/nws_icons/medium/day/wind_skc',
                    'skins/nws/nws_icons/medium/day/skc',
                    'skins/nws/nws_icons/medium/day/tsra',
                    'skins/nws/nws_icons/medium/day/rain',
                    'skins/nws/nws_icons/medium/day/snow',
                    'skins/nws/nws_icons/medium/day/sct',
                    'skins/nws/nws_icons/medium/day/tsra_sct',
                    'skins/nws/nws_icons/medium/day/ovc',
                    'skins/nws/nws_icons/medium/day/rain_sleet',
                    'skins/nws/nws_icons/medium/day/rain_snow',
                    'skins/nws/nws_icons/medium/day/tropical_storm',
                    'skins/nws/nws_icons/medium/day/fzra',
                    'skins/nws/nws_icons/medium/day/haze',
                    'skins/nws/nws_icons/medium/day/few',
                    'skins/nws/nws_icons/medium/day/snow_sleet',
                    'skins/nws/nws_icons/medium/day/rain_fzra',
                    'skins/nws/nws_icons/medium/day/tornado',
                    'skins/nws/nws_icons/medium/day/tsra_hi',
                    'skins/nws/nws_icons/medium/day/wind_ovc',
                    'skins/nws/nws_icons/medium/day/blizzard',
                    'skins/nws/nws_icons/medium/day/snow_fzra',
                    'skins/nws/nws_icons/medium/day/hurricane',
                    'skins/nws/nws_icons/medium/day/rain_showers_hi',
                    'skins/nws/nws_icons/medium/day/wind_few',
                    'skins/nws/nws_icons/medium/day/bkn',
                    'skins/nws/nws_icons/medium/day/wind_sct',
                ]),
            ]
        )
