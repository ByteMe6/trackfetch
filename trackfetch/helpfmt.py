# SPDX-License-Identifier: GPL-3.0-or-later
"""Help formatter with stable alignment and post-render colors.

The plain help text is laid out and wrapped first, with no ANSI codes in the
strings that argparse measures. Color is added afterwards, line by line, so
the escape sequences never affect column widths.
"""

import argparse
import re
import textwrap

from . import colors

HELP_POSITION = 30

_HEADING = re.compile(r"[A-Za-z][A-Za-z -]*:")
_OPTION_LINE = re.compile(r"^  (\S.*?)(\s{2,})(\S.*)$")
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text):
    """Remove ANSI escape sequences (used by tests and by plain fallbacks)."""
    return _ANSI.sub("", text)


def _colorize_option(line):
    """Color the flags part of an option line, keeping the help text plain."""
    match = _OPTION_LINE.match(line)

    if match:
        header, padding, help_text = match.groups()
        return f"  {colors.label(header)}{padding}{help_text}"

    # A long flag that did not fit the help column: its description is on the
    # next line, so the whole line is the flag.
    return f"  {colors.label(line[2:].rstrip())}"


def colorize_help(text):
    """Add theme colors to already wrapped help text."""
    if not colors.color_enabled():
        return text

    lines = []
    section = None

    for line in text.split("\n"):
        stripped = line.strip()

        if not stripped:
            lines.append(line)

        elif line.startswith("usage:"):
            rest = line[len("usage:") :].lstrip()
            lines.append(f"{colors.label('usage:')} {colors.accent_bright(rest)}")

        elif _HEADING.fullmatch(stripped):
            section = stripped[:-1].strip().lower()
            lines.append(colors.heading(stripped))

        elif line.startswith("  -"):
            lines.append(_colorize_option(line))

        elif section == "config" and stripped.startswith(
            ("--", "$", ".", "~")
        ):
            lines.append(f"  {colors.accent(stripped)}")

        elif section == "examples" and line.startswith("  "):
            lines.append(f"  {colors.accent(stripped)}")

        else:
            lines.append(line)

    return "\n".join(lines)


class TrackFetchHelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Lay out plain text with a fixed help column, then add ANSI color."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_help_position", HELP_POSITION)
        super().__init__(*args, **kwargs)

    def _fill_text(self, text, width, indent):
        """Wrap prose paragraphs but keep indented list items intact."""
        wrapped = []
        paragraph = []

        def flush():
            if paragraph:
                wrapped.extend(
                    textwrap.wrap(
                        " ".join(paragraph),
                        width=max(width, 40),
                        initial_indent=indent,
                        subsequent_indent=indent,
                    )
                )
                paragraph.clear()

        for line in text.split("\n"):
            stripped = line.strip()

            if not stripped:
                flush()
                wrapped.append("")

            elif line.startswith(" ") or stripped.endswith(":"):
                flush()
                wrapped.append(indent + line)

            else:
                paragraph.append(stripped)

        flush()

        return "\n".join(wrapped)

    def format_help(self):
        return colorize_help(super().format_help())
