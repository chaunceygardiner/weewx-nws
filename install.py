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
    # This section configures the weewx-nws extension.  The manual is at
    # https://chaunceygardiner.github.io/weewx-nws/
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
            version="6.0",
            name='nws',
            description='Fetch NWS Hourly Forecast.',
            author="John A Kline",
            author_email="john@johnkline.com",
            data_services='user.nws.NWS',
            config=nws_dict,
            files=[
                ('bin/user', ['bin/user/nws.py', 'bin/user/nwsicons.py',
                              'bin/user/nwsskin.py']),
                ('skins/nws', [
                    'skins/nws/alerts.html.tmpl',
                    'skins/nws/hours.html.tmpl',
                    'skins/nws/index.html.tmpl',
                    'skins/nws/menubar.inc',
                    'skins/nws/skin.conf',
                ]),
                ('skins/nws/css', ['skins/nws/css/nws.css']),
                ('skins/nws/scripts', ['skins/nws/scripts/nws.js']),
            ]
        )
