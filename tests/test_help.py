# SPDX-License-Identifier: GPL-3.0-or-later
"""The help output must stay compact and list every option exactly once."""

import re

import pytest

from trackfetch.cli import build_parser


@pytest.fixture
def parser():
    return build_parser()


@pytest.fixture
def help_text(parser):
    return parser.format_help()


def option_strings(parser):
    """Return every option string the parser accepts, e.g. ``--color``."""
    names = []

    for action in parser._actions:
        names.extend(action.option_strings)

    return names


class TestHelpOutput:
    def test_usage_line_is_short(self, help_text):
        first = help_text.splitlines()[0]

        assert first == "usage: trackfetch [OPTIONS] [INPUT ...]"

    def test_usage_does_not_expand_options(self, help_text):
        usage = help_text.splitlines()[0]

        for flag in ("--color", "--format", "--lyrics", "--cache"):
            assert flag not in usage

        assert "[INPUT ...]" in usage

    def test_manual_options_block_is_gone(self, help_text):
        assert "Options:" not in help_text

    def test_each_option_appears_in_exactly_one_line(self, help_text):
        parser = build_parser()

        for action in parser._actions:
            for flag in action.option_strings:
                lines = [
                    line
                    for line in help_text.splitlines()
                    if line.lstrip().startswith("-")
                    and re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", line)
                ]

                assert len(lines) == 1, f"{flag} appears in {len(lines)} lines: {lines}"

    def test_no_duplicate_option_strings_in_parser(self):
        names = option_strings(build_parser())

        assert len(names) == len(set(names))

    def test_config_lookup_paragraph_appears_once(self, help_text):
        assert help_text.count("$TRACKFETCH_CONFIG") == 1

    def test_defaults_are_visible(self, help_text):
        assert "(default: mp3)" in help_text
        assert "(default: 1.0)" in help_text
        assert "(default: auto)" in help_text or "auto (default)" in help_text
        assert "(default: cassette)" in help_text or "cassette (default)" in help_text
        assert "metadata-cache.json" in help_text

    def test_every_positional_and_option_has_help(self, parser):
        for action in parser._actions:
            assert action.help, f"{action.dest} has no help text"

    def test_all_formats_are_advertised(self, help_text):
        assert "{mp3,m4a,opus}" in help_text

    def test_lyrics_and_cache_are_documented(self, help_text):
        assert "USLT" in help_text
        assert "©lyr" in help_text
        assert "LYRICS" in help_text
        assert "metadata-cache.json" in help_text
