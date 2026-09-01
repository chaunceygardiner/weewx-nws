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

"""A drawn SVG icon for every NWS forecast condition.

NWS gives each forecast period an `icon` URL naming one of 34 conditions
(https://api.weather.gov/icons is the index) and serves a photograph for it.
This module draws those 34 instead, day and night, as one <symbol> per icon on
a shared 32x32 grid: crisp at any size, recolourable by the consuming skin,
and free of the "X then Y" split composites the raster set produces, which read
as rendering glitches at the size a forecast table uses.

A skin reaches this through $nwsforecast rather than importing it:

    $nwsforecast.icon_sprite                     ... once per page
    $nwsforecast.icon($period.iconUrl)           ... per period
    $nwsforecast.icon_name($period.iconUrl)      ... (condition, night, known)

THREE NAMING CONTRACTS.  Consumers write all of these into their own templates
and stylesheets, so none may change without a major version:

  * symbol ids   wx-<condition>-<day|night>, e.g. wx-fog-night
  * css classes  wxi on the <svg>; wxi wxi-fallback on the <img> a not-yet-drawn
                 condition falls back to; wxi wxi-unknown on the empty box that
                 stands in when NWS itself has no icon
  * css custom properties  the --wx-* names in PALETTE below

COLOUR.  Every fill and every opacity is emitted as var(--wx-NAME, default),
so the defaults ARE the finished look: a skin that defines nothing gets the
shipped icons, and a skin that wants a dark theme redefines what it cares
about -- or pastes DARK below, which is a complete set chosen for a dark
ground rather than eighteen guesses.  (Verified in Chromium and Firefox:
var() resolves in SVG presentation attributes, including opacity, and a custom
property set on the host <svg> inherits through <use> into the shadow tree, so
one page can carry differently-coloured instances.)

CONDITIONS WE HAVE NO SYMBOL FOR.  Coverage is complete as of this release --
the drawn set, the names NWS publishes and the descriptions all match exactly,
and a test holds them together.  So an unrecognised name means NWS has ADDED a
condition since, which is worth hearing about: it is logged once per weewxd
run, and the period falls back to NWS's own hosted image so the reader still
sees the right weather.  The fallback has to be the remote URL; a condition
invented after this shipped has no local file either.

The one name that gets a different answer is NWS's own 'unknown', which it
emits when it has no icon for a period.  api.weather.gov answers 400 for that
URL (and for any other name it does not serve), so hot-linking it would give
the reader a broken image rather than the weather; that case renders an empty
box of the right size instead, classed wxi-unknown.

That IS a live path.  Through 5.1 nws.py failed the whole reply on an
'unknown' icon, so no such period ever reached a template; since 5.2 it keeps
the period -- throwing away 156 periods of good data over one missing glyph
was the worse trade -- and logs a count once per reply.
"""

import html
import logging
import math

log = logging.getLogger(__name__)

