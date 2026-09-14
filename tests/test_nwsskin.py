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

"""Tests for bin/user/nwsskin.py -- the sample report's charts and cards.

Run from the repo root with the WeeWX venv python:
    /home/weewx/weewx-venv/bin/python -m pytest tests

Unlike the $nwsforecast tags, nothing here is a contract; these tests exist
because the arithmetic is easy to get subtly wrong in ways that render as a
plausible-looking picture.  An axis that excludes a point still draws a chart;
a bar clamped wrongly still draws a bar.

Note the dew-point axis line is written out TWICE, once in week_chart() and
once in day_chart(), and every test that covers it is parameterised over BOTH.
That duplication is inherited deliberately and left intact -- deduplicating it
in the same change that ported it would make any difference impossible to
attribute -- so the tests are what stop the two drifting.
"""

import datetime
import json
import os
import re
import sys
import time
import types

os.environ['TZ'] = 'America/Los_Angeles'
time.tzset()

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'bin', 'user'))

import pytest

import weewx
import weewx.units

from nwsskin import NWSSkin


def vh(value, obs='dateTime'):
    group = weewx.units.obs_group_dict[obs]
    units = weewx.units.USUnits[group]
    return weewx.units.ValueHelper((value, units, group))


def ts(y, mo, d, h, mi=0):
    return datetime.datetime(y, mo, d, h, mi).timestamp()


def pt(start, temp, dewpoint=50.0, pop=10, is_daytime=True):
    """A points() row -- plain numbers, which is what the charts consume."""
    return {'startTime': int(start), 'outTemp': temp, 'dewpoint': dewpoint,
            'pop': pop, 'isDaytime': is_daytime}


def obs(start, temp, is_daytime=True):
    """An observations() row: a temperature or nothing at all, and never a
    dew point or a chance of rain -- the station's own past carries neither
    onto this chart."""
    return {'startTime': int(start), 'outTemp': temp, 'dewpoint': None,
            'pop': None, 'isDaytime': is_daytime}


def week_of_obs(hours=24, base=None, temp=55.0, **kw):
    base = base if base is not None else ts(2026, 8, 31, 0)
    return [obs(base + i * 3600, temp, **kw) for i in range(hours)]


def day_of_points(hours=24, base=None, **kw):
    base = base if base is not None else ts(2026, 9, 1, 0)
    return [pt(base + i * 3600, 60.0 + i, **kw) for i in range(hours)]


def wind_period(speed, speed2=None, direction=270.0):
    return {
        'windSpeed': vh(speed, 'windSpeed'),
        'windSpeed2': vh(speed2, 'windSpeed') if speed2 is not None else None,
        'windDir': vh(direction, 'windDir') if direction is not None else None,
    }


def alert_rec(onset=None, ends=None, expires=None, effective=None,
              severity='Severe', event='Heat Advisory', headline='hot',
              nws_headline=None, description='Some prose.', instructions=None,
              area=None, response=None):
    return {
        'areaDesc': area, 'response': response,
        'onset': vh(onset), 'ends': vh(ends), 'expires': vh(expires),
        'effective': vh(effective if effective is not None else onset),
        'severity': severity, 'event': event, 'headline': headline,
        'nwsHeadline': nws_headline, 'description': description,
        'instructions': instructions, 'senderName': 'NWS Bay Area',
        'messageType': 'Alert', 'certainty': 'Likely', 'urgency': 'Expected',
    }


CSS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        '..', 'skins', 'nws', 'css', 'nws.css')


def _css_sizes(cls):
    """Every font-size the stylesheet gives one chart class, across all its
    media queries.  The charts are drawn in user units and the stylesheet is
    what decides how big those get, so geometry that has to clear the type
    must be checked against the type as it actually ships."""
    css = open(CSS_PATH).read()
    sizes = []
    for body in re.findall(r'\.%s\s*\{([^}]*)\}' % cls, css):
        found = re.search(r'font-size:\s*(\d+)px', body)
        if found:
            sizes.append(int(found.group(1)))
    assert sizes, cls
    return sizes


def _skin_with(group_unit_dict=None, db_lookup=None):
    """An NWSSkin with no report engine behind it.  The converter is the only
    thing the engine supplies that this module reads, so a bare namespace
    carrying one is the whole of the fake."""
    skin = NWSSkin.__new__(NWSSkin)
    skin.generator = types.SimpleNamespace(
        converter=weewx.units.Converter(group_unit_dict or weewx.units.USUnits))
    if db_lookup is not None:
        skin.db_lookup = db_lookup
    return skin


BOTH_CHARTS = pytest.mark.parametrize(
    'chart', ['week_chart', 'day_chart'],
    ids=['week_chart', 'day_chart'])


# ---------------------------------------------------------------------------

class TestAxis:

    def test_axis_brackets_the_data(self):
        lo, hi, span = NWSSkin._axis(52.3, 78.9)
        assert lo <= 52.3 and hi >= 78.9 and span == hi - lo

    def test_a_sub_zero_low_floors_downward(self):
        """floor(), not int(): int() truncates toward zero, so int(-0.5) is 0
        -- an axis floor ABOVE the data, which draws the point outside the
        plot."""
        lo, _hi, _span = NWSSkin._axis(-0.5, 20.0)
        assert lo == -5
        lo, _hi, _span = NWSSkin._axis(-12.0, 20.0)
        assert lo <= -12.0

    def test_a_flat_series_still_has_a_span(self):
        """A day with one temperature all through would divide by zero."""
        lo, hi, span = NWSSkin._axis(60.0, 60.0)
        assert span >= 1


class TestChartsDewPointAxis:
    """The axis must contain the dew point, not only the temperature.

    Both charts compute this with their own copy of the same line; a sabotage
    that changes only one must fail here, which is why every case runs twice.
    """

    @BOTH_CHARTS
    def test_a_dew_point_below_the_temperature_range_is_inside_the_axis(self, chart):
        hours = [pt(ts(2026, 9, 1, h), 70.0, dewpoint=20.0) for h in range(24)]
        svg = getattr(NWSSkin, chart)(hours)
        assert 'class="ylab">20&deg;' in svg or 'class="ylab">15&deg;' in svg
        assert 'class="dline"' in svg

    @BOTH_CHARTS
    def test_a_dew_point_of_exactly_zero_is_a_reading_not_an_absence(self, chart):
        """`is not None`, not truthiness -- 0 is a real dew point and _path
        plots it, so the axis has to reach it."""
        hours = [pt(ts(2026, 9, 1, h), 70.0, dewpoint=0.0) for h in range(24)]
        svg = getattr(NWSSkin, chart)(hours)
        assert 'class="ylab">0&deg;' in svg

    @BOTH_CHARTS
    def test_an_absent_dew_point_does_not_break_the_axis(self, chart):
        hours = [pt(ts(2026, 9, 1, h), 70.0, dewpoint=None) for h in range(24)]
        svg = getattr(NWSSkin, chart)(hours)
        assert '<svg' in svg

    @BOTH_CHARTS
    def test_a_mixed_series_keeps_the_present_dew_points(self, chart):
        hours = [pt(ts(2026, 9, 1, h), 70.0,
                    dewpoint=(None if h % 2 else 10.0)) for h in range(24)]
        svg = getattr(NWSSkin, chart)(hours)
        assert 'class="dline"' in svg
        assert 'class="ylab">10&deg;' in svg


class TestAxisGutter:
    """The room left of the plot for the y-axis labels.

    It is set by the NARROWEST screen, not the widest.  SVG text is in user
    units, so the stylesheet scales the axis labels UP as the chart is
    squeezed -- and a gutter sized for the desktop's 10-unit type does not
    clip the label, it clips the DIGITS.  A phone showed "0, 7, 5" for an axis
    reading 90, 67 and 45: not a cosmetic failure, a wrong chart.
    """

    def test_the_gutter_fits_the_widest_label_at_the_largest_type(self):
        """The widest label is THREE digits and a degree sign -- "100&deg;",
        an ordinary summer afternoon -- not the "-10&deg;" the first version
        of this test assumed.  A hundred is wider than a minus sign and two
        digits, and sizing for the wrong worst case clipped the leading 1 off
        a real render.

        2.40 is measured, not estimated: at a 26-unit font Chromium reports
        62.5 user units for "100&deg;" and 46.0 for "72&deg;".  Plus the 6
        units the labels are drawn clear of the plot.
        """
        biggest = max(_css_sizes('ylab'))
        needed = biggest * 2.40 + 6
        assert NWSSkin.PADL >= needed
        # And with HEADROOM, because 2.40 is DejaVu Sans -- the font this
        # machine substitutes for the Open Sans the stylesheet asks for and
        # does not have.  A reader's machine may substitute something wider.
        # A gutter that merely FITS the font in front of us is one font away
        # from clipping again.
        assert NWSSkin.PADL >= needed * 1.10, (
            'no headroom for a wider substitute font')

    def test_every_chart_uses_it(self):
        """Three charts, one gutter: a fix that reached only the chart the
        bug was noticed on would leave the other two clipping."""
        for name in ('sparkline', 'week_chart', 'day_chart'):
            spec = json.loads(re.search(
                r"data-chart='([^']*)'", getattr(NWSSkin, name)(day_of_points())).group(1))
            assert spec['x0'] == NWSSkin.PADL, name


