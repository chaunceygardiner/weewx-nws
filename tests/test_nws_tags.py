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

"""Tests for the $nwsforecast reporting tags that shape the feed for a report.

Run from the repo root with the WeeWX venv python:
    /home/weewx/weewx-venv/bin/python -m pytest tests

These nine tags are NWS and CAP semantics rather than any skin's taste --
which is why they are here and not in a skin -- so what they encode is how
the feed actually behaves, measured rather than assumed.  The alert cases in
particular come from an unfiltered national snapshot of
api.weather.gov/alerts/active: three separator forms after a '* HEADER', the
tropical products' '- ' sub-bullets, and descriptions that are free prose
with no structure at all (three quarters of them).

The tags take the ValueHelper-wrapped records NWSForecastVariables returns,
not raw database rows, so these tests wrap their inputs the same way the
extension does.
"""

import datetime
import os
import sys
import time

os.environ['TZ'] = 'America/Los_Angeles'
time.tzset()

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'bin', 'user'))

import weewx
import weewx.units

from nws import NWSForecastVariables


# ---------------------------------------------------------------------------
# Wrapping helpers: the tags index .raw, so inputs must be ValueHelpers.

def vh(value, obs='dateTime'):
    group = weewx.units.obs_group_dict[obs]
    units = weewx.units.USUnits[group]
    return weewx.units.ValueHelper((value, units, group))


def ts(y, mo, d, h, mi=0):
    return datetime.datetime(y, mo, d, h, mi).timestamp()


def period(start, temp, is_daytime, name='Tuesday', pop=10, dewpoint=50.0):
    """A twelve-hour or one-hour forecast period as the tags see it."""
    return {
        'startTime': vh(start),
        'outTemp': vh(temp, 'outTemp'),
        'dewpoint': vh(dewpoint, 'dewpoint'),
        'pop': vh(pop, 'outHumidity'),
        'isDaytime': is_daytime,
        'name': name,
    }


def alert(onset=None, ends=None, expires=None, severity='Severe'):
    return {
        'onset': vh(onset),
        'ends': vh(ends),
        'expires': vh(expires),
        'severity': severity,
    }


# ---------------------------------------------------------------------------

