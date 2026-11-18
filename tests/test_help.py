# SPDX-License-Identifier: GPL-3.0-or-later
"""The help output must stay compact, aligned and color-independent."""

import re

import pytest

from trackfetch import colors
from trackfetch.cli import build_parser
from trackfetch.helpfmt import HELP_POSITION, strip_ansi

WIDTHS = (80, 100, 140)


def render(parser, width):
    factory = parser.formatter_class
    parser.formatter_class = lambda prog: factory(prog=prog, width=width)

    try:
        return parser.format_help()

    finally:
        parser.formatter_class = factory


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


def all_actions(parser):
    """Walk the parser and every argument group it owns."""
    yield from parser._actions

    for group in parser._action_groups:
        yield from group._group_actions


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
        options = help_text.split("\nConfig:\n", 1)[0]

        for action in parser._actions:
            for flag in action.option_strings:
                lines = [
                    line
                    for line in options.splitlines()
                    if line.lstrip().startswith("-")
                    and re.search(
                        rf"^  (?:\S+,\s+)?{re.escape(flag)}(?=[ ,])",
                        line,
                    )
                ]

                assert len(lines) == 1, f"{flag} appears in {len(lines)} lines: {lines}"

    def test_each_flag_appears_exactly_once(self, help_text):
        """Every option string is defined exactly once.

        Only definition rows count. Help text may mention a flag as an
        example (``--provider-opt``) and Examples deliberately use flags.
        """
        parser = build_parser()
        options = help_text.split("\nConfig:\n", 1)[0]
        headers = []

        for line in options.splitlines():
            if not line.startswith("  -"):
                continue

            match = re.match(r"^  (\S.*?)( {2,}|$)", line)

            if match:
                headers.append(match.group(1))

        for action in parser._actions:
            for flag in action.option_strings:
                occurrences = sum(
                    1
                    for header in headers
                    if re.search(
                        rf"(?<![\w-]){re.escape(flag)}(?![\w-])",
                        header,
                    )
                )

                assert occurrences == 1, (
                    f"{flag} is defined {occurrences} times"
                )

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
        for action in all_actions(parser):
            assert action.help, f"{action.dest} has no help text"

    def test_all_formats_are_advertised(self, help_text):
        assert "{mp3,m4a,opus}" in help_text

    def test_lyrics_and_cache_are_documented(self, help_text):
        assert "USLT" in help_text
        assert "©lyr" in help_text
        assert "LYRICS" in help_text
        assert "metadata-cache.json" in help_text


class TestGroups:
    def titles(self, parser):
        return [
            group.title
            for group in parser._action_groups
            if group.title not in ("positional arguments", "options")
        ]

    def test_named_groups_exist(self, parser):
        assert self.titles(parser) == [
            "Input",
            "Output",
            "Metadata",
            "Behavior",
            "Appearance",
        ]

    def test_cache_is_in_behavior(self, parser):
        group = next(g for g in parser._action_groups if g.title == "Behavior")
        dests = {action.dest for action in group._group_actions}

        assert {"cache_enabled", "lyrics_enabled", "delay", "no_logs"} <= dests

    def test_help_and_config_are_in_behavior(self, parser):
        group = next(g for g in parser._action_groups if g.title == "Behavior")
        dests = {action.dest for action in group._group_actions}

        assert {"help", "config"} <= dests

    def test_no_single_flag_help_group(self, parser):
        assert "Help" not in self.titles(parser)

    def test_metadata_flags_are_grouped(self, parser):
        group = next(g for g in parser._action_groups if g.title == "Metadata")
        dests = {action.dest for action in group._group_actions}

        assert {
            "metadata_sources",
            "disable_sources",
            "provider_opt",
            "match_threshold",
            "title_threshold",
            "list_sources",
            "spotify_client_id",
            "spotify_client_secret",
        } == dests

    def test_appearance_flags_are_grouped(self, parser):
        group = next(g for g in parser._action_groups if g.title == "Appearance")
        dests = {action.dest for action in group._group_actions}

        assert {"color", "color_theme", "themes_file"} == dests

    def test_section_headings_end_with_colon(self, help_text):
        for title in ("Input:", "Output:", "Metadata:", "Behavior:"):
            assert f"\n{title}\n" in help_text

        assert "\nAppearance:\n" in help_text