class TestCharts:

    def test_sparkline_carries_a_temperature_scale(self):
        """Without one it says only "it cools at night", which is worth
        nothing."""
        svg = NWSSkin.sparkline(day_of_points())
        assert svg.count('class="ylab"') == 3
        assert 'class="tline"' in svg

    def test_sparkline_draws_no_rain_strip(self):
        """The rain strip belongs to the instrument charts; the sparkline is
        the week's rhythm only."""
        svg = NWSSkin.sparkline(day_of_points())
        assert 'class="parea"' not in svg
        assert 'Chance of rain' not in svg

    @BOTH_CHARTS
    def test_the_instrument_charts_draw_the_rain_strip(self, chart):
        svg = getattr(NWSSkin, chart)(day_of_points())
        assert 'class="parea"' in svg and 'Chance of rain' in svg

    @BOTH_CHARTS
    def test_the_rain_strip_reports_its_peak(self, chart):
        hours = [pt(ts(2026, 9, 1, h), 60.0, pop=(90 if h == 5 else 3))
                 for h in range(24)]
        svg = getattr(NWSSkin, chart)(hours)
        assert 'peaks at 90%' in svg

    @BOTH_CHARTS
    def test_an_absent_chance_of_rain_counts_as_zero_not_a_crash(self, chart):
        hours = [pt(ts(2026, 9, 1, h), 60.0, pop=None) for h in range(24)]
        svg = getattr(NWSSkin, chart)(hours)
        assert 'peaks at 0%' in svg

    def test_night_hours_get_a_shaded_band(self):
        hours = ([pt(ts(2026, 9, 1, h), 55.0, is_daytime=False) for h in range(6)]
                 + [pt(ts(2026, 9, 1, h), 70.0, is_daytime=True) for h in range(6, 18)])
        svg = NWSSkin.sparkline(hours)
        assert 'class="night"' in svg

    def test_an_all_daylight_series_gets_no_band(self):
        hours = [pt(ts(2026, 9, 1, h), 70.0, is_daytime=True) for h in range(12)]
        svg = NWSSkin.sparkline(hours)
        assert 'class="night"' not in svg

    def test_the_day_chart_labels_every_third_hour(self):
        """At 24 points a label fits under every third hour; that is the
        whole reason the day chart exists."""
        svg = NWSSkin.day_chart(day_of_points())
        assert svg.count('class="xlab"') == 8

    def test_the_sparkline_reports_only_what_it_plots(self):
        """It builds its axis from temperature ALONE, and the crosshair
        positions the dew-point dot with that axis -- so carrying a dew point
        put the dot at y=382 in a 132-unit viewBox and made the readout
        announce a dew point and a chance of rain for two series the
        sparkline does not draw."""
        import json
        import re as _re
        hours = [pt(ts(2026, 9, 1, h), 75.0 + h % 3, dewpoint=59.0, pop=40)
                 for h in range(24)]
        spec = json.loads(_re.search(r"data-chart='([^']*)'",
                                     NWSSkin.sparkline(hours)).group(1))
        assert set(spec['p'][0]) == {'t', 'T'}
        assert 'class="dline"' not in NWSSkin.sparkline(hours)

    def test_the_instrument_charts_do_carry_dew_and_rain(self):
        """The other half: they draw both, so they must report both."""
        import json
        import re as _re
        hours = [pt(ts(2026, 9, 1, h), 75.0 + h % 3, dewpoint=59.0, pop=40)
                 for h in range(24)]
        for name in ('week_chart', 'day_chart'):
            svg = getattr(NWSSkin, name)(hours)
            spec = json.loads(_re.search(r"data-chart='([^']*)'", svg).group(1))
            assert set(spec['p'][0]) == {'t', 'T', 'd', 'r'}, name
            assert 'class="dline"' in svg, name

    def test_every_chart_carries_its_points_for_the_crosshair(self):
        for name in ('sparkline', 'week_chart', 'day_chart'):
            svg = getattr(NWSSkin, name)(day_of_points())
            assert 'data-chart=' in svg and '"p":[' in svg

    def test_every_chart_is_reachable_by_keyboard(self):
        """tabindex="0" is what lets Tab reach the chart; the page script's
        arrow keys then walk the same crosshair the pointer drives.  Without
        it the chart is mouse-only."""
        for name in ('sparkline', 'week_chart', 'day_chart'):
            svg = getattr(NWSSkin, name)(day_of_points())
            assert 'tabindex="0"' in svg, name

    def test_the_page_script_binds_the_arrow_keys(self):
        """The other half of the pair: markup that is focusable but has no
        key handler is worse than not focusable, because Tab then stops on
        something that does nothing."""
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              '..', 'skins', 'nws', 'scripts', 'nws.js')
        js = open(script).read()
        assert "addEventListener('keydown'" in js
        for key in ('ArrowRight', 'ArrowLeft', 'Home', 'End', 'Escape'):
            assert "'%s'" % key in js, key
        # preventDefault must be reached only after a key is known to be ours,
        # or the chart swallows page scrolling for every other key.
        assert 'e.preventDefault();' in js

    def test_every_chart_emits_the_crosshair_group(self):
        for name in ('sparkline', 'week_chart', 'day_chart'):
            assert 'class="cross off"' in getattr(NWSSkin, name)(day_of_points())

    def test_the_crosshair_group_is_hidden_by_class_not_the_hidden_attribute(self):
        """`hidden` is an HTML attribute and is not valid on an SVG <g> -- the
        Nu checker rejects it, and the UA's [hidden] rule does not reach into
        SVG anyway, so it was never doing the hiding."""
        assert 'hidden' not in NWSSkin.CROSS

    def test_no_chart_bakes_a_color(self):
        """Every mark is a class, so the stylesheet owns the palette and the
        dark theme needs nothing in this module."""
        for name in ('sparkline', 'week_chart', 'day_chart'):
            svg = getattr(NWSSkin, name)(day_of_points())
            assert 'fill="#' not in svg and 'stroke="#' not in svg

    def test_a_two_point_series_still_renders(self):
        """The last day of the feed can be very short."""
        hours = [pt(ts(2026, 9, 1, 0), 60.0), pt(ts(2026, 9, 1, 1), 61.0)]
        assert '<svg' in NWSSkin.day_chart(hours)


