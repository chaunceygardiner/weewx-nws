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

"""Tests for install.py's config stanza.

Run from the repo root with the WeeWX venv python:
    /home/weewx/weewx-venv/bin/python -m pytest tests

The stanza is only ever read by `weectl extension install`, and weecfg merges
it with weeutil.config.conditional_merge, which fills in absent keys only and
never rewrites an existing weewx.conf.  So a wrong value here ships silently
to every fresh install and can never be corrected by an upgrade -- which is
why most of [NWS] is written COMMENTED OUT, leaving nws.py's own fallbacks to
govern.  These tests pin the three things that scheme depends on: which
options stay live, that every commented-out value equals the fallback that
governs, and that the comments survive the merge.
"""

import collections
import importlib
import importlib.util
import io
import os
import re
import sys
import time

from typing import Dict

os.environ['TZ'] = 'America/Los_Angeles'
time.tzset()

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'bin', 'user'))

import configobj
import pytest

import weeutil.config
from weeutil.weeutil import to_bool, to_int
from weewx.engine import StdEngine

from nws import NWS, WEEWX_NWS_VERSION

from test_nws import load_fixture, make_alert, make_alerts_json
from test_nws_service import freshen, make_config, write_forecast_files

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# A commented-out assignment ('#poll_secs = 1800'), never a prose comment,
# which always has a space after the '#'.
COMMENTED_OPTION_RE = re.compile(r'^(\s*)#([\w-]+)\s*=\s*(.+?)\s*$')
SECTION_RE = re.compile(r'^\s*(\[+)([^\]]+)\]+\s*$')

# The two shapes a target weewx.conf can have, because they fail differently.
# conditional_merge transfers a key's comments only when it CREATES the key.
# In a VIRGIN config it creates [DataBindings] and the rest, so a misplaced
# comment block survives -- dedented out of the section it documents.  In a
# REALISTIC one those sections already exist, so the same misplaced block is
# not written at the wrong indent, it is dropped without trace.  Every real
# station is the realistic case; the virgin one is what an indentation check
# can actually see.  Both are merged below.
VIRGIN_WEEWX_CONF = """
[Station]
    location = home
"""

REALISTIC_WEEWX_CONF = """
[Station]
    location = home

[StdArchive]
    archive_interval = 300

[DataBindings]
    [[wx_binding]]
        database = archive_sqlite
        table_name = archive
        manager = weewx.manager.DaySummaryManager
        schema = schemas.wview_extended.schema

[Databases]
    [[archive_sqlite]]
        database_name = weewx.sdb
        database_type = SQLite

[StdReport]
    SKIN_ROOT = skins
    HTML_ROOT = public_html
    [[SeasonsReport]]
        skin = Seasons
        enable = true
"""

def install_module():
    """install.py, loaded as a module.  Loading it needs weecfg.extension
    imported first: that module aliases itself as 'setup' in sys.modules for
    installers written against the pre-5.0 name, which is what install.py's
    own import resolves through."""
    importlib.import_module('weecfg.extension')  # registers the alias
    spec = importlib.util.spec_from_file_location(
        'nws_install', os.path.join(REPO_DIR, 'install.py'))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def installer_config() -> configobj.ConfigObj:
    """install.py's config stanza, whichever form it is written in."""
    return install_module().NWSInstaller()['config']

def commented_options() -> Dict[str, Dict[str, str]]:
    """install.py's commented-out assignments, as {section: {option: value}},
    keyed by the innermost section the option sits in.  Read out of CONFIG as
    TEXT because a commented-out option is by definition absent from the
    parsed object -- any test that walks the parsed stanza silently stops
    covering it."""
    found: Dict[str, Dict[str, str]] = {}
    section = ''
    for line in install_module().CONFIG.splitlines():
        header = SECTION_RE.match(line)
        if header:
            section = header.group(2).strip()
            continue
        option = COMMENTED_OPTION_RE.match(line)
        if option:
            found.setdefault(section, {})[option.group(2)] = option.group(3)
    return found

def default_service(tmp_path) -> NWS:
    """An NWS service built from a weewx.conf that sets NOTHING the installer
    now writes commented out, so every value in its Configuration is the
    fallback nws.py applies when the key is absent."""
    read_dir = str(tmp_path / 'forecasts')
    os.mkdir(read_dir)
    write_forecast_files(
        read_dir,
        one_hour    = freshen(load_fixture('one_hour.json')),
        twelve_hour = freshen(load_fixture('twelve_hour.json')),
        alerts      = make_alerts_json(make_alert()))
    config = make_config(str(tmp_path / 'nws.sdb'), read_dir)
    return NWS(StdEngine(config), config)