# The palette, as (public css custom property, built-in default).  Every fill
# is emitted as var(--wx-NAME, #default), so a skin that defines nothing gets
# these exact colours and a skin that defines one gets its own.  The property
# names are a contract; see the module docstring.
PALETTE = {
    'sun':    ('--wx-sun',     '#F2B705'),
    'sunray': ('--wx-sunray',  '#E0A800'),
    'moon':   ('--wx-moon',    '#8A93A0'),

    # THE CLOUD RAMP -- three steps of one ramp, not three separate colours.
    # Two cloud shapes in the same grey merge into one blob, so every stacked
    # symbol paints its back cloud a step along from its front cloud; that gap
    # is the whole reason bkn and ovc are told apart at 34px.  The steps are
    # NOT named for depth (step 2 is the BACK cloud in bkn and the FRONT cloud
    # in ovc) and NOT named for tone (a dark theme inverts the ramp, so step 3
    # becomes the lightest value there).  Ordinal is the only name that stays
    # true in both directions: 1 is the lightest on the default light palette.
    'cloud':  ('--wx-cloud',   '#C3CBD6'),
    'cloud2': ('--wx-cloud-2', '#9AA5B4'),
    'cloudd': ('--wx-cloud-3', '#7E8998'),

    'rain':   ('--wx-rain',    '#2F6EA8'),
    'snow':   ('--wx-snow',    '#6FA8D8'),
    'sleet':  ('--wx-sleet',   '#4A7FB5'),
    'bolt':   ('--wx-bolt',    '#E0A800'),
    'fog':    ('--wx-fog',     '#8B93A0'),
    'wind':   ('--wx-wind',    '#6E7B8B'),
    'hot':    ('--wx-hot',     '#C0392B'),
    'cold':   ('--wx-cold',    '#2F6EA8'),
    'dust':   ('--wx-dust',    '#B08A50'),
    'smoke':  ('--wx-smoke',   '#8B93A0'),

    # The tornado funnel is a ramp too, lightening toward the ground.  Its
    # steps used to be one colour at three opacities; see TONE IS COLOUR below.
    'swirl':  ('--wx-swirl',   '#6E7B8B'),
    'swirl2': ('--wx-swirl-2', '#8B95A2'),
    'swirl3': ('--wx-swirl-3', '#A5ADB7'),

    # A cyclone's eye.  The centre is simply not painted, so the page -- whatever
    # colour it is -- shows through, and the eye is right on every background
    # without anyone setting anything.  Set this only to fill the eye instead.
    'eye':    ('--wx-eye',     'transparent'),
}

# TONE IS COLOUR, TRANSLUCENCY IS OPACITY.
#
# A fill at partial opacity does not composite against a colour, it composites
# against THE PAGE, which no token can know.  Measured on the default palette:
# ovc's back cloud (step 3 at .75) came out 1.4 luma LIGHTER than its front
# cloud on white -- an invisible depth cue -- and 56 luma DARKER on a #111834
# card.  The cue reversed direction between themes.  So anywhere opacity was
# encoding a permanent tonal step it is now a solid step on a ramp, which
# themes correctly by construction.
#
# What remains below is genuine translucency -- "this is fainter than that" is
# the intent -- and stays tunable.
OPACITY = {
    # A tropical storm is the same drawing as a hurricane, fainter.  That IS
    # the distinction between the two symbols, so it is not a tonal step.
    'band': ('--wx-op-band', '.66'),
    # The thermometer's tube behind the mercury.
    'tube': ('--wx-op-tube', '.28'),
}

# A DARK PALETTE, CHOSEN RATHER THAN GUESSED.
#
# The cost of theming these is not typing twenty lines, it is picking twenty
# values that keep the ramps legible on a dark ground -- work that should be
# done once, here, by whoever owns the drawing, instead of re-derived by every
# consumer.  Measured against #111834 (luma 27), a real card colour:
#
#   cloud ramp   207 / 161 / 120   gaps of 46 and 41, and the darkest step
#                                  still sits 93 above the background
#   swirl ramp   158 / 121 /  85   the tornado funnel fades toward the GROUND,
#                                  so on a dark page it darkens downward --
#                                  the ramp direction inverts with the theme,
#                                  which is precisely what an opacity could
#                                  never express
#
# Blues and the moon are lifted hard: #2F6EA8 rain reads at luma 98, which is
# nearly invisible on a dark card.  --wx-eye is already transparent and needs
# no dark value; it is listed so this stays a complete mirror of PALETTE.
DARK = {
    'sun':    '#F2B705',
    'sunray': '#E0A800',
    'moon':   '#C9D2E0',
    'cloud':  '#C8D0DC',
    'cloud2': '#97A3B5',
    'cloudd': '#6D7A8D',
    'rain':   '#5D9BD8',
    'snow':   '#A8D4F0',
    'sleet':  '#7FB0DE',
    'bolt':   '#E0A800',
    'fog':    '#A9B2C0',
    'wind':   '#93A0B2',
    'hot':    '#E05C4A',
    'cold':   '#5D9BD8',
    'dust':   '#C7A268',
    'smoke':  '#A9B2C0',
    'swirl':  '#93A0B2',
    'swirl2': '#6E7A8B',
    'swirl3': '#4C5666',
    'eye':    'transparent',
}

