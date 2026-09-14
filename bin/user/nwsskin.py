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

  sparkline()  two weeks, no rain strip -- the week the station RECORDED
               beside the week NWS forecasts, heading the 7 Day list, whose
               range bars already carry the forecast highs and lows.
  week_chart() ~150 h, full furniture: temperature, dew point and rain.
  day_chart()    24 h, same furniture, with hour labels that can be read and a
               dew-point spread that is actually visible -- which is exactly
               what 150 hours squeezed into 1040 units destroys.
"""

import datetime
import html
import json
import logging
import math
import re

from typing import Any, Callable, Dict, List, Optional, Tuple

import weewx.almanac
import weewx.units

from weewx.cheetahgenerator import SearchList

log = logging.getLogger(__name__)

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

    # The report engine hands a search list a timespan and a database lookup;
    # this one KEEPS the lookup, because observations() below reads the
    # station's own archive -- the one thing on these pages that does not come
    # from NWS.  Everything else here is a static function of what it is given.
    def get_extension_list(self, timespan, db_lookup) -> List[Dict[str, 'NWSSkin']]:
        self.db_lookup = db_lookup
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

    # ---- the station's own past ------------------------------------------
    #
    # The 7 Day page's chart is two weeks: the week the STATION RECORDED, then
    # the week NWS FORECASTS.  Everything here is what it takes to put the
    # first half on the same axis as the second.

    # One week of hourly SLOTS.  Slots, not records: the archive is sampled
    # every few minutes and the forecast is hourly, so the two only share an
    # axis once the archive has been averaged onto the forecast's own grid.
    PAST_HOURS = 168

    # Whether the archive could be read at all is worth exactly ONE line per
    # weewxd run.  The report regenerates every archive interval, so an
    # unreadable binding would otherwise write the same line every few minutes
    # for as long as weewxd runs.  Module state, like nwsicons.UNKNOWN.
    _READ_FAILED = False

    def _forecast_temp_unit(self) -> str:
        """The unit the forecast half of the curve is plotted in: this
        report's own target unit for outTemp.

        $nwsforecast builds its ValueHelpers with this report's converter, so
        points() hands the chart numbers that are ALREADY in the report's
        unit.  The observed half arrives from the station's archive in
        whatever the station records in, and has to be brought to that same
        one -- 20 C and 68 F are the same afternoon, and plotted on one axis
        unconverted they land 48 degrees apart.

        Asking the converter, rather than assuming US, is what keeps the two
        halves together when the report is set to metric.
        """
        return self.generator.converter.getTargetUnit('outTemp')[0]

    def observations(self, forecast: List[Dict[str, Any]],
                     back: Optional[int] = None) -> List[Dict[str, Any]]:
        """The station's OWN hourly temperature for the week before the
        forecast begins, in the shape $nwsforecast.points() returns.

        The seam is the forecast's FIRST hour, not the wall clock: it is where
        the forecast curve begins, so it is the only place the join can be
        drawn honestly.  (Periods that have already ended are dropped on read,
        so that first hour is the current one.)

        One row per hour, INCLUDING the hours with nothing in them -- a
        station that was down for a day must leave a hole in the line rather
        than a confident stroke across it, and the crosshair indexes this list
        by position, so a missing hour has to keep its place.  Leading empty
        hours are dropped instead: a station three days old gets three days of
        chart, not a week four sevenths of which is a lie.  Trailing ones are
        NOT dropped -- a gap between the last reading and the forecast is
        exactly the news that weewxd stopped.

        Returns [] when there is no forecast to hang it from, when the archive
        holds nothing yet, or when it cannot be read at all.  The chart then
        degrades to the forecast week alone, which is what a fresh install
        sees.
        """
        back = NWSSkin.PAST_HOURS if back is None else back
        if not forecast:
            return []
        seam = int(forecast[0]['startTime'])
        start = seam - back * 3600
        readings = self._hourly_means(start, seam)
        # Before the almanac, not after: with nothing to plot there is nothing
        # to shade, and the fresh-install path is the common one.
        if not readings:
            return []
        is_day = self._daytime(start, seam)
        return NWSSkin._from_first_reading(
            [{'startTime': t,
              'outTemp': readings.get(t),
              # The sparkline plots temperature alone, but the shape has to
              # match points() -- one list of both halves goes to the night
              # bands and to the crosshair.
              'dewpoint': None,
              'pop': None,
              'isDaytime': is_day(t)}
             for t in range(start, seam, 3600)])

    @staticmethod
    def _from_first_reading(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """`rows` from its first hour that HAS a reading -- the data-driven
        width.  Everything, if the first hour has one; nothing, if none has."""
        for i, r in enumerate(rows):
            if r['outTemp'] is not None:
                return rows[i:]
        return []

    def _hourly_means(self, start: int, stop: int) -> Dict[int, float]:
        """{hour start -> mean temperature}, on ABSOLUTE hourly boundaries and
        converted to the unit the forecast is plotted in.  Hours the archive
        has nothing for are simply absent from the mapping.

        NOT weewx.xtypes.get_series(..., 'avg', 3600), which would otherwise
        be the obvious way to ask.  Its intervals come from
        weeutil.intervalgen, whose boundaries are constant in LOCAL time, and
        this chart's x axis is absolute time -- the forecast half is hourly in
        absolute time and the two halves share one geometry.  They agree on an
        ordinary day and at the spring change; they do NOT agree at the fall
        change, where the hour the clock repeats gets no interval of its own
        and its neighbor's interval runs two hours instead of one.  The result
        would be a one-hour hole in the recorded week every November, next to
        an hour whose mean silently covered two -- and it would appear on the
        day nobody thinks to re-check.

        Two lesser reasons, both real: one query instead of one per hour, and
        the unit question settled per RECORD rather than per series, so a
        station that changed unit system mid-week still averages correctly
        (get_series refuses that case outright).

        A binding that cannot be read costs the chart, never the page.  This
        runs on the report thread, so there is no Terminate to let through,
        and a sample report whose 7 Day page vanishes because an archive is
        misconfigured is worse than one drawn without its observed half.  The
        CONVERSION is inside that guard too, and not by accident: WeeWX knows
        three unit systems, and getStandardUnitType() raises KeyError for any
        other value -- so one corrupt or hand-edited archive row carrying a
        usUnits of 0 or 3 would otherwise take the whole page down, which is
        the exact failure this guard exists to prevent.
        """
        try:
            target = self._forecast_temp_unit()
            manager = self.db_lookup()
            rows = manager.genSql(
                'SELECT dateTime, usUnits, outTemp FROM %s WHERE dateTime > ? '
                'AND dateTime <= ? AND outTemp IS NOT NULL' % manager.table_name,
                (start, stop))
            # (slot, usUnits) -> [sum, count].  Split by unit system as well as
            # by hour: raw values from two systems cannot be added together,
            # and the conversion has to happen before they meet.
            buckets: Dict[Tuple[int, int], List[float]] = {}
            for when, units, value in rows:
                # weewx stamps a record at the END of its interval, so the
                # window is (start, stop] and a reading landing exactly on an
                # hour belongs to the hour BEFORE it.
                slot = start + ((int(when) - start - 1) // 3600) * 3600
                acc = buckets.setdefault((slot, int(units)), [0.0, 0.0])
                acc[0] += float(value)
                acc[1] += 1
            totals: Dict[int, List[float]] = {}
            for (slot, units), (total, count) in buckets.items():
                unit, group = weewx.units.getStandardUnitType(units, 'outTemp')
                mean = weewx.units.convert(
                    weewx.units.ValueTuple(total / count, unit, group), target)[0]
                got = totals.setdefault(slot, [0.0, 0.0])
                got[0] += mean * count
                got[1] += count
            return {slot: total / count for slot, (total, count) in totals.items()}
        except Exception as e:
            if not NWSSkin._READ_FAILED:
                NWSSkin._READ_FAILED = True
                log.info('nwsskin: cannot read the station archive for the '
                         "7 Day chart's observed week (%s); drawing the "
                         'forecast alone.' % e)
            return {}

    def _daytime(self, first_ts: int, last_ts: int) -> Callable[[int], bool]:
        """Is this instant daylight at the station?  One sunrise/sunset pair
        per calendar day, looked up once and closed over.

        The forecast half of the chart gets isDaytime from NWS itself.  The
        observed half has to be reckoned here, and the two must agree across
        the seam -- night shading that stops dead at the join would read as
        two charts pasted together.

        A day the almanac will not answer for -- a polar summer, a polar
        winter, an almanac that raises -- is left UNSHADED rather than
        guessed.  A band is a claim about where the sun was; no band claims
        nothing.
        """
        lat = self.generator.stn_info.latitude_f
        lon = self.generator.stn_info.longitude_f
        windows: Dict[Any, Tuple[Optional[float], Optional[float]]] = {}
        day = datetime.date.fromtimestamp(first_ts)
        end = datetime.date.fromtimestamp(last_ts)
        while day <= end:
            noon = datetime.datetime(day.year, day.month, day.day, 12).timestamp()
            try:
                alm = weewx.almanac.Almanac(noon, lat, lon)
                windows[day] = (alm.sunrise.raw, alm.sunset.raw)
            except Exception:
                windows[day] = (None, None)
            day += datetime.timedelta(days=1)

        def is_day(when: int) -> bool:
            rise, set_ = windows.get(datetime.date.fromtimestamp(when), (None, None))
            if rise is None or set_ is None:
                return True
            return bool(rise <= when < set_)

        return is_day

    # ---- chart primitives -------------------------------------------------

    # Room to the left of the plot for the y-axis labels, and it is set by the
    # NARROWEST screen, not the widest.  SVG text is in USER UNITS, so the
    # stylesheet scales the axis labels UP as the chart is squeezed -- to 26
    # units below 620px.  A gutter sized for the desktop's 10-unit type does
    # not clip the label, it clips the DIGITS: a phone showed "0&deg;, 7&deg;,
    # 5&deg;" for an axis reading 90, 67 and 45, which is not a cosmetic
    # failure but a wrong chart.
    #
    # MEASURED in a browser at 26 units rather than estimated, because the
    # estimate was wrong twice: two digits and a degree sign come to 46.0
    # units, THREE digits to 62.5.  The governing label is "100&deg;" -- an
    # ordinary summer afternoon here -- not the "-10&deg;" the first fix sized
    # for; a hundred is wider than a minus sign and two digits.  A three-digit
    # NEGATIVE would want more still, and is not reachable: the lowest
    # temperature ever recorded in the United States is -80F.
    #
    # The rain strip's "100%" is the same width, and the stylesheet hides it
    # below 620px; above that it is 17 units and fits easily.
    #
    # 76 rather than the 68.5 that measurement alone calls for, and the extra
    # is NOT slack for antialiasing.  62.5 was measured in DejaVu Sans, which
    # is what this machine substitutes -- the stylesheet asks for Open Sans
    # first and does not have it.  A reader's machine may substitute something
    # else, and the glyph advances differ by more than a rounding error
    # between the candidates (DejaVu's digits are the widest of the usual
    # three, Arial's the narrowest).  So the margin is absorbing a DIFFERENT
    # TYPEFACE, not a fraction of a pixel, and 76 leaves 7.5 units -- room for
    # a substitute 12% wider than the one measured here.  It costs 6 units of
    # plot width out of 1040.
    PADL = 76

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
    def _path(hours: List[Dict[str, Any]], px, py, key: str,
              offset: int = 0, gaps: bool = False) -> str:
        """One series as a path.

        `offset` shifts every point along the x geometry, so a SLICE of a
        longer series can be drawn as its own stroke -- which is how the
        observed week and the forecast week end up as two strokes on one set
        of coordinates.

        `gaps` decides what a missing value MEANS, and the two answers are
        both right.  In a forecast series a hole is one of two curves missing
        a reading the other has -- an hour with no dew point between two that
        have one -- and joining across it is the truth.  In the OBSERVED
        series it means the station recorded nothing at all, and joining
        across it would draw a confident line through an outage.  So that
        stroke BREAKS and starts again; see _orphans() for what survives a
        break alone.
        """
        pts = [(i, h[key]) for i, h in enumerate(hours) if h.get(key) is not None]
        if not pts:
            return ''
        if not gaps:
            return 'M ' + ' L '.join('%.1f %.1f' % (px(offset + i), py(v))
                                     for i, v in pts)
        out, prev = [], None
        for i, v in pts:
            out.append('%s %.1f %.1f' % ('L' if prev == i - 1 else 'M',
                                         px(offset + i), py(v)))
            prev = i
        return ' '.join(out)

    @staticmethod
    def _orphans(hours: List[Dict[str, Any]], px, py, key: str,
                 offset: int = 0) -> str:
        """A dot for every reading whose neighbors are both missing.

        A broken stroke draws NOTHING for a lone point: a subpath of one
        moveto has no length.  So an hour the station caught between two
        outages would vanish from a chart whose whole job is to say what was
        recorded -- and vanish silently, which is the failure this file's
        tests exist for.
        """
        have = [h.get(key) is not None for h in hours]
        return ''.join(
            '<circle cx="%.1f" cy="%.1f" r="1.8" class="adot"/>'
            % (px(offset + i), py(hours[i][key]))
            for i in range(len(have))
            if have[i]
            and not (i and have[i - 1])
            and not (i + 1 < len(have) and have[i + 1]))

    @staticmethod
    def _series(hours: List[Dict[str, Any]], x0: float, x1: float,
                ty0: int, ty1: int, lo_ax: int, span: int,
                with_dew_and_rain: bool = True, past_n: int = 0) -> str:
        """The points the crosshair reads, plus the geometry it needs to
        invert a pointer position into an index.  Carried on the <svg> as
        data-chart so one small script drives every chart on the page.

        EVERY slot goes in, including an observed hour with no reading, and
        its `T` is then null.  The script turns a pointer position into an
        INDEX by dividing the plot width by the number of points, so a list
        that quietly left the empty hours out would put every crosshair
        reading on the wrong hour.  The script draws no dot and says "no
        reading" for those.

        `past_n` marks how many of the leading points are the station's own
        record rather than a forecast, so the readout can say which it is
        showing.  A chart must not present a measurement and a prediction in
        the same words.

        `with_dew_and_rain` is FALSE for the sparkline, and that is not a
        tidiness argument.  The crosshair positions the dew-point dot with
        the axis carried here, and the sparkline's axis is built from
        temperature ALONE -- so a dew point of 59 against a 75-80 scale
        computed to y=382 in a 132-unit viewBox, far outside the plot, while
        the readout announced a dew point and a chance of rain for two series
        the sparkline does not draw.  A chart may only report what it plots.
        """
        points = []
        for i, h in enumerate(hours):
            point: Dict[str, Any] = {
                't': datetime.datetime.fromtimestamp(h['startTime'])
                     .strftime('%a %-I %p').replace('AM', 'am').replace('PM', 'pm'),
                'T': round(h['outTemp']) if h['outTemp'] is not None else None,
            }
            if with_dew_and_rain:
                point['d'] = round(h['dewpoint']) if h['dewpoint'] is not None else None
                point['r'] = h['pop'] or 0
            if i < past_n:
                point['o'] = 1
            points.append(point)
        return json.dumps({
            'x0': x0, 'x1': x1, 'y0': ty0, 'y1': ty1,
            'lo': lo_ax, 'span': span,
            'p': points,
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

    # ---- the two chips that name the halves --------------------------------
    #
    # PAST n DAYS ACTUAL and FORECASTED TEMPERATURES: one filled rectangle
    # each side of the rule, both the same width, the words centered in them.
    # Each box is filled with its own half's curve color, so the label IS the
    # swatch -- which is what the two floating words this replaced could never
    # be.  At chart size "Observed" and "Forecast" read as one phrase, and the
    # full-height rule was already a patch for that.
    #
    # THEY ARE MARKUP, NOT SVG <text>, and that is the whole design.  Two
    # reasons, either of which would be enough on its own:
    #
    #   NOTHING HERE COMPUTES A WIDTH.  A filled box has to be exactly as wide
    #   as the words inside it, and the words are not one fixed string -- the
    #   day count follows the archive -- while the stylesheet draws them at
    #   three sizes as the page narrows, in whatever face the reader's machine
    #   substitutes for Open Sans, which this skin names and deliberately does
    #   not load.  A box sized in Python is a box sized for one string, at one
    #   size, in one face, out of the dozen combinations that actually render.
    #   A box sized by the browser is right in all of them -- and the equal
    #   widths come free with it, from a two-column max-content grid.
    #
    #   AND IT IS THE ONLY WAY THE WORDS CAN BE READ AT ALL.  The chart
    #   carries role="img" with an aria-label, which hides every <text> inside
    #   it from assistive technology -- so the two words saying which half was
    #   which could be reached by no route.  As markup beside the chart they
    #   are read like any other text on the page.
    #
    # ARITHMETIC HERE DECIDES ONLY WHETHER THE PAIR IS SHOWN, never how wide
    # it is.  So getting CHIP_WIDTH wrong drops a pair on a young station; it
    # cannot clip ink on a station with a week behind it, which is every
    # station that has been up a week.
    #
    # BOTH CHIPS OR NEITHER.  The old asymmetric words could be dropped one at
    # a time; a matched pair centered on the rule cannot -- one of them alone
    # would straddle the rule it is meant to stand beside.  On this geometry
    # the pair fits from 134 observed hours up, so a station shows no chips
    # for its first five and a half days and keeps them from then on; below
    # that the caption under the chart is what names the two halves.
    #
    # GAP is the space each chip stands clear of the rule.  It lives HERE and
    # only here: the stylesheet is handed twice this as the gutter the pair
    # straddles, along with the x the rule was actually drawn at, so the
    # placement cannot drift from the room test that allowed it.
    CHIP_GAP = 8
    # MEASURED, like PADL, and for the same reason: an estimate here is the
    # mistake that clipped the axis in 6.1.1.  This is the widest chip the
    # stylesheet ever draws -- FORECASTED TEMPERATURES at the narrow-screen 21
    # units -- read off the rendered page in both engines at 423.1 units, and
    # rounded UP by 2% for a machine whose substituted face is wider than this
    # one's.  2% and not more, and the reason is the paragraph below.
    #
    # FORECASTED TEMPERATURES is much the longer of the two strings, so it
    # sets the pair's width in every case: the longest the left chip can ever
    # be is PAST 23 HOURS ACTUAL, which is shorter.  (That is what made ACTUAL
    # free to add.  PAST n DAYS ACTUAL TEMPERATURES would not have been -- it
    # overtakes the forecast chip and would widen both boxes.)
    #
    # SLACK IS NOT FREE HERE, which is what makes this different from PADL.
    # It is bounded on BOTH sides, and the two bounds pull against each other:
    #
    #   too small and a chip overruns its side of the plot -- and the right
    #   one has only 8 units of margin before the edge of the card, where the
    #   left has the whole 76-unit axis gutter, empty at this height
    #
    #   too large and the pair vanishes from a station that is perfectly
    #   healthy.  The forecast half is not a fixed 156 hours: ended periods
    #   are dropped on read, so it shrinks by an hour every hour until NWS
    #   issues the next generation.  Measured on this station's own database,
    #   every generation is 156 records, the drawn half runs 152-156, and the
    #   gaps between generations run half an hour to four hours.  432 holds
    #   the pair through a TWELVE-hour gap; 445 would have lost it at four,
    #   so the chips would have blinked out and back on a working station.
    #
    # The face this was measured in is DejaVu, which is what fontconfig
    # substitutes here for a stack of 'Open Sans', arial, sans-serif -- the
    # skin names Open Sans and deliberately loads no webfont.  DejaVu is at
    # the WIDE end of the common sans faces (Arial and Helvetica are
    # narrower, and Open Sans itself measures 374), so 423 is close to a
    # ceiling rather than a typical value, and 2% on top of it is real room.
    #
    # RE-MEASURE WHENEVER THE STRINGS OR .seamchip's SIZE MOVE.
    # tests/verify_theme.py measures the real chips in a real browser, prints
    # what it saw and FAILS if one is wider than this, so it cannot quietly go
    # stale.
    CHIP_WIDTH = 432
    CHIP_ROOM = CHIP_WIDTH + CHIP_GAP
    # How far the plot is pushed down to open the band the chips sit in.  The
    # chip is 1.6 times its type size tall -- line-height:1 plus .3em of
    # padding above and below -- which is 33.6 units at the largest type the
    # stylesheet ever gives them, the narrow-screen 21, and the band it is
    # centered in is this plus the 12 units of top padding the plot has
    # anyway.  28 leaves it 3.2 clear top and bottom.  The stylesheet does not
    # know this number: it is handed the band's midpoint.
    CHIP_BAND = 28

    @staticmethod
    def _observed_span(past: List[Dict[str, Any]]) -> int:
        """Hours of the observed half that have a reading BEHIND them: the
        index of the last row with an outTemp, plus one.

        NOT len(past), which is how wide the half is DRAWN.  observations()
        drops leading empty hours but deliberately keeps trailing ones -- a
        gap between the last reading and the forecast is exactly the news that
        weewxd stopped -- so a station whose sensor died six days ago still
        returns a full 168 rows, 24 of them with anything in them.  Counting
        the rows there printed PAST 7 DAYS ACTUAL over a curve that stops six
        days back, and "The past 7 days this station recorded" under it, which
        is the class of claim these labels were written to retire.

        Rounding DOWN to the last reading is the same rule _span_words works
        to: a label may understate what was drawn, never overstate it.  A
        station that missed the last three hours says 6 days rather than 7,
        and that is the safe direction.
        """
        for i in range(len(past) - 1, -1, -1):
            if past[i]['outTemp'] is not None:
                return i + 1
        return 0

    @staticmethod
    def _span_words(hours: int) -> str:
        """"7 DAYS" / "3 DAYS" / "18 HOURS" for a half that many hours wide.

        THE CLAIM HAS TO MATCH THE CHART.  The observed half is as wide as the
        archive is long -- three days of archive draw three days, by design,
        and observations() drops leading empty hours to make that so -- and a
        chip that always said 7 would be a printed lie on a station that had
        just been built.

        ROUNDED DOWN, and that is the whole of the rule: a label may
        understate what was drawn, never overstate it.  Under a day it counts
        hours instead, because the day count is floored and a five-hour-old
        station would otherwise read "0 DAYS".
        """
        if hours >= 24:
            days = hours // 24
            return '%d DAY%s' % (days, '' if days == 1 else 'S')
        return '%d HOUR%s' % (hours, '' if hours == 1 else 'S')

    @staticmethod
    def _seam_chips(width: int, y0: int, sx: float, x0: float, x1: float,
                    n_obs: int) -> str:
        """The two chips, as markup placed over the chart's label band.

        Empty when either side is too narrow to hold one -- see CHIP_ROOM
        above for why it is both or neither.

        ONLY THE OBSERVED HALF IS COUNTED.  The forecast chip takes no span
        deliberately and so needs no number: the NWS hourly feed is 156
        records and the chart plots from the current hour, so that half is
        6.5 days at its widest, and a day count there would read 6 while
        every reader took the chart for a week of forecast.
        """
        if min(sx - x0, x1 - sx) < NWSSkin.CHIP_ROOM:
            return ''
        # THREE NUMBERS, and every one comes from the geometry this chart was
        # actually drawn with rather than being written down a second time in
        # the stylesheet:
        #   --seam       the rule's own x, as a percentage of the chart's
        #                width -- which is the wrapper's width, since the svg
        #                is width:100% of it
        #   --chip-gap   the gutter the pair straddles the rule with, in
        #                viewBox units, so the placement cannot drift from the
        #                room test that allowed it
        #   --band-mid   half the plot's top edge, which is the middle of the
        #                band the chips are centered in
        # Bare numbers rather than lengths for the last two: the stylesheet
        # turns units into pixels with the container query that also sizes the
        # type, and a percentage gap inside a max-content grid resolves
        # against a width that is not yet known -- to zero.
        return ('<div class="seamlegend" style="--seam:%.2f%%;--chip-gap:%d;'
                '--band-mid:%.1f">'
                '<span class="seamchip obs">PAST %s ACTUAL</span>'
                '<span class="seamchip fcast">FORECASTED TEMPERATURES</span>'
                '</div>'
                % (100.0 * sx / width, 2 * NWSSkin.CHIP_GAP, y0 / 2.0,
                   NWSSkin._span_words(n_obs)))

    @staticmethod
    def sparkline_caption(past: Optional[List[Dict[str, Any]]] = None) -> str:
        """The words under the 7 Day chart, matching what was drawn.

        IT COUNTED THE SAME WEEK THE CHIP DOES, one line below it: "the week
        this station recorded" was the identical claim to a chip fixed at
        seven days, on the identical half, and wrong on the identical station.
        Worse where it survives longest -- below CHIP_ROOM the chips go and
        this sentence is the only thing naming the halves at all, so the
        shorter the archive, the more weight the wrong number carried.  It
        takes its span from _span_words, so the two cannot disagree.

        WHAT IS DELIBERATELY LEFT: "the week the Weather Service forecasts".
        That half is 6.5 days, so "week" is loose -- but it is loose the way a
        reader's own "the week ahead" is loose, and it names no number to be
        wrong about.
        """
        # The hours with readings, not the width of the half -- see
        # _observed_span.  A half that is all holes has nothing to claim and
        # falls through to the fresh-install sentence, which is true of it.
        recorded = NWSSkin._observed_span(list(past or []))
        if recorded:
            return ('The past %s this station recorded, then the week the '
                    'Weather Service forecasts, on one temperature scale.  '
                    'Night shaded.' % NWSSkin._span_words(recorded).lower())
        return ('Forecast temperature every hour of the week, night shaded.  '
                'Once this station has archive records behind it, the week it '
                'recorded is drawn here too.')

    @staticmethod
    def sparkline(hours: List[Dict[str, Any]],
                  past: Optional[List[Dict[str, Any]]] = None) -> str:
        """Two weeks on one scale: the week the station RECORDED, then the
        week NWS forecasts, with the seam between them named.

        One axis, deliberately.  A cold snap last week rescales the forecast
        half, and that is the point -- "warm for the week" and "warm for the
        fortnight" are different claims, and only a shared scale can tell them
        apart.  The two halves are drawn as SEPARATE strokes and are not
        joined across the seam: the last reading and the first forecast hour
        rarely agree, because NWS forecasts a grid square and the station
        measures its own back yard, and that step is worth seeing rather than
        smoothing away.

        Without a scale the curve says only "it cools at night" -- true, and
        worth nothing: you cannot tell how warm the afternoons get, how cold
        the nights get, or whether the fortnight is trending.  Three labeled
        gridlines cost 20px and answer all three.  The instrument version,
        with dew point and the rain strip, is week_chart().

        With no `past` -- a fresh install, an archive that cannot be read --
        this is EXACTLY the one-week chart it has always been: same viewBox,
        same plot, no seam, no label band.  Nothing about the empty case is
        announced on the chart itself; the caption below it says what it is.
        """
        past = list(past or [])
        series = past + list(hours)
        seam_i = len(past)
        W = 1040
        # The chip band above the plot exists only when there is a seam to
        # name, so the degraded chart keeps its old proportions exactly.
        #
        # NOTHING HERE PLACES THE CHIPS VERTICALLY.  Its depth is CHIP_BAND,
        # which is sized by the tallest type the stylesheet ever gives them
        # (the narrow-screen 21 units, in the same viewBox units the geometry
        # is written in), and the stylesheet centers them in it.
        band = NWSSkin.CHIP_BAND if seam_i else 0
        H, y0 = 132 + band, 12 + band
        x0, x1, y1 = NWSSkin.PADL, W - 8, y0 + 88
        px = NWSSkin._geom(series, x0, x1)
        # Observed hours can be empty; forecast hours cannot (points() drops
        # an hour it could not plot), so there is always something to scale.
        temps = [h['outTemp'] for h in series if h['outTemp'] is not None]
        lo_ax, hi_ax, span = NWSSkin._axis(min(temps), max(temps))

        def py(t):
            return y1 - (y1 - y0) * (t - lo_ax) / span

        grid, ylab, labels, ticks = [], [], [], []
        for t in (lo_ax, (lo_ax + hi_ax) // 2, hi_ax):
            grid.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" class="hgrid"/>'
                        % (x0, py(t), x1, py(t)))
            ylab.append('<text x="%d" y="%.1f" class="ylab">%d&deg;</text>'
                        % (x0 - 6, py(t) + 4, t))
        for i, h in enumerate(series):
            lt = datetime.datetime.fromtimestamp(h['startTime'])
            if lt.hour == 0 and i:
                ticks.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" class="vgrid"/>'
                             % (px(i), y0, px(i), y1))
            if lt.hour == 12:
                labels.append('<text x="%.1f" y="%d" class="xlab">%s</text>'
                              % (px(i), H - 6, lt.strftime('%a')))
        seam, legend = '', ''
        if seam_i:
            # BETWEEN the two points, not on one of them.  Drawn at px(seam_i)
            # the rule touches the first forecast point while standing a full
            # hour clear of the last observed one, so the gap reads as a
            # mistake on one side only.  The boundary is between the last
            # reading and the first prediction; the line belongs between them,
            # clear of both by the same amount.
            sx = (px(seam_i - 1) + px(seam_i)) / 2.0
            # THE RULE RUNS THE FULL HEIGHT, chip band included.  Stopped at
            # the top of the plot it left the two labels side by side with
            # nothing between them, which at this size reads as one phrase
            # rather than two labels.  The line is what makes them two; the
            # chips stand CHIP_GAP clear either side of it for the same reason.
            #
            # From y=3, which is the top of the BAND rather than the top of
            # the chips: the chips are opaque and cover the rule where they
            # sit, so what a reader sees is the gutter between them, plus a
            # short stub above them wherever the type is smaller than the
            # narrow-screen size the band was cut for.
            seam = ('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" class="seam"/>'
                    % (sx, 3, sx, y1))
            legend = NWSSkin._seam_chips(W, y0, sx, x0, x1,
                                         NWSSkin._observed_span(past))
        # Emitted only when there is something to draw: an empty d= would put
        # a <path> that draws nothing into every fresh install's page.
        recorded = NWSSkin._path(past, px, py, 'outTemp', gaps=True)
        if recorded:
            recorded = ('<path d="%s" class="aline"/>%s'
                        % (recorded, NWSSkin._orphans(past, px, py, 'outTemp')))
        # THE SAME SPAN, IN THE SAME WORDS, as the chips and the caption: this
        # sentence is what a screen reader gets INSTEAD of the picture, so "the
        # week just gone" over three days of archive is the one place the wrong
        # number cannot be checked against what is on the screen.
        label = ('Temperature every hour: the past %s this station recorded, then '
                 'the week the National Weather Service forecasts, night shaded'
                 % NWSSkin._span_words(NWSSkin._observed_span(past)).lower()
                 if seam_i else
                 'Forecast temperature every hour across the week, night shaded')
        # The chips ride OUTSIDE the svg, in the wrapper the template already
        # makes position:relative -- see CHIP_GAP for why they are markup.  The
        # template places what this returns as one thing; there is nothing for
        # it to position, and nothing here to recompute the geometry from.
        return ('<svg viewBox="0 0 %d %d" class="sparkcurve chart" data-chart=\'%s\' '
                'tabindex="0" role="img" aria-label="%s">%s%s%s%s%s%s'
                '<path d="%s" class="tline"/>%s%s</svg>%s'
                % (W, H, NWSSkin._series(series, x0, x1, y0, y1, lo_ax, span,
                                         with_dew_and_rain=False, past_n=seam_i),
                   label,
                   NWSSkin._night_bands(series, px, y0, y1), ''.join(grid),
                   ''.join(ticks), ''.join(ylab), seam, recorded,
                   NWSSkin._path(hours, px, py, 'outTemp', offset=seam_i),
                   NWSSkin.CROSS, ''.join(labels), legend))

    @staticmethod
    def week_chart(hours: List[Dict[str, Any]]) -> str:
        """Every hour the feed carries, for the trend rather than the detail."""
        W, H = 1040, 306
        PADR = 16
        TY0, TY1, RY0, RY1 = 18, 208, 238, 278
        x0, x1 = NWSSkin.PADL, W - PADR
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
        PADR = 16
        TY0, TY1, RY0, RY1 = 18, 146, 176, 208
        x0, x1 = NWSSkin.PADL, W - PADR
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
        # Never None: an absent onset falls back to the effective time, which
        # the schema stores NOT NULL.
        assert onset is not None
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

        # Both ends of the window as alert_window() reckons them, each marked
        # when it is a message time standing in for an event time.  Stamping
        # the raw onset printed N/A beside a bar drawn from the effective time.
        given = alert['onset'].raw is not None
        start_text = '%s%s' % (NWSSkin.stamp(alert['onset'] if given else alert['effective']),
                               '' if given else ' <i>(effective)</i>')
        end_text = '%s%s' % (ends_text, ' <i>(expires)</i>' if open_ended else '')
        if finish is not None and finish > onset:
            frac = min(max((now - onset) / float(finish - onset), 0.0), 1.0) * 100.0
            window = ('<div class="awindow"><span class="aw-t">%s</span>'
                      '<span class="aw-bar">'
                      '<span class="aw-fill" style="width:%.1f%%"></span>'
                      '<span class="aw-now" style="left:%.1f%%"></span></span>'
                      '<span class="aw-t">%s</span></div>'
                      % (start_text, frac, frac, end_text))
        else:
            # An end at or before the start leaves no span to draw a bar
            # across.  NWS does not mean to send one, but the card still says
            # both times rather than claiming there is no end.
            window = ('<div class="awindow"><span class="aw-t">%s</span>'
                      '<span class="aw-t">&ndash; %s</span></div>'
                      % (start_text, end_text))

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
        attrs = ' data-onset="%d"' % onset
        if not open_ended:
            attrs += ' data-ends="%d"' % finish
        if expires is not None:
            attrs += ' data-expires="%d"' % expires

        return (
            '<section class="alert sev-%s"%s>'
            '<h2 class="ahead"><span class="sevchip">%s</span>'
            '<span class="aevent">%s</span>'
            '<span class="badge %s">%s</span>'
            '<span class="anote" data-ends-text="%s">%s</span></h2>'
            '<p class="aline">%s</p>%s%s'
            '<div class="asecs">%s</div>%s'
            '<p class="ameta">%s &middot; %s &middot; %s certainty &middot; '
            '%s urgency &middot; issued %s</p>'
            '</section>'
            # The severity is NAMED, in the slot where it was a bare colored
            # dot -- so it is no longer carried by color alone, which a
            # colorblind reader gets nothing from and which is a WCAG 1.4.1
            # failure.  It mattered more here than the rule suggests: these
            # cards are SORTED by severity and the count line above them says
            # "most serious first", so the page announced that the order means
            # something while keeping the key in eight-point gray at the foot
            # of each card.  The footer no longer repeats it; certainty and
            # urgency stay there, being genuinely secondary.
            % (NWSSkin.esc(severity.lower()), attrs, NWSSkin.esc(severity),
               NWSSkin.esc(alert['event']),
               badge_cls, badge, ends_text, note, headline, sub, window,
               body, todo, NWSSkin.esc(alert['senderName']),
               NWSSkin.esc(alert['messageType']),
               NWSSkin.esc(alert['certainty']), NWSSkin.esc(alert['urgency']),
               NWSSkin.stamp(alert['effective'])))