class TestTwoWeekSparkline:
    """The 7 Day chart's observed half, and the seam between the two weeks.

    What every case here is really guarding is that the two halves stay ONE
    chart: one x geometry, one temperature scale, one night shading and one
    crosshair index -- with a visible, named join.  Each of those is easy to
    break in a way that still draws a perfectly plausible picture.
    """

    @staticmethod
    def _d(svg, cls):
        m = re.search(r'<path d="([^"]*)" class="%s"/>' % cls, svg)
        return m.group(1) if m else None

    @staticmethod
    def _seam_x(svg):
        m = re.search(r'<line x1="([\d.]+)" y1="(-?\d+)" x2="[\d.]+" y2="(-?\d+)" '
                      r'class="seam"/>', svg)
        return float(m.group(1)) if m else None

    @staticmethod
    def _seam_ys(svg):
        m = re.search(r'<line x1="[\d.]+" y1="(-?\d+)" x2="[\d.]+" y2="(-?\d+)" '
                      r'class="seam"/>', svg)
        return (int(m.group(1)), int(m.group(2))) if m else None

    @staticmethod
    def _spec(svg):
        return json.loads(re.search(r"data-chart='([^']*)'", svg).group(1))

    @staticmethod
    def _chips(svg):
        """(observed text, forecast text, custom properties) or None.

        The chips ride OUTSIDE the svg -- see NWSSkin.CHIP_GAP -- so what
        sparkline() returns is the chart followed by their markup, or by
        nothing at all when neither half is wide enough for the pair.
        """
        legend = re.search(r'<div class="seamlegend" style="([^"]*)">(.*)</div>',
                           svg)
        if not legend:
            return None
        css = dict(kv.split(':', 1) for kv in legend.group(1).rstrip(';').split(';'))
        text = re.findall(r'<span class="seamchip \w+">([^<]*)</span>',
                          legend.group(2))
        assert len(text) == 2, text
        return text[0], text[1], css

    # A full NWS hourly feed is 156 records, and the production archive is a
    # week.  That shape is what the chips are sized for, and CHIP_ROOM leaves
    # no room for them on the toy 24-hour series the other cases use.
    FEED = 156
    WEEK = 168

    @staticmethod
    def _first_xy(d):
        parts = d.split()
        return float(parts[1]), float(parts[2])

    @staticmethod
    def _last_xy(d):
        parts = d.split()
        return float(parts[-2]), float(parts[-1])

    @staticmethod
    def _ys(d):
        """Every y in a path: the tokens run <cmd> <x> <y>."""
        parts = d.split()
        return [float(v) for i, v in enumerate(parts) if i % 3 == 2]

    def test_no_past_is_exactly_the_chart_it_has_always_been(self):
        """A fresh install has an empty archive, and the degraded chart must
        not be a different chart with an empty half: same viewBox, same plot,
        no seam and no label band."""
        hours = day_of_points()
        assert NWSSkin.sparkline(hours, []) == NWSSkin.sparkline(hours)
        svg = NWSSkin.sparkline(hours, [])
        assert 'viewBox="0 0 1040 132"' in svg
        assert 'class="seam"' not in svg
        assert 'class="aline"' not in svg
        assert 'Observed' not in svg and 'Forecast</text>' not in svg

    def test_an_empty_observed_path_is_not_emitted_at_all(self):
        """An empty d= would put a path that draws nothing into the page of
        every station whose archive is still empty."""
        assert '<path d=""' not in NWSSkin.sparkline(day_of_points(), [])

    def test_the_seam_is_drawn_and_both_sides_are_named(self):
        svg = NWSSkin.sparkline(day_of_points(self.FEED), week_of_obs(self.WEEK))
        assert 'class="seam"' in svg
        obs, fcast, _css = self._chips(svg)
        assert obs == 'PAST 7 DAYS ACTUAL'
        assert fcast == 'FORECASTED TEMPERATURES'

    def test_the_chip_counts_the_days_that_were_actually_drawn(self):
        """A chip fixed at seven would be a printed lie on a station that had
        just been built -- the observed half is as wide as the archive is
        long, by design.  ROUNDED DOWN: a label may understate what was drawn,
        never overstate it."""
        for hours, expected in ((self.WEEK, 'PAST 7 DAYS ACTUAL'),
                                (167, 'PAST 6 DAYS ACTUAL'),
                                (144, 'PAST 6 DAYS ACTUAL'),
                                (135, 'PAST 5 DAYS ACTUAL')):
            svg = NWSSkin.sparkline(day_of_points(self.FEED), week_of_obs(hours))
            assert self._chips(svg)[0] == expected, hours

    def test_a_dead_sensor_does_not_buy_a_week_of_credit(self):
        """observations() keeps TRAILING empty hours -- a gap between the last
        reading and the forecast is the news that weewxd stopped -- so a
        station whose sensor died six days ago still hands over 168 rows with
        24 readings in them.  Counting the rows printed PAST 7 DAYS ACTUAL
        over a curve that stops six days back, which is the class of claim
        these labels were written to retire.

        All THREE places that say it are checked, because they are three
        separate sentences and only the chip can be checked against the
        picture."""
        past = week_of_obs(self.WEEK)
        for row in past[24:]:
            row['outTemp'] = None
        assert NWSSkin._observed_span(past) == 24
        svg = NWSSkin.sparkline(day_of_points(self.FEED), past)
        assert self._chips(svg)[0] == 'PAST 1 DAY ACTUAL'
        assert 'the past 1 day this station recorded' in svg
        assert '1 day' in NWSSkin.sparkline_caption(past)
        # The half is still DRAWN a week wide -- the geometry is unchanged and
        # the hole is the point.  Only the claim shrank.
        assert self._spec(svg)['x0'] < self._seam_x(svg)

    def test_a_half_that_is_all_holes_claims_nothing(self):
        """_from_first_reading makes this unreachable from observations(), but
        the caption is a public tag and takes whatever a skin hands it."""
        past = week_of_obs(48)
        for row in past:
            row['outTemp'] = None
        assert NWSSkin._observed_span(past) == 0
        assert 'archive records behind it' in NWSSkin.sparkline_caption(past)

    def test_the_forecast_chip_claims_no_span(self):
        """Deliberate.  The NWS hourly feed is 156 records and the chart plots
        from the current hour, so that half is 6.5 days at its widest -- a day
        count there would read 6 while every reader took the chart for a
        week's forecast."""
        svg = NWSSkin.sparkline(day_of_points(self.FEED), week_of_obs(self.WEEK))
        assert not re.search(r'\d', self._chips(svg)[1])

    def test_under_a_day_the_chip_counts_hours(self):
        """The day count is floored, so a five-hour-old station would
        otherwise read "0 DAYS"."""
        assert NWSSkin._span_words(5) == '5 HOURS'
        assert NWSSkin._span_words(1) == '1 HOUR'
        assert NWSSkin._span_words(23) == '23 HOURS'
        assert NWSSkin._span_words(24) == '1 DAY'
        assert NWSSkin._span_words(47) == '1 DAY'

    def test_the_caption_counts_the_same_days_the_chip_does(self):
        """One line below the chip, and on the identical half.  Below
        CHIP_ROOM the chips go and this sentence is the only thing naming the
        halves at all, so the shorter the archive the more weight it carries.
        """
        assert '7 days' in NWSSkin.sparkline_caption(week_of_obs(self.WEEK))
        assert '3 days' in NWSSkin.sparkline_caption(week_of_obs(72))
        assert '5 hours' in NWSSkin.sparkline_caption(week_of_obs(5))
        # A fresh install has no observed half to count.
        assert 'past' not in NWSSkin.sparkline_caption([])
        assert 'archive records behind it' in NWSSkin.sparkline_caption([])

    def test_the_aria_label_counts_them_too(self):
        """This sentence is what a screen reader gets INSTEAD of the picture,
        so it is the one place the wrong number cannot be checked against what
        is on the screen."""
        svg = NWSSkin.sparkline(day_of_points(self.FEED), week_of_obs(72))
        label = re.search(r'aria-label="([^"]*)"', svg).group(1)
        assert 'the past 3 days this station recorded' in label

    def test_the_seam_falls_BETWEEN_the_two_halves(self):
        """Not ON the first forecast point.  Drawn there the rule touches the
        forecast curve while standing a full hour clear of the last observed
        one, and the gap then reads as a mistake on one side only.  The
        boundary is between the last reading and the first prediction."""
        past = week_of_obs(48)
        svg = NWSSkin.sparkline(day_of_points(), past)
        x0, x1 = float(NWSSkin.PADL), 1040 - 8
        n = 48 + 24 - 1
        step = (x1 - x0) / n
        last_observed = x0 + step * 47
        first_forecast = x0 + step * 48
        sx = self._seam_x(svg)
        assert abs(sx - (last_observed + first_forecast) / 2) < 0.1
        # Equidistant from both, which is the whole point.  The tolerance is
        # 0.11 rather than 0, because the coordinate is emitted to one decimal
        # -- up to 0.05 of rounding, which this difference sees twice.
        assert abs((sx - last_observed) - (first_forecast - sx)) < 0.11

    def test_the_seam_rule_divides_the_two_chips(self):
        """It runs the FULL height, chip band included.  Stopped at the top of
        the plot it left the two labels side by side with nothing between
        them, which at this size reads as one phrase rather than two labels.
        The line is what makes them two."""
        svg = NWSSkin.sparkline(day_of_points(self.FEED), week_of_obs(self.WEEK))
        top, bottom = self._seam_ys(svg)
        spec = self._spec(svg)
        # From the top of the BAND, not the top of the chips: the chips are
        # opaque and cover the rule where they sit, so what a reader sees is
        # the gutter between them plus a stub above them wherever the type is
        # smaller than the size the band was cut for.
        assert 0 <= top < spec['y0']
        assert bottom == spec['y1']

    def test_the_band_is_deep_enough_for_the_largest_chip_the_css_draws(self):
        """The band above the plot is sized by the chips' own type, which the
        stylesheet scales UP as the page narrows.  Too shallow and the chip is
        cut off by the top of the viewBox or sits on the curve.

        A chip is 1.6 times its type size tall: line-height:1 plus .3em of
        padding above and below.  A source-text check, which is not proof that
        anything WORKS -- tests/verify_theme.py measures the real boxes in a
        real browser.
        """
        biggest = max(_css_sizes('seamchip'))
        svg = NWSSkin.sparkline(day_of_points(self.FEED), week_of_obs(self.WEEK))
        band = self._spec(svg)['y0']
        assert band >= 1.6 * biggest
        # And not so deep that the chip rattles around in it.  The stylesheet
        # centers the chip in the band, so this bounds the clearance.
        assert band - 1.6 * biggest <= 8

    def test_the_two_halves_are_separate_strokes_that_are_not_joined(self):
        """NWS forecasts a grid square and the station measures its own back
        yard, so the last reading and the first forecast hour seldom agree.
        One stroke across the seam would smooth that step away and claim a
        continuity neither series has."""
        svg = NWSSkin.sparkline(day_of_points(), week_of_obs(48))
        sx = self._seam_x(svg)
        assert self._last_xy(self._d(svg, 'aline'))[0] < sx
        assert self._first_xy(self._d(svg, 'tline'))[0] > sx

    def test_each_half_is_drawn_from_its_own_rows(self):
        """A stroke built from the wrong slice would still draw a plausible
        line -- of the wrong data, in the right place."""
        past = week_of_obs(24, temp=40.0)
        hours = [pt(ts(2026, 9, 1, h), 80.0) for h in range(24)]
        svg = NWSSkin.sparkline(hours, past)
        observed, forecast = self._ys(self._d(svg, 'aline')), self._ys(self._d(svg, 'tline'))
        assert len(set(observed)) == 1 and len(set(forecast)) == 1
        # Colder is further down the plot, and y grows downward.
        assert observed[0] > forecast[0]

    def test_an_outage_breaks_the_observed_line(self):
        """Joining across an hour the station recorded nothing in draws a
        confident stroke through an outage."""
        past = week_of_obs(24)
        for i in range(8, 14):
            past[i]['outTemp'] = None
        d = self._d(NWSSkin.sparkline(day_of_points(), past), 'aline')
        assert d.count('M') == 2

    def test_an_unbroken_week_is_one_stroke(self):
        d = self._d(NWSSkin.sparkline(day_of_points(), week_of_obs(24)), 'aline')
        assert d.count('M') == 1

    def test_a_lone_reading_between_outages_still_appears(self):
        """A broken stroke draws NOTHING for a single point -- a subpath of
        one moveto has no length -- so the hour would vanish silently."""
        past = week_of_obs(24)
        for i, r in enumerate(past):
            if i != 12:
                r['outTemp'] = None
        svg = NWSSkin.sparkline(day_of_points(), past)
        assert svg.count('class="adot"') == 1

    def test_a_reading_with_a_neighbor_gets_no_dot(self):
        assert 'class="adot"' not in NWSSkin.sparkline(day_of_points(), week_of_obs(24))

    def test_one_scale_covers_both_weeks(self):
        """A cold snap last week rescales the forecast half, and that is the
        point: "warm for the week" and "warm for the fortnight" are different
        claims and only a shared scale tells them apart."""
        past = week_of_obs(24, temp=10.0)
        svg = NWSSkin.sparkline(day_of_points(), past)     # forecast is 60..83
        assert 'class="ylab">10&deg;' in svg
        assert 'class="ylab">85&deg;' in svg

    def test_night_shading_crosses_the_seam(self):
        """Shading that stopped at the join would read as two charts pasted
        together rather than one fortnight."""
        past = week_of_obs(24, is_daytime=False)
        hours = [pt(ts(2026, 9, 1, h), 70.0, is_daytime=False) for h in range(24)]
        svg = NWSSkin.sparkline(hours, past)
        band = re.search(r'<rect x="([\d.]+)" y="\d+" width="([\d.]+)"', svg)
        assert band and float(band.group(1)) < self._seam_x(svg)
        assert float(band.group(1)) + float(band.group(2)) > self._seam_x(svg)

    def test_every_slot_reaches_the_crosshair_including_the_empty_ones(self):
        """The script turns a pointer position into an INDEX by dividing the
        plot width by the number of points.  Leaving the empty hours out of
        that list would put every reading on the wrong hour."""
        past = week_of_obs(24)
        past[5]['outTemp'] = None
        spec = self._spec(NWSSkin.sparkline(day_of_points(), past))
        assert len(spec['p']) == 48
        assert spec['p'][5]['T'] is None
        assert spec['p'][6]['T'] is not None

    def test_the_observed_points_say_so(self):
        """A measurement and a prediction must not be reported in the same
        words."""
        spec = self._spec(NWSSkin.sparkline(day_of_points(), week_of_obs(24)))
        assert all(p.get('o') == 1 for p in spec['p'][:24])
        assert all('o' not in p for p in spec['p'][24:])

    def test_the_page_script_withholds_a_dot_for_an_empty_hour(self):
        """An empty hour keeps its place in the list, so the crosshair still
        moves to it; what it must not do is compute a y from null."""
        js = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               '..', 'skins', 'nws', 'scripts', 'nws.js')).read()
        assert 'no reading' in js
        assert "pt.T === null" in js
        assert "classList.toggle('past'" in js

    def test_a_very_short_history_keeps_the_seam_and_drops_BOTH_chips(self):
        """A station two hours old still gets the join; what it does not get
        is a chip hanging off the left edge.

        BOTH OR NEITHER.  The asymmetric words this replaced could be dropped
        one at a time; a matched pair centered on the rule cannot -- one of
        them alone would straddle the rule it is meant to stand beside.  The
        caption under the chart still names both halves.
        """
        svg = NWSSkin.sparkline(day_of_points(self.FEED), week_of_obs(2))
        assert 'class="seam"' in svg
        assert self._chips(svg) is None

    def test_the_pair_goes_the_moment_either_side_is_too_narrow(self):
        """Both sides are tested, not just the short one: a week of archive
        against a four-period feed pushes the seam so far RIGHT that the
        forecast chip is the one with nowhere to sit."""
        wide = NWSSkin.sparkline(day_of_points(self.FEED), week_of_obs(self.WEEK))
        assert self._chips(wide) is not None
        assert self._chips(NWSSkin.sparkline(day_of_points(4),
                                             week_of_obs(self.WEEK))) is None

    def test_a_shown_chip_clears_the_plot_edge(self):
        """What CHIP_ROOM exists to guarantee, in the units the geometry is
        written in: the pair is shown only where a chip of the widest size the
        stylesheet ever draws fits between the rule and the edge of the plot.

        The widths themselves are the browser's business -- see CHIP_GAP for
        why nothing here computes one -- so this checks the DECISION against
        the measured constant, and tests/verify_theme.py checks the constant
        against the real boxes.
        """
        # 134 is the shortest archive the pair fits against a full feed;
        # a shorter feed lets it in sooner, which the case below covers.
        for hours in (134, 144, self.WEEK):
            svg = NWSSkin.sparkline(day_of_points(self.FEED), week_of_obs(hours))
            assert self._chips(svg) is not None, hours
            spec, sx = self._spec(svg), self._seam_x(svg)
            need = NWSSkin.CHIP_WIDTH + NWSSkin.CHIP_GAP
            assert sx - spec['x0'] >= need, hours
            assert spec['x1'] - sx >= need, hours

    def test_the_pair_survives_the_feed_shrinking_between_generations(self):
        """The forecast half is NOT a fixed 156 hours.  Ended periods are
        dropped on read, so it loses an hour every hour until NWS issues the
        next generation -- and the seam walks right as it does, which is the
        direction that squeezes the forecast chip.

        Measured on a production database: every generation is 156 records,
        the drawn half runs 152-156, and gaps between generations run half an
        hour to four.  CHIP_WIDTH is sized so the pair holds through twelve,
        because chips that blink out and back on a healthy station are worse
        than chips that are never shown at all.
        """
        for feed in range(144, self.FEED + 1):
            svg = NWSSkin.sparkline(day_of_points(feed), week_of_obs(self.WEEK))
            assert self._chips(svg) is not None, feed

    def test_the_chips_are_placed_from_the_geometry_the_chart_was_drawn_with(self):
        """Every number handed to the stylesheet comes from THIS chart rather
        than being written down a second time in the css, so the placement
        cannot drift from the room test that allowed it.

        --chip-gap and --band-mid are bare NUMBERS of viewBox units, not
        lengths: the stylesheet turns units into pixels with the container
        query that also sizes the type, and a percentage gap inside a
        max-content grid resolves against a width that is not yet known -- to
        zero.
        """
        svg = NWSSkin.sparkline(day_of_points(self.FEED), week_of_obs(self.WEEK))
        _obs, _fcast, css = self._chips(svg)
        spec, sx = self._spec(svg), self._seam_x(svg)
        assert abs(float(css['--seam'].rstrip('%')) - 100.0 * sx / 1040) < 0.01
        # The pair straddles the rule, so each chip stands CHIP_GAP clear.
        assert float(css['--chip-gap']) == 2 * NWSSkin.CHIP_GAP
        assert float(css['--band-mid']) == spec['y0'] / 2.0

    def test_the_chips_ride_outside_the_svg(self):
        """The chart carries role="img" with an aria-label, which hides every
        <text> inside it from assistive technology -- so as SVG the two words
        naming the halves could be reached by no route at all.  As markup
        beside the chart they are read like any other text on the page."""
        svg = NWSSkin.sparkline(day_of_points(self.FEED), week_of_obs(self.WEEK))
        assert svg.index('</svg>') < svg.index('seamlegend')
        assert 'role="img"' in svg

    def test_each_chip_carries_its_own_half_s_curve_color(self):
        """The box IS the swatch, which is what the two floating words this
        replaced could never be: --fc-muted is the recorded curve (.aline) and
        --fc-hi is the forecast one (.tline).

        A source-text check, which is not proof that anything WORKS: the
        computed fills are probed in a real browser by tests/verify_theme.py,
        and tests/test_nws_css.py is what proves they are legible on each
        other in both palettes.
        """
        css = open(CSS_PATH).read()
        assert re.search(r'\.seamchip\{[^}]*background:var\(--fc-muted\)', css)
        assert re.search(r'\.seamchip\.fcast\{background:var\(--fc-hi\)', css)
        assert re.search(r'\.seamchip\{[^}]*color:var\(--fc-on-accent\)', css)
        # line-height:1 is load-bearing, not tidiness: at `normal` the
        # fallback face gives about 1.36, which takes the narrow-screen chip
        # off the top of the viewBox and into the plot at once.  It is also
        # what makes the box exactly 1.6em tall, which the band is cut for.
        assert re.search(r'\.seamchip\{[^}]*line-height:1[;}]', css)

    def test_the_readout_is_pushed_clear_of_the_chip_band(self):
        """The crosshair readout is anchored to the top of the same wrapper
        and is sized in PAGE pixels, while the chips are sized in the chart's
        units -- two ladders that cross, so whether they collide depends on
        the page width.  At 1280 they do not; at 800 the readout covered the
        forecast chip by 69x20, hiding the label while the reader works the
        chart.

        The offset is the band, and NWSSkin owns that number.  A source-text
        check that the two have not drifted apart; the real boxes are measured
        in a browser by tests/verify_theme.py.
        """
        css = open(CSS_PATH).read()
        band = 12 + NWSSkin.CHIP_BAND
        assert ('.twoweek .readout{top:calc(100cqw * %d / 1040)}' % band) in css

    def test_the_chips_are_sized_in_the_charts_own_units(self):
        """An em ladder rooted in the page's 16px cannot do this: the chips
        have to track the chart's other labels as the page narrows, and the
        chart is stretched to the column width.  100cqw of the wrapper is
        1040 viewBox units, which is what makes the two the same scale --
        so the wrapper has to BE a container."""
        css = open(CSS_PATH).read()
        assert re.search(r'\.sparkwrap\{[^}]*container-type:inline-size', css)
        for size in _css_sizes('seamchip'):
            assert 'calc(100cqw * %d / 1040)' % size in css

    def test_the_two_week_chart_bakes_no_color_either(self):
        svg = NWSSkin.sparkline(day_of_points(), week_of_obs(24))
        assert 'fill="#' not in svg and 'stroke="#' not in svg


