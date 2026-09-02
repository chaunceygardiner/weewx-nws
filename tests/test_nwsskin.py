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
import os
import sys
import time

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
              nws_headline=None, description='Some prose.', instructions=None):
    return {
        'onset': vh(onset), 'ends': vh(ends), 'expires': vh(expires),
        'effective': vh(effective if effective is not None else onset),
        'severity': severity, 'event': event, 'headline': headline,
        'nwsHeadline': nws_headline, 'description': description,
        'instructions': instructions, 'senderName': 'NWS Bay Area',
        'messageType': 'Alert', 'certainty': 'Likely', 'urgency': 'Expected',
    }


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

    def test_an_alert_with_no_onset_does_not_raise(self):
        """`onset - now` on a None is what this branch exists to avoid."""
        now = datetime.datetime.now().timestamp()
        out = NWSSkin.card(alert_rec(onset=None, ends=now + 3600,
                                     expires=now + 3600))
        assert 'Not yet begun' in out
        assert 'start not given' in out

    def test_an_alert_with_no_onset_whose_window_closed_reads_expired(self):
        """All three consumers used to disagree about this one alert: the
        count line called it upcoming, the card badged it "Not yet begun",
        and the page script never saw it at all because it selected
        .alert[data-onset] and no onset attribute is written.  They now share
        one classification."""
        now = datetime.datetime.now().timestamp()
        rec = alert_rec(onset=None, ends=now - 3600, expires=now - 3600)
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

    def test_ends_equal_to_expires_is_treated_as_open_ended(self):
        now = datetime.datetime.now().timestamp()
        out = NWSSkin.card(alert_rec(onset=now - 60, ends=now + 3600,
                                     expires=now + 3600))
        assert 'no end time given' in out
        assert 'data-ends=' not in out

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

    def test_an_absent_severity_becomes_unknown(self):
        now = datetime.datetime.now().timestamp()
        out = NWSSkin.card(alert_rec(onset=now - 60, ends=now + 60,
                                     expires=now + 60, severity=None))
        assert 'sev-unknown' in out

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
