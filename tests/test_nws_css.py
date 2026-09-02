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

"""The sample skin's two palettes, asserted as one set of rules.

EVERY RULE HERE RUNS OVER BOTH PALETTES, and light must pass unchanged.  That
is the point: a rule that only the new values satisfy has been fitted to them
and describes nothing.  Asserting it over the palette that was designed,
shipped and liked is what shows the rule is real -- and it works: this
condition is what caught --fc-accent failing AA on the tint in LIGHT mode,
which two earlier contrast sweeps had both missed because both measured every
token against the card.

GROUNDS is the load-bearing data: which ground each token lands on, and at
what effective px, because that is what decides whether its bar is 4.5 (small
text) or 3.0 (large).

It is built from the RULES -- every color-bearing selector paired with the
grounds it CAN reach -- and only checked against a render.  That order matters
and was learned the hard way: a walk of the rendered DOM sees what one page
happened to show on one day.  It misses the readout, which is empty until a
pointer touches a chart; it misses the "begins later" badge, which needs an
alert that has not started; and on a station with no active alert it misses
the entire alert card, including the callout label whose contrast failure
this file exists to have caught.

A new element that puts an existing token on a new ground must be added here,
and until it is, this suite cannot see it.  `.fc .live` was deleted rather
than added: nothing emits it -- it arrived with the stylesheet from a mockup
that had a decorative LIVE badge, and no template here has ever produced one.

No third-party color library: WCAG contrast, CIE L* and OKLab are all short
and exactly specified, and a test dependency for thirty lines of arithmetic
would not be worth it.
"""

import os
import re

import pytest

CSS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        '..', 'skins', 'nws', 'css', 'nws.css')

# token -> [(ground token, required contrast ratio), ...]
# Measured by walking the rendered pages; see the module docstring.
GROUNDS = {
    '--fc-accent':    [('--fc-page', 3.0), ('--fc-surface', 4.5), ('--fc-tint', 4.5)],
    '--fc-faint':     [('--fc-surface', 4.5), ('--fc-tint', 4.5)],
    '--fc-hi':        [('--fc-surface', 4.5)],
    '--fc-ink':       [('--fc-surface', 4.5), ('--fc-tint', 4.5)],
    '--fc-ink-2':     [('--fc-surface', 4.5)],
    '--fc-ink-3':     [('--fc-surface', 4.5), ('--fc-tint', 4.5), ('--fc-tint-2', 4.5)],
    '--fc-link':      [('--fc-surface', 4.5)],
    '--fc-lo':        [('--fc-surface', 4.5)],
    '--fc-muted':     [('--fc-page', 4.5), ('--fc-surface', 4.5),
                       ('--fc-tint', 4.5), ('--fc-tint-2', 4.5)],
    '--fc-nav-ink':   [('--fc-nav-bg', 4.5)],
    '--fc-ok':        [('--fc-surface', 3.0)],
    '--fc-on-accent': [('--fc-accent', 4.5), ('--fc-sev-severe', 4.5)],
    '--fc-rain':      [('--fc-surface', 4.5), ('--fc-tint', 4.5)],
    # These two render only in states a walk of one day's pages does not
    # produce: the readout is empty until a pointer touches a chart, and the
    # "begins later" badge needs an alert that has not started.  They are here
    # from the RULES, not from a render.
    '--fc-dew':       [('--fc-surface', 4.5)],
    '--fc-warn-ink':  [('--fc-warn-bg', 4.5)],
}

LADDER = ['--fc-ink', '--fc-ink-2', '--fc-ink-3', '--fc-muted', '--fc-faint']
# extreme..minor only: 'unknown' is not a severity level, it is the absence of
# one, so it has no place in the ordering.
SEVERITY = ['--fc-sev-extreme', '--fc-sev-severe', '--fc-sev-moderate', '--fc-sev-minor']
LINES = ['--fc-line', '--fc-hair', '--fc-hair-2', '--fc-rule', '--fc-grid',
         '--fc-grid-2', '--fc-axis', '--fc-band', '--fc-head-rule']

