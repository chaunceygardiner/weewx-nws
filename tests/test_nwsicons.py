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

"""Tests for the drawn icon set.

The interesting one is test_matches_nws_icon_index: NWS publishes the
authoritative list at https://api.weather.gov/icons, so the set can be held
against the source of truth rather than against a list someone copied down
once.  It is marked `network` and pytest.ini deselects that marker, so a plain
`pytest tests` stays hermetic and offline; run it deliberately with

    python -m pytest tests -m network

so that NWS adding a condition is found the day it happens rather than years
later, by a user staring at a fallback image.
"""

import logging
import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'bin', 'user'))

import pytest

import nwsicons

NWS_ICON_INDEX = 'https://api.weather.gov/icons'
USER_AGENT = '(weewx-nws test suite, john@johnkline.com)'


class TestModuleIdentity(unittest.TestCase):
    """The suite must test THIS repo's nwsicons.py, not an installed copy.

    nws.py resolves nwsicons as `user.nwsicons` when any `user` package is
    importable and as the flat `nwsicons` otherwise.  A PYTHONPATH naming the
    parent of an installed WeeWX `user` package -- which docs/utilities.md
    tells users to export -- makes those two DIFFERENT module objects in one
    process, each with its own UNKNOWN set and its own memoized sprite.  Then
    nws.py renders through /home/weewx/bin/user/nwsicons.py while this file
    tests the repo's, and the suite reports on a file it never exercised.

    That is loud only while the installed copy is stale.  Once the versions
    match it goes green and stays wrong, which is why this is asserted rather
    than left to the other tests to notice.
    """

    def test_nws_and_this_module_agree(self):
        import nws
        self.assertIs(
            nws.nwsicons, nwsicons,
            'nws.py resolved a DIFFERENT nwsicons module than this test '
            'imported:\n  nws.py     -> %s\n  this test  -> %s\n'
            'A `user` package on PYTHONPATH is shadowing the repo copy.  Run '
            'the suite with PYTHONPATH unset, or drop the entry naming the '
            'parent of an installed WeeWX `user` package.'
            % (getattr(nws.nwsicons, '__file__', '?'),
               getattr(nwsicons, '__file__', '?')))