class TestObservations:
    """observations() -- the archive on the forecast's own hourly grid."""

    class _Skin(NWSSkin):
        """A search list with no report engine behind it: the archive read and
        the almanac are the two things that need one, and each case here
        supplies its own."""
        def __init__(self, readings=None):
            self._readings = readings or {}

        def _hourly_means(self, start, stop):
            return dict(self._readings)

        def _daytime(self, first_ts, last_ts):
            return lambda when: True

    @staticmethod
    def _forecast(start):
        return [pt(start + i * 3600, 70.0) for i in range(12)]

    def test_an_empty_archive_costs_no_almanac_work(self):
        """With nothing to plot there is nothing to shade, and the
        fresh-install path -- an archive with nothing in it yet -- is the
        common one.  Eight sunrise/sunset lookups per report cycle to decide
        the shading of a chart that will not be drawn is work nobody asked
        for."""
        class _NoAlmanac(TestObservations._Skin):
            def _daytime(self, first_ts, last_ts):
                raise AssertionError('the almanac was consulted anyway')

        assert _NoAlmanac().observations(self._forecast(ts(2026, 9, 1, 12))) == []

    def test_no_forecast_means_no_observed_week(self):
        """There is nothing to hang the seam on."""
        assert self._Skin().observations([]) == []

    def test_an_empty_archive_gives_an_empty_week(self):
        assert self._Skin().observations(self._forecast(ts(2026, 9, 1, 12))) == []

    def test_one_row_per_hour_back_to_the_first_reading(self):
        seam = int(ts(2026, 9, 1, 12))
        readings = {seam - i * 3600: 50.0 + i for i in range(1, 5)}
        rows = self._Skin(readings).observations(self._forecast(seam), back=168)
        assert len(rows) == 4
        assert [r['startTime'] for r in rows] == [seam - i * 3600 for i in (4, 3, 2, 1)]
        assert rows[-1]['outTemp'] == 51.0

    def test_a_young_station_gets_a_short_chart_not_a_week_of_lies(self):
        """Data-driven width: two days of archive is two days of chart."""
        seam = int(ts(2026, 9, 1, 12))
        readings = {seam - i * 3600: 60.0 for i in range(1, 49)}
        rows = self._Skin(readings).observations(self._forecast(seam))
        assert len(rows) == 48

    def test_an_interior_outage_keeps_its_place(self):
        """The crosshair indexes this list by position, and the line must
        break where the station stopped -- both need the hour to stay."""
        seam = int(ts(2026, 9, 1, 12))
        readings = {seam - i * 3600: 60.0 for i in (1, 2, 5, 6)}
        rows = self._Skin(readings).observations(self._forecast(seam))
        assert len(rows) == 6
        assert [r['outTemp'] is None for r in rows] == [False, False, True, True,
                                                        False, False]

    def test_a_trailing_outage_is_kept_not_trimmed(self):
        """A gap between the last reading and the forecast is exactly the
        news that weewxd stopped; closing it would hide that."""
        seam = int(ts(2026, 9, 1, 12))
        readings = {seam - i * 3600: 60.0 for i in (10, 11, 12)}
        rows = self._Skin(readings).observations(self._forecast(seam))
        assert len(rows) == 12
        assert rows[-1]['outTemp'] is None

    def test_an_unreadable_archive_costs_the_chart_not_the_page(self):
        """A misconfigured binding must not take the 7 Day page down with it.
        This runs on the report thread, so there is no Terminate to let
        through, and a sample report is exactly where a broken archive is
        most likely."""
        def no_such_binding():
            raise ValueError('no such binding')

        assert _skin_with(db_lookup=no_such_binding)._hourly_means(0, 3600) == {}

    def test_the_rows_are_shaped_like_points(self):
        """One list of both halves goes to the night bands and the crosshair,
        so the observed rows must carry the same keys."""
        seam = int(ts(2026, 9, 1, 12))
        rows = self._Skin({seam - 3600: 60.0}).observations(self._forecast(seam))
        assert set(rows[0]) == {'startTime', 'outTemp', 'dewpoint', 'pop', 'isDaytime'}

    def test_the_chart_unit_is_the_reports_own(self):
        """Not "whatever nws.py stored".  $nwsforecast now hands the chart
        numbers already converted to the report's unit, so the observed half
        has to be brought to that same one -- 20 C and 68 F are the same
        afternoon, and on one axis unconverted they land 48 degrees apart."""
        assert _skin_with(weewx.units.USUnits)._forecast_temp_unit() == 'degree_F'
        assert _skin_with(weewx.units.MetricUnits)._forecast_temp_unit() == 'degree_C'