class TestAlignment:
    @pytest.mark.parametrize("width", WIDTHS)
    def test_help_column_is_fixed(self, parser, width):
        text = render(parser, width)

        for line in text.splitlines():
            stripped = line.lstrip()

            if not stripped.startswith("-") or line.startswith(" " * 4):
                continue

            # Either the whole flag line fits the column, or nothing follows.
            assert len(line) <= width
            assert line[2:HELP_POSITION].strip() or len(line.strip()) <= HELP_POSITION

    @pytest.mark.parametrize("width", WIDTHS)
    def test_descriptions_start_at_the_same_column(self, parser, width):
        text = render(parser, width)
        starts = set()

        for line in text.splitlines():
            if not line.startswith("  -"):
                continue

            match = re.match(r"^  (\S.*?)( {2,})(\S.*)$", line)

            if not match:
                # A flag too long for the column; its help is on the next row.
                continue

            header, padding, _help = match.groups()
            starts.add(2 + len(header) + len(padding))

        assert starts == {HELP_POSITION}

    @pytest.mark.parametrize("width", WIDTHS)
    def test_long_flags_wrap_without_blank_line(self, parser, width):
        text = render(parser, width)
        lines = text.splitlines()

        assert "  --track ARTIST - TITLE [ARTIST - TITLE ...]" in lines

        index = lines.index("  --track ARTIST - TITLE [ARTIST - TITLE ...]")
        following = lines[index + 1]

        assert following.startswith(" " * HELP_POSITION)
        assert "Track to download inline" in following
        assert lines[index + 1].strip()

    @pytest.mark.parametrize("width", WIDTHS)
    def test_sections_are_separated_by_one_blank_line(self, parser, width):
        text = render(parser, width)
        lines = text.splitlines()

        assert lines[0].startswith("usage:")
        assert lines[1] == ""
        assert lines[2].startswith("Download music")
        assert lines[3] == ""

        for title in (
            "Input:",
            "Output:",
            "Metadata:",
            "Behavior:",
            "Appearance:",
            "Config:",
            "Examples:",
        ):
            index = lines.index(title)

            assert index > 0
            assert lines[index - 1] == "", f"{title} needs a blank line before it"
            assert lines[index + 1] != "", f"{title} needs content"

    def test_epilog_has_config_list_and_priority(self, help_text):
        assert "\nConfig:\n" in help_text
        assert help_text.count("trackfetch.ini") >= 2

        config = help_text.split("Config:\n", 1)[1]

        for path in (
            "--config PATH",
            "$TRACKFETCH_CONFIG",
            "./trackfetch.ini",
            "$XDG_CONFIG_HOME/trackfetch/trackfetch.ini",
            "~/.config/trackfetch/trackfetch.ini",
            "~/.trackfetch.ini",
        ):
            assert path in config

        assert "A flag wins over the config file" in config

    def test_epilog_has_examples(self, help_text):
        assert "\nExamples:\n" in help_text
        examples = help_text.split("Examples:\n", 1)[1]

        assert examples.count("trackfetch ") >= 3