class TestDays:
    """Grouping twelve-hour periods by the calendar day each one STARTS in."""

    def test_periods_group_by_start_date(self):
        periods = [
            period(ts(2026, 9, 1, 6), 78.0, True, 'Tuesday'),
            period(ts(2026, 9, 1, 18), 55.0, False, 'Tuesday Night'),
            period(ts(2026, 9, 2, 6), 80.0, True, 'Wednesday'),
        ]
        days = NWSForecastVariables.days(periods)
        assert [d['date'] for d in days] == [
            datetime.date(2026, 9, 1), datetime.date(2026, 9, 2)]
        assert len(days[0]['group']) == 2
        assert len(days[1]['group']) == 1

    def test_a_night_ending_next_day_belongs_to_the_day_it_starts(self):
        """"Tuesday Night" runs 18:00 Tue to 06:00 Wed and is Tuesday's."""
        periods = [
            period(ts(2026, 9, 1, 18), 55.0, False, 'Tuesday Night'),
            period(ts(2026, 9, 2, 6), 80.0, True, 'Wednesday'),
        ]
        days = NWSForecastVariables.days(periods)
        assert days[0]['date'] == datetime.date(2026, 9, 1)
        assert days[0]['group'][0]['name'] == 'Tuesday Night'
        assert days[0]['day'] is None

    def test_a_leading_overnight_does_not_take_a_row_of_its_own(self):
        """The pair-walk bug: at 05:35 the feed leads with Overnight
        (01:00-06:00) then Tuesday (06:00-18:00).  Both start on the 1st, so
        they share one row -- a pair-walk gave Overnight its own and printed
        the same date twice."""
        periods = [
            period(ts(2026, 9, 1, 1), 52.0, False, 'Overnight'),
            period(ts(2026, 9, 1, 6), 78.0, True, 'Tuesday'),
            period(ts(2026, 9, 1, 18), 55.0, False, 'Tuesday Night'),
        ]
        days = NWSForecastVariables.days(periods)
        assert len(days) == 1
        assert len(days[0]['group']) == 3
        assert days[0]['day']['name'] == 'Tuesday'
        assert [n['name'] for n in days[0]['nights']] == ['Overnight', 'Tuesday Night']

    def test_hi_is_the_daytime_period_and_lo_the_coldest_night(self):
        periods = [
            period(ts(2026, 9, 1, 1), 52.0, False, 'Overnight'),
            period(ts(2026, 9, 1, 6), 78.0, True, 'Tuesday'),
            period(ts(2026, 9, 1, 18), 49.0, False, 'Tuesday Night'),
        ]
        d = NWSForecastVariables.days(periods)[0]
        assert d['hi'] == 78.0
        assert d['lo'] == 49.0

    def test_a_night_with_no_temperature_does_not_raise(self):
        """The None filter on `lows` is a fix, not an accident.  days() runs
        from a Cheetah #set directive, which #errorCatcher Echo does NOT
        catch, so an unfiltered None took the whole page down rather than
        degrading one value."""
        periods = [
            period(ts(2026, 9, 1, 6), 78.0, True, 'Tuesday'),
            period(ts(2026, 9, 1, 18), None, False, 'Tuesday Night'),
        ]
        d = NWSForecastVariables.days(periods)[0]
        assert d['lo'] is None
        assert d['hi'] == 78.0

    def test_a_present_low_survives_a_sibling_night_with_no_temperature(self):
        """The case that actually proves the filter.  With one night, an
        unfiltered min([None]) still returns None and looks fine; it is a day
        carrying TWO nights, one of them absent, where min() raises."""
        periods = [
            period(ts(2026, 9, 1, 1), 52.0, False, 'Overnight'),
            period(ts(2026, 9, 1, 6), 78.0, True, 'Tuesday'),
            period(ts(2026, 9, 1, 18), None, False, 'Tuesday Night'),
        ]
        d = NWSForecastVariables.days(periods)[0]
        assert d['lo'] == 52.0

    def test_a_day_with_no_temperatures_at_all_yields_none_not_an_exception(self):
        periods = [period(ts(2026, 9, 1, 18), None, False, 'Tuesday Night')]
        d = NWSForecastVariables.days(periods)[0]
        assert d['hi'] is None and d['lo'] is None

    def test_periods_within_a_day_come_back_in_time_order(self):
        periods = [
            period(ts(2026, 9, 1, 18), 55.0, False, 'Tuesday Night'),
            period(ts(2026, 9, 1, 1), 52.0, False, 'Overnight'),
            period(ts(2026, 9, 1, 6), 78.0, True, 'Tuesday'),
        ]
        d = NWSForecastVariables.days(periods)[0]
        assert [p['name'] for p in d['group']] == ['Overnight', 'Tuesday', 'Tuesday Night']

    def test_only_the_first_daytime_period_becomes_day(self):
        periods = [
            period(ts(2026, 9, 1, 6), 78.0, True, 'Tuesday'),
            period(ts(2026, 9, 1, 12), 81.0, True, 'Tuesday Afternoon'),
        ]
        d = NWSForecastVariables.days(periods)[0]
        assert d['day']['name'] == 'Tuesday'
        assert d['hi'] == 78.0

    def test_today_is_labeled_today_and_others_by_weekday(self):
        today = datetime.date.today()
        other = today + datetime.timedelta(days=2)
        periods = [
            period(datetime.datetime.combine(
                today, datetime.time(12)).timestamp(), 70.0, True),
            period(datetime.datetime.combine(
                other, datetime.time(12)).timestamp(), 70.0, True),
        ]
        days = NWSForecastVariables.days(periods)
        assert days[0]['label'] == 'Today'
        assert days[1]['label'] == other.strftime('%A')

    def test_no_slicing_happens_here(self):
        """How many rows to draw is the caller's judgment, so the tag hands
        back every date it was given -- including a trailing one that holds
        only a night, which is why a caller might want to slice."""
        periods = []
        for i in range(8):
            periods.append(period(ts(2026, 9, 1 + i, 6), 78.0, True))
            periods.append(period(ts(2026, 9, 1 + i, 18), 55.0, False, 'Night'))
        periods.append(period(ts(2026, 9, 9, 1), 52.0, False, 'Overnight'))
        days = NWSForecastVariables.days(periods)
        assert len(days) == 9
        assert days[-1]['day'] is None and days[-1]['hi'] is None

    def test_an_evening_poll_puts_a_lone_night_first_and_a_lone_day_last(self):
        """The shape that actually produces an eighth date, measured over 64
        real generations: an evening poll leads with "Tonight", so the first
        date holds only a night and the last only a DAY.  Both ends degrade,
        and they degrade differently -- a day-only row has no `nights` and no
        `lo`, where a night-only row has no `day` and no `hi`."""
        periods = [period(ts(2026, 8, 24, 20), 61.0, False, 'Tonight')]
        for i in range(6):
            periods.append(period(ts(2026, 8, 25 + i, 6), 78.0, True))
            periods.append(period(ts(2026, 8, 25 + i, 18), 55.0, False, 'Night'))
        periods.append(period(ts(2026, 8, 31, 6), 80.0, True, 'Monday'))
        days = NWSForecastVariables.days(periods)
        assert len(days) == 8
        assert days[0]['day'] is None and days[0]['hi'] is None
        assert days[0]['lo'] == 61.0
        assert days[-1]['nights'] == [] and days[-1]['lo'] is None
        assert days[-1]['hi'] == 80.0

    def test_a_period_with_no_start_time_is_dropped_not_raised(self):
        """days() runs from a Cheetah #set, which #errorCatcher Echo does
        NOT catch, so raising here loses the whole page rather than one row.
        hour_days() and points() skip such records; this must agree."""
        periods = [period(None, 70.0, True, 'Tuesday'),
                   period(ts(2026, 9, 1, 6), 78.0, True, 'Tuesday')]
        days = NWSForecastVariables.days(periods)
        assert len(days) == 1
        assert days[0]['hi'] == 78.0

    def test_empty_input_is_an_empty_list(self):
        assert NWSForecastVariables.days([]) == []