class TestHourlyMeans:
    """The archive on the chart's own grid: ABSOLUTE hourly slots, whatever
    the clock did that week, and every record converted from the unit system
    it was recorded in."""

    class _Manager:
        table_name = 'archive'

        def __init__(self, rows):
            self.rows = rows

        def genSql(self, _sql, args):
            start, stop = args
            return ((w, u, v) for w, u, v in self.rows if start < w <= stop)

    def _skin(self, rows, report_units=None):
        return _skin_with(report_units,
                          db_lookup=lambda: TestHourlyMeans._Manager(rows))

    def test_the_fall_clock_change_does_not_lose_an_hour(self):
        """weewx.xtypes.get_series(..., 'avg', 3600) would be the obvious way
        to ask, and it is the wrong one here: its intervals are constant in
        LOCAL time, while this chart's x axis is absolute time -- the forecast
        half is hourly in absolute time and the two halves share one geometry.

        The second assertion is what keeps the first from being vacuous: on
        the night the clock goes back, intervalgen yields one interval FEWER
        than there are hours, because the repeated hour gets none of its own
        and its neighbor's runs two hours.  Reading through it would leave a
        one-hour hole in the recorded week every November, beside an hour
        whose mean silently covered two.
        """
        # 2026-11-01: 2 am PDT becomes 1 am PST.  Twelve absolute hours from
        # 10 pm the night before carry the window straight through it.
        start = int(ts(2026, 10, 31, 22))
        rows = [(start + h * 3600 + 1800, weewx.US, 50.0 + h) for h in range(12)]
        means = self._skin(rows)._hourly_means(start, start + 12 * 3600)
        assert sorted(means) == [start + h * 3600 for h in range(12)]
        assert means[start + 11 * 3600] == 61.0

        import weeutil.weeutil
        assert len(list(weeutil.weeutil.intervalgen(
            start, start + 12 * 3600, 3600))) == 11

    def test_a_reading_on_the_hour_belongs_to_the_hour_before_it(self):
        """weewx stamps a record at the END of its interval, so the window is
        (start, stop] and 10:00 closes the 9 o'clock hour."""
        start = int(ts(2026, 9, 1, 9))
        means = self._skin([(start + 3600, weewx.US, 70.0)])._hourly_means(
            start, start + 7200)
        assert list(means) == [start]

    def test_an_hour_is_the_mean_of_its_readings(self):
        start = int(ts(2026, 9, 1, 9))
        rows = [(start + 900, weewx.US, 60.0), (start + 1800, weewx.US, 62.0),
                (start + 2700, weewx.US, 64.0)]
        assert self._skin(rows)._hourly_means(start, start + 3600) == {start: 62.0}

    def test_a_metric_station_is_converted_not_plotted_raw(self):
        """20 C and 68 F are the same afternoon; on one axis unconverted they
        land 48 degrees apart."""
        start = int(ts(2026, 9, 1, 9))
        means = self._skin([(start + 1800, weewx.METRIC, 20.0)])._hourly_means(
            start, start + 3600)
        assert round(means[start]) == 68

    def test_an_hour_with_two_unit_systems_averages_after_converting(self):
        """Raw values from two systems cannot be added: a station switched
        mid-hour would otherwise average 20 C with 68 F and report 44."""
        start = int(ts(2026, 9, 1, 9))
        rows = [(start + 900, weewx.METRIC, 20.0), (start + 1800, weewx.US, 68.0)]
        assert round(self._skin(rows)._hourly_means(start, start + 3600)[start]) == 68

    def test_a_metric_report_gets_celsius_from_a_us_archive(self):
        """The other direction, and the one that matters now: the forecast
        half arrives already converted to the report's unit, so a US archive
        on a metric report has to be converted too or the two halves would be
        drawn on one axis in two scales."""
        start = int(ts(2026, 9, 1, 9))
        means = self._skin([(start + 1800, weewx.US, 68.0)],
                           report_units=weewx.units.MetricUnits)._hourly_means(
            start, start + 3600)
        assert round(means[start]) == 20

    def test_a_corrupt_unit_system_costs_the_chart_not_the_page(self):
        """WeeWX knows three unit systems and getStandardUnitType() raises
        KeyError for anything else, so a hand-edited archive row carrying a
        usUnits of 3 would take the whole 7 Day page down if the conversion
        sat outside the guard -- which is the failure the guard exists to
        prevent."""
        start = int(ts(2026, 9, 1, 9))
        assert self._skin([(start + 1800, 3, 60.0)])._hourly_means(
            start, start + 3600) == {}

    def test_an_empty_window_is_an_empty_mapping(self):
        start = int(ts(2026, 9, 1, 9))
        assert self._skin([])._hourly_means(start, start + 3600) == {}


