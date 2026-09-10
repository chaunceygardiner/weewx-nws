"""
test_american_english.py

Copyright (C)2022-2026 by John A Kline (john@johnkline.com)
Distributed under the terms of the GNU Public License (GPLv3)

American English, in every byte this repository tracks.

The tests below are SHARED, not written here: the same block runs in the
sibling extensions, and a fix found in any one of them is pasted into the
rest rather than rediscovered.  Only the five constants marked PER-REPO
are this repo's to set.  Read the comments in the block before changing
anything in it -- every guard in there was paid for by a defect somewhere.
"""

import os
import re
import subprocess
import unittest

TEST_DIR = os.path.dirname(os.path.abspath(__file__))


class TestAmericanEnglish(unittest.TestCase):

    REPO_ROOT = os.path.dirname(TEST_DIR)

    # ------------------------------------------------------------------
    # American English
    # ------------------------------------------------------------------
    #
    # A ratchet.  Prose drifts one word at a time and the drift is
    # invisible in review, because every one of these spellings is
    # correct somewhere -- just not here.  This is a sweep of every
    # tracked text file, so it covers comments, docstrings, templates,
    # changes.txt, the manual and the shipped skin, which is where all
    # twenty-two of the words fixed on 2026-09-08 were living.
    #
    # THIS BLOCK IS SHARED VERBATIM with weewx-loopdata, weewx-celestial,
    # weewx-skyfield and one private sibling.  Naming all four the same
    # way keeps this sentence identical in every copy, and names no
    # private repository in a public one.  The word lists, the guards and
    # the oracle are byte for byte the same, so a fix made in one is
    # pasted into the rest rather than rediscovered there.  Four
    # independent versions of this test is what the sharing exists to
    # prevent.
    #
    # EXACTLY FIVE THINGS ARE PER-REPO, and they are marked PER-REPO where
    # they are defined: NOT_OURS, QUOTED_PROPER_NOUNS, LANG_DIR,
    # LANG_IN_ENGLISH and A_TRACKED_FILE.  An earlier version of this
    # comment said two, having forgotten that the sanity check names a
    # file; whoever pasted it next met a failure that blamed their working
    # directory.  If you add a sixth, say so HERE -- the next person
    # should read what differs, not discover it.
    #
    # IN A PYTEST-ONLY SUITE, host it as
    # `class TestAmericanEnglish(unittest.TestCase)` with `REPO_ROOT` as a
    # class attribute.  pytest collects a TestCase without complaint and
    # every method body below stays byte-identical, where translating the
    # assertions to bare asserts would end the sharing at the first edit.
    #
    # THE '*' IN EVERY ENTRY IS STRIPPED BEFORE USE.  It is there so that
    # no British spelling appears literally in this file, which is what
    # lets the sweep cover this file too -- no self-exclusion, and so no
    # blind spot in the eleven thousand lines of tests around it.  A word
    # added without its '*' fails the sweep on its own line, which is the
    # right way round to get that wrong.
    #
    # Add a word here when one turns up, rather than fixing a file
    # quietly.  If a British spelling is ever legitimate -- a quoted
    # product name, a proper noun -- this is the place to record it.
    BRITISH_SPELLINGS = (
        'label*led', 'unlabel*led', 'label*ling', 'colo*ur', 'colo*urs',
        'colo*ured', 'colo*uring', 'behavio*ur', 'behavio*urs', 'hono*ur',
        'cent*re', 'cent*res', 'cent*red', 'gr*ey', 'gr*eyer', 'gr*eyish',
        'judge*ment', 'judge*ments', 'age*ing', 'whil*st', 'among*st',
        'analog*ue', 'orientat*ed', 'defen*ce', 'licen*ce', 'program*me',
        'catalog*ue', 'cancel*led', 'model*led', 'travel*ling',
        'signal*ling', 'met*re', 'met*res', 'fib*re', 'scept*ic',
        'artef*act', 'enr*ol', 'fulf*il', 'inst*il', 'skil*ful',
        'favo*ur', 'flavo*ur', 'neighbo*ur', 'labo*ur', 'vapo*ur',
        'armo*ur', 'rumo*ur', 'savo*ur', 'harbo*ur', 'humo*ur', 'odo*ur',
        'valo*ur', 'cando*ur', 'demeano*ur', 'endeavo*ur', 'splendo*ur',
        'savio*ur', 'clamo*ur', 'parlo*ur',
        'theat*re', 'lit*re', 'calib*re', 'somb*re', 'spect*re', 'lust*re',
        'manoeuv*re', 'offen*ce', 'preten*ce', 'practi*se', 'practi*sing',
        'cent*ring',
        'cancel*ling', 'model*ling', 'travel*led', 'signal*led',
        'level*led', 'level*ling', 'total*led', 'fuel*led', 'dial*led',
        'dial*ling', 'equal*led', 'channel*led', 'marvel*lous',
        'mo*uld', 'plo*ugh', 'dra*ught', 'lear*nt',
        # The -y*se verbs and the four -i*se verbs whose AMERICAN form is
        # itself the stem.  These CANNOT become stems below: analy*sis,
        # emphas*is, Polar*is and Borealis are all correct, and a stem
        # would flag every one of them.  Because they are entered as
        # whole words, each inflection has to be listed -- which is the
        # very cost the stems exist to avoid, so keep this list short.
        'analy*se', 'analy*sed', 'analy*sing',
        'paraly*se', 'paraly*sed', 'paraly*sing',
        'cataly*se', 'cataly*sed', 'cataly*sing',
        'reali*se', 'reali*sed', 'reali*sing', 'reali*sation',
        'emphasi*se', 'emphasi*sed', 'emphasi*sing',
        'polari*se', 'polari*sed', 'polari*sing', 'polari*sation',
        # DELIBERATELY ABSENT: glamo*ur, which is the ordinary American
        # spelling as well, and dialog*ue, which American style accepts
        # alongside dialog.  A word only belongs here if the American
        # form is the ONLY correct one.
    )

    # The -i*se verbs, as STEMS ENDING IN `is` rather than as words.
    #
    # This is the whole reason the list above is not simply longer.  The
    # four inflections do not contain one another: token*ise does NOT
    # match token*ising, because the letter after `is` is an i and not an
    # e, and neither of them matches token*isation.  A list of -i*se
    # WORDS therefore sees roughly one inflection in three -- measured on
    # this tree, twenty of twenty -ing and -ation forms were invisible,
    # and a recogn*ising in docs/troubleshooting.md had been sitting
    # through a green suite because of it.  One stem catches all four.
    #
    # Every stem is guarded (?![mt]), uniformly rather than by naming
    # exceptions, because each one runs into the -ism and -ist nouns:
    # unguarded, these flag characteristics, realistic, optimistic,
    # specialist, finalist, apologist, organism and criticism, all
    # correct American.  Nothing is lost, because no British-only
    # spelling puts an m or a t after `is`.
    #
    # The guard is a constant rather than a value inlined in the builder
    # so that it can be taken away and the loss measured.  It is already
    # pinned: emptying it fails test_british_spelling_pattern, because
    # MUST_SPARE carries characteristics, organism, specialist and the
    # rest of the -ism and -ist nouns it exists to spare.
    IS_STEM_GUARD = 'mt'

    BRITISH_IS_STEMS = (
        'util*is', 'custom*is', 'optim*is', 'normal*is', 'initial*is',
        'serial*is', 'standard*is', 'synchron*is', 'visual*is',
        'special*is', 'priorit*is', 'minim*is', 'maxim*is', 'apolog*is',
        'critic*is', 'token*is', 'author*is', 'categor*is', 'character*is',
        'familiar*is', 'final*is', 'general*is', 'item*is', 'memor*is',
        'modern*is', 'random*is', 'stabil*is', 'symbol*is', 'sanit*is',
        'summar*is', 'recogn*is', 'organ*is', 'local*is',
    )

    # Letters that must NOT follow a spelling, where it is a prefix of a
    # correct American word.  Without these, substring matching cries
    # wolf on fulfill, instill, enrolled, greyhound, programmer and
    # PROGRAMMED -- the last of which is ordinary American and cost a
    # code review to find, because a single-letter guard for programmer
    # let it through.  The -se guards spare analyses, paralyses and
    # catalyses, the ordinary American plurals of analysis, paralysis
    # and catalysis.  (The cost is that the British VERB analyses goes
    # unseen; a false alarm on correct prose would be worse, and
    # analy*sed is still caught.)
    PREFIX_OF_AN_AMERICAN_WORD = {
        'fulf*il': 'l', 'inst*il': 'l', 'enr*ol': 'l', 'gr*ey': 'h',
        'program*me': 'rd', 'analy*se': 's', 'paraly*se': 's',
        'cataly*se': 's',
    }

    # Files this repo ships but does not AUTHOR.  The rule is about the
    # bytes we write; someone else's verbatim text is not ours to
    # correct, and "fix the spelling" and "keep it verbatim" cannot both
    # be obeyed.  PER-REPO: this tuple is the one part of the shared
    # block that differs between the four repos.
    #
    # LICENSE is the FSF's text.  It happens to clear the pattern today
    # -- this is a guard against a future revision of it, not a fix for
    # a present failure.
    #
    # The four weewx.conf fixtures are Tom Keffer's WEEWX CONFIGURATION
    # FILE, copied whole so the tests parse what a real station parses.
    # Editing them would be a worse bug than the one it prevents: they
    # would stop matching what WeeWX ships, which is the only reason
    # they exist.  The word in them is WeeWX's own comment on its meter
    # label, offering the British spelling to the reader as a choice --
    # a sentence that cannot survive having its subject corrected.
    # Identifiers from other people's code that this project only
    # QUOTES.  Python's asyncio really does spell it Cancel*ledError, and
    # the British word is a strict PREFIX of that name, so no guard
    # letter can separate them -- the only way is to remove the token
    # from the text before matching.  Shared, not per-repo: it is
    # Python's name, and any repo that mentions asyncio meets it the day
    # it pastes this block.  Stripped before splitlines(), so the
    # whole-file pass and the line pass agree.
    FOREIGN = ('Cancel*ledError',)

    # Phrases in OUR OWN prose that are somebody else's name: a
    # publication title, an organization's English name, a product.
    # NOT_OURS exempts whole files we did not author; this exempts a
    # PHRASE inside a file we did.  A sibling repo needs it for a
    # catalog title and an institute's name that appear in a credit its
    # data license requires verbatim -- Americanizing either would
    # misquote a title or rename an organization, which is a worse fault
    # than the spelling.
    #
    # PER-REPO, like NOT_OURS.  Most repos have none, and an empty tuple
    # is the normal case; this repo quotes no such title.  The mechanism
    # is carried anyway so that it is here the day one is quoted, and so
    # that the copies stay identical -- the same reason the lang
    # constants below are carried by a repo with no translations.
    #
    # Three properties, each of which cost a sibling something to learn:
    # entries carry the '*' like every other list here, because literal
    # ones would be blanked out of THIS file too and it would pass while
    # containing what it forbids; the blanking is scoped to the PHRASE
    # and never the line, since a misspelling typed beside a quoted title
    # is still a mistake and those paragraphs are the ones most likely to
    # be re-edited; and a phrase is replaced by a SPACE rather than
    # removed, so the words on either side cannot run together into a
    # match.  Matching is literal, so a phrase must sit on one line --
    # the staleness assertion at the end of the sweep is what says so
    # when a citation gets reflowed.
    QUOTED_PROPER_NOUNS = (
        # This repo quotes no such title.  An empty tuple is the normal
        # case; the mechanism stays so the rule is here when one arrives.
    )

    # PER-REPO.  A file the sweep can be sure is tracked, so that an
    # empty or wrong listing is reported as such instead of passing as a
    # clean tree.
    A_TRACKED_FILE = 'bin/user/nws.py'

    # PER-REPO.
    NOT_OURS = (
        'LICENSE',
        # Real trimmed NWS responses for gridpoint MTR/92,88 (Palo Alto),
        # in the tree so the suite parses what a real station parses.
        # The forecast prose in them is the National Weather Service's,
        # written by its forecasters; correcting a word would both
        # misquote them and stop the fixtures matching what the API
        # returns, which is the only reason they exist.
        'tests/fixtures/one_hour.json',
        'tests/fixtures/twelve_hour.json',
    )

    # The translations are not English, and an English spelling rule
    # applied to them is simply wrong: fr.conf's French for "they use",
    # and no.conf's and sv.conf's Norwegian and Swedish for
    # "standardizes", all carry the British verb ending and all three
    # are correct in their own language.
    #
    # But only the TRANSLATED half is exempt.  Every lang file opens
    # with an English header this repo wrote -- nineteen to twenty-seven
    # lines of it, explaining where the vocabulary came from and where
    # to send corrections -- and a file-level exemption hid all of it
    # while this test's docstring claimed every tracked byte.  So the
    # sweep runs down to the first [section] and stops there, which is
    # where the translated text starts in all nine files.
    #
    # en.conf is swept whole: it is English, and it is the reference
    # dictionary every other lang file is checked against.  Derived from
    # the PATH rather than listed, so a new translation is exempt the day
    # it lands.  PER-REPO: a repo with no lang directory keeps these
    # constants and the code, so the rule is already in place when one
    # arrives.
    LANG_DIR = 'skins/nws/lang/'
    LANG_IN_ENGLISH = 'skins/nws/lang/en.conf'

    def _british_spelling_re(self):
        """One alternation, matched ANYWHERE in a line.

        Lower case only, and the caller lowers the text to match.  The
        obvious re.IGNORECASE costs 5.4 seconds over this tree against
        0.7 for lowering the text first -- a third of the whole suite,
        and paid again on every mutant, since this test is in the
        spec-only runner and can never kill one.  The entries must
        therefore stay lower case, guard letters included.
        """
        words, bars = self._british_words_and_bars()
        # A guard on the guards: a typo in a PREFIX key would silently
        # stop guarding the word it names, and the false alarm that
        # follows looks like a spelling error in correct prose.
        self.assertEqual(
            sorted(set(bars) - set(words)), [],
            'PREFIX_OF_AN_AMERICAN_WORD names a word in neither list')
        self.assertEqual(
            [entry for entry in self.BRITISH_SPELLINGS + self.BRITISH_IS_STEMS
             if entry.lower() != entry], [],
            'the word lists must be lower case; see _british_spelling_re')
        return re.compile(
            '|'.join(re.escape(word) +
                     ('(?![%s])' % bars[word] if bars.get(word) else '')
                     for word in words))

    def _british_words_and_bars(self):
        """Every spelling to look for, and the letters barred after it."""
        bars = {word.replace('*', ''): letters for word, letters
                in self.PREFIX_OF_AN_AMERICAN_WORD.items()}
        words = [entry.replace('*', '') for entry in self.BRITISH_SPELLINGS]
        for stem in self.BRITISH_IS_STEMS:
            stem = stem.replace('*', '')
            words.append(stem)
            bars[stem] = self.IS_STEM_GUARD
        return words, bars

    # What the pattern must catch, and what it must leave alone.  Same
    # '*' convention as the lists above.
    MUST_FLAG = (
        'colo*ur', 'colo*urs', 'recolo*ur', 'colo*urful', 'behavio*ur',
        'hono*urs', 'neighbo*ur', 'cent*re', 'centimet*re', 'met*res',
        'gr*ey', 'judge*ment', 'label*led', 'cancel*ling', 'travel*led',
        'level*ling', 'program*me', 'program*mes', 'fulf*il', 'inst*il',
        'enr*ol', 'licen*ce', 'defen*ce', 'offen*ce', 'preten*ce',
        'practi*se', 'theat*re', 'lit*re', 'calib*re', 'mo*uld',
        'smo*ulder', 'plo*ugh', 'dra*ught', 'lear*nt', 'artef*act',
        'scept*ical', 'whil*st', 'among*st', 'age*ing', 'analog*ue',
        'catalog*ue', 'orientat*ed', 'local*isation', 'local*ised',
        'scept*icism', 'practi*sing', 'cent*ring',
        # The four inflections of a stem, which is the whole point of
        # BRITISH_IS_STEMS -- delete the stems and the last two of these
        # go unseen while everything else here still passes.
        'token*ise', 'token*ised', 'token*ising', 'token*isation',
        'recogn*ising', 'organ*isation', 'normal*ising',
        'character*ised', 'critic*ising', 'special*isation',
        # The words that had to stay whole because their American form
        # is the stem.
        'analy*sed', 'analy*sing', 'paraly*sed', 'reali*se',
        'reali*sing', 'reali*sation', 'emphasi*sed', 'emphasi*sing',
        'polari*sed', 'polari*sing',
        # An identifier, with no word boundary anywhere near the word.
        'test_colo*urs_arrive',
    )

    MUST_SPARE = (
        # Correct American spellings of the words above.
        'color', 'colors', 'colorful', 'behavior', 'honor', 'honorable',
        'neighbor', 'center', 'centered', 'concentrate', 'centimeter',
        'meters', 'barometer', 'thermometer', 'diameter', 'parameters',
        'gray', 'grayscale', 'judgment', 'labeled', 'canceling',
        'traveled', 'leveling', 'license', 'licensed', 'defense',
        'offense', 'pretense', 'practice', 'theater', 'liter', 'caliber',
        'mold', 'smolder', 'plow', 'draft', 'learned', 'artifact',
        'skeptical', 'skeptic', 'skepticism', 'analog', 'catalog',
        'oriented', 'fiber', 'somber', 'localization', 'localized',
        'practicing', 'centering',
        # The prefix traps, every one of which a naive matcher flags.
        'programmed', 'programmer', 'programming', 'fulfill', 'fulfilled',
        'instill', 'install', 'installer', 'enroll', 'enrolled',
        'enrollment', 'greyhound', 'cancellation', 'skillful',
        # American plurals and nouns that ARE the British verb's stem.
        'analyses', 'analysis', 'paralyses', 'paralysis', 'catalyses',
        'emphasis', 'synthesis', 'hypothesis',
        # Proper nouns.  Every one of these is a star or a constellation
        # this family of extensions names, and Borealis is what a
        # real*is stem flagged in en.conf before it was entered whole.
        'Polaris', 'Corona Borealis', 'Corona Australis',
        # The -ism and -ist nouns the (?![mt]) guard exists for.
        'characteristics', 'realistic', 'optimistic', 'specialist',
        'finalist', 'apologist', 'organism', 'criticism', 'symbolism',
        'modernist', 'journalist', 'scientist', 'utility',
        # American -ize forms, which must never be mistaken for their
        # British cousins.
        'recognized', 'organized', 'normalizing', 'tokenization',
        'initialized', 'summarized', 'authorized', 'categorized',
        # Verbs that end in -ise in AMERICAN English.
        'advertise', 'exercise', 'surprise', 'compromise', 'supervise',
        'franchise', 'enterprise', 'comprise', 'precise', 'concise',
        'otherwise', 'revise', 'devise', 'improvise', 'disguise',
        'promise', 'premise', 'wise',
        # Ordinary words that happen to contain a fragment of one.
        'should', 'shoulder', 'could', 'would', 'through', 'thorough',
        'drought', 'learning', 'aging', 'managing', 'messaging',
    )

    def test_british_spelling_pattern(self):
        """The oracle, and it is not optional.

        A PASSING SWEEP PROVES NOTHING ABOUT THE WORD LIST.  An empty
        list passes.  So does one whose guards are so wide they spare
        the words they were meant to catch, and so does one that misses
        two inflections in four.  Both of those were real here: the
        sweep, a green suite and eleven hand-run sabotage cases all
        passed while `programmed` was being flagged as British and every
        -i*sing and -i*sation form was invisible.  This test is what
        sees that class, by asserting on the compiled pattern directly
        rather than on the tree.

        Add to MUST_SPARE whenever a guard is widened, and to MUST_FLAG
        whenever a word or a stem is added.
        """
        want = self._british_spelling_re()
        missed = [entry.replace('*', '') for entry in self.MUST_FLAG
                  if not want.search(entry.replace('*', '').lower())]
        self.assertEqual(missed, [],
                         'the pattern does not catch these British spellings')
        flagged = []
        for word in self.MUST_SPARE:
            found = want.search(word.lower())
            if found is not None:
                flagged.append('%s (matched %r)' % (word, found.group(0)))
        self.assertEqual(flagged, [],
                         'the pattern flags correct American English')

    def test_every_entry_can_still_be_reached(self):
        """A guard can retire the word it was meant to protect.

        Widen one -- 'gr*ey': 'h' to 'hs', say, to spare some new word --
        and gr*eys stops being caught while every other test here stays
        green, because MUST_FLAG holds the bare word and a bare word
        always matches: the lookahead sits at the end of the string with
        nothing to reject.  Seventy-nine of the entries are not in
        MUST_FLAG at all, so most of the list can be retired this way
        without anything noticing.

        Two assertions close it.  The first appends a letter the guard
        PERMITS, so an entry made unreachable is seen.  The second is the
        one that matters: every letter barred by a hand-written guard
        must be JUSTIFIED by a word in MUST_SPARE that needs it -- which
        is what widening a guard legitimately means.  Widen one without
        adding the American word that forced it, and this fails.

        The uniform stem guard is deliberately exempt from the second
        rule: it is one policy justified once, by the -ism and -ist nouns
        in MUST_SPARE, not a per-word judgment, and no British-only
        spelling puts an m or a t after `is`.
        """
        want = self._british_spelling_re()
        words, bars = self._british_words_and_bars()
        spare = [word.lower() for word in self.MUST_SPARE]
        stems = {stem.replace('*', '') for stem in self.BRITISH_IS_STEMS}
        unreachable, unjustified = [], []
        for word in words:
            barred = bars.get(word, '')
            allowed = next((c for c in 'abcdefghijklmnopqrstuvwxyz'
                            if c not in barred), None)
            self.assertIsNotNone(
                allowed, '%s bars every letter there is' % word)
            if not want.search(word + allowed):
                unreachable.append(word + allowed)
            if word in stems:
                continue
            for letter in barred:
                if not any(word + letter in word_spared for word_spared in spare):
                    unjustified.append('%s(?!%s)' % (word, letter))
        self.assertEqual(unreachable, [],
                         'these spellings can no longer be matched at all')
        self.assertEqual(
            unjustified, [],
            'a guard bars a letter with no MUST_SPARE word needing it; '
            'add the American word that forced the guard, or narrow it')

    def test_no_british_spellings(self):
        """American English, in every byte this repo tracks.

        MATCHING IS BY SUBSTRING, NOT BY WHOLE WORD.  A word-boundary
        search has two blind spots, and a sibling repo fell into both.
        It misses a spelling inside an IDENTIFIER, because '_' is
        itself a word character and the boundary never appears -- a
        test named test_colo*urs_arrive went unseen that way.  And it
        misses a spelling inside a longer WORD, because to such a
        search hono*urs is simply a different word from hono*ur.  Hence
        no boundaries; the handful of British spellings that are
        prefixes of correct American words carry an explicit guard
        instead of relying on \\b to do it by accident.

        Sabotage it by putting one British spelling in any tracked text
        file, including this one.
        """
        listed = subprocess.run(['git', 'ls-files'], cwd=self.REPO_ROOT,
                                capture_output=True, text=True)
        self.assertEqual(listed.returncode, 0, listed.stderr)
        names = [name for name in listed.stdout.split('\n') if name]
        self.assertIn(self.A_TRACKED_FILE, names,
                      'git ls-files listed nothing useful; is REPO_ROOT right?')
        # An exemption for a file that no longer exists is not a
        # harmless leftover.  Rename a fixture and its NOT_OURS entry
        # stops matching, so WeeWX's text is swept as though it were
        # ours; rename the skin and every translation is.  Either way
        # the failure that follows is a pile of correct prose, and the
        # obvious reading of it is that the sweep is broken.  Say which
        # exemption went stale instead.
        for name in self.NOT_OURS:
            self.assertIn(name, names,
                          'NOT_OURS names a file git does not track')
        translations = [n for n in names if n.startswith(self.LANG_DIR)
                        and n != self.LANG_IN_ENGLISH]
        # Only where a lang directory actually exists.  A repo with no
        # translations still carries the constants and the line-level
        # exemption below, dormant, so the rule is already in place the
        # day one lands -- and an unconditional assertion here would
        # mean such a repo could not paste this block at all.
        if any(name.startswith(self.LANG_DIR) for name in names):
            self.assertIn(self.LANG_IN_ENGLISH, names,
                          'the reference lang file moved; LANG_DIR is stale')
            self.assertTrue(translations,
                            'no translations under LANG_DIR; the path is stale')
        want = self._british_spelling_re()
        hits = []
        seen_quoted = set()
        for name in names:
            if name in self.NOT_OURS:
                continue
            try:
                with open(os.path.join(self.REPO_ROOT, name), 'rb') as f:
                    blob = f.read()
            except OSError:
                # Tracked but not on disk: a deleted file, a half-done
                # rename, or a path git has quoted.  There is nothing to
                # sweep, and erroring the whole run over it would read
                # as the sweep being broken.
                continue
            if b'\x00' in blob:
                continue                # an image, not text
            # errors='replace' rather than a skip on failure: a file
            # that will not decode cleanly is still swept, so one stray
            # byte cannot hide the rest of it.
            text = blob.decode('utf-8', 'replace')
            for token in self.FOREIGN:
                text = text.replace(token.replace('*', ''), '')
            for phrase in self.QUOTED_PROPER_NOUNS:
                phrase = phrase.replace('*', '')
                if phrase in text:
                    seen_quoted.add(phrase)
                    text = text.replace(phrase, ' ')
            lines = text.splitlines()
            if name in translations:
                # The English header only, down to the first [section].
                cut = next((i for i, line in enumerate(lines)
                            if line.lstrip().startswith('[')), None)
                self.assertIsNotNone(
                    cut, '%s has no [section]; the header cannot be found, '
                         'and sweeping it whole would flag its translation'
                         % name)
                lines = lines[:cut]
            # Whole file first, line by line only when that hits, so the
            # line numbers cost nothing on the files that are clean --
            # which is all of them, every run but the one that matters.
            if want.search('\n'.join(lines).lower()) is None:
                continue
            for number, line in enumerate(lines, 1):
                found = want.search(line.lower())
                if found is not None:
                    hits.append('%s:%d: %s' % (name, number, line.strip()))
        self.assertEqual(
            hits, [],
            'British spellings found; this project writes American English:\n'
            + '\n'.join(hits))
        self.assertEqual(
            sorted(phrase.replace('*', '') for phrase in
                   self.QUOTED_PROPER_NOUNS
                   if phrase.replace('*', '') not in seen_quoted), [],
            'QUOTED_PROPER_NOUNS names a phrase that is not in the tree on '
            'one line; reword the entry or reflow the prose')