# Partial opacity composites toward the PAGE, so the same value reads weaker on
# a dark ground than on a light one; both are lifted to compensate.
DARK_OPACITY = {
    'band': '.74',
    'tube': '.38',
}


def dark_css(selector=':root'):
    """The dark palette as a paste-able css rule.

    Emitted from the same dicts the drawing uses, so it cannot drift from the
    icons the way a block copied into a stylesheet would.
    """
    lines = ['%s {' % selector]
    for key, (prop, _default) in PALETTE.items():
        lines.append('  %s: %s;' % (prop, DARK[key]))
    for key, (prop, _default) in OPACITY.items():
        lines.append('  %s: %s;' % (prop, DARK_OPACITY[key]))
    lines.append('}')
    return '\n'.join(lines)


C = {key: 'var(%s, %s)' % (prop, default)
     for key, (prop, default) in PALETTE.items()}

O = {key: 'var(%s, %s)' % (prop, default)
     for key, (prop, default) in OPACITY.items()}

NAMES = ['skc', 'few', 'sct', 'bkn', 'ovc', 'wind_skc', 'wind_few', 'wind_sct',
         'wind_bkn', 'wind_ovc', 'snow', 'rain_snow', 'rain_sleet', 'snow_sleet',
         'fzra', 'rain_fzra', 'snow_fzra', 'sleet', 'rain', 'rain_showers',
         'rain_showers_hi', 'tsra', 'tsra_sct', 'tsra_hi', 'tornado', 'hurricane',
         'tropical_storm', 'dust', 'smoke', 'haze', 'hot', 'cold', 'blizzard', 'fog']


# ---- primitives -------------------------------------------------------
def sun(cx=16.0, cy=13.0, r=5.0, rays=True):
    out = []
    if rays:
        for k in range(8):
            a = math.radians(k * 45)
            x1, y1 = cx + math.cos(a) * (r + 2.1), cy + math.sin(a) * (r + 2.1)
            x2, y2 = cx + math.cos(a) * (r + 4.6), cy + math.sin(a) * (r + 4.6)
            out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" '
                       'stroke-width="1.9" stroke-linecap="round"/>'
                       % (x1, y1, x2, y2, C['sunray']))
    out.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s"/>' % (cx, cy, r, C['sun']))
    return ''.join(out)


def moon(cx=16.0, cy=13.0, r=6.6):
    # A crescent: one arc out, a tighter arc back.
    return ('<path d="M %.2f %.2f A %.2f %.2f 0 1 0 %.2f %.2f A %.2f %.2f 0 0 1 %.2f %.2f Z" '
            'fill="%s"/>'
            % (cx + r * 0.42, cy - r * 0.91, r, r, cx + r * 0.42, cy + r * 0.91,
               r * 0.82, r * 0.82, cx + r * 0.42, cy - r * 0.91, C['moon']))


def cloud(x=0.0, y=0.0, s=1.0, fill=None):
    # No opacity parameter on purpose.  A cloud's tone is a step on the colour
    # ramp (see PALETTE); drawing one at partial opacity composites it against
    # the page instead, which is what made ovc invisible on white and reversed
    # the depth cue on a dark card.
    f = fill or C['cloud']
    return ('<g transform="translate(%.2f %.2f) scale(%.3f)" fill="%s">'
            '<circle cx="13" cy="15" r="6"/><circle cx="21" cy="17.5" r="4.6"/>'
            '<circle cx="8.4" cy="18" r="4.3"/>'
            '<rect x="8" y="16.9" width="14" height="5.7" rx="2.85"/></g>'
            % (x, y, s, f))