class TestTempBar:

    def test_a_normal_day_spans_low_to_high(self):
        out = NWSSkin.temp_bar({'hi': 80.0, 'lo': 60.0}, 50.0, 90.0)
        assert 'class="lo">60&deg;' in out and 'class="hi">80&deg;' in out
        assert 'class="fill"' in out

    def test_the_hottest_day_does_not_paint_outside_the_track(self):
        """A minimum width makes a one-value day visible, but on the day
        holding the week's high it would start at 100% and overflow."""
        out = NWSSkin.temp_bar({'hi': 90.0, 'lo': 90.0}, 50.0, 90.0)
        left = float(out.split('left:')[1].split('%')[0])
        width = float(out.split('width:')[1].split('%')[0])
        assert left + width <= 100.0

    def test_a_day_whose_daylight_has_passed_shows_a_marker_not_a_range(self):
        out = NWSSkin.temp_bar({'hi': None, 'lo': 58.0}, 50.0, 90.0)
        assert 'class="dot"' in out and 'class="hi part">low' in out
        assert 'class="fill"' not in out

    def test_a_day_with_no_low_yet_still_draws_its_high(self):
        out = NWSSkin.temp_bar({'hi': 80.0, 'lo': None}, 50.0, 90.0)
        assert 'class="hi">80&deg;' in out and '&mdash;' in out

    def test_a_day_with_neither_is_an_em_dash(self):
        assert NWSSkin.temp_bar({'hi': None, 'lo': None}, 50.0, 90.0) == \
            '<span class="hi part">&mdash;</span>'

    def test_a_zero_width_week_does_not_divide_by_zero(self):
        out = NWSSkin.temp_bar({'hi': 70.0, 'lo': 70.0}, 70.0, 70.0)
        assert '<span' in out


class TestPopCell:

    def test_a_value_at_or_above_the_threshold_shows_with_a_droplet(self):
        out = NWSSkin.pop_cell({'pop': vh(40, 'outHumidity')})
        assert '40%' in out and 'class="drop"' in out

    def test_a_value_below_the_threshold_renders_as_nothing_at_all(self):
        """Blank on the quiet days is what makes a number pull the eye."""
        assert NWSSkin.pop_cell({'pop': vh(14, 'outHumidity')}) == ''

    def test_the_threshold_is_weather_govs_own_fifteen(self):
        assert NWSSkin.POP_MIN == 15
        assert NWSSkin.pop_cell({'pop': vh(15, 'outHumidity')}) != ''
        assert NWSSkin.pop_cell({'pop': vh(14, 'outHumidity')}) == ''

    def test_an_absent_value_is_an_em_dash_not_a_blank(self):
        """A suppressed value and a missing one must not look the same."""
        out = NWSSkin.pop_cell({'pop': vh(None, 'outHumidity')})
        assert '&mdash;' in out and 'pop-na' in out

    def test_a_low_but_shown_value_gets_its_own_class(self):
        assert 'pop-lo' in NWSSkin.pop_cell({'pop': vh(17, 'outHumidity')})
        assert 'pop-lo' not in NWSSkin.pop_cell({'pop': vh(25, 'outHumidity')})


class TestWind:

    def test_a_range_is_printed_as_a_range(self):
        out = NWSSkin.wind_cell(wind_period(2.0, 9.0), ' mph')
        assert '2&ndash;9 mph' in out

    def test_a_single_speed_is_printed_alone(self):
        out = NWSSkin.wind_cell(wind_period(9.0), ' mph')
        assert '9 mph' in out and '&ndash;' not in out

    def test_a_range_whose_ends_round_together_collapses(self):
        out = NWSSkin.wind_cell(wind_period(9.1, 9.4), ' mph')
        assert '&ndash;' not in out

    def test_an_absent_direction_is_left_out_rather_than_printed_as_na(self):
        out = NWSSkin.wind_cell(wind_period(9.0, direction=None), ' mph')
        assert 'class="wd"' not in out and '9 mph' in out

    def test_an_absent_speed_yields_an_empty_cell(self):
        assert NWSSkin.wind_cell(wind_period(None), ' mph') == ''

    def test_wind_text_is_a_sentence_not_a_stack(self):
        out = NWSSkin.wind_text(wind_period(2.0, 9.0), ' mph')
        assert '<span' not in out and '2&ndash;9 mph' in out

    def test_wind_text_with_no_speed_is_an_em_dash(self):
        assert NWSSkin.wind_text(wind_period(None), ' mph') == '&mdash;'


class TestNumCell:

    def test_a_value_is_rounded_and_suffixed(self):
        assert NWSSkin.num_cell(vh(67.4, 'outTemp')) == '67&deg;'
        assert NWSSkin.num_cell(vh(67.4, 'outTemp'), '%') == '67%'

    def test_an_absent_value_is_an_em_dash(self):
        """`.format()` prints the literal "N/A", which would then get a
        degree sign glued to it."""
        assert NWSSkin.num_cell(vh(None, 'outTemp')) == '&mdash;'

    def test_a_missing_value_helper_is_an_em_dash(self):
        """The empty-archive case: on a fresh install $day.outTemp has
        nothing in it, and the sample report is often the first page a new
        user sees."""
        assert NWSSkin.num_cell(None) == '&mdash;'


