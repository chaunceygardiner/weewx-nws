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
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

"""The sample report's own presentation code: charts, chips and alert cards.

THIS IS NOT A CONTRACT.  Everything here is markup and layout -- one skin's
taste about how a forecast should look -- and it is deliberately separate from
the $nwsforecast tags in nws.py, which are.  Nothing in this module is
promised to survive a release, and a skin that wants a different look should
copy what it needs rather than call it.  The line between the two is worth
stating because it is easy to blur:

  nws.py     WHAT the feed means.  Grouping periods by calendar day, the
             chance-of-rain threshold's existence, which alert is more
             serious, how a CAP description is structured.  NWS and CAP
             semantics that every skin author would get subtly wrong, so
             every skin gets one answer.  Those are $nwsforecast tags.

  nwsicons.py  The drawn conditions, whose ids, classes and --wx-* color
             properties ARE a contract, because consuming skins write them
             into their own stylesheets.

  this file  How THIS report chooses to draw it: an svg chart at these
             dimensions, a droplet glyph, a severity rail, an em-dash for an
             absent number.  Presentation, duplicated rather than shared, and
             free to diverge from any other skin's.

Reached from the templates as $nwsskin.  Every mark the charts emit carries a
class and no inline color, so skins/nws/css/nws.css owns the palette and the
light/dark themes need nothing here.

Chart geometry is arithmetic over ~150 hourly records, which is Python's job
rather than Cheetah's: a template computing 150 path points with #for would be
unreadable and slow.  The templates ask for a finished <svg> and place it.
Three slices of one code path, because a week of hourly data and a day of it
answer different questions:

  sparkline()  ~150 h, no rain strip -- the week's RHYTHM, heading the 7 Day
               list, whose range bars already carry the highs and the lows.
  week_chart() ~150 h, full furniture: temperature, dew point and rain.
  day_chart()    24 h, same furniture, with hour labels that can be read and a
               dew-point spread that is actually visible -- which is exactly
               what 150 hours squeezed into 1040 units destroys.
"""

import datetime
import html
import json
import math
import re

from typing import Any, Dict, List, Optional, Tuple

from weewx.cheetahgenerator import SearchList

# Same dual-arm import as nws.py's for nwsicons, and for the same reason:
# under weewxd this module is `user.nwsskin` with WEEWX_ROOT/bin on the path,
# but nws.py is also run directly, where sys.path[0] IS bin/user and there is
# no `user` package for the dotted name to resolve through.
try:
    import user.nws as nws
except ImportError:
    import nws  # type: ignore[no-redef]