def drops(xs, y=25.5, h=4.0, col=None, w=1.9):
    col = col or C['rain']
    return ''.join('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" '
                   'stroke-width="%.1f" stroke-linecap="round"/>'
                   % (x + 1.0, y, x - 1.0, y + h, col, w) for x in xs)


def flakes(xs, y=26.6, r=1.9, col=None):
    col = col or C['snow']
    out = []
    for x in xs:
        for a in (0, 60, 120):
            dx, dy = math.cos(math.radians(a)) * r, math.sin(math.radians(a)) * r
            out.append('<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f" stroke="%s" '
                       'stroke-width="1.5" stroke-linecap="round"/>'
                       % (x - dx, y - dy, x + dx, y + dy, col))
    return ''.join(out)


def pellets(xs, y=26.4, col=None):
    col = col or C['sleet']
    return ''.join('<circle cx="%.1f" cy="%.1f" r="1.5" fill="%s"/>' % (x, y, col)
                   for x in xs)


def bolt(x=15.5, y=23.0):
    return ('<path d="M %.1f %.1f l 4.6 0 l -2.6 3.6 l 3.0 0 l -6.2 6.4 l 1.9 -4.6 '
            'l -2.6 0 Z" fill="%s"/>' % (x, y, C['bolt']))


def windlines(y0=24.0, col=None, n=3):
    col = col or C['wind']
    rows = [(5.0, 17.5), (7.5, 22.0), (5.0, 15.0)][:n]
    return ''.join('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" '
                   'stroke-width="1.9" stroke-linecap="round"/>'
                   % (a, y0 + i * 3.1, b, y0 + i * 3.1, col)
                   for i, (a, b) in enumerate(rows))


def cyclone(heavy=True):
    """Two thick spiral bands curling round a hollow eye.

    What "reads as an S" meant: the first attempt drew two thin OPEN arcs in
    one colour with a solid dot between them.  At 34px two 2.4-wide strokes
    of the same colour, meeting head to tail, merge into one continuous
    sinuous line -- there is nothing to say they are two separate masses --
    and a filled centre dot reads as a full stop sitting on that line.  The
    eye is the whole symbol and it had been drawn as ink rather than as a
    hole.

    So: bands with MASS, tapering from thick at the rim to a point at the
    centre (a taper is what says rotation), 180-degree rotational symmetry,
    and an eye you can see through.  Built numerically -- an outer edge swept
    at a constant radius and an inner edge swept back while its radius closes
    to meet it -- because hand-written cubics at this size are guesswork.

    THE EYE IS A HOLE, NOT PAINT.  It used to be a white disc drawn at the
    centre.  Measure the geometry and that disc was covering NOTHING: the
    bands sweep between radius r0 (5.4) and R (11.6) and never come within
    3.6 of the centre, so the disc was painting white over bare background --
    invisible on a white page, a white blob on a tinted card or any dark
    theme, which is where the bug lived.  What actually draws the eye is the
    stroked ring below.  So the centre is simply left unpainted and whatever
    is behind the icon shows through, correct on every background with
    nothing for a consumer to set.  --wx-eye survives as an escape hatch for
    someone who wants it filled after all, and defaults to transparent.

    (Cutting it with fill-rule="evenodd" was tried and is wrong for the same
    reason: with no band ink at the centre to subtract from, an eye subpath
    ADDS a filled disc.  Verified by sampling the centre pixel.)
    """
    col = C['swirl']
    cx = cy = 16.0
    R = 11.6 if heavy else 10.6
    r0 = 5.4 if heavy else 6.4          # a lighter storm = a thinner band
    a1, a2 = -8.0, -128.0               # the band's span, degrees

    def arc(start, end, rad_fn, steps=18):
        pts = []
        for k in range(steps + 1):
            f = k / float(steps)
            ang = math.radians(start + (end - start) * f)
            rad = rad_fn(f)
            pts.append((cx + math.cos(ang) * rad, cy + math.sin(ang) * rad))
        return pts

    outer = arc(a1, a2, lambda f: R)
    # Coming back, the inner edge closes on the outer one, so the band ends
    # in a point rather than a blunt stub.
    inner = arc(a2, a1, lambda f: R - (R - r0) * f)
    pts = outer + inner
    d = 'M ' + ' L '.join('%.2f %.2f' % p for p in pts) + ' Z'
    op = '1' if heavy else O['band']
    eye = 3.6 if heavy else 3.3
    return ('<g fill="%s" opacity="%s">'
            '<path d="%s"/>'
            '<path d="%s" transform="rotate(180 %.1f %.1f)"/>'
            '</g>'
            # Unpainted by default: the page shows through the eye.  Kept as a
            # token so a skin that wants it filled can say so.
            '<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s"/>'
            '<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="%s" '
            'stroke-width="2.3" opacity="%s"/>'
            % (col, op, d, d, cx, cy, cx, cy, eye, C['eye'], cx, cy, eye, col, op))