class TestInstallerConfig:
    """install.py's [NWS], [DataBindings], [Databases] and [StdReport]
    defaults, and the comments that ride with them."""

    def test_version_is_in_lockstep(self):
        """The version lives in three places and they must agree: install.py's
        version=, WEEWX_NWS_VERSION in nws.py, and [Extras] version in
        skins/nws/skin.conf.  A release that bumps two of the three ships a
        skin reporting the wrong version, which nothing else would catch."""
        installer_version = install_module().NWSInstaller()['version']
        skin = configobj.ConfigObj(
            os.path.join(REPO_DIR, 'skins', 'nws', 'skin.conf'),
            encoding='utf-8', file_error=True)
        assert installer_version == WEEWX_NWS_VERSION
        assert skin['Extras']['version'] == WEEWX_NWS_VERSION

    def test_html_root_is_a_bare_subdirectory(self):
        """HTML_ROOT must NOT carry a public_html prefix.  weecfg prepends the
        installation's own StdReport HTML_ROOT at install time
        (ExtensionEngine.install_config -> prepend_path), so 'nws' becomes
        public_html/nws -- or whatever that installation uses.  Writing
        'public_html/nws' here would land the report in
        public_html/public_html/nws."""
        report = installer_config()['StdReport']['NWSReport']
        assert report['HTML_ROOT'] == 'nws'
        assert report['skin'] == 'nws'

    def test_sample_report_is_enabled_by_default(self):
        # The sample report is meant to render without the user turning it on.
        report = installer_config()['StdReport']['NWSReport']
        assert to_bool(report['enable'])

    def test_live_options_are_the_ones_with_no_default(self):
        """Two keys stay live in [NWS].  User-Agent is a placeholder the user
        must replace, so nws.py cannot supply it.  data_binding is live
        because that is what a data binding is across the whole of WeeWX --
        [StdArchive] and [StdReport] carry theirs live, and so does
        weewx-xtide, the sibling extension built to this same shape; it names
        the database this extension writes to, and a station reading its
        weewx.conf should see that named rather than have to know a default.
        Everything else has a real fallback and is commented out, so it is
        absent from the parsed stanza -- which is what lets nws.py's own
        default govern, including a better one a later release might bring.

        The live keys are pinned as a COMPLETE SET, not by checking that
        today's commented-out options are absent.  A named-absence check only
        guards the options that already exist: a release that adds a new one
        live -- 'retries = 3' in the stanza against a get('retries', 5) in the
        code -- would be the very drift this scheme exists to prevent, and
        would sail past a test that only looks for poll_secs and timeout_secs.
        Adding a live key here has to be a deliberate act that edits this
        test.

        User-Agent is also last in its section, and that is load-bearing:
        ConfigObj attaches a comment block to the NEXT key, so the whole
        [NWS] block -- prose and commented-out options alike -- rides on it.

        The other three sections are wholly live: [DataBindings] and
        [Databases] are structure rather than settings, and weectl needs
        HTML_ROOT/enable/skin to make the report run."""
        config = installer_config()
        nws_section = config['NWS']
        assert nws_section.scalars == ['data_binding', 'User-Agent']
        assert nws_section.sections == []
        assert nws_section['data_binding'] == 'nws_binding'
        assert nws_section['User-Agent'] == '(my-weather-site.com, me@my-weather-site.com)'

        assert config['DataBindings'].sections == ['nws_binding']
        assert sorted(config['DataBindings']['nws_binding'].scalars) == [
            'database', 'manager', 'schema', 'table_name']
        assert config['Databases'].sections == ['nws_sqlite']
        assert sorted(config['Databases']['nws_sqlite'].scalars) == [
            'database_name', 'driver']
        assert config['StdReport'].sections == ['NWSReport']
        assert sorted(config['StdReport']['NWSReport'].scalars) == [
            'HTML_ROOT', 'enable', 'skin']

    def test_placeholder_user_agent_is_marked_as_a_placeholder(self):
        """User-Agent carries a PLACEHOLDER -- comment.  Three kinds of line
        share the stanza and the user has to tell them apart at a glance: a
        commented-out assignment (the value nws.py supplies, uncomment only to
        pin it), a live setting that means what it says (enable), and a live
        setting whose value is deliberately fake.  Only the last kind breaks
        the extension if it is ignored -- NWS's API rules ask that requests
        identify who is making them -- and it is the one that looks most like
        a working setting.  The marker is what the comment leads with rather
        than something buried at the end of the prose.  weewx-purple and
        weewx-celestial mark their placeholders the same way."""
        comment = ' '.join(installer_config()['NWS'].comments['User-Agent'])
        assert 'PLACEHOLDER' in comment

    def test_commented_options_match_the_code_defaults(self, tmp_path):
        """The drift guard.  A commented-out option shows the user the value
        that will actually be used, so it must equal the fallback nws.py
        applies when the key is absent -- and nothing but nws.py governs it
        once the installer stops writing it live.

        WHICH SIDE MOVES WHEN THIS FAILS IS A JUDGEMENT, NOT A FORMALITY.  Do
        not make it pass by editing the commented-out assignment to match the
        code.  While the option was written live, the installer's value is
        what every fresh install has actually been running and the code's
        fallback was never reached, so editing the assignment down to the
        fallback turns the test green while silently changing what new
        stations get.  Moving the fallback to match the installer is usually
        what preserves behavior; moving the assignment is a deliberate change
        of default and belongs in changes.txt.  Existing stations are
        unaffected either way -- their weewx.conf already carries the value
        the installer wrote, and an upgrade never rewrites it.

        weewx-purple caught two instances of this drift in a week, so the
        agreement here is not to be taken on faith."""
        options = dict(commented_options()['NWS'])
        cfg = default_service(tmp_path).cfg
        assert to_int(options.pop('days_to_keep')) == cfg.days_to_keep
        assert to_int(options.pop('poll_secs')) == cfg.poll_secs
        assert to_int(options.pop('alert_poll_secs')) == cfg.alert_poll_secs
        assert to_int(options.pop('retry_wait_secs')) == cfg.retry_wait_secs
        assert to_int(options.pop('alert_retry_wait_secs')) == cfg.alert_retry_wait_secs
        assert to_int(options.pop('timeout_secs')) == cfg.timeout_secs
        # Anything else commented out is a default nothing checks.
        assert options == {}
        # And nothing outside [NWS] is commented out at all.
        assert list(commented_options()) == ['NWS']

    def test_no_comment_rides_on_a_key_weectl_rewrites(self):
        """weectl does not merge this stanza verbatim.  ExtensionEngine's
        _inject_config rewrites [Databases] on the way in: for an extension
        that names a driver rather than a database_type it pops 'driver' and
        puts 'database_type' in its place (weecfg/extension.py).  A comment
        block attached to 'driver' would go with it -- dropped in the user's
        file, and invisible to the merge guard below, which calls
        conditional_merge directly and so never sees that rewrite.  Today the
        nws_sqlite prose rides on database_name and survives; this keeps it
        that way."""
        database = installer_config()['Databases']['nws_sqlite']
        assert database['driver'] == 'weedb.sqlite'
        assert database.comments.get('driver', []) == []
        assert database.comments['database_name'] != []

    @pytest.mark.parametrize('target', [VIRGIN_WEEWX_CONF, REALISTIC_WEEWX_CONF],
                             ids=['virgin', 'realistic'])
    def test_merged_stanza_keeps_its_comments(self, target):
        """The placement rule, checked through the real merge, both ways.

        ConfigObj attaches a comment block to the NEXT key and writes it at
        THAT key's indent, so a block whose next key is shallower is dedented
        out of the section it documents -- which is what the indentation check
        below measures, and it can only ever see it in a config where the
        following section had to be created.  In a real weewx.conf
        [DataBindings] already exists, so conditional_merge never creates it,
        never transfers its comments, and the same misplaced block is dropped
        outright.  No indentation check can catch that: there is no line left
        to measure.  Comparing the comment lines that come out against the
        ones that went in is what catches it, and it is the failure that
        actually reaches the field.  Hence User-Agent last in [NWS]."""
        merged = configobj.ConfigObj(io.StringIO(target), encoding='utf-8')
        weeutil.config.conditional_merge(merged, installer_config())
        out = io.BytesIO()
        merged.write(out)
        rendered = out.getvalue().decode('utf-8').splitlines()

        # Nothing dropped and nothing duplicated: the merged config carries
        # exactly the comment lines CONFIG does (neither target has any of its
        # own).
        def comment_lines(lines):
            return collections.Counter(
                line.strip() for line in lines if line.strip().startswith('#'))
        assert comment_lines(rendered) == comment_lines(
            install_module().CONFIG.splitlines())

        # And every comment line landed at the indent of the section it
        # belongs to, so it reads as documenting that section and not its
        # parent.
        depth = 0
        seen = 0
        for line in rendered:
            header = SECTION_RE.match(line)
            if header:
                depth = len(header.group(1))
                continue
            if not line.strip().startswith('#'):
                continue
            assert len(line) - len(line.lstrip()) == 4 * depth, (
                'wrong indentation, so it merged outside its section: %r' % line)
            if COMMENTED_OPTION_RE.match(line):
                seen += 1
        # days_to_keep, poll_secs, alert_poll_secs, retry_wait_secs,
        # alert_retry_wait_secs and timeout_secs.
        assert seen == 6