class TestHourDays:
    """The Hourly page's day tabs -- calendar days, and no chart geometry."""

    def test_hours_group_by_calendar_day(self):
        records = [
            period(ts(2026, 9, 1, 23), 60.0, False),
            period(ts(2026, 9, 2, 0), 59.0, False),
            period(ts(2026, 9, 2, 1), 58.0, False),
        ]
        tabs = NWSForecastVariables.hour_days(records)
        assert [t['key'] for t in tabs] == ['2026-09-01', '2026-09-02']
        assert len(tabs[0]['rows']) == 1
        assert len(tabs[1]['rows']) == 2

    def test_no_points_key(self):
        """points() is a separate tag.  Embedding it here was the one place
        chart geometry leaked into a grouping function."""
        tabs = NWSForecastVariables.hour_days([period(ts(2026, 9, 1, 5), 60.0, False)])
        assert 'points' not in tabs[0]

    def test_an_hour_with_no_start_time_is_dropped(self):
        records = [period(None, 60.0, False), period(ts(2026, 9, 1, 5), 61.0, False)]
        tabs = NWSForecastVariables.hour_days(records)
        assert len(tabs) == 1 and len(tabs[0]['rows']) == 1

    def test_rows_are_time_ordered_within_a_tab(self):
        records = [
            period(ts(2026, 9, 1, 9), 66.0, True),
            period(ts(2026, 9, 1, 5), 60.0, False),
        ]
        rows = NWSForecastVariables.hour_days(records)[0]['rows']
        assert [r['startTime'].raw for r in rows] == [ts(2026, 9, 1, 5), ts(2026, 9, 1, 9)]

    def test_label_uses_the_short_weekday(self):
        other = datetime.date.today() + datetime.timedelta(days=3)
        rec = period(datetime.datetime.combine(
            other, datetime.time(12)).timestamp(), 70.0, True)
        tab = NWSForecastVariables.hour_days([rec])[0]
        assert tab['label'] == other.strftime('%a')
        assert tab['datestr'] == other.strftime('%b %-d')

    def test_empty_input_is_an_empty_list(self):
        assert NWSForecastVariables.hour_days([]) == []