class TestIconSet(unittest.TestCase):

    def test_every_condition_draws_day_and_night(self):
        for name in nwsicons.NAMES:
            for night in (False, True):
                markup = nwsicons.build(name, night)
                self.assertTrue(markup, '%s/%s drew nothing'
                                % (name, 'night' if night else 'day'))

    def test_sprite_defines_a_symbol_for_every_condition(self):
        sprite = nwsicons.sprite()
        ids = set(re.findall(r'<symbol id="([^"]+)"', sprite))
        expected = {'wx-%s-%s' % (n, k)
                    for n in nwsicons.NAMES for k in ('day', 'night')}
        self.assertEqual(ids, expected)

    def test_symbol_ids_are_a_contract(self):
        # Consumers write these into their own templates; a rename breaks
        # every skin downstream.  Spot-check the shape rather than all 68.
        sprite = nwsicons.sprite()
        for wanted in ('wx-skc-day', 'wx-fog-night', 'wx-tsra_hi-day'):
            self.assertIn('<symbol id="%s"' % wanted, sprite)

    def test_icon_markup_carries_the_class_contract(self):
        markup = nwsicons.icon('https://api.weather.gov/icons/land/day/few?size=medium')
        self.assertIn('class="wxi"', markup)
        self.assertIn('href="#wx-few-day"', markup)

    def test_url_shapes(self):
        cases = [
            ('https://api.weather.gov/icons/land/day/few?size=medium', 'few', False),
            ('https://api.weather.gov/icons/land/night/bkn?size=small', 'bkn', True),
            # A ",NN" chance-of-precipitation suffix is not part of the name.
            ('https://api.weather.gov/icons/land/day/rain_showers,20?size=small',
             'rain_showers', False),
            # A two-condition composite resolves to the FIRST condition; the
            # period's own text already says "... then ...".
            ('https://api.weather.gov/icons/land/day/sct/fog?size=medium', 'sct', False),
            ('https://api.weather.gov/icons/land/night/tsra_sct,40/fog?size=medium',
             'tsra_sct', True),
        ]
        for url, cond, night in cases:
            got_cond, got_night, known = nwsicons.icon_name(url)
            self.assertEqual((got_cond, got_night, known), (cond, night, True), url)

    def test_unknown_condition_falls_back_to_the_nws_image(self):
        url = 'https://api.weather.gov/icons/land/day/nonesuch_condition?size=medium'
        cond, night, known = nwsicons.icon_name(url)
        self.assertEqual(cond, 'nonesuch_condition')
        self.assertFalse(known)
        markup = nwsicons.icon(url)
        # An <img> at NWS's own art, asked for at the size a drawn icon fills.
        self.assertIn('<img', markup)
        self.assertIn('wxi-fallback', markup)
        self.assertIn('size=large', markup)

    def test_fallback_escapes_what_nws_supplied(self):
        # The fallback path exists for names never seen before, so its input is
        # the least predictable in the module; a quote in either the URL or the
        # condition must not break out of the attribute.
        url = 'https://api.weather.gov/icons/land/day/od"onerror=x&lt;?size=medium'
        markup = nwsicons.icon(url)
        self.assertIn('wxi-fallback', markup)
        self.assertNotIn('"onerror=', markup)
        self.assertIn('&quot;', markup)

    def test_unknown_condition_is_reported_once(self):
        url = 'https://api.weather.gov/icons/land/day/report_me_once?size=medium'
        nwsicons.UNKNOWN.discard('report_me_once')
        with self.assertLogs('nwsicons', level='INFO') as captured:
            nwsicons.icon_name(url)
            nwsicons.icon_name(url)
            nwsicons.icon_name(url)
        # A 7-day forecast would otherwise log the same name fourteen times,
        # and the hourly page 147.
        self.assertEqual(len(captured.output), 1, captured.output)
        nwsicons.UNKNOWN.discard('report_me_once')

    def test_empty_icon_url_means_no_icon_not_clear_sky(self):
        # It used to answer ('skc', False, True) -- fair weather, silently.
        # nws.py stores iconUrl='' on every ALERT record, so a skin calling
        # $nwsforecast.icon($alert.iconUrl) would put a sun over a tornado
        # warning.  "No icon" is the honest answer and it has a box already.
        for blank in ('', None):
            self.assertEqual(nwsicons.icon_name(blank),
                             (nwsicons.NWS_HAS_NO_ICON, False, False), repr(blank))
            markup = nwsicons.icon(blank)
            self.assertIn('wxi-unknown', markup, repr(blank))
            self.assertNotIn('<img', markup, repr(blank))
            self.assertNotIn('wx-skc', markup, repr(blank))

    def test_a_blank_url_is_not_logged(self):
        # A blank iconUrl on an alert is normal operation, not a surprise; one
        # log line per alert would be noise.  NWS's 'unknown' sentinel in a
        # FORECAST is the surprise, and that one is logged.
        nwsicons.UNKNOWN.discard(nwsicons.NWS_HAS_NO_ICON)
        logger = logging.getLogger('nwsicons')
        with mock.patch.object(logger, 'info') as info:
            nwsicons.icon_name('')
            nwsicons.icon_name(None)
        self.assertEqual(info.call_count, 0)

    def test_nws_unknown_does_not_hot_link_a_400(self):
        # NWS emits .../land/night/unknown when it has no icon for a period,
        # and api.weather.gov answers 400 for that URL -- so the one thing this
        # must NOT do is put it in an <img src>, which is a broken image.
        # nws.py rejects such forecasts upstream; this is the belt to that
        # braces, and it is what keeps the docstring's promise honest.
        url = 'https://api.weather.gov/icons/land/night/unknown?size=medium'
        markup = nwsicons.icon(url)
        self.assertIn('wxi-unknown', markup)
        self.assertNotIn('<img', markup)
        self.assertNotIn('api.weather.gov', markup)
        # Still a sized box, so the row it sits in keeps its alignment.
        self.assertIn('viewBox="0 0 32 32"', markup)
        self.assertIn('class="wxi wxi-unknown"', markup)

    def test_class_argument_is_escaped_on_every_path(self):
        # cls reaches the attribute on all three paths; only the fallback one
        # used to escape it.
        evil = 'wxi" onload="x'
        for url in ('https://api.weather.gov/icons/land/day/few?size=medium',
                    'https://api.weather.gov/icons/land/day/nonesuch?size=medium',
                    'https://api.weather.gov/icons/land/day/unknown?size=medium'):
            markup = nwsicons.icon(url, evil)
            # The literal text may appear -- escaped, inside the value, inert.
            # What must not appear is a real quote closing the attribute.
            self.assertNotIn('" onload="', markup, url)
            self.assertIn('&quot; onload=&quot;', markup, url)