def haze_lines(col=None, y0=11.0, n=4, w=1.9):
    col = col or C['fog']
    spans = [(6.0, 26.0), (8.5, 23.5), (5.0, 24.0), (9.0, 27.0)][:n]
    return ''.join('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" '
                   'stroke-width="%.1f" stroke-linecap="round"/>'
                   % (a, y0 + i * 4.4, b, y0 + i * 4.4, col, w)
                   for i, (a, b) in enumerate(spans))


def thermo(col, hot=True):
    """hot / cold.  Deliberately the plain instrument: a sun beside "cold" is
    a contradiction, and a bare snowflake reads as snow no matter what the
    rest of the set does."""
    return ('<rect x="14.4" y="4.5" width="3.2" height="17" rx="1.6" fill="%s" '
            'opacity="%s"/>'
            '<rect x="15.1" y="%.1f" width="1.8" height="%.1f" fill="%s"/>'
            '<circle cx="16" cy="25" r="4.2" fill="%s"/>'
            % (col, O['tube'], 7.0 if hot else 15.0,
               (14.5 if hot else 6.5), col, col))


# ---- the sky base (celestial body + cloud coverage) --------------------
def base(cover, night):
    """cover: 'skc' | 'few' | 'sct' | 'bkn' | 'ovc'"""
    if cover == 'skc':
        return moon() if night else sun()
    if cover == 'few':
        b = moon(cx=13.0, cy=11.5, r=5.6) if night else sun(cx=13.0, cy=11.0, r=4.4)
        return b + cloud(x=6.0, y=6.0, s=0.66, fill=C['cloud'])
    if cover == 'sct':
        b = moon(cx=12.0, cy=10.5, r=5.4) if night else sun(cx=12.0, cy=10.0, r=4.2)
        return b + cloud(x=3.0, y=4.0, s=0.82, fill=C['cloud'])
    if cover == 'bkn':
        b = moon(cx=11.0, cy=9.5, r=4.8) if night else sun(cx=11.0, cy=9.0, r=3.8)
        return (b + cloud(x=8.0, y=1.0, s=0.55, fill=C['cloud2'])
                + cloud(x=0.0, y=2.5, s=0.95, fill=C['cloud']))
    return cloud(x=8.0, y=0.0, s=0.5, fill=C['cloudd']) + \
        cloud(x=-0.5, y=2.0, s=1.0, fill=C['cloud2'])