class TestFuzzy:

    def test_half_rounds_up_like_javascript_not_like_python(self):
        """python rounds half to EVEN, so an alert 30 seconds out would first
        paint "0 minutes" and silently become "1 minute" on the first tick of
        the page script, which uses Math.round."""
        assert NWSSkin._round_half_up(0.5) == 1
        assert NWSSkin._round_half_up(2.5) == 3
        assert NWSSkin.fuzzy(30) == '1 minute'

    def test_singular_and_plural(self):
        assert NWSSkin.fuzzy(3600) == '1 hour'
        assert NWSSkin.fuzzy(7200) == '2 hours'
        assert NWSSkin.fuzzy(86400 * 3) == '3 days'

    def test_the_ladder_switches_at_an_hour_and_two_days(self):
        assert NWSSkin.fuzzy(3599).endswith('minutes')
        assert NWSSkin.fuzzy(3601).endswith('hour')
        assert NWSSkin.fuzzy(86400 * 2 - 1).endswith('hours')
        assert NWSSkin.fuzzy(86400 * 2 + 1).endswith('days')

    def test_a_negative_span_reads_the_same(self):
        assert NWSSkin.fuzzy(-7200) == '2 hours'


class TestAlertCard:

    def test_an_in_effect_alert_gets_the_on_badge(self):
        now = datetime.datetime.now().timestamp()
        out = NWSSkin.card(alert_rec(onset=now - 60, ends=now + 3600,
                                     expires=now + 7200))
        assert 'class="badge on"' in out and 'In effect now' in out

    def test_a_future_alert_counts_down_to_its_start(self):
        now = datetime.datetime.now().timestamp()
        out = NWSSkin.card(alert_rec(onset=now + 7200, ends=now + 10800,
                                     expires=now + 10800))
        assert 'class="badge soon"' in out and 'Begins in 2 hours' in out

    def test_a_finished_alert_reads_expired(self):
        now = datetime.datetime.now().timestamp()
        out = NWSSkin.card(alert_rec(onset=now - 7200, ends=now - 3600,
                                     expires=now - 3600))
        assert 'class="badge past"' in out and 'Expired' in out

    def test_an_alert_with_no_onset_is_in_effect_from_its_effective_time(self):
        """The case a station actually sees, and the one that matters most:
        NWS gave no onset, but it always says when the message took effect, so
        the alert is in effect from then.

        Before 6.1 such an alert could not be stored at all -- the sanity
        check threw away the whole reply -- so this was unreachable.  The
        moment it became reachable, getting it wrong would badge an
        Evacuation Immediate that is in effect RIGHT NOW as "Not yet begun".
        Two of the three null-onset alerts in a national sample were exactly
        that event.
        """
        now = datetime.datetime.now().timestamp()
        rec = alert_rec(onset=None, effective=now - 3600,
                        ends=now + 3600, expires=now + 3600)
        out = NWSSkin.card(rec)
        assert 'class="badge on"' in out and 'In effect now' in out
        assert 'Not yet begun' not in out
        assert '<b>1 alert</b> in effect' in NWSSkin.count_line([rec])

    def test_an_alert_with_no_onset_starts_at_its_effective_time(self):
        """The window's start is printed from the same fallback its bar is
        drawn from, and the page script is handed that same instant.
        Stamping the raw onset printed N/A beside a bar that began at the
        effective time."""
        now = datetime.datetime.now().timestamp()
        out = NWSSkin.card(alert_rec(onset=None, effective=now - 3600,
                                     ends=now + 3600, expires=now + 3600))
        assert 'N/A' not in out
        assert NWSSkin.stamp(vh(now - 3600)) + ' <i>(effective)</i>' in out
        assert 'data-onset="%d"' % (now - 3600) in out

    def test_an_end_at_or_before_the_start_shows_both_times(self):
        """No span to draw a bar across, but still an end: the card says both
        times, and never that there is no end."""
        now = datetime.datetime.now().timestamp()
        out = NWSSkin.card(alert_rec(onset=now + 7200, ends=now + 3600,
                                     expires=now + 10800))
        assert 'aw-bar' not in out
        assert 'no end time given' not in out
        assert '&ndash; ' + NWSSkin.stamp(vh(now + 3600)) in out

    def test_an_alert_with_no_onset_whose_window_closed_reads_expired(self):
        """All three consumers used to disagree about this one alert: the
        count line called it upcoming, the card badged it "Not yet begun",
        and the page script never saw it at all because it selected
        .alert[data-onset] and no onset attribute was written.  They now share
        one classification."""
        now = datetime.datetime.now().timestamp()
        rec = alert_rec(onset=None, effective=now - 7200,
                        ends=now - 3600, expires=now - 3600)
        out = NWSSkin.card(rec)
        assert 'class="badge past"' in out and 'Expired' in out
        assert 'Not yet begun' not in out
        assert 'ended 1 hour ago' in out
        assert 'none in effect now' in NWSSkin.count_line([rec])

    def test_an_open_ended_alert_says_so_and_leans_on_expires(self):
        """One alert in ten never ends; expires is the honest stand-in and
        the card says which it is showing."""
        now = datetime.datetime.now().timestamp()
        out = NWSSkin.card(alert_rec(onset=now - 60, ends=None,
                                     expires=now + 3600))
        assert 'no end time given' in out
        assert '(expires)' in out

    def test_an_open_ended_alert_carries_no_data_ends(self):
        """The page script infers open-endedness from the attribute being
        absent, so writing it would flip the card's meaning."""
        now = datetime.datetime.now().timestamp()
        out = NWSSkin.card(alert_rec(onset=now - 60, ends=None,
                                     expires=now + 3600))
        assert 'data-ends=' not in out
        assert 'data-onset=' in out and 'data-expires=' in out

    def test_a_null_end_reads_as_no_end_time_given(self):
        now = datetime.datetime.now().timestamp()
        out = NWSSkin.card(alert_rec(onset=now - 60, ends=None,
                                     expires=now + 3600))
        assert 'no end time given' in out
        assert 'data-ends=' not in out

    def test_a_real_end_on_the_expiry_still_gets_an_end_time(self):
        """The 6.0 reading -- ends equal to expires means open-ended -- was a
        false positive on an alert that genuinely ends when its message
        expires.  Such a card now shows the end it was given."""
        now = datetime.datetime.now().timestamp()
        out = NWSSkin.card(alert_rec(onset=now - 60, ends=now + 3600,
                                     expires=now + 3600))
        assert 'no end time given' not in out
        assert 'data-ends=' in out

    def test_the_window_bar_places_now_between_onset_and_end(self):
        now = datetime.datetime.now().timestamp()
        out = NWSSkin.card(alert_rec(onset=now - 3600, ends=now + 3600,
                                     expires=now + 3600 * 2))
        frac = float(out.split('aw-now" style="left:')[1].split('%')[0])
        assert 40.0 < frac < 60.0

    def test_a_severity_becomes_a_rail_class(self):
        now = datetime.datetime.now().timestamp()
        for sev in ('Extreme', 'Severe', 'Moderate', 'Minor'):
            out = NWSSkin.card(alert_rec(onset=now - 60, ends=now + 60,
                                         expires=now + 60, severity=sev))
            assert 'sev-%s' % sev.lower() in out

    def test_the_severity_is_NAMED_not_just_colored(self):
        """Through 6.0 severity reached the reader as a rail color and a bare
        colored dot, and the word appeared once -- sixth in a six-item gray
        footer.  Color alone conveys nothing to a reader who cannot see the
        difference, which is a WCAG 1.4.1 failure, and it mattered more here
        than the rule suggests: these cards are SORTED by severity and the
        count line says "most serious first", so the page announced that the
        order meant something while hiding the key.
        """
        now = datetime.datetime.now().timestamp()
        for sev in ('Extreme', 'Severe', 'Moderate', 'Minor'):
            out = NWSSkin.card(alert_rec(onset=now - 60, ends=now + 60,
                                         expires=now + 60, severity=sev))
            assert '<span class="sevchip">%s</span>' % sev in out, sev

    def test_the_bare_colored_dot_is_gone(self):
        """It was the only thing in that slot and it said nothing at all: no
        text, no title, no aria-label."""
        now = datetime.datetime.now().timestamp()
        out = NWSSkin.card(alert_rec(onset=now - 60, ends=now + 60,
                                     expires=now + 60, severity='Severe'))
        assert 'sevdot' not in out

    def test_the_footer_no_longer_repeats_the_severity(self):
        """Certainty and urgency stay there, being genuinely secondary."""
        now = datetime.datetime.now().timestamp()
        out = NWSSkin.card(alert_rec(onset=now - 60, ends=now + 60,
                                     expires=now + 60, severity='Moderate'))
        assert 'severity' not in out
        assert 'Likely certainty' in out and 'Expected urgency' in out

    def test_an_absent_severity_becomes_unknown(self):
        now = datetime.datetime.now().timestamp()
        out = NWSSkin.card(alert_rec(onset=now - 60, ends=now + 60,
                                     expires=now + 60, severity=None))
        assert 'sev-unknown' in out
        assert '<span class="sevchip">Unknown</span>' in out

    def test_a_response_becomes_a_chip_in_a_readers_words(self):
        now = datetime.datetime.now().timestamp()
        for cap, words in (('Execute', 'Act now'), ('Shelter', 'Take shelter'),
                           ('AllClear', 'All clear'), ('Avoid', 'Avoid'),
                           ('SomethingNew', 'SomethingNew')):
            out = NWSSkin.card(alert_rec(onset=now - 60, ends=now + 60,
                                         expires=now + 60, response=cap))
            assert '<span class="respchip">%s</span>' % words in out, cap

    def test_no_response_or_none_gets_no_chip(self):
        now = datetime.datetime.now().timestamp()
        for cap in (None, 'None'):
            out = NWSSkin.card(alert_rec(onset=now - 60, ends=now + 60,
                                         expires=now + 60, response=cap))
            assert 'respchip' not in out, cap

    def test_a_short_area_list_is_inline_and_a_long_one_folds(self):
        """A marine alert can name fifty-odd zones; the card lists a few and
        folds the rest behind their count, without script."""
        now = datetime.datetime.now().timestamp()
        def card(area):
            return NWSSkin.card(alert_rec(onset=now - 60, ends=now + 60,
                                          expires=now + 60, area=area))
        assert '<p class="aarea">Covers Presque Isle; Alpena</p>' in card('Presque Isle; Alpena')
        many = card('; '.join('Zone %d' % i for i in range(12)))
        assert '<summary>Covers 12 areas</summary>' in many and 'Zone 11' in many
        assert 'aarea' not in card(None) and 'aarea' not in card('')

    def test_an_instruction_gets_a_callout_and_its_absence_does_not(self):
        """Four alerts in five carry no instruction; they get no empty box."""
        now = datetime.datetime.now().timestamp()
        with_i = NWSSkin.card(alert_rec(onset=now - 60, ends=now + 60,
                                        expires=now + 60,
                                        instructions='Stay indoors.'))
        without = NWSSkin.card(alert_rec(onset=now - 60, ends=now + 60,
                                         expires=now + 60))
        assert 'What to do' in with_i and 'Stay indoors.' in with_i
        assert 'What to do' not in without

    def test_an_instruction_is_reflowed_like_the_description(self):
        now = datetime.datetime.now().timestamp()
        out = NWSSkin.card(alert_rec(
            onset=now - 60, ends=now + 60, expires=now + 60,
            instructions='Stay\nindoors and\nkeep cool.\n\nCheck on neighbors.'))
        assert 'Stay indoors and keep cool.' in out
        assert out.count('<p>') == 2

    def test_an_nws_headline_is_title_cased_with_the_plain_one_beneath(self):
        now = datetime.datetime.now().timestamp()
        out = NWSSkin.card(alert_rec(
            onset=now - 60, ends=now + 60, expires=now + 60,
            nws_headline='HEAT ADVISORY IN EFFECT UNTIL 8 PM PDT',
            headline='Heat Advisory issued'))
        assert 'Heat Advisory In Effect Until 8 PM PDT' in out
        assert 'class="asub"' in out

    def test_without_an_nws_headline_the_plain_one_stands_alone(self):
        now = datetime.datetime.now().timestamp()
        out = NWSSkin.card(alert_rec(onset=now - 60, ends=now + 60,
                                     expires=now + 60, headline='Heat Advisory'))
        assert 'class="asub"' not in out
        assert 'Heat Advisory' in out

    def test_a_starred_description_becomes_labeled_sections(self):
        now = datetime.datetime.now().timestamp()
        out = NWSSkin.card(alert_rec(
            onset=now - 60, ends=now + 60, expires=now + 60,
            description='* WHAT...Damaging winds.\n* WHERE...The coast.'))
        assert out.count('class="asec"') == 2
        assert 'class="ak">What<' in out and 'class="ak">Where<' in out

    def test_free_prose_falls_through_to_measured_paragraphs(self):
        """Three quarters of real alerts have no structure at all."""
        now = datetime.datetime.now().timestamp()
        out = NWSSkin.card(alert_rec(
            onset=now - 60, ends=now + 60, expires=now + 60,
            description='A strong storm approaches.'))
        assert 'class="alead"' in out and 'class="asec"' not in out

    def test_markup_in_the_feed_is_escaped(self):
        """Forecast and alert prose lands in markup and Cheetah does not
        escape it, so an ampersand would reach the validator raw."""
        now = datetime.datetime.now().timestamp()
        out = NWSSkin.card(alert_rec(
            onset=now - 60, ends=now + 60, expires=now + 60,
            description='Wind & rain <b>now</b>'))
        assert '&amp;' in out and '&lt;b&gt;' in out
        assert '<b>now</b>' not in out

    def test_the_cap_id_and_sender_address_are_not_on_the_page(self):
        """The footer carries office, type, severity, certainty, urgency and
        the issue time -- not fifteen rows of CAP plumbing."""
        now = datetime.datetime.now().timestamp()
        out = NWSSkin.card(alert_rec(onset=now - 60, ends=now + 60,
                                     expires=now + 60))
        assert 'class="ameta"' in out
        assert 'NWS Bay Area' in out and 'Likely certainty' in out


