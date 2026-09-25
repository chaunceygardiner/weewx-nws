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

EVERY RULE HERE RUNS OVER BOTH PALETTES.  That is the point: a rule that only
the dark values satisfy has been fitted to them and describes nothing.
Asserting it over the palette that was designed, shipped and liked is what
shows the rule is real -- and it works: this condition is what caught
--fc-accent failing AA on the tint in LIGHT mode, which two earlier contrast
sweeps had both missed because both measured every token against the card.

THE BAR IS TWO MEASURES, AND BOTH MUST CLEAR (6.1.2).  Text clears WCAG 2 4.5
AND APCA Lc 60, whatever its size or weight.  A mark a reader has to see -- a
chart line, a marker, a severity rail -- clears WCAG 3.0 AND APCA Lc 30.  The
WCAG ratio alone is wrong in a known direction: it passed every pair of the
dark palette before this one, while APCA scored 26 of them under 60, the
faint tier at Lc 35.  weewx-xtide and weewx-tempestas hold the same bars.
Holding them moved light twice -- --fc-accent, for the page title, and
--fc-axis -- and nothing else in light needed to move.

GROUNDS is the load-bearing data: which ground each token lands on, and
whether it is text or a mark there, because that decides its bar.

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

No third-party color library.  The WCAG and APCA arithmetic below is
weewx-tempestas' tools/contrast.py, verbatim, so the skins cannot disagree
about a number; CIE L* and OKLab are short and exactly specified.
"""

import os
import re

import pytest

CSS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        '..', 'skins', 'nws', 'css', 'nws.css')

# (WCAG 2 ratio, APCA |Lc|) that each kind must clear.
BARS = {'text': (4.5, 60), 'mark': (3.0, 30)}

# token -> [(ground token, 'text' or 'mark'[, opacity]), ...]
# A mark is listed only where no text entry already holds the token to a
# stricter bar on that ground at that opacity.
GROUNDS = {
    # Text on all three: the page title sits on the page.  Its marks -- the
    # current nav tab's fill on the page, the chart focus ring and the
    # current day tab on the card -- are covered by those text entries.
    '--fc-accent':    [('--fc-page', 'text'), ('--fc-surface', 'text'), ('--fc-tint', 'text')],
    '--fc-faint':     [('--fc-surface', 'text'), ('--fc-tint', 'text')],
    # The temperature curve crosses the night shading, and the day's range
    # bar is drawn on the empty track.
    '--fc-hi':        [('--fc-surface', 'text'), ('--fc-band', 'mark'), ('--fc-grid', 'mark')],
    '--fc-ink':       [('--fc-surface', 'text'), ('--fc-tint', 'text')],
    '--fc-ink-2':     [('--fc-surface', 'text')],
    '--fc-ink-3':     [('--fc-surface', 'text'), ('--fc-tint', 'text'), ('--fc-tint-2', 'text')],
    # Nothing these templates emit is a link; .fc a is there for a copier's.
    '--fc-link':      [('--fc-surface', 'text')],
    '--fc-lo':        [('--fc-surface', 'text'), ('--fc-grid', 'mark')],
    # --fc-band is the past alert's badge.  The recorded curve crossing the
    # night shading is a mark, and the text entry there already holds it.
    '--fc-muted':     [('--fc-page', 'text'), ('--fc-surface', 'text'),
                       ('--fc-tint', 'text'), ('--fc-tint-2', 'text'), ('--fc-band', 'text')],
    '--fc-nav-ink':   [('--fc-nav-bg', 'text'), ('--fc-nav-hover', 'text')],
    # The all-clear heading; the tick beside it is covered.
    '--fc-ok':        [('--fc-surface', 'text')],
    # --fc-muted and --fc-hi joined this list in 6.1.2: the 7 Day chart's two
    # seam chips are filled with the curve colors they name, and the words in
    # them are --fc-on-accent.
    '--fc-on-accent': [('--fc-accent', 'text'), ('--fc-sev-severe', 'text'),
                       ('--fc-muted', 'text'), ('--fc-hi', 'text')],
    # The rain strip is filled at opacity .8, and so is its legend swatch.
    '--fc-rain':      [('--fc-surface', 'text'), ('--fc-tint', 'text'),
                       ('--fc-surface', 'mark', .8)],
    # The severity colors became TEXT in 6.1 -- the named chip on an alert
    # card.  The rail down the card's left edge is a mark, and it borders
    # the page as well as the card.  --fc-sev-severe is also the alert
    # window's now marker, on its empty track.
    '--fc-sev-extreme':  [('--fc-surface', 'text'), ('--fc-page', 'mark')],
    '--fc-sev-severe':   [('--fc-surface', 'text'), ('--fc-page', 'mark'), ('--fc-grid', 'mark')],
    '--fc-sev-moderate': [('--fc-surface', 'text'), ('--fc-page', 'mark')],
    '--fc-sev-minor':    [('--fc-surface', 'text'), ('--fc-page', 'mark')],
    '--fc-sev-unknown':  [('--fc-surface', 'text'), ('--fc-page', 'mark')],
    # These render only in states a walk of one day's pages does not
    # produce: the readout is empty until a pointer touches a chart, and the
    # "begins later" badge needs an alert that has not started.  They are here
    # from the RULES, not from a render.  The dew point line crosses the
    # night shading.
    '--fc-dew':       [('--fc-surface', 'text'), ('--fc-band', 'mark')],
    '--fc-warn-ink':  [('--fc-warn-bg', 'text')],
    # The chart axes and the 7 Day chart's dividing rule, which crosses the
    # night shading.
    '--fc-axis':      [('--fc-surface', 'mark'), ('--fc-band', 'mark')],
}

# Tokens held to no bar, each with its reason.  Every --fc-* token is a
# ground, is in GROUNDS, is in MATCHED, or is here.
NO_BAR = {
    '--fc-line':      'the card border; a card is told from the page by its fill',
    '--fc-hair':      'the night legend swatch\'s outline, beside the words naming it',
    '--fc-rule':      ('the readout border, and the dashed box standing in for an icon '
                       'NWS has none for, whose hour the row\'s words describe'),
    '--fc-grid':      ('chart gridlines, and the empty track under the range and '
                       'alert-window bars; the bar on it is the data'),
    '--fc-grid-2':    ('the dashed day ticks, and the elapsed part of the alert '
                       'window, whose position the now marker carries'),
    '--fc-band':      ('the night shading, which each chart\'s caption names, and the '
                       'legend swatch naming it'),
}

# Dividers and control outlines: token -> the ground it sits on.  Held to no
# bar in either theme; instead DARK scores what LIGHT scores (APCA Lc) on
# that ground, so a line exactly as visible as the design made it in light
# is exactly as visible in dark.  A control's ground is what lies OUTSIDE
# it, not its own fill: that is what the outline separates it from.  The
# -divider tokens and --fc-control-line, --fc-chip-line and --fc-nav-line
# each twin a base token in light; the base token still draws the boxes and
# chart lines, which keep their prominence band.  The other three are the
# only users of their tokens.
MATCHED = {
    '--fc-hair-divider': '--fc-surface',   # between the 7 Day rows
    '--fc-hair-2':       '--fc-surface',   # between the Hourly rows
    '--fc-line-divider': '--fc-surface',   # under both column heads
    '--fc-rule-divider': '--fc-surface',   # beside, or over, Right now's stats
    '--fc-grid-divider': '--fc-surface',   # an alert's sections and its footer
    '--fc-page-divider': '--fc-page',      # over the page footer
    '--fc-head-rule':    '--fc-page',      # under the page title
    '--fc-control-line': '--fc-surface',   # a day tab
    '--fc-chip-line':    '--fc-surface',   # the response chip
    '--fc-warn-line':    '--fc-surface',   # the begins-later badge
    '--fc-nav-line':     '--fc-page',      # a nav tab
}
# How far dark may miss light's score.  A hex step moves a line on these
# grounds by about half an Lc.
MATCH_TOLERANCE = 1.0

# Every opacity in the stylesheet, by selector.  Each is measured above.
OPACITY = {'.fc svg.chart .parea': .8, '.fc .legend .sw-r': .8}

# Text on a FILLED chip, tab or badge clears its bar with the fill's channels
# moved this far either way.  A fill does not always come back from the
# renderer byte for byte: tests/verify_ink.py read the dark forecast chip's
# #ff9690 as #fe958f, and text derived to clear that fill at exactly Lc 60
# scored 59.5 on it.  The page and card grounds rendered exact; chips did not.
FILL_TOLERANCE = 2
TEXT_ON_FILLS = ['--fc-on-accent', '--fc-warn-ink']

LADDER = ['--fc-ink', '--fc-ink-2', '--fc-ink-3', '--fc-muted', '--fc-faint']
# extreme..minor only: 'unknown' is not a severity level, it is the absence of
# one, so it has no place in the ordering.
SEVERITY = ['--fc-sev-extreme', '--fc-sev-severe', '--fc-sev-moderate', '--fc-sev-minor']
LINES = ['--fc-line', '--fc-hair', '--fc-hair-2', '--fc-rule', '--fc-grid',
         '--fc-grid-2', '--fc-axis', '--fc-band', '--fc-head-rule',
         '--fc-hair-divider', '--fc-line-divider', '--fc-rule-divider',
         '--fc-grid-divider', '--fc-page-divider', '--fc-control-line',
         '--fc-chip-line', '--fc-nav-line']

# nwsicons.DARK was derived against exactly these two grounds.
ICON_GROUNDS = {'--fc-surface': '#111834', '--fc-tint': '#151c38'}


# ---- WCAG 2 and APCA: weewx-tempestas tools/contrast.py, verbatim ----------

# APCA-W3 0.0.98G-4g
_TRC = 2.4
_COEF = (0.2126729, 0.7151522, 0.0721750)
_NORM_BG, _NORM_TXT, _REV_TXT, _REV_BG = 0.56, 0.57, 0.62, 0.65
_BLK_THRS, _BLK_CLMP = 0.022, 1.414
_SCALE = 1.14
_OFFSET = 0.027
_DELTA_Y_MIN = 0.0005
_LO_CLIP = 0.1


def parse(color):
    """'#rgb', '#rrggbb', 'rgb(r,g,b)' or 'rgba(r,g,b,a)' -> (r, g, b, a)."""
    c = color.strip().lower()
    m = re.fullmatch(r'#([0-9a-f]{3}|[0-9a-f]{6})', c)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = ''.join(ch * 2 for ch in h)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0)
    m = re.fullmatch(r'rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)', c)
    if m:
        a = 1.0 if m.group(4) is None else float(m.group(4))
        return (float(m.group(1)), float(m.group(2)), float(m.group(3)), a)
    raise ValueError('not a color this reads: %r' % color)


def flatten(*layers):
    """Colors from the top down to an opaque bottom -> the opaque (r, g, b)
    a reader sees.  `flatten(chip, header)` is the chip over the header."""
    colors = [parse(c) if isinstance(c, str) else c for c in layers]
    r, g, b, a = colors[-1]
    if a < 1:
        raise ValueError('the bottom layer must be opaque: %r' % (layers[-1],))
    for top in reversed(colors[:-1]):
        tr, tg, tb, ta = top
        r, g, b = (tr * ta + r * (1 - ta), tg * ta + g * (1 - ta), tb * ta + b * (1 - ta))
    return (r, g, b)


def _wcag_lum(rgb):
    def lin(v):
        v /= 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def wcag(text, ground):
    """The WCAG 2 contrast ratio of two opaque (r, g, b) colors."""
    hi, lo = sorted((_wcag_lum(text), _wcag_lum(ground)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _apca_y(rgb):
    y = sum(k * (v / 255.0) ** _TRC for k, v in zip(_COEF, rgb))
    return y + (_BLK_THRS - y) ** _BLK_CLMP if y <= _BLK_THRS else y


def apca(text, ground):
    """APCA Lc of opaque (r, g, b) text on an opaque (r, g, b) ground."""
    ty, gy = _apca_y(text), _apca_y(ground)
    if abs(gy - ty) < _DELTA_Y_MIN:
        return 0.0
    if gy > ty:
        s = (gy ** _NORM_BG - ty ** _NORM_TXT) * _SCALE
        return 0.0 if s < _LO_CLIP else (s - _OFFSET) * 100
    s = (gy ** _REV_BG - ty ** _REV_TXT) * _SCALE
    return 0.0 if s > -_LO_CLIP else (s + _OFFSET) * 100


def measure(text, *ground):
    """Text over a ground given as layers (see flatten) -> (wcag, apca)."""
    under = flatten(*ground)
    over = flatten(text, under + (1.0,))
    return wcag(over, under), apca(over, under)


def clears(color, ground, kind, opacity=1.0):
    """(clears both bars?, WCAG ratio, APCA Lc) for '#rrggbb' `color` at
    `opacity` over the opaque '#rrggbb' `ground`."""
    ratio, lc = measure(parse(color)[:3] + (opacity,), ground)
    wcag_bar, apca_bar = BARS[kind]
    return ratio + 1e-9 >= wcag_bar and abs(lc) >= apca_bar, ratio, lc


def entries(tok):
    """GROUNDS[tok] with every opacity spelled out."""
    return [(e[0], e[1], e[2] if len(e) > 2 else 1.0) for e in GROUNDS.get(tok, [])]


def as_rendered(color, t=FILL_TOLERANCE):
    """'#rrggbb' with every channel moved t each way: the lightest and darkest
    a renderer may paint it."""
    r, g, b, _ = parse(color)
    return ['#%02x%02x%02x' % tuple(min(255, max(0, int(c) + d)) for c in (r, g, b))
            for d in (-t, t)]


# ---- CIE L* and OKLab ------------------------------------------------------

def _rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))

def _linear(v):
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

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


class TestTheMeasures:

    def test_the_measures_are_the_published_ones(self):
        """The oracle.  A passing sweep proves nothing about the arithmetic:
        a wrong exponent or a swapped sign passes pairs as easily as it fails
        them.  APCA-W3 publishes Lc 106.04 for black on white and -107.88 for
        white on black; the WCAG ratio of the two is 21 by definition."""
        black, white = (0, 0, 0), (255, 255, 255)
        assert abs(apca(black, white) - 106.04) < 0.01
        assert abs(apca(white, black) + 107.88) < 0.01
        assert abs(wcag(black, white) - 21.0) < 1e-9

    def test_opacity_is_applied_before_scoring(self):
        """Half-transparent black over white is the gray a reader sees, not
        black."""
        ratio, _ = measure((0, 0, 0, .5), '#ffffff')
        assert abs(ratio - wcag((127.5, 127.5, 127.5), (255, 255, 255))) < 1e-9

    def test_every_token_is_accounted_for(self):
        """A token nobody classified is a token nobody measured."""
        grounds = {e[0] for pairs in GROUNDS.values() for e in pairs}
        missing = sorted(t for t in LIGHT if t.startswith('--fc-')
                         and t not in GROUNDS and t not in grounds and t not in NO_BAR
                         and t not in MATCHED)
        assert not missing, ('in no GROUNDS entry and not in NO_BAR or MATCHED: %s'
                             % ', '.join(missing))
        stale = sorted(t for t in list(NO_BAR) + list(MATCHED) if t not in LIGHT)
        assert not stale, ('NO_BAR or MATCHED names tokens the stylesheet no longer has: %s'
                           % ', '.join(stale))
        both = sorted(set(NO_BAR) & set(MATCHED))
        assert not both, 'in NO_BAR and MATCHED: %s' % ', '.join(both)

    def test_every_opacity_is_measured(self):
        """Opacity is part of the color, and a token table cannot see it.
        Every opacity in the stylesheet is listed in OPACITY, and each value
        there is one GROUNDS measures --fc-rain at, the only token drawn
        translucent."""
        css = re.sub(r'/\*.*?\*/', '', open(CSS_PATH).read(), flags=re.S)
        found = {}
        for selector, body in re.findall(r'([^{}]+)\{([^{}]*)\}', css):
            for value in re.findall(r'(?<![-\w])opacity\s*:\s*([\d.]+)', body):
                found[selector.strip()] = float(value)
        assert found == OPACITY
        measured = {o for _, kind, o in entries('--fc-rain') if kind == 'mark'}
        assert set(OPACITY.values()) <= measured


@pytest.mark.parametrize('name,palette', PALETTES, ids=IDS)
class TestBothPalettes:
    """Light passing too is the proof that these rules are real."""

    def test_every_token_clears_both_bars_on_every_ground_it_reaches(self, name, palette):
        bad = []
        for tok in sorted(GROUNDS):
            for ground, kind, opacity in entries(tok):
                ok, ratio, lc = clears(palette[tok], palette[ground], kind, opacity)
                if not ok:
                    bad.append('%s%s on %s (%s): WCAG %.2f, APCA Lc %.1f'
                               % (tok, '' if opacity == 1 else ' at %g' % opacity,
                                  ground, kind, ratio, lc))
        assert not bad, '%s palette: %s' % (name, '; '.join(bad))

    def test_text_on_a_fill_clears_its_bar_as_the_fill_renders(self, name, palette):
        """See FILL_TOLERANCE: a bar met at exactly the token is missed by a
        chip painted one unit darker."""
        bad = []
        for tok in TEXT_ON_FILLS:
            for ground, kind, opacity in entries(tok):
                for fill in as_rendered(palette[ground]):
                    ok, ratio, lc = clears(palette[tok], fill, kind, opacity)
                    if not ok:
                        bad.append('%s on %s painted %s: WCAG %.2f, APCA Lc %.1f'
                                   % (tok, ground, fill, ratio, lc))
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

    def test_the_lower_tiers_stay_distinct(self, name, palette):
        """Lifting dark's muted and faint tiers to Lc 60 is exactly what could
        merge them into the ink above them: a tier has to stay a tier, not
        just pass.  From ink-2 down, each sits at least 5 Lc below the one
        above it on the card.  The top pair is left to the L* test above,
        because APCA flattens near black: light's ink and ink-2, an even L*
        step apart, score 4.5 Lc apart."""
        card = palette['--fc-surface']
        lc = [abs(clears(palette[t], card, 'text')[2]) for t in LADDER]
        gaps = [lc[i] - lc[i + 1] for i in range(1, len(lc) - 1)]
        assert min(gaps) >= 5, (
            '%s: ladder Lc on the card %s' % (name, ['%.1f' % v for v in lc]))

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

    def test_every_divider_scores_what_it_scores_in_light(self):
        """Dark's dividers and control outlines were Lc 0 to 50 where light's
        are 8 to 62: the same page with its structure rubbed out.  Each one,
        on the ground it sits on, now scores what light scores there."""
        bad = []
        for tok, ground in sorted(MATCHED.items()):
            want = abs(clears(LIGHT[tok], LIGHT[ground], 'mark')[2])
            got = abs(clears(DARK[tok], DARK[ground], 'mark')[2])
            if abs(got - want) > MATCH_TOLERANCE:
                bad.append('%s on %s: Lc %.1f in dark, %.1f in light'
                           % (tok, ground, got, want))
        assert not bad, '; '.join(bad)

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