class TestPalette(unittest.TestCase):
    """Color is a contract too: the custom-property names are public, and the
    defaults must render byte-for-byte what the untokenized module rendered."""

    def test_every_fill_is_an_overridable_token(self):
        sprite = nwsicons.sprite()
        # No bare hex may survive anywhere in the drawn output; every color
        # has to come through var(--wx-*, #default) or a skin cannot theme it.
        bare = re.findall(r'(?:fill|stroke)="(#[0-9A-Fa-f]{3,8})"', sprite)
        self.assertEqual(bare, [], 'un-tokenized colors: %s' % sorted(set(bare)))

    def test_defaults_are_the_shipped_look(self):
        # A skin that defines nothing must get exactly these colors; changing
        # a default is a visible change to every consumer, not a refactor.
        self.assertEqual(nwsicons.PALETTE['sun'], ('--wx-sun', '#F2B705'))
        self.assertEqual(nwsicons.PALETTE['moon'], ('--wx-moon', '#8A93A0'))
        for key, (prop, default) in nwsicons.PALETTE.items():
            self.assertTrue(prop.startswith('--wx-'), prop)
            self.assertEqual(nwsicons.C[key], 'var(%s, %s)' % (prop, default))
        for key, (prop, default) in nwsicons.OPACITY.items():
            self.assertTrue(prop.startswith('--wx-op-'), prop)
            self.assertEqual(nwsicons.O[key], 'var(%s, %s)' % (prop, default))

    def test_the_eye_defaults_to_transparent(self):
        # Not white.  A painted eye is only ever right on one background.
        # The center is simply LEFT UNPAINTED -- the bands never reach it, so
        # there is nothing to cut and fill-rule=evenodd is wrong here (it adds
        # a filled disc; this was tried and measured).  The token exists only
        # for someone who wants the eye painted after all.
        self.assertEqual(nwsicons.PALETTE['eye'], ('--wx-eye', 'transparent'))

    def test_property_names_are_a_contract(self):
        # Consumers write these into their stylesheets; a rename is a major
        # version.  Pinned as a COMPLETE set so adding one is a deliberate act.
        self.assertEqual(
            {prop for prop, _ in nwsicons.PALETTE.values()},
            {'--wx-sun', '--wx-sunray', '--wx-moon',
             '--wx-cloud', '--wx-cloud-2', '--wx-cloud-3',
             '--wx-rain', '--wx-snow', '--wx-sleet', '--wx-bolt', '--wx-fog',
             '--wx-wind', '--wx-hot', '--wx-cold', '--wx-dust', '--wx-smoke',
             '--wx-swirl', '--wx-swirl-2', '--wx-swirl-3', '--wx-eye'})
        self.assertEqual(
            {prop for prop, _ in nwsicons.OPACITY.values()},
            {'--wx-op-band', '--wx-op-tube'})

    def test_no_cloud_or_funnel_is_drawn_at_partial_opacity(self):
        # Tone is color.  A fill at partial opacity composites against the
        # PAGE, so the depth cue it encodes reverses between a light and a
        # dark theme -- measured at 1.4 luma on white and -56 on #111834 for
        # ovc.  Those steps are solid ramp colors now; only genuine
        # translucency (the two --wx-op-* tokens) may set opacity.
        sprite = nwsicons.sprite()
        literal = re.findall(r'opacity="(?!var\()([^"]*)"', sprite)
        self.assertEqual(set(literal), {'1'},
                         'un-tokenized opacity survives: %s' % sorted(set(literal)))

    def test_the_cyclone_eye_is_left_unpainted(self):
        # The bands never reach the center (they sweep r0=5.4..R=11.6 around a
        # 3.6 eye), so the old white disc was painting over bare background --
        # invisible on white, a white blob anywhere else.  Nothing may paint
        # the center opaque now.
        for name in ('hurricane', 'tropical_storm'):
            markup = nwsicons.build(name, False)
            self.assertNotIn('#ffffff', markup, name)
            self.assertIn('fill="var(--wx-eye, transparent)"', markup, name)
            # The ring is what draws the eye, and it must survive.
            self.assertIn('fill="none" stroke=', markup, name)

    def test_dark_palette_mirrors_the_light_one(self):
        # A dark value for every token, and no orphans: if someone adds a
        # color and forgets its dark counterpart, the icons theme half-way,
        # which looks like a rendering bug rather than a missing entry.
        self.assertEqual(set(nwsicons.DARK), set(nwsicons.PALETTE))
        self.assertEqual(set(nwsicons.DARK_OPACITY), set(nwsicons.OPACITY))

    # ---- prominence, the property both palettes share ------------------
    #
    # "Prominence" is how far a color stands from the page it is drawn on.
    # Stated that way the light and dark palettes are the SAME SHAPE, even
    # though dark inverts the cloud ramp's absolute lightness -- so these
    # rules are asserted over both, and light passing unchanged is the proof
    # that they describe the real design rather than being fitted to the new
    # dark numbers.
    #
    # The derivation used OKLab dE; this uses luma distance, which needs no
    # dependency and agreed with dE on every check that mattered (it is what
    # first caught the inversion bug).

    LIGHT_GROUND = '#ffffff'
    DARK_GROUND  = '#111834'          # named so a changed surface fails loudly

    @staticmethod
    def _luma(hexv):
        h = hexv.lstrip('#')
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        return 0.299 * r + 0.587 * g + 0.114 * b

    @classmethod
    def _prom(cls, hexv, ground):
        return abs(cls._luma(hexv) - cls._luma(ground))

    def _palettes(self):
        light = {k: v for k, (p, v) in nwsicons.PALETTE.items()}
        return (('light', light, self.LIGHT_GROUND),
                ('dark', nwsicons.DARK, self.DARK_GROUND))

    def test_severe_weather_outshouts_ordinary_sky(self):
        """The constraint the first dark palette lost.

        A cloud is the substrate; the weather is the signal.  If an overcast
        cloud is louder than a tornado the hierarchy is inverted -- which is
        exactly what shipped in the first cut of DARK, where the four leads
        below ran 0.72x to 0.92x of cloud.
        """
        for name, pal, ground in self._palettes():
            cloud = self._prom(pal['cloud'], ground)
            for key, symbol in (('swirl', 'tornado/hurricane/tropical storm'),
                                ('bolt', 'thunderstorm'),
                                ('hot', 'extreme heat'),
                                ('cold', 'extreme cold')):
                ratio = self._prom(pal[key], ground) / cloud
                self.assertGreaterEqual(
                    ratio, 1.0,
                    '%s palette: %s (%s) is only %.2fx as prominent as an '
                    'ordinary cloud on %s' % (name, key, symbol, ratio, ground))

    def test_ramps_keep_their_prominence_order(self):
        """Both ramps run the same way in both palettes, in PROMINENCE.

        Absolute lightness inverts between themes and that is fine; what may
        not change is which end of a ramp is the loud one.  Two clouds at the
        same prominence merge into one blob and bkn/ovc stop being tellable
        apart, which is the whole reason the ramp exists.
        """
        for name, pal, ground in self._palettes():
            cloud = [self._prom(pal[k], ground)
                     for k in ('cloud', 'cloud2', 'cloudd')]
            self.assertTrue(cloud[0] < cloud[1] < cloud[2],
                            '%s: cloud ramp not ascending in prominence: %s'
                            % (name, [round(x, 1) for x in cloud]))
            funnel = [self._prom(pal[k], ground)
                      for k in ('swirl', 'swirl2', 'swirl3')]
            self.assertTrue(funnel[0] > funnel[1] > funnel[2],
                            '%s: funnel ramp not descending in prominence: %s'
                            % (name, [round(x, 1) for x in funnel]))
            for step in (cloud, funnel):
                for a, b in zip(step, step[1:]):
                    self.assertGreater(abs(a - b), 20,
                                       '%s: ramp step too small to see: %s'
                                       % (name, [round(x, 1) for x in step]))

    def test_nothing_vanishes_into_its_page(self):
        for name, pal, ground in self._palettes():
            for key, value in pal.items():
                if value == 'transparent':      # the cyclone eye is a hole
                    continue
                self.assertGreater(
                    self._prom(value, ground), 40,
                    '%s: %s is too close to %s to see' % (name, key, ground))

    def test_dark_css_names_every_property(self):
        css = nwsicons.dark_css()
        for prop, _ in nwsicons.PALETTE.values():
            self.assertIn('%s:' % prop, css)
        for prop, _ in nwsicons.OPACITY.values():
            self.assertIn('%s:' % prop, css)

    def test_sprite_is_built_once(self):
        # It is ~60k characters of trigonometry; a report cycle rendering
        # several pages should pay for it once.
        self.assertIs(nwsicons.sprite(), nwsicons.sprite())

    def test_build_refuses_a_name_it_has_no_drawing_for(self):
        # Better a loud failure than a plausible-looking 'ovc' hiding a typo.
        with self.assertRaises(KeyError):
            nwsicons.build('not_a_condition', False)


@pytest.mark.network
class TestAgainstNWS(unittest.TestCase):
    """Held against NWS itself, not against a list we wrote down.

    Deselected unless `-m network` is given; see pytest.ini.

    NOTE the count is 34, not 35: NWS's `unknown` is a SENTINEL meaning "no
    icon for this period", not a condition.  It is deliberately absent from
    /icons -- which is exactly why api.weather.gov answers 400 for it -- and
    it must stay out of NAMES.  Do not "fix" this to 35."""

    def test_matches_nws_icon_index(self):
        import json
        import urllib.request
        req = urllib.request.Request(NWS_ICON_INDEX,
                                     headers={'User-Agent': USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                published = set(json.load(resp)['icons'])
        except Exception as e:
            self.skipTest('could not reach %s: %s' % (NWS_ICON_INDEX, e))

        drawn = set(nwsicons.NAMES)
        self.assertEqual(published - drawn, set(),
                         'NWS publishes conditions this extension does not draw; '
                         'add a symbol for each in bin/user/nwsicons.py')
        self.assertEqual(drawn - published, set(),
                         'this extension draws conditions NWS no longer publishes')


if __name__ == '__main__':
    unittest.main()