class TestCountLine:
    """The line that heads the alerts page.

    It states how many alerts are IN EFFECT, which is a fact about the clock,
    so scripts/nws.js rewrites it every minute from the cards' own recomputed
    state.  Both implementations must produce identical text -- see
    test_the_page_script_carries_the_same_wording.
    """

    def test_all_in_effect(self):
        now = datetime.datetime.now().timestamp()
        alerts = [alert_rec(onset=now - 60, ends=now + 60, expires=now + 60)]
        assert 'in effect' in NWSSkin.count_line(alerts)

    def test_a_mix_names_both_groups(self):
        now = datetime.datetime.now().timestamp()
        alerts = [alert_rec(onset=now - 60, ends=now + 60, expires=now + 60),
                  alert_rec(onset=now + 3600, ends=now + 7200, expires=now + 7200)]
        line = NWSSkin.count_line(alerts)
        assert 'in effect now' in line and 'beginning later' in line

    def test_none_yet_begun(self):
        now = datetime.datetime.now().timestamp()
        alerts = [alert_rec(onset=now + 3600, ends=now + 7200, expires=now + 7200)]
        assert 'not yet begun' in NWSSkin.count_line(alerts)

    def test_an_expired_alert_is_not_counted_as_beginning_later(self):
        """An alert that has ENDED is neither in effect nor upcoming, and
        counting it as upcoming produced a heading its own cards disproved.

        Note where this can actually happen: NOT at generation.  A report-time
        page never holds an ended alert -- fetch_records_internal drops any
        row whose endTime has passed as it builds them, which
        TestEndedAlertsAreNotRendered pins.  This branch exists for the CLOCK:
        a tab left open crosses an end time and the page script recomputes.
        It is tested here because the two wordings must agree."""
        now = datetime.datetime.now().timestamp()
        alerts = [alert_rec(onset=now - 7200, ends=now - 60, expires=now - 60)]
        line = NWSSkin.count_line(alerts)
        assert 'not yet begun' not in line
        assert 'none in effect now' in line
        assert '1 alert<' in line

    def test_an_expired_alert_does_not_inflate_the_upcoming_count(self):
        now = datetime.datetime.now().timestamp()
        alerts = [alert_rec(onset=now - 7200, ends=now - 60, expires=now - 60),
                  alert_rec(onset=now + 3600, ends=now + 7200, expires=now + 7200)]
        assert '1 alert</b> not yet begun' in NWSSkin.count_line(alerts)

    def test_one_alert_is_singular(self):
        now = datetime.datetime.now().timestamp()
        alerts = [alert_rec(onset=now - 60, ends=now + 60, expires=now + 60)]
        assert '1 alert<' in NWSSkin.count_line(alerts)

    def test_the_page_script_carries_the_same_wording(self):
        """Two implementations of one sentence.  The realistic failure is
        editing one and forgetting the other, which this catches without
        needing a javascript runtime: every distinctive phrase this function
        can emit must appear in the script that rewrites it."""
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              '..', 'skins', 'nws', 'scripts', 'nws.js')
        js = open(script).read()
        for phrase in ('in effect now, ', 'beginning later',
                       'in effect first, ', 'then most serious first.',
                       'in effect ', 'most serious first.',
                       'not yet begun.', 'none in effect now.'):
            assert phrase in js, 'nws.js is missing the phrase %r' % phrase