# nwsicons.DARK was derived against exactly these two grounds.
ICON_GROUNDS = {'--fc-surface': '#111834', '--fc-tint': '#151c38'}


# ---- color arithmetic ----------------------------------------------------

def _rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))

def _linear(v):
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

def relative_luminance(h):
    r, g, b = (_linear(v) for v in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b

def contrast(a, b):
    l1, l2 = relative_luminance(a), relative_luminance(b)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)

def _xyz(h):
    r, g, b = (_linear(v) for v in _rgb(h))
    return (0.4124564 * r + 0.3575761 * g + 0.1804375 * b,
            0.2126729 * r + 0.7151522 * g + 0.0721750 * b,
            0.0193339 * r + 0.1191920 * g + 0.9503041 * b)

def lstar(h):
    y = _xyz(h)[1]
    return 116 * (y ** (1 / 3.0)) - 16 if y > 0.008856 else 903.3 * y

def _oklab(h):
    r, g, b = (_linear(v) for v in _rgb(h))
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3.0)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3.0)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3.0)
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)

def prominence(color, ground):
    """Perceptual distance from the ground a thing sits on.  This is what the
    objective means by prominence -- never absolute lightness."""
    a, b = _oklab(color), _oklab(ground)
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


# ---- the two palettes, read out of the stylesheet -------------------------

def _palettes():
    css = open(CSS_PATH).read()
    light = dict(re.findall(r'(--[\w-]+)\s*:\s*(#[0-9a-fA-F]{6})',
                            re.search(r':root\s*\{(.*?)\n\}', css, re.S).group(1)))
    dark_block = re.search(r'@media \(prefers-color-scheme: dark\)\s*\{\s*'
                           r':root\s*\{(.*?)\n\}', css, re.S)
    assert dark_block, 'no prefers-color-scheme dark block in nws.css'
    dark = dict(light)
    dark.update(re.findall(r'(--[\w-]+)\s*:\s*(#[0-9a-fA-F]{6})', dark_block.group(1)))
    return light, dark, dark_block.group(1)

LIGHT, DARK, DARK_TEXT = _palettes()
PALETTES = [('light', LIGHT), ('dark', DARK)]
IDS = [name for name, _ in PALETTES]


@pytest.mark.parametrize('name,palette', PALETTES, ids=IDS)
class TestBothPalettes:
    """Light passing unchanged is the proof that these rules are real."""

    def test_every_token_clears_its_bar_on_every_ground_it_reaches(self, name, palette):
        bad = []
        for tok, pairs in sorted(GROUNDS.items()):
            for ground, bar in pairs:
                got = contrast(palette[tok], palette[ground])
                if got + 1e-9 < bar:
                    bad.append('%s on %s: %.2f < %.1f' % (tok, ground, got, bar))
        assert not bad, '%s palette: %s' % (name, '; '.join(bad))

    def test_the_ink_ladder_is_ordered_and_evenly_stepped(self, name, palette):
        """Five TIERS, not five grays: a step that is not a real level is
        decoration, and a ladder that is not monotonic is not a ladder."""
        card = palette['--fc-surface']
        seps = [abs(lstar(palette[t]) - lstar(card)) for t in LADDER]
        assert seps == sorted(seps, reverse=True), '%s: ladder not monotonic' % name
        steps = [seps[i] - seps[i + 1] for i in range(len(seps) - 1)]
        assert min(steps) > 0, '%s: a ladder step is zero or negative' % name
        assert max(steps) / min(steps) <= 2.0, (
            '%s: uneven ladder steps %s' % (name, ['%.1f' % s for s in steps]))

    def test_a_more_severe_alert_is_more_prominent(self, name, palette):
        """The rule the first hand-picked dark palette broke, putting an
        ordinary advisory above a warning."""
        card = palette['--fc-surface']
        got = [prominence(palette[t], card) for t in SEVERITY]
        assert got == sorted(got, reverse=True), (
            '%s: severity prominence out of order: %s'
            % (name, dict(zip(SEVERITY, ['%.3f' % g for g in got]))))

    def test_no_rule_out_shouts_the_text_it_separates(self, name, palette):
        """Hairlines are seen, not read.  One louder than body text makes the
        page look like a table of borders."""
        card = palette['--fc-surface']
        body = prominence(palette['--fc-ink-3'], card)
        for tok in LINES:
            assert prominence(palette[tok], card) <= body, (
                '%s: %s is more prominent than the body text' % (name, tok))