class TestPoints:
    """Plain numbers for chart arithmetic, with the ValueHelpers unwrapped."""

    def test_values_come_back_unwrapped(self):
        pts = NWSForecastVariables.points(
            [period(ts(2026, 9, 1, 5), 60.0, False, pop=25, dewpoint=48.0)])
        assert pts == [{'startTime': int(ts(2026, 9, 1, 5)), 'outTemp': 60.0,
                        'dewpoint': 48.0, 'pop': 25, 'isDaytime': False}]

    def test_an_hour_with_no_temperature_is_dropped(self):
        """It cannot be plotted, and leaving it in breaks min()/max()."""
        pts = NWSForecastVariables.points(
            [period(ts(2026, 9, 1, 5), None, False), period(ts(2026, 9, 1, 6), 60.0, False)])
        assert len(pts) == 1 and pts[0]['outTemp'] == 60.0

    def test_an_hour_with_no_start_time_is_dropped(self):
        assert NWSForecastVariables.points([period(None, 60.0, False)]) == []

    def test_absent_dewpoint_and_pop_are_kept_as_none(self):
        """Both are allowed to be absent; every consumer guards them.  Only
        time and temperature are load-bearing."""
        pts = NWSForecastVariables.points(
            [period(ts(2026, 9, 1, 5), 60.0, False, pop=None, dewpoint=None)])
        assert pts[0]['dewpoint'] is None and pts[0]['pop'] is None

    def test_start_time_is_an_int(self):
        pts = NWSForecastVariables.points([period(ts(2026, 9, 1, 5) + 0.7, 60.0, False)])
        assert isinstance(pts[0]['startTime'], int)


class TestWeekRange:

    def test_min_and_max_across_every_period_on_show(self):
        periods = [
            period(ts(2026, 9, 1, 6), 78.0, True),
            period(ts(2026, 9, 1, 18), 49.0, False, 'Night'),
            period(ts(2026, 9, 2, 6), 91.0, True),
        ]
        days = NWSForecastVariables.days(periods)
        assert NWSForecastVariables.week_range(days) == (49.0, 91.0)

    def test_absent_temperatures_are_ignored(self):
        periods = [
            period(ts(2026, 9, 1, 6), 78.0, True),
            period(ts(2026, 9, 1, 18), None, False, 'Night'),
        ]
        days = NWSForecastVariables.days(periods)
        assert NWSForecastVariables.week_range(days) == (78.0, 78.0)

    def test_no_values_yields_the_placeholder(self):
        """(0.0, 1.0) is a placeholder, not a range.  A caller must not
        caption it -- printing "0 to 1 degrees" over an empty list is the bug
        this guards."""
        assert NWSForecastVariables.week_range([]) == (0.0, 1.0)
        days = NWSForecastVariables.days([period(ts(2026, 9, 1, 6), None, True)])
        assert NWSForecastVariables.week_range(days) == (0.0, 1.0)


class TestLineLabel:
    """NWS's period name, kept only where it says something the row does not."""

    def test_a_daytime_period_is_day(self):
        assert NWSForecastVariables.line_label(
            period(ts(2026, 9, 1, 6), 78.0, True, 'Tuesday')) == 'Day'

    def test_weekday_night_becomes_plain_night(self):
        assert NWSForecastVariables.line_label(
            period(ts(2026, 9, 1, 18), 55.0, False, 'Tuesday Night')) == 'Night'

    def test_tonight_becomes_night(self):
        assert NWSForecastVariables.line_label(
            period(ts(2026, 9, 1, 18), 55.0, False, 'Tonight')) == 'Night'

    def test_overnight_is_kept_because_it_says_something(self):
        assert NWSForecastVariables.line_label(
            period(ts(2026, 9, 1, 1), 52.0, False, 'Overnight')) == 'Overnight'

    def test_an_unnamed_night_still_gets_a_label(self):
        assert NWSForecastVariables.line_label(
            period(ts(2026, 9, 1, 1), 52.0, False, None)) == 'Night'


class TestNiceCaps:
    """Title case that survives NWS's shouted headlines."""

    def test_shouted_text_is_title_cased(self):
        assert NWSForecastVariables.nice_caps(
            'HEAT ADVISORY IN EFFECT') == 'Heat Advisory In Effect'

    def test_acronyms_stay_upright(self):
        """str.title() gives "11 Am Pdt", which is the bug this exists for."""
        assert NWSForecastVariables.nice_caps(
            'UNTIL 11 AM PDT') == 'Until 11 AM PDT'

    def test_compass_points_stay_upright(self):
        assert NWSForecastVariables.nice_caps('WINDS FROM THE WNW') == 'Winds From The WNW'

    def test_punctuation_does_not_hide_an_acronym(self):
        assert NWSForecastVariables.nice_caps('ISSUED BY NWS.') == 'Issued By NWS.'

    def test_none_and_empty_are_empty(self):
        assert NWSForecastVariables.nice_caps(None) == ''
        assert NWSForecastVariables.nice_caps('') == ''