class NWSSkin(SearchList):
    """$nwsskin -- the sample report's charts, chips and alert cards."""

    def get_extension_list(self, timespan, db_lookup) -> List[Dict[str, 'NWSSkin']]:
        return [{'nwsskin': self}]

    # ---- small formatting helpers ---------------------------------------

    @staticmethod
    def esc(text: Optional[str]) -> str:
        """Forecast prose comes straight out of the NWS feed and lands in
        markup.  Cheetah does not escape it -- `encoding = html_entities` only
        maps non-ASCII -- so an ampersand in a detailed forecast would reach
        the validator raw."""
        return html.escape(text or '')

    @staticmethod
    def hm(value: Any, fmt: str = '%-I:%M %p') -> str:
        """A time ValueHelper as these pages write clock times: 6:39 am, not
        06:39 AM.  One helper rather than a .replace() chain at every call
        site."""
        return value.format(fmt).replace('AM', 'am').replace('PM', 'pm')

    @staticmethod
    def num_cell(value: Any, suffix: str = '&deg;') -> str:
        """A rounded number with its bare unit, or an em-dash when the feed
        has none.

        Not `.format()`: that prints the literal "N/A" for an absent value,
        which would then get a degree sign glued to it.  The em-dash is also
        what the "Right now" card shows on a fresh install, where the
        station's own archive is still empty and $day.outTemp has nothing in
        it -- the sample report is often the first page a new user sees, so
        that case degrades rather than rendering blank.
        """
        if value is None or value.raw is None:
            return '&mdash;'
        return '%d%s' % (round(value.raw), suffix)

    @staticmethod
    def degrees(value: float) -> str:
        """A bare temperature the way these pages print one -- 56&deg;, no
        unit letter.  The row bars and the charts do the same, so a caption
        naming the week's range has to agree with them."""
        return '%d&deg;' % round(value)

    # ---- the chance of rain ---------------------------------------------

    # weather.gov's own threshold.  Below it the number is not shown: on a
    # typical week 13 of 14 periods and 155 of 156 hours fall under 15%, and a
    # column that always carries a value teaches the eye to skip it.  Blank on
    # the quiet days is what makes a number in it pull the eye.  The charts
    # still draw every hour's chance in full, so nothing is lost.
    POP_MIN = 15

    DROP = ('<svg class="drop" viewBox="0 0 8 10" aria-hidden="true">'
            '<path d="M4 0C4 0 7.5 4.2 7.5 6.4A3.5 3.5 0 0 1 .5 6.4C.5 4.2 4 0 4 0Z"/>'
            '</svg>')

    @staticmethod
    def pop_cell(period: Dict[str, Any]) -> str:
        """Chance of rain, blank below the threshold.

        A SUPPRESSED value renders as nothing at all; an ABSENT one renders as
        an em-dash, so a blank can never be misread as missing data.
        """
        v = period['pop'].raw
        if v is None:
            return '<span class="pop pop-na">&mdash;</span>'
        if v < NWSSkin.POP_MIN:
            return ''
        cls = 'pop' if v >= 20 else 'pop pop-lo'
        return '<span class="%s">%s%d%%</span>' % (cls, NWSSkin.DROP, round(v))

    # ---- wind ------------------------------------------------------------

    @staticmethod
    def _wind(period: Dict[str, Any], label: str) -> Tuple[str, str]:
        """(speed, direction) for a forecast period.  NWS gives a range on
        most periods and a single speed on the rest, and an absent direction
        is left out rather than printed as N/A.  `label` is the report's own
        $unit.label.windSpeed, so units stay the skin's to set."""
        lo = period['windSpeed'].raw
        if lo is None:
            return '', ''
        hi = period['windSpeed2'].raw if period['windSpeed2'] is not None else None
        if hi is None or round(hi) == round(lo):
            speed = '%d%s' % (round(lo), label)
        else:
            speed = '%d&ndash;%d%s' % (round(lo), round(hi), label)
        direction = period['windDir']
        if direction is None or direction.raw is None:
            return speed, ''
        return speed, direction.ordinal_compass()

    @staticmethod
    def wind_cell(period: Dict[str, Any], label: str) -> str:
        """The Wind column: speed over direction on the wide 7 Day rows, side
        by side in the hour table, which the stylesheet decides."""
        speed, direction = NWSSkin._wind(period, label)
        if not speed:
            return ''
        out = '<span class="w">%s</span>' % speed
        if direction:
            out += '<span class="wd">%s</span>' % direction
        return out

    @staticmethod
    def wind_text(period: Dict[str, Any], label: str) -> str:
        """The same wind as one plain run of text, for the "Right now" card's
        statistic -- which is a sentence, not a column."""
        speed, direction = NWSSkin._wind(period, label)
        if not speed:
            return '&mdash;'
        return ('%s %s' % (speed, direction)) if direction else speed

    # ---- the 7 Day temperature bar ---------------------------------------

    @staticmethod
    def temp_bar(entry: Dict[str, Any], tmin: float, tmax: float) -> str:
        """A day's low-to-high bar, positioned across the whole week's range
        so the days can be read against each other.

        `entry` is one row from $nwsforecast.days().  A day whose daylight
        period has already passed has no high left to show, and gets a single
        marker at its low rather than a two-pixel range.
        """
        span = max(tmax - tmin, 1.0)
        hi, lo = entry['hi'], entry['lo']
        if hi is None and lo is None:
            return '<span class="hi part">&mdash;</span>'
        if hi is None:
            pos = (lo - tmin) / span * 100.0
            return ('<span class="lo">%d&deg;</span><span class="track">'
                    '<span class="dot" style="left:%.1f%%"></span></span>'
                    '<span class="hi part">low</span>' % (round(lo), pos))
        bar_lo = lo if lo is not None else hi
        left = (bar_lo - tmin) / span * 100.0
        # The minimum width is what makes a one-value day visible at all --
        # the last day of the feed has a high and no night low yet -- but on
        # the day that HOLDS the week's high it would start at 100% and paint
        # those two per cent outside the track.  Clamp it back inside.
        width = max((hi - bar_lo) / span * 100.0, 2.0)
        left = min(left, 100.0 - width)
        lo_txt = '%d&deg;' % round(lo) if lo is not None else '&mdash;'
        return ('<span class="lo">%s</span><span class="track">'
                '<span class="fill" style="left:%.1f%%;width:%.1f%%"></span></span>'
                '<span class="hi">%d&deg;</span>'
                % (lo_txt, left, width, round(hi)))

    # ---- chart primitives -------------------------------------------------

    @staticmethod
    def _geom(hours: List[Dict[str, Any]], x0: float, x1: float):
        n = max(len(hours) - 1, 1)
        return lambda i: x0 + (x1 - x0) * i / n

    @staticmethod
    def _night_bands(hours: List[Dict[str, Any]], px, y0: int, y1: int,
                     last_i: Optional[int] = None) -> str:
        out, prev, start = [], None, 0
        end_i = last_i if last_i is not None else len(hours) - 1
        for i, h in enumerate(list(hours) + [None]):
            night = (not h['isDaytime']) if h else not prev
            if prev is None:
                prev, start = night, i
            elif night != prev or h is None:
                if prev:
                    a, b = px(start), px(min(i, end_i))
                    out.append('<rect x="%.1f" y="%d" width="%.1f" height="%d" class="night"/>'
                               % (a, y0, max(b - a, 0.5), y1 - y0))
                prev, start = night, i
        return ''.join(out)

    @staticmethod
    def _axis(lo: float, hi: float, step: int = 5) -> Tuple[int, int, int]:
        # floor/ceil, NOT int(): int() truncates toward zero, so for a
        # sub-zero reading it rounds UP -- int(-0.5) is 0, which would put the
        # axis floor above the data and draw the point below the plot.
        lo_ax = int(math.floor(lo / float(step))) * step
        hi_ax = int(math.ceil(hi / float(step))) * step
        return lo_ax, hi_ax, max(hi_ax - lo_ax, 1)

    @staticmethod
    def _path(hours: List[Dict[str, Any]], px, py, key: str) -> str:
        pts = [(i, h[key]) for i, h in enumerate(hours) if h.get(key) is not None]
        if not pts:
            return ''
        return 'M ' + ' L '.join('%.1f %.1f' % (px(i), py(v)) for i, v in pts)

    @staticmethod
    def _series(hours: List[Dict[str, Any]], x0: float, x1: float,
                ty0: int, ty1: int, lo_ax: int, span: int,
                with_dew_and_rain: bool = True) -> str:
        """The points the crosshair reads, plus the geometry it needs to
        invert a pointer position into an index.  Carried on the <svg> as
        data-chart so one small script drives every chart on the page.

        `with_dew_and_rain` is FALSE for the sparkline, and that is not a
        tidiness argument.  The crosshair positions the dew-point dot with
        the axis carried here, and the sparkline's axis is built from
        temperature ALONE -- so a dew point of 59 against a 75-80 scale
        computed to y=382 in a 132-unit viewBox, far outside the plot, while
        the readout announced a dew point and a chance of rain for two series
        the sparkline does not draw.  A chart may only report what it plots.
        """
        return json.dumps({
            'x0': x0, 'x1': x1, 'y0': ty0, 'y1': ty1,
            'lo': lo_ax, 'span': span,
            'p': [dict({
                't': datetime.datetime.fromtimestamp(h['startTime'])
                     .strftime('%a %-I %p').replace('AM', 'am').replace('PM', 'pm'),
                'T': round(h['outTemp']),
            }, **({
                'd': round(h['dewpoint']) if h['dewpoint'] is not None else None,
                'r': h['pop'] or 0,
            } if with_dew_and_rain else {})) for h in hours],
        }, separators=(',', ':'))

    # `off`, not the html `hidden` attribute: hidden is an HTML thing and is
    # not valid on an SVG <g> -- the Nu checker rejects it, and the UA's
    # [hidden] rule does not reach into SVG anyway, so it was never doing the
    # hiding.  The stylesheet owns the class and the page script toggles it.
    CROSS = ('<g class="cross off">'
             '<line class="cx" x1="0" y1="0" x2="0" y2="0"/>'
             '<circle class="cdot" r="3.4" cx="0" cy="0"/>'
             '<circle class="cdotd" r="2.8" cx="0" cy="0"/></g>')

    @staticmethod
    def _rain(hours: List[Dict[str, Any]], px, x0: float, x1: float,
              ry0: int, ry1: int, note: str) -> str:
        def ry(v):
            return ry1 - (ry1 - ry0) * min(max(v, 0), 100) / 100.0
        step = ['M %.1f %.1f' % (x0, ry1)]
        for i, h in enumerate(hours):
            step.append('L %.1f %.1f' % (px(i), ry(h['pop'] or 0)))
        step.append('L %.1f %.1f Z' % (px(len(hours) - 1), ry1))
        peak = max((h['pop'] or 0) for h in hours)
        return (
            '<text x="%d" y="%d" class="striplab">Chance of rain</text>'
            '<text x="%d" y="%d" class="striplab peak">%s %d%%</text>'
            '<line x1="%d" y1="%d" x2="%d" y2="%d" class="hgrid"/>'
            '<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" class="hgrid"/>'
            '<line x1="%d" y1="%d" x2="%d" y2="%d" class="axis"/>'
            '<text x="%d" y="%d" class="ylab rainlab">100%%</text>'
            '<text x="%d" y="%.1f" class="ylab rainlab">50</text>'
            '<text x="%d" y="%d" class="ylab rainlab">0</text>'
            '<path d="%s" class="parea"/>'
            % (x0, ry0 - 8, x1, ry0 - 8, note, peak,
               x0, ry0, x1, ry0, x0, ry(50), x1, ry(50), x0, ry1, x1, ry1,
               x0 - 6, ry0 + 4, x0 - 6, ry(50) + 4, x0 - 6, ry1 + 4, ' '.join(step)))

    # ---- the three charts -------------------------------------------------

    @staticmethod
    def sparkline(hours: List[Dict[str, Any]]) -> str:
        """The week's rhythm, WITH a temperature scale.

        Without a scale it says only "it cools at night" -- true, and worth
        nothing: you cannot tell how warm the afternoons get, how cold the
        nights get, or whether the week is trending.  Three labeled
        gridlines cost 20px and answer all three.  The instrument version,
        with dew point and the rain strip, is week_chart().
        """
        W, H = 1040, 132
        PADL = 34
        x0, x1, y0, y1 = PADL, W - 8, 12, 100
        px = NWSSkin._geom(hours, x0, x1)
        lo_ax, hi_ax, span = NWSSkin._axis(min(h['outTemp'] for h in hours),
                                           max(h['outTemp'] for h in hours))

        def py(t):
            return y1 - (y1 - y0) * (t - lo_ax) / span

        grid, ylab, labels, ticks = [], [], [], []
        for t in (lo_ax, (lo_ax + hi_ax) // 2, hi_ax):
            grid.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" class="hgrid"/>'
                        % (x0, py(t), x1, py(t)))
            ylab.append('<text x="%d" y="%.1f" class="ylab">%d&deg;</text>'
                        % (x0 - 6, py(t) + 4, t))
        for i, h in enumerate(hours):
            lt = datetime.datetime.fromtimestamp(h['startTime'])
            if lt.hour == 0 and i:
                ticks.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" class="vgrid"/>'
                             % (px(i), y0, px(i), y1))
            if lt.hour == 12:
                labels.append('<text x="%.1f" y="%d" class="xlab">%s</text>'
                              % (px(i), H - 6, lt.strftime('%a')))
        return ('<svg viewBox="0 0 %d %d" class="sparkcurve chart" data-chart=\'%s\' '
                'tabindex="0" role="img" aria-label="Forecast temperature every hour across the week, '
                'night shaded">%s%s%s%s<path d="%s" class="tline"/>%s%s</svg>'
                % (W, H, NWSSkin._series(hours, x0, x1, y0, y1, lo_ax, span,
                                          with_dew_and_rain=False),
                   NWSSkin._night_bands(hours, px, y0, y1), ''.join(grid), ''.join(ticks),
                   ''.join(ylab), NWSSkin._path(hours, px, py, 'outTemp'),
                   NWSSkin.CROSS, ''.join(labels)))

    @staticmethod
    def week_chart(hours: List[Dict[str, Any]]) -> str:
        """Every hour the feed carries, for the trend rather than the detail."""
        W, H = 1040, 306
        PADL, PADR = 48, 16
        TY0, TY1, RY0, RY1 = 18, 208, 238, 278
        x0, x1 = PADL, W - PADR
        px = NWSSkin._geom(hours, x0, x1)
        # `is not None`, not truthiness: a dew point of exactly 0 is a real
        # reading, and _path plots it, so the axis has to contain it.  This
        # line is written out again in day_chart(); both paths are tested.
        vals = ([h['outTemp'] for h in hours]
                + [h['dewpoint'] for h in hours if h['dewpoint'] is not None])
        lo_ax, hi_ax, span = NWSSkin._axis(min(vals), max(vals))

        def py(t):
            return TY1 - (TY1 - TY0) * (t - lo_ax) / span

        hgrid, ylab, ticks, labels = [], [], [], []
        t = lo_ax
        while t <= hi_ax:
            hgrid.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" class="hgrid"/>'
                         % (x0, py(t), x1, py(t)))
            ylab.append('<text x="%d" y="%.1f" class="ylab">%d&deg;</text>'
                        % (x0 - 6, py(t) + 4, t))
            t += 5
        for i, h in enumerate(hours):
            lt = datetime.datetime.fromtimestamp(h['startTime'])
            if lt.hour == 0 and i:
                ticks.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" class="vgrid"/>'
                             % (px(i), TY0, px(i), TY1))
            if lt.hour == 12:
                labels.append('<text x="%.1f" y="%d" class="xlab">%s</text>'
                              % (px(i), H - 6, lt.strftime('%a')))
        return ('<svg viewBox="0 0 %d %d" class="weekcurve chart" data-chart=\'%s\' '
                'tabindex="0" role="img" aria-label="Forecast temperature and dew point every hour for '
                'the week, with the hourly chance of rain beneath">%s%s%s%s'
                '<path d="%s" class="dline"/><path d="%s" class="tline"/>%s%s%s</svg>'
                % (W, H, NWSSkin._series(hours, x0, x1, TY0, TY1, lo_ax, span),
                   NWSSkin._night_bands(hours, px, TY0, TY1), ''.join(hgrid), ''.join(ticks),
                   ''.join(ylab), NWSSkin._path(hours, px, py, 'dewpoint'),
                   NWSSkin._path(hours, px, py, 'outTemp'),
                   NWSSkin._rain(hours, px, x0, x1, RY0, RY1, 'peaks at'),
                   NWSSkin.CROSS, ''.join(labels)))

    @staticmethod
    def day_chart(hours: List[Dict[str, Any]]) -> str:
        """One calendar day.  Same furniture as the week -- but 24 points
        instead of ~150, so the hour labels fit and the temperature/dew-point
        spread is readable.  That gap closing is the fog the forecast text
        keeps mentioning, and it is exactly what the week chart destroys."""
        W, H = 1040, 236
        PADL, PADR = 48, 16
        TY0, TY1, RY0, RY1 = 18, 146, 176, 208
        x0, x1 = PADL, W - PADR
        px = NWSSkin._geom(hours, x0, x1)
        # See week_chart(): `is not None`, and the same line in both places.
        vals = ([h['outTemp'] for h in hours]
                + [h['dewpoint'] for h in hours if h['dewpoint'] is not None])
        lo_ax, hi_ax, span = NWSSkin._axis(min(vals), max(vals))

        def py(t):
            return TY1 - (TY1 - TY0) * (t - lo_ax) / span

        hgrid, ylab, labels, dots = [], [], [], []
        t = lo_ax
        while t <= hi_ax:
            hgrid.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" class="hgrid"/>'
                         % (x0, py(t), x1, py(t)))
            ylab.append('<text x="%d" y="%.1f" class="ylab">%d&deg;</text>'
                        % (x0 - 6, py(t) + 4, t))
            t += 5
        for i, h in enumerate(hours):
            lt = datetime.datetime.fromtimestamp(h['startTime'])
            if lt.hour % 3 == 0:
                labels.append('<text x="%.1f" y="%d" class="xlab">%s</text>'
                              % (px(i), H - 6, lt.strftime('%-I%p')
                                 .replace('AM', 'a').replace('PM', 'p')))
            dots.append('<circle cx="%.1f" cy="%.1f" r="2.1" class="tdot"/>'
                        % (px(i), py(h['outTemp'])))
        return ('<svg viewBox="0 0 %d %d" class="daycurve chart" data-chart=\'%s\' '
                'tabindex="0" role="img" aria-label="Forecast temperature and dew point for each hour '
                'of this day, with the chance of rain beneath">%s%s%s'
                '<path d="%s" class="dline"/><path d="%s" class="tline"/>%s%s%s%s</svg>'
                % (W, H, NWSSkin._series(hours, x0, x1, TY0, TY1, lo_ax, span),
                   NWSSkin._night_bands(hours, px, TY0, TY1), ''.join(hgrid), ''.join(ylab),
                   NWSSkin._path(hours, px, py, 'dewpoint'),
                   NWSSkin._path(hours, px, py, 'outTemp'),
                   ''.join(dots), NWSSkin._rain(hours, px, x0, x1, RY0, RY1, 'peaks at'),
                   NWSSkin.CROSS, ''.join(labels)))

    LEGEND = ('<div class="legend">'
              '<span><i class="sw-t"></i>Temperature</span>'
              '<span><i class="sw-d"></i>Dew point</span>'
              '<span><i class="sw-r"></i>Chance of rain</span>'
              '<span><i class="sw-n"></i>Night</span>'
              '</div>')

    # ---- the alert card ---------------------------------------------------
    #
    # The CAP semantics this leans on are $nwsforecast's, not this file's:
    # alert_window(), parse_description(), nice_caps(), is_active() and
    # ordered() all live in nws.py because they are facts about the feed.
    # What is here is one report's idea of a card -- a severity rail, a
    # status badge, a window bar, one gray footer line.
    #
    # NOTHING TIME-RELATIVE IS BAKED ONLY.  Each card carries its instants as
    # data attributes and the page script rewrites the badge, the note and
    # the bar every minute; what is rendered here is that same reckoning at
    # the generation instant, so the first paint -- and a reader with
    # javascript off -- is right too.  The two ladders must agree exactly.

    @staticmethod
    def _round_half_up(value: float) -> int:
        """javascript's Math.round, which is NOT python's round().

        Python rounds half to EVEN -- round(0.5) is 0 and round(2.5) is 2 --
        while Math.round always goes up.  The badge is written here at
        generation and again by the page script a minute later, so under
        python's rule an alert 30 seconds away first paints "Begins in 0
        minutes" and then silently becomes "1 minute" on the first tick.  The
        argument is always an absolute span, so half-up is just this.
        """
        return int(value + 0.5)

    @staticmethod
    def fuzzy(seconds: float) -> str:
        secs = abs(seconds)
        if secs < 3600:
            n, unit = NWSSkin._round_half_up(secs / 60.0), 'minute'
        elif secs < 86400 * 2:
            n, unit = NWSSkin._round_half_up(secs / 3600.0), 'hour'
        else:
            n, unit = NWSSkin._round_half_up(secs / 86400.0), 'day'
        return '%d %s%s' % (n, unit, '' if n == 1 else 's')

    @staticmethod
    def stamp(value: Any) -> str:
        return NWSSkin.hm(value, '%a %-d %b, %-I:%M %p')

    @staticmethod
    def _plural(n: int, word: str) -> str:
        return '%d %s%s' % (n, word, '' if n == 1 else 's')

    @staticmethod
    def count_line(alerts: List[Dict[str, Any]]) -> str:
        """How many alerts, and how many are actually in effect.

        THREE states, not two.  An alert that has ENDED is neither in effect
        nor beginning later, and counting it as "beginning later" -- which
        this did -- produced a line that its own cards disproved.

        WHERE THE ENDED STATE ACTUALLY COMES FROM is worth being exact about,
        because it is not where it looks.  A report-time page never holds one:
        fetch_records_internal drops any alert whose endTime has passed as it
        builds the rows, so $nwsforecast.alerts() cannot return one and this
        branch is unreachable at generation.  It exists for the CLOCK: the
        page is built from alerts live at that instant, and a tab left open
        crosses an end time.  scripts/nws.js recomputes both totals from the
        cards, and its wording must match this function's, so the branch is
        carried on both sides.

        One `now` for the whole count, so an alert cannot be counted in
        effect here and rendered expired by the card below.

        scripts/nws.js rewrites this string every minute from the cards' own
        recomputed state, because the count is a fact about the clock and
        goes stale exactly as the badges do.  The two must produce identical
        text; TestCountLine pins these branches, and its
        test_the_page_script_carries_the_same_wording asserts that every
        phrase this can emit also appears in the script.
        """
        now = datetime.datetime.now().timestamp()
        active = later = 0
        for alert in alerts:
            state = nws.NWSForecastVariables.alert_state(alert, now)
            if state == 'active':
                active += 1
            elif state == 'upcoming':
                later += 1
        if active and later:
            return ('<b>%s</b> in effect now, <b>%s</b> beginning later '
                    '&mdash; in effect first, then most serious first.'
                    % (NWSSkin._plural(active, 'alert'),
                       NWSSkin._plural(later, 'alert')))
        if active:
            return ('<b>%s</b> in effect &mdash; most serious first.'
                    % NWSSkin._plural(active, 'alert'))
        if later:
            return '<b>%s</b> not yet begun.' % NWSSkin._plural(later, 'alert')
        return ('<b>%s</b> &mdash; none in effect now.'
                % NWSSkin._plural(len(alerts), 'alert'))

    @staticmethod
    def card(alert: Dict[str, Any]) -> str:
        """One alert as a finished <section>."""
        tags = nws.NWSForecastVariables
        now = datetime.datetime.now().timestamp()
        onset, finish, open_ended = tags.alert_window(alert)
        expires = alert['expires'].raw
        # One classification, from the tag, rather than this card's own
        # reckoning: 'started but not active' is the obvious spelling and it
        # is wrong for an alert with no onset whose window has closed.
        state = tags.alert_state(alert, now)
        active = state == 'active'

        if active:
            badge_cls, badge = 'on', 'In effect now'
        elif state == 'ended':
            badge_cls, badge = 'past', 'Expired'
        elif onset is None:
            # Upcoming, with no onset to count down from.  This is the branch
            # the "start not given" window below is written for; without it
            # `onset - now` raises and that fallback is unreachable.
            badge_cls, badge = 'soon', 'Not yet begun'
        else:
            badge_cls = 'soon'
            badge = 'Begins in %s' % NWSSkin.fuzzy(onset - now)

        ends_text = NWSSkin.stamp(alert['expires'] if open_ended else alert['ends'])
        if active and open_ended and expires is not None:
            note = ('no end time given &middot; next update in %s'
                    % NWSSkin.fuzzy(expires - now))
        elif active and finish is not None:
            note = 'ends in %s' % NWSSkin.fuzzy(finish - now)
        elif state == 'upcoming' and finish is not None:
            note = 'runs to %s' % ends_text
        elif state == 'ended' and finish is not None:
            note = 'ended %s ago' % NWSSkin.fuzzy(finish - now)
        else:
            note = ''

        if onset is not None and finish is not None and finish > onset:
            frac = min(max((now - onset) / float(finish - onset), 0.0), 1.0) * 100.0
            window = ('<div class="awindow"><span class="aw-t">%s</span>'
                      '<span class="aw-bar">'
                      '<span class="aw-fill" style="width:%.1f%%"></span>'
                      '<span class="aw-now" style="left:%.1f%%"></span></span>'
                      '<span class="aw-t">%s%s</span></div>'
                      % (NWSSkin.stamp(alert['onset']), frac, frac, ends_text,
                         ' <i>(expires)</i>' if open_ended else ''))
        else:
            window = ('<div class="awindow"><span class="aw-t">%s</span>'
                      '<span class="aw-t open">&mdash; no end time given</span></div>'
                      % (NWSSkin.stamp(alert['onset']) if onset is not None
                         else 'start not given'))

        body = ''
        for block in tags.parse_description(alert['description']):
            inner = ''.join('<p class="aprose">%s</p>' % NWSSkin.esc(p)
                            for p in block['paragraphs'])
            if block['bullets']:
                inner += ('<ul class="abul">%s</ul>'
                          % ''.join('<li>%s</li>' % NWSSkin.esc(b)
                                    for b in block['bullets']))
            if block['label']:
                body += ('<div class="asec"><div class="ak">%s</div>'
                         '<div class="av">%s</div></div>'
                         % (NWSSkin.esc(block['label']), inner))
            else:
                body += '<div class="alead">%s</div>' % inner

        # Four alerts in five carry no instruction; they get no empty
        # callout.  The text is teletype-wrapped like the description, so it
        # is reflowed by the same rule rather than dumped as one run-on.
        instructions = alert['instructions']
        if instructions:
            paras = ''.join(
                '<p>%s</p>' % NWSSkin.esc(' '.join(p.split()))
                for p in re.split(r'\n\s*\n', instructions) if p.strip())
            todo = ('<div class="ado"><div class="ak">What to do</div>%s</div>'
                    % paras)
        else:
            todo = ''

        if alert['nwsHeadline']:
            headline = NWSSkin.esc(tags.nice_caps(alert['nwsHeadline']))
            sub = '<p class="asub">%s</p>' % NWSSkin.esc(alert['headline'])
        else:
            headline = NWSSkin.esc(alert['headline'])
            sub = ''

        severity = alert['severity'] or 'Unknown'
        attrs = ' data-onset="%d"' % onset if onset is not None else ''
        if not open_ended:
            attrs += ' data-ends="%d"' % finish
        if expires is not None:
            attrs += ' data-expires="%d"' % expires

        return (
            '<section class="alert sev-%s"%s>'
            '<h2 class="ahead"><span class="sevdot"></span>'
            '<span class="aevent">%s</span>'
            '<span class="badge %s">%s</span>'
            '<span class="anote" data-ends-text="%s">%s</span></h2>'
            '<p class="aline">%s</p>%s%s'
            '<div class="asecs">%s</div>%s'
            '<p class="ameta">%s &middot; %s &middot; %s severity &middot; '
            '%s certainty &middot; %s urgency &middot; issued %s</p>'
            '</section>'
            % (NWSSkin.esc(severity.lower()), attrs, NWSSkin.esc(alert['event']),
               badge_cls, badge, ends_text, note, headline, sub, window,
               body, todo, NWSSkin.esc(alert['senderName']),
               NWSSkin.esc(alert['messageType']), NWSSkin.esc(severity),
               NWSSkin.esc(alert['certainty']), NWSSkin.esc(alert['urgency']),
               NWSSkin.stamp(alert['effective'])))