class TestColorStability:
    @pytest.mark.parametrize("width", WIDTHS)
    def test_cli_help_colors_strip_to_plain(self, width):
        """-h --color always strips to exactly -h --color never."""
        import os
        import subprocess
        import sys

        env = dict(
            os.environ,
            COLUMNS=str(width),
            COLUMNS_WIDTH=str(width),
            COLORTERM="truecolor",
        )

        def run(mode):
            return subprocess.run(
                [sys.executable, "-m", "trackfetch", "-h", "--color", mode],
                capture_output=True,
                text=True,
                env=env,
                check=True,
            ).stdout

        plain = run("never")
        colored = run("always")

        assert "\x1b[" not in plain
        assert "\x1b[" in colored
        assert strip_ansi(colored) == plain

    @pytest.mark.parametrize("width", WIDTHS)
    def test_always_strips_to_never(self, parser, width, monkeypatch):
        monkeypatch.setenv("COLORTERM", "truecolor")

        colors.set_color_mode("never")
        plain = render(parser, width)

        colors.set_color_mode("always")
        colored = render(parser, width)

        assert "\x1b[" not in plain
        assert "\x1b[" in colored
        assert strip_ansi(colored) == plain

    @pytest.mark.parametrize("width", WIDTHS)
    def test_alignment_ignores_ansi(self, parser, width, monkeypatch):
        monkeypatch.setenv("COLORTERM", "truecolor")
        colors.set_color_mode("never")
        plain = render(parser, width)

        colors.set_color_mode("always")

        try:
            colored = render(parser, width)

            assert strip_ansi(colored) == plain

            # ANSI never pushes a visible line past the terminal width.
            for line in colored.splitlines():
                assert len(strip_ansi(line)) <= width or line.startswith("  A flag")

        finally:
            colors.set_color_mode("never")

    def test_never_mode_has_no_ansi(self, parser, monkeypatch):
        colors.set_color_mode("never")

        assert "\x1b[" not in render(parser, 100)

    def test_auto_on_pipe_has_no_ansi(self, parser, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.delenv("TERM", raising=False)
        monkeypatch.setattr(colors, "color_enabled", lambda stream=None: False)
        colors.set_color_mode("auto")

        assert "\x1b[" not in render(parser, 100)


def cli_help(args, env_extra=None, width=100):
    """Run ``trackfetch -h ...`` in a subprocess and return its output."""
    import os
    import subprocess
    import sys

    env = dict(
        os.environ,
        COLUMNS=str(width),
        COLORTERM="truecolor",
    )
    env.update(env_extra or {})

    return subprocess.run(
        [sys.executable, "-m", "trackfetch", *args],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )


BUILTIN_THEMES = ("cassette", "neon-tape", "mono", "vinyl")


class TestThemeRoles:
    @pytest.mark.parametrize("theme", BUILTIN_THEMES)
    def test_every_builtin_theme_defines_help_roles(self, theme):
        palette = colors.THEMES[theme]

        for role in colors.HELP_ROLES:
            assert role in palette, f"{theme} is missing {role}"

    def test_help_roles_are_part_of_the_role_list(self):
        for role in colors.HELP_ROLES:
            assert role in colors.ROLES

    def test_unknown_custom_role_is_rejected(self, tmp_path):
        from trackfetch import themes

        path = tmp_path / "themes.ini"
        path.write_text("[mine]\nnotarole = #fff\n", encoding="utf-8")

        with pytest.raises(ValueError, match="unknown option"):
            themes.parse_theme_file(path)

    def test_missing_help_roles_fall_back(self):
        core = {
            role: dict(colors.THEMES["cassette"][role])
            for role in colors.ROLES
            if role not in colors.HELP_ROLES
        }

        palette = colors.normalize_palette(core)

        for role in colors.HELP_ROLES:
            fallback = colors.HELP_ROLE_FALLBACK[role]
            assert palette[role] == palette[fallback]

    def test_core_role_missing_is_an_error(self):
        palette = {
            role: dict(colors.THEMES["cassette"][role])
            for role in colors.ROLES
            if role != "accent"
        }

        with pytest.raises(ValueError, match="missing"):
            colors.normalize_palette(palette)

    def test_normalize_keeps_explicit_help_roles(self):
        palette = {
            role: dict(colors.THEMES["cassette"][role])
            for role in colors.ROLES
        }
        palette["heading"] = {"16": 31, "256": 196, "truecolor": (255, 0, 0)}
        palette.pop("flag")

        result = colors.normalize_palette(palette)

        assert result["heading"]["truecolor"] == (255, 0, 0)
        assert result["flag"] == result["accent"]

    @pytest.mark.parametrize("theme", BUILTIN_THEMES)
    def test_help_uses_the_theme_palette(self, parser, theme, monkeypatch):
        monkeypatch.setenv("COLORTERM", "truecolor")
        colors.set_theme(theme)
        colors.set_color_mode("always")

        try:
            text = render(parser, 100)
        finally:
            colors.set_color_mode("never")

        assert "\x1b[" in text

        if theme != "mono":
            code = colors.paint("x", "accent").split("x")[0]
            assert code in text


class TestCliThemes:
    @pytest.mark.parametrize("theme", BUILTIN_THEMES)
    def test_always_colors_every_theme(self, theme):
        result = cli_help(["-h", "--color", "always", "--color-theme", theme])

        assert "\x1b[" in result.stdout

    @pytest.mark.parametrize("theme", BUILTIN_THEMES)
    @pytest.mark.parametrize("width", WIDTHS)
    def test_stripped_always_equals_never(self, theme, width):
        always = cli_help(
            ["-h", "--color", "always", "--color-theme", theme],
            width=width,
        )
        never = cli_help(
            ["-h", "--color", "never", "--color-theme", theme],
            width=width,
        )

        assert "\x1b[" not in never.stdout
        assert strip_ansi(always.stdout) == never.stdout

    def test_pipe_has_no_ansi(self):
        result = cli_help(["-h"])

        assert "\x1b[" not in result.stdout

    def test_no_color_env_is_plain(self):
        result = cli_help(["-h", "--color", "auto"], {"NO_COLOR": "1"})

        assert "\x1b[" not in result.stdout

    def test_theme_from_config(self, tmp_path):
        config = tmp_path / "trackfetch.ini"
        config.write_text(
            "[trackfetch]\ncolor = always\ncolor_theme = vinyl\n",
            encoding="utf-8",
        )

        result = cli_help(["-h"], {"TRACKFETCH_CONFIG": str(config)})

        assert "\x1b[" in result.stdout
        assert "212;175;55" in result.stdout

    def test_flag_beats_config_theme(self, tmp_path):
        config = tmp_path / "trackfetch.ini"
        config.write_text(
            "[trackfetch]\ncolor = always\ncolor_theme = vinyl\n",
            encoding="utf-8",
        )

        result = cli_help(
            ["-h", "--color-theme", "neon-tape"],
            {"TRACKFETCH_CONFIG": str(config)},
        )

        assert "95;215;255" in result.stdout
        assert "212;175;55" not in result.stdout

    def test_custom_theme_applies_to_help(self, tmp_path):
        theme_file = tmp_path / "themes.ini"
        theme_file.write_text(
            "[mine]\n"
            "base = cassette\n"
            "heading = #ff0000\n"
            "prog = #00ff00\n"
            "flag = #0000ff\n",
            encoding="utf-8",
        )

        result = cli_help(
            [
                "-h",
                "--color",
                "always",
                "--color-theme",
                "mine",
                "--themes-file",
                str(theme_file),
            ]
        )

        assert "255;0;0" in result.stdout
        assert "0;255;0" in result.stdout
        assert "0;0;255" in result.stdout

    def test_custom_theme_without_help_roles_still_prints(self, tmp_path):
        theme_file = tmp_path / "themes.ini"
        theme_file.write_text(
            "[plain]\nbase = cassette\naccent = #ff8800\n",
            encoding="utf-8",
        )

        result = cli_help(
            [
                "-h",
                "--color",
                "always",
                "--color-theme",
                "plain",
                "--themes-file",
                str(theme_file),
            ]
        )

        assert result.returncode == 0
        assert "usage: trackfetch" in strip_ansi(result.stdout)

    def test_unknown_theme_warns_and_prints_default(self):
        result = cli_help(
            ["-h", "--color", "always", "--color-theme", "nope"]
        )

        assert result.returncode == 0
        assert "usage: trackfetch" in strip_ansi(result.stdout)
        assert "nope" in result.stderr
        assert "cassette" in result.stderr

    def test_mono_help_has_only_attributes(self):
        result = cli_help(["-h", "--color", "always", "--color-theme", "mono"])

        codes = set(re.findall(r"\x1b\[([0-9;]*)m", result.stdout))

        # Only the reset and bold/dim attributes, never a color code.
        assert codes <= {"0", "1", "2"}