class TestParseDescription:
    """A CAP description turned into structure.

    The three separator forms and the sub-bullets are what the live national
    feed actually produces; the shipped parser before this did five hardcoded
    string replaces and handled only the first, so '* TIMING...' and every
    '- PLAN:' reached the page as raw punctuation.
    """

    def test_empty_description_is_an_empty_list(self):
        assert NWSForecastVariables.parse_description(None) == []
        assert NWSForecastVariables.parse_description('') == []

    def test_unlabeled_prose_gets_an_empty_label(self):
        """Three quarters of real alerts are nothing but this."""
        out = NWSForecastVariables.parse_description('A strong storm approaches.')
        assert out == [{'label': '', 'paragraphs': ['A strong storm approaches.'],
                        'bullets': []}]

    def test_ellipsis_separator(self):
        out = NWSForecastVariables.parse_description('* WHAT...Damaging winds.')
        assert out[0]['label'] == 'What'
        assert out[0]['paragraphs'] == ['Damaging winds.']

    def test_colon_separator(self):
        out = NWSForecastVariables.parse_description('* WHERE: Coastal counties.')
        assert out[0]['label'] == 'Where'
        assert out[0]['paragraphs'] == ['Coastal counties.']

    def test_header_alone_on_its_line_with_sub_bullets(self):
        """The tropical products' shape: 874 '- ' lines in one snapshot."""
        out = NWSForecastVariables.parse_description(
            '* LOCATIONS AFFECTED\n- Cameron\n- Creole')
        assert out[0]['label'] == 'Locations Affected'
        assert out[0]['paragraphs'] == []
        assert out[0]['bullets'] == ['Cameron', 'Creole']

    def test_a_soft_wrapped_paragraph_is_reflowed(self):
        """A single newline is ALWAYS teletype wrapping in this feed."""
        out = NWSForecastVariables.parse_description(
            'Damaging winds are\nexpected across the\nentire area.')
        assert out[0]['paragraphs'] == [
            'Damaging winds are expected across the entire area.']

    def test_a_blank_line_is_always_a_paragraph_break(self):
        out = NWSForecastVariables.parse_description('First one.\n\nSecond one.')
        assert out[0]['paragraphs'] == ['First one.', 'Second one.']

    def test_a_wrapped_sub_bullet_continues_that_bullet(self):
        out = NWSForecastVariables.parse_description(
            '* WHAT\n- A very long bullet that\ncontinues here')
        assert out[0]['bullets'] == ['A very long bullet that continues here']

    def test_internal_whitespace_is_normalized(self):
        out = NWSForecastVariables.parse_description('Too    many     spaces.')
        assert out[0]['paragraphs'] == ['Too many spaces.']

    def test_labels_are_not_a_fixed_set(self):
        """TIMING, OUTFLOW WINDS and RELATIVE HUMIDITY all appear live, so
        nothing enumerates them."""
        out = NWSForecastVariables.parse_description(
            '* TIMING...Through 8 PM.\n* OUTFLOW WINDS...To 40 mph.')
        assert [b['label'] for b in out] == ['Timing', 'Outflow Winds']

    def test_an_empty_block_is_dropped(self):
        out = NWSForecastVariables.parse_description('* WHAT\n\n* WHERE...Here.')
        assert [b['label'] for b in out] == ['Where']

    def test_a_label_is_title_cased_through_nice_caps(self):
        out = NWSForecastVariables.parse_description('* WHAT...x')
        assert out[0]['label'] == 'What'

    def test_a_bare_uppercase_label_becomes_a_section(self):
        """The severe-thunderstorm and flash-flood products write HAZARD,
        SOURCE and IMPACT with no asterisk, and those three are the most
        useful lines in the alert.  34 of 371 active alerts carried them in
        an unfiltered national snapshot."""
        out = NWSForecastVariables.parse_description(
            'HAZARD...60 mph wind gusts.\n\nSOURCE...Radar indicated.')
        assert [b['label'] for b in out] == ['Hazard', 'Source']
        assert out[0]['paragraphs'] == ['60 mph wind gusts.']

    def test_a_bare_label_with_no_content_is_not_a_label(self):
        """The guard, and the reason it exists.  A starred label may be empty
        -- the asterisk is the signal -- but a bare one with nothing after
        the ellipsis is almost always the END OF A WRAPPED SENTENCE.  This is
        a real Red Flag Warning whose headline wraps onto a line reading
        "NEVADA...", which without the guard becomes a heading mid-sentence.
        """
        out = NWSForecastVariables.parse_description(
            '...RED FLAG WARNING IN EFFECT FOR PORTIONS OF NE CALIFORNIA AND NW\n'
            'NEVADA...\n\n* CHANGES...None.')
        assert [b['label'] for b in out] == ['', 'Changes']
        assert 'NEVADA' in out[0]['paragraphs'][0]

    def test_a_starred_label_may_still_be_empty(self):
        """The asymmetry is deliberate: "* LOCATIONS AFFECTED" alone on its
        line is legitimate and must keep working."""
        out = NWSForecastVariables.parse_description(
            '* LOCATIONS AFFECTED\n- Cameron')
        assert out[0]['label'] == 'Locations Affected'
        assert out[0]['bullets'] == ['Cameron']

    def test_a_wrapped_bare_label_joins_its_continuation(self):
        out = NWSForecastVariables.parse_description(
            'HAZARD...60 mph wind gusts and half dollar\nsize hail.')
        assert out[0]['paragraphs'] == ['60 mph wind gusts and half dollar size hail.']

    def test_mixed_case_after_an_ellipsis_is_not_a_label(self):
        """"* Severe Thunderstorm Warning for... Eastern Lycoming County..."
        is prose that happens to contain an ellipsis."""
        out = NWSForecastVariables.parse_description(
            'Severe Thunderstorm Warning for... Eastern Lycoming County...')
        assert out[0]['label'] == ''

    def test_a_starred_line_that_is_not_shouted_is_a_bullet(self):
        """The warning products list their facts as starred lines whose text
        is ordinary prose.  These are bullets, not sections, and before this
        they fell through and the asterisk reached the page as raw
        punctuation.  38 of 388 active alerts carried them in a national
        snapshot -- 156 lines, led by Severe Thunderstorm and Flash Flood
        Warnings, the most common warnings in the country."""
        out = NWSForecastVariables.parse_description(
            '* Until 630 PM EDT.\n\n* At 541 PM EDT, a severe thunderstorm was located.')
        assert out[0]['bullets'] == ['Until 630 PM EDT.',
                                     'At 541 PM EDT, a severe thunderstorm was located.']
        assert not any('*' in p for p in out[0]['paragraphs'])

    def test_a_shouted_starred_label_is_still_a_header(self):
        """The case split is the feed's own: shouted means header, prose
        means bullet.  All three header forms must survive it."""
        out = NWSForecastVariables.parse_description(
            '* WHAT...Damaging winds.\n* LOCATIONS AFFECTED\n- Cameron\n* CHANGES...None.')
        assert [b['label'] for b in out] == ['What', 'Locations Affected', 'Changes']
        assert out[1]['bullets'] == ['Cameron']

    def test_a_wrapped_starred_bullet_joins_its_continuation(self):
        out = NWSForecastVariables.parse_description(
            '* Severe Thunderstorm Warning for...\nWest central Columbia County...')
        assert out[0]['bullets'] == [
            'Severe Thunderstorm Warning for... West central Columbia County...']

    def test_no_asterisk_survives_into_any_output(self):
        """The whole point: whatever a starred line turns out to be, the
        marker itself must not reach the page."""
        out = NWSForecastVariables.parse_description(
            '* WHAT...Winds.\n\n* Until 630 PM EDT.\n\n* LOCATIONS AFFECTED\n- Cameron')
        for block in out:
            assert '*' not in block['label']
            assert not any('*' in p for p in block['paragraphs'])
            assert not any('*' in b for b in block['bullets'])

    def test_a_double_asterisk_banner_is_unwrapped(self):
        """The tropical statements banner a line with ** ... **, and it can
        wrap -- the closing pair lands on the next source line, so the two
        only meet after reflow.  That is why it is stripped once the
        paragraph is whole rather than line by line."""
        out = NWSForecastVariables.parse_description(
            '**Tropical Storm Edouard Made Landfall Near Johnsons\nBayou **')
        assert out[0]['paragraphs'] == [
            'Tropical Storm Edouard Made Landfall Near Johnsons Bayou']

    def test_an_unwrapped_banner_on_one_line_is_stripped_too(self):
        out = NWSForecastVariables.parse_description(
            '**Tropical Storm Edouard Continues To Strengthen**')
        assert out[0]['paragraphs'] == ['Tropical Storm Edouard Continues To Strengthen']

    def test_ordinary_prose_containing_an_asterisk_is_left_alone(self):
        out = NWSForecastVariables.parse_description('Winds 20*30 mph in gusts.')
        assert out[0]['paragraphs'] == ['Winds 20*30 mph in gusts.']

    def test_returns_dicts_not_tuples(self):
        """A public tag: a fixed-width tuple could never gain a field
        without breaking every caller."""
        out = NWSForecastVariables.parse_description('* WHAT...Damaging winds.')
        assert isinstance(out[0], dict)
        assert set(out[0]) == {'label', 'paragraphs', 'bullets'}


