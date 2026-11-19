# SPDX-License-Identifier: GPL-3.0-or-later
"""Help formatter with stable alignment and theme-driven colors.

The plain help text is laid out and wrapped first, with no ANSI codes in the
strings argparse measures. Color is added afterwards, span by span, using the
roles of the active theme, so escape sequences never affect column widths.

Help roles (all defined by every built-in theme and by ``themes.ini``):

``heading``  section titles and ``usage:``
``prog``     the program name in the usage line and in examples
``flag``     ``--long`` and ``-s`` option names
``metavar``  ``ARTIST - TITLE``, ``OUTPUT``, ``SCORE`` and similar
``choices``  ``{mp3,m4a,opus}``-style enumerations
``default``  the ``(default: ...)`` notes
``text``     ordinary descriptions
``dim``      config lookup paths and secondary notes
"""

import argparse
import re
import textwrap

from . import colors

HELP_POSITION = 30

_HEADING = re.compile(r"^[A-Za-z][A-Za-z -]*:$")
_OPTION_HEADER = re.compile(r"^((?:-[^\s,]+(?:,\s*)?)+)(.*)$")
_OPTION_LINE = re.compile(r"^  (\S.*?)( {2,})(\S.*)$")
_CHOICES = re.compile(r"\{[^{}]*\}")
_DEFAULT = re.compile(r"\(default(?::[^)]*)?\)")
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text):
    """Remove ANSI escape sequences (used by tests and by plain fallbacks)."""
    return _ANSI.sub("", text)


def _paint(text, role, *attrs):
    """Color ``text`` with a theme role, keeping empty strings empty.

    When the ``dim`` role has no color of its own (as in Mono) the dim
    attribute is added, so secondary text still looks secondary.
    """
    if not text:
        return text

    styles = [role, *attrs]

    if role == "dim" or "dim" in attrs:
        styles.append("dim")

    return colors.paint(text, *styles)


def _paint_defaults(text):
    """Color the ``(default: ...)`` spans inside a description."""
    parts = re.split(r"(\(default(?::[^)]*)?\))", text)
    pieces = []

    for part in parts:
        if not part:
            continue

        role = "default" if _DEFAULT.fullmatch(part) else "text"
        pieces.append(_paint(part, role))

    return "".join(pieces)


def _paint_metavar(rest):
    """Color the metavar/choices tail of an option header.

    Leading whitespace stays plain so no escape sequence wraps a bare space.
    """
    stripped = rest.lstrip()
    lead = rest[: len(rest) - len(stripped)]
    pieces = []

    for part in re.split(r"(\{[^{}]*\})", stripped):
        if not part:
            continue

        if _CHOICES.fullmatch(part):
            pieces.append(_paint(part, "choices", "bold"))

        else:
            pieces.append(_paint(part, "metavar"))

    return lead + "".join(pieces)


def _paint_header(header):
    """Color an option or positional header: flags, metavar and choices."""
    match = _OPTION_HEADER.match(header)

    if not match:
        return _paint_metavar(header)

    flags, rest = match.groups()

    return _paint(flags, "flag", "bold") + _paint_metavar(rest)


def _paint_usage(line):
    """Color ``usage: prog [...]`` with heading, prog and dim."""
    match = re.match(r"^(\s*)(usage:)(\s+)(\S+)(.*)$", line)

    if not match:
        return _paint(line, "dim")

    indent, word, space, prog, tail = match.groups()

    return "".join(
        (
            indent,
            _paint(word, "heading", "bold"),
            space,
            _paint(prog, "prog", "bold"),
            _paint(tail, "dim"),
        )
    )


def _paint_example(line):
    """Color the program name in an example command."""
    match = re.match(r"^(\s*)(\S+)(.*)$", line)

    if not match:
        return line

    indent, prog, tail = match.groups()

    return (
        f"{indent}{_paint(prog, 'prog', 'bold')}"
        f"{_paint_defaults(tail)}"
    )


def _paint_option(line):
    """Color one option line, with or without a description on the row."""
    match = _OPTION_LINE.match(line)

    if not match:
        # A flag too long for the help column: the whole line is the header.
        return f"  {_paint_header(line[2:].rstrip())}"

    header, padding, description = match.groups()

    return (
        f"  {_paint_header(header)}"
        f"{padding}{_paint_defaults(description)}"
    )


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
            lines.append(_paint_usage(line))

        elif _HEADING.match(stripped):
            section = stripped[:-1].strip().lower()
            lines.append(_paint(stripped, "heading", "bold"))

        elif section == "config" and line.startswith("  "):
            lines.append("  " + _paint(stripped, "dim"))

        elif section == "config":
            lines.append(_paint(stripped, "dim"))

        elif section == "examples":
            lines.append(_paint_example(line))

        elif line.startswith("  -"):
            lines.append(_paint_option(line))

        else:
            lines.append(_paint_defaults(line))

    return "\n".join(lines)


class TrackFetchHelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Lay out plain text with a fixed help column, then add theme color."""

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