# ---- the 34 conditions ------------------------------------------------
def build(name, night):
    n = night
    if name in ('skc', 'few', 'sct', 'bkn', 'ovc'):
        return base(name, n)
    if name.startswith('wind_'):
        return base(name[5:], n) + windlines(y0=24.5)
    if name == 'rain':
        return base('ovc', n) + drops([11.0, 16.0, 21.0])
    if name == 'rain_showers':
        return base('bkn', n) + drops([12.5, 18.5])
    if name == 'rain_showers_hi':
        return base('sct', n) + drops([13.5, 19.0])
    if name == 'snow':
        return base('ovc', n) + flakes([10.5, 16.0, 21.5])
    if name == 'blizzard':
        return base('ovc', n) + flakes([10.0, 15.5, 21.0]) + \
            windlines(y0=29.0, col=C['fog'], n=1)
    if name == 'sleet':
        return base('ovc', n) + pellets([11.0, 16.0, 21.0])
    if name == 'rain_snow':
        return base('ovc', n) + drops([11.5]) + flakes([20.0])
    if name == 'rain_sleet':
        return base('ovc', n) + drops([11.5]) + pellets([20.0])
    if name == 'snow_sleet':
        return base('ovc', n) + flakes([11.5]) + pellets([20.0])
    if name == 'fzra':
        return base('ovc', n) + drops([12.0, 20.0]) + pellets([16.0], y=29.4)
    if name == 'rain_fzra':
        return base('ovc', n) + drops([11.0, 16.0]) + pellets([21.0], y=29.4)
    if name == 'snow_fzra':
        return base('ovc', n) + flakes([11.5]) + drops([19.5]) + pellets([16.0], y=29.8)
    if name == 'tsra':
        return base('ovc', n) + bolt() + drops([10.0], y=25.0)
    if name == 'tsra_sct':
        return base('bkn', n) + bolt()
    if name == 'tsra_hi':
        return base('sct', n) + bolt()
    if name == 'fog':
        return base('bkn', n) + haze_lines(y0=20.0, n=3, col=C['fog'])
    if name == 'haze':
        return (moon() if n else sun()) + haze_lines(y0=17.0, n=3, col=C['fog'], w=1.7)
    if name == 'smoke':
        return (moon(cx=12.0, cy=10.0, r=5.0) if n else sun(cx=12.0, cy=10.0, r=4.2)) + \
            haze_lines(y0=17.0, n=3, col=C['smoke'], w=2.3)
    if name == 'dust':
        return (moon(cx=12.0, cy=10.0, r=5.0) if n else sun(cx=12.0, cy=10.0, r=4.2)) + \
            haze_lines(y0=17.5, n=3, col=C['dust'], w=2.3)
    if name == 'hot':
        return thermo(C['hot'], hot=True)
    if name == 'cold':
        return thermo(C['cold'], hot=False)
    if name == 'tornado':
        return ('<path d="M 5 5 L 27 5 L 20.5 12 L 9.5 12 Z" fill="%s"/>'
                '<path d="M 9.5 12 L 20.5 12 L 17.5 19 L 12.5 19 Z" fill="%s"/>'
                '<path d="M 12.5 19 L 17.5 19 L 16.6 27.5 L 14 27.5 Z" fill="%s"/>'
                % (C['swirl'], C['swirl2'], C['swirl3']))
    if name in ('hurricane', 'tropical_storm'):
        return cyclone(heavy=(name == 'hurricane'))
    # build() is only ever called across NAMES.  Returning a plausible-looking
    # 'ovc' for anything else would hide a typo in NAMES behind a wrong icon.
    raise KeyError('nwsicons: no drawing for condition %r' % name)


_SPRITE = None


def sprite():
    """All 68 symbol definitions, built once per process.

    It is a pure function of module constants and runs about 60k characters of
    trigonometry and string building, so a report cycle that renders several
    pages should pay for it once rather than once a page."""
    global _SPRITE
    if _SPRITE is None:
        syms = []
        for name in NAMES:
            for night in (False, True):
                syms.append('<symbol id="wx-%s-%s" viewBox="0 0 32 32">%s</symbol>'
                            % (name, 'night' if night else 'day', build(name, night)))
        _SPRITE = ('<svg xmlns="http://www.w3.org/2000/svg" style="display:none" '
                   'aria-hidden="true">%s</svg>' % ''.join(syms))
    return _SPRITE