class TestAlertWindowAndActive:

    def test_ends_equal_to_expires_means_open_ended(self):
        """This extension never leaves endTime empty: where NWS gave no
        `ends` it stores `expires`, so equality is what open-ended looks
        like by the time a skin sees it.  One alert in ten has no end."""
        a = alert(onset=1000.0, ends=5000.0, expires=5000.0)
        onset, finish, open_ended = NWSForecastVariables.alert_window(a)
        assert open_ended is True and finish == 5000.0

    def test_a_real_end_is_not_open_ended(self):
        a = alert(onset=1000.0, ends=4000.0, expires=5000.0)
        onset, finish, open_ended = NWSForecastVariables.alert_window(a)
        assert open_ended is False and finish == 4000.0

    def test_a_null_ends_is_open_ended_and_leans_on_expires(self):
        a = alert(onset=1000.0, ends=None, expires=5000.0)
        _onset, finish, open_ended = NWSForecastVariables.alert_window(a)
        assert open_ended is True and finish == 5000.0

    def test_in_window_is_active(self):
        a = alert(onset=1000.0, ends=5000.0, expires=5000.0)
        assert NWSForecastVariables.is_active(a, now=3000.0) is True

    def test_before_onset_is_not_active(self):
        a = alert(onset=1000.0, ends=5000.0, expires=5000.0)
        assert NWSForecastVariables.is_active(a, now=500.0) is False

    def test_after_the_end_is_not_active(self):
        a = alert(onset=1000.0, ends=5000.0, expires=5000.0)
        assert NWSForecastVariables.is_active(a, now=9000.0) is False

    def test_a_null_onset_is_never_active(self):
        """The branch that made card() raise: `onset - now` on a None."""
        a = alert(onset=None, ends=5000.0, expires=5000.0)
        assert NWSForecastVariables.is_active(a, now=3000.0) is False

    def test_now_defaults_to_this_instant(self):
        now = datetime.datetime.now().timestamp()
        a = alert(onset=now - 60, ends=now + 60, expires=now + 60)
        assert NWSForecastVariables.is_active(a) is True

    def test_now_is_a_public_parameter(self):
        """Callers rendering a batch pass ONE instant to every call, so an
        alert cannot be counted active and then rendered expired in the same
        pass."""
        a = alert(onset=1000.0, ends=5000.0, expires=5000.0)
        assert NWSForecastVariables.is_active(a, 3000.0) is True
        assert NWSForecastVariables.is_active(a, 6000.0) is False