class TestDarkSpecifics:

    def test_the_icon_grounds_are_unmoved(self):
        """nwsicons.DARK was derived against these two colors specifically,
        and --wx-hot and --wx-sleet sit at the sRGB ceiling for them.  Moving
        either silently invalidates all nineteen icon colors."""
        for tok, expected in ICON_GROUNDS.items():
            assert DARK[tok].lower() == expected, (
                '%s moved to %s; nwsicons.DARK must be re-derived' % (tok, DARK[tok]))

    def test_the_icon_palette_is_the_modules_own(self):
        """A copy of the module's values could only drift from it."""
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        '..', 'bin', 'user'))
        import nwsicons
        spelling = {'cloud2': 'cloud-2', 'cloudd': 'cloud-3',
                    'swirl2': 'swirl-2', 'swirl3': 'swirl-3'}
        in_css = dict(re.findall(r'(--wx-[\w-]+)\s*:\s*(#[0-9a-fA-F]{6})', DARK_TEXT))
        expected = {'--wx-%s' % spelling.get(k, k): v
                    for k, v in nwsicons.DARK.items() if k != 'eye'}
        assert in_css == {k: v for k, v in expected.items()}, (
            'the dark icon palette in nws.css has drifted from nwsicons.DARK')

    def test_no_light_icon_default_is_restated(self):
        """The light icon values live in the module, and a skin that defines
        none renders them byte for byte.  Restating one here is how the two
        drift -- so --wx-* may appear in this stylesheet ONLY in the dark
        block, and nowhere else."""
        css = open(CSS_PATH).read()
        outside = css.replace(DARK_TEXT, '')
        offenders = sorted(set(re.findall(r'--wx-[\w-]+', outside)))
        assert not offenders, (
            'light --wx-* defaults restated outside the dark block: %s'
            % ', '.join(offenders))

    def test_every_light_token_has_a_dark_counterpart(self):
        """A token defined only in :root keeps its LIGHT value on a dark
        page -- which is how one unreadable element survives a theme."""
        light_only = sorted(t for t in LIGHT
                            if t.startswith('--fc-')
                            and t not in dict(re.findall(
                                r'(--[\w-]+)\s*:\s*(#[0-9a-fA-F]{6})', DARK_TEXT)))
        assert not light_only, 'no dark value for: %s' % ', '.join(light_only)

    def test_text_on_a_fill_inverts(self):
        """--fc-on-accent is the one token whose direction reverses: the
        accent fill is LIGHTER on dark, so readable text on it is dark.  If
        this ever comes back as near-white, the fill has been misderived."""
        assert lstar(LIGHT['--fc-on-accent']) > 50
        assert lstar(DARK['--fc-on-accent']) < 50

    def test_the_tints_sit_above_the_card_on_dark(self):
        """In light they are below it only because white is the gamut
        ceiling; that was never a decision about depth."""
        for tok in ('--fc-tint', '--fc-tint-2'):
            assert lstar(LIGHT[tok]) < lstar(LIGHT['--fc-surface']), tok
            assert lstar(DARK[tok]) > lstar(DARK['--fc-surface']), tok

    def test_the_page_stays_behind_the_cards(self):
        """The page is recessed in BOTH themes -- it is the ground the cards
        sit on, and a page lighter than its cards inverts the figure."""
        for palette in (LIGHT, DARK):
            assert lstar(palette['--fc-page']) < lstar(palette['--fc-surface'])