# Every icon name the feed has shown us that we have no symbol for.  Module
# state, so each name is logged once per weewxd process -- not once per report
# run, and certainly not once per period: a seven-day forecast would otherwise
# repeat the same line fourteen times and the hourly page 147.  weewxd runs for
# days, so one line per new condition is what an operator actually sees.
UNKNOWN = set()

# NWS's own "I have no icon for this period" name.  api.weather.gov answers 400
# for the URL, so it is the one unrecognised name we must NOT hot-link.
NWS_HAS_NO_ICON = 'unknown'


def icon_name(icon_url):
    """NWS icon URL -> (condition, is_night, known).

    Handles the documented URL shapes: plain, a ",NN" chance-of-precip
    suffix, and a "sct/fog" two-condition composite -- the FIRST condition
    wins, because the period's own text already says "... then ...".

    An unrecognised condition is reported as such rather than quietly
    becoming 'skc'.  Silently substituting fair weather for a name we do not
    know is the worst of the options: the page looks right, so nobody ever
    finds out an icon is missing.

    A blank or missing URL gets the same treatment, for the same reason: it
    means "no icon", not "clear sky".  It is reachable -- nws.py stores
    iconUrl='' on every ALERT record -- so a skin calling
    $nwsforecast.icon($alert.iconUrl) would otherwise put a sun over a tornado
    warning.  Nothing is logged for it: a blank URL on an alert is normal, and
    a line per alert would be noise.  NWS's own 'unknown' sentinel, which IS a
    surprise, is logged where it is recognised below.
    """
    if not icon_url:
        return NWS_HAS_NO_ICON, False, False
    path = icon_url.split('?')[0]
    tail = path.split('/icons/land/')[-1]
    parts = [p for p in tail.split('/') if p]
    night = parts[0] == 'night' if parts else False
    cond = (parts[1] if len(parts) > 1 else 'skc').split(',')[0]
    if cond in NAMES:
        return cond, night, True
    if cond not in UNKNOWN:
        UNKNOWN.add(cond)
        if cond == NWS_HAS_NO_ICON:
            log.info('nwsicons: NWS supplied no icon for a period (%s); '
                     'rendering an empty icon box.' % icon_url)
        else:
            log.info('nwsicons: no drawn icon for condition %r (%s); using '
                     "NWS's own image.  If NWS has added a condition, this "
                     'extension needs a symbol for it.' % (cond, icon_url))
    return cond, night, False


def nws_img(icon_url):
    """The NWS raster, asked for at the largest size so it is not blurry in
    the box a drawn icon would have filled."""
    return (icon_url.replace('?size=medium', '?size=large')
            .replace('?size=small', '?size=large').replace(',0?', '?'))


def icon(icon_url, cls='wxi'):
    cond, night, known = icon_name(icon_url)
    esc_cls = html.escape(cls, quote=True)
    if cond == NWS_HAS_NO_ICON:
        # NWS is telling us it has no icon for this period, and 400s the URL.
        # An empty box of the right size keeps the row's alignment; hot-linking
        # would give the reader a broken image instead.
        return ('<svg class="%s wxi-unknown" viewBox="0 0 32 32" role="img" '
                'aria-label="forecast icon unavailable"></svg>' % esc_cls)
    if not known:
        # Still show the reader the right weather.  The drawn set can catch
        # up on the next release; the page must not be wrong meanwhile.
        label = html.escape(cond.replace('_', ' '), quote=True)
        return ('<img class="%s wxi-fallback" src="%s" alt="%s" title="%s">'
                % (esc_cls, html.escape(nws_img(icon_url), quote=True),
                   label, label))
    return ('<svg class="%s" viewBox="0 0 32 32" role="img" aria-label="%s">'
            '<use href="#wx-%s-%s"/></svg>'
            % (esc_cls, cond.replace('_', ' '), cond, 'night' if night else 'day'))