class TestAlertState:
    """'active' / 'upcoming' / 'ended' -- total and mutually exclusive.

    This is a tag rather than each skin's business because two skins wrote the
    classification independently and both got it wrong, from opposite
    directions: one counted an ended alert as beginning later, the other
    misfiled an alert that has no onset.
    """

    def test_in_its_window_is_active(self):
        assert NWSForecastVariables.alert_state(
            alert(onset=1000.0, ends=5000.0, expires=5000.0), 3000.0) == 'active'

    def test_before_its_onset_is_upcoming(self):
        assert NWSForecastVariables.alert_state(
            alert(onset=1000.0, ends=5000.0, expires=5000.0), 500.0) == 'upcoming'

    def test_after_its_window_is_ended(self):
        assert NWSForecastVariables.alert_state(
            alert(onset=1000.0, ends=5000.0, expires=5000.0), 9000.0) == 'ended'

    def test_no_onset_with_a_closed_window_is_ENDED_not_upcoming(self):
        """The rule that matters, and the one both skins got wrong.  NWS does
        not always give an onset.  Spelling `ended` as "started but not
        active" files this as upcoming, because `started` is false for it --
        so the test must be on FINISH, whatever the onset says."""
        assert NWSForecastVariables.alert_state(
            alert(onset=None, ends=5000.0, expires=5000.0), 9000.0) == 'ended'

    def test_no_onset_with_an_open_window_is_upcoming(self):
        assert NWSForecastVariables.alert_state(
            alert(onset=None, ends=5000.0, expires=5000.0), 3000.0) == 'upcoming'

    def test_an_open_ended_alert_that_has_begun_is_active(self):
        a = alert(onset=1000.0, ends=None, expires=9000.0)
        assert NWSForecastVariables.alert_state(a, 3000.0) == 'active'

    def test_the_three_states_are_total_and_exclusive(self):
        """Whatever the feed sends, exactly one of the three applies."""
        stamps = (None, 1000.0, 5000.0)
        seen = set()
        for onset in stamps:
            for ends in stamps:
                for expires in stamps:
                    for now in (500.0, 3000.0, 9000.0):
                        state = NWSForecastVariables.alert_state(
                            alert(onset=onset, ends=ends, expires=expires), now)
                        assert state in ('active', 'upcoming', 'ended')
                        seen.add(state)
        assert seen == {'active', 'upcoming', 'ended'}

    def test_it_agrees_with_is_active_exactly(self):
        """The pair must not drift: one is the binary form of the other."""
        stamps = (None, 1000.0, 5000.0)
        for onset in stamps:
            for ends in stamps:
                for expires in stamps:
                    for now in (500.0, 3000.0, 9000.0):
                        a = alert(onset=onset, ends=ends, expires=expires)
                        assert ((NWSForecastVariables.alert_state(a, now) == 'active')
                                is NWSForecastVariables.is_active(a, now))

    def test_now_defaults_to_this_instant(self):
        now = datetime.datetime.now().timestamp()
        assert NWSForecastVariables.alert_state(
            alert(onset=now - 60, ends=now + 60, expires=now + 60)) == 'active'


class TestOrdered:
    """In effect first, then most serious first."""

    def test_active_alerts_sort_before_future_ones(self):
        now = datetime.datetime.now().timestamp()
        future = alert(onset=now + 3600, ends=now + 7200, expires=now + 7200,
                       severity='Extreme')
        active = alert(onset=now - 60, ends=now + 60, expires=now + 60,
                       severity='Minor')
        out = NWSForecastVariables.ordered([future, active])
        assert out[0] is active

    def test_severity_orders_within_the_active_group(self):
        now = datetime.datetime.now().timestamp()
        minor = alert(onset=now - 60, ends=now + 60, expires=now + 60, severity='Minor')
        extreme = alert(onset=now - 60, ends=now + 60, expires=now + 60, severity='Extreme')
        moderate = alert(onset=now - 60, ends=now + 60, expires=now + 60, severity='Moderate')
        out = NWSForecastVariables.ordered([minor, extreme, moderate])
        assert [a['severity'] for a in out] == ['Extreme', 'Moderate', 'Minor']

    def test_an_unknown_severity_sorts_last_rather_than_raising(self):
        """CAP permits values we have not seen."""
        now = datetime.datetime.now().timestamp()
        weird = alert(onset=now - 60, ends=now + 60, expires=now + 60, severity='Bogus')
        minor = alert(onset=now - 60, ends=now + 60, expires=now + 60, severity='Minor')
        out = NWSForecastVariables.ordered([weird, minor])
        assert out[0] is minor

    def test_a_null_onset_does_not_break_the_sort(self):
        now = datetime.datetime.now().timestamp()
        nulled = alert(onset=None, ends=now + 60, expires=now + 60, severity='Severe')
        active = alert(onset=now - 60, ends=now + 60, expires=now + 60, severity='Severe')
        out = NWSForecastVariables.ordered([nulled, active])
        assert out[0] is active

    def test_empty_input_is_an_empty_list(self):
        assert NWSForecastVariables.ordered([]) == []
