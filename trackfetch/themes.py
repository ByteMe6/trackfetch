# SPDX-License-Identifier: GPL-3.0-or-later
"""Custom color themes read from ``themes.ini`` beside the config file.

Each INI section defines one theme. A theme inherits the roles it does not
override from ``base`` (``cassette`` by default), so a custom theme can be as
small as one or two colors.
"""

import configparser
import re
from pathlib import Path

from . import colors
from .constants import THEMES_FILENAME
from .settings import config_candidates

_HEX_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_DEFAULT_NAMES = ("", "default", "none", "terminal")

_ANSI_RGB = (
    (0, 0, 0),
    (128, 0, 0),
    (0, 128, 0),
    (128, 128, 0),
    (0, 0, 128),
    (128, 0, 128),
    (0, 128, 128),
    (192, 192, 192),
    (128, 128, 128),
    (255, 0, 0),
    (0, 255, 0),
    (255, 255, 0),
    (0, 0, 255),
    (255, 0, 255),
    (0, 255, 255),
    (255, 255, 255),
)

_NAMED_INDEX = {
    "black": 0,
    "red": 1,
    "green": 2,
    "yellow": 3,
    "blue": 4,
    "magenta": 5,
    "cyan": 6,
    "white": 7,
    "bright-black": 8,
    "bright-red": 9,
    "bright-green": 10,
    "bright-yellow": 11,
    "bright-blue": 12,
    "bright-magenta": 13,
    "bright-cyan": 14,
    "bright-white": 15,
    "gray": 8,
    "grey": 8,
}

_CUBE = (0, 95, 135, 175, 215, 255)


def _ansi16_code(index: int) -> int:
    return 30 + index if index < 8 else 90 + index - 8


def _xterm_rgb(index: int):
    """RGB value of a standard xterm 256-color palette entry."""
    index = max(0, min(255, index))

    if index < 16:
        return _ANSI_RGB[index]

    if index < 232:
        index -= 16
        return (
            _CUBE[index // 36],
            _CUBE[(index % 36) // 6],
            _CUBE[index % 6],
        )

    level = 8 + (index - 232) * 10
    return level, level, level


def _nearest(rgb, palette):
    return min(
        range(len(palette)),
        key=lambda index: sum(
            (rgb[channel] - palette[index][channel]) ** 2
            for channel in range(3)
        ),
    )


def _rgb_to_256(rgb) -> int:
    return min(
        range(256),
        key=lambda index: sum(
            (rgb[channel] - _xterm_rgb(index)[channel]) ** 2
            for channel in range(3)
        ),
    )


def _rgb_to_16(rgb) -> int:
    return _ansi16_code(_nearest(rgb, _ANSI_RGB))


def _palette_from_rgb(rgb):
    return {
        "16": _rgb_to_16(rgb),
        "256": _rgb_to_256(rgb),
        "truecolor": tuple(rgb),
    }


def _parse_color(value, label: str):
    raw = str(value).strip()
    lowered = raw.lower()

    if lowered in _DEFAULT_NAMES:
        return {"16": None, "256": None, "truecolor": None}

    match = _HEX_RE.match(raw)

    if match:
        digits = match.group(1)

        if len(digits) == 3:
            digits = "".join(character * 2 for character in digits)

        rgb = tuple(
            int(digits[index:index + 2], 16)
            for index in (0, 2, 4)
        )

        return _palette_from_rgb(rgb)

    if raw.isdigit():
        index = int(raw)

        if not 0 <= index <= 255:
            raise ValueError(
                f"Invalid color for '{label}': {value!r} "
                "(a 256-color index must be 0-255)"
            )

        return {
            "16": _rgb_to_16(_xterm_rgb(index)),
            "256": index,
            "truecolor": _xterm_rgb(index),
        }

    key = lowered.replace("_", "-").replace(" ", "-")

    if key in _NAMED_INDEX:
        index = _NAMED_INDEX[key]
        rgb = _ANSI_RGB[index]

        return {
            "16": _ansi16_code(index),
            "256": _rgb_to_256(rgb),
            "truecolor": rgb,
        }

    raise ValueError(
        f"Invalid color for '{label}': {value!r} "
        "(use #RRGGBB, 0-255, a color name or 'default')"
    )


def parse_theme_file(path) -> dict:
    """Parse a ``themes.ini`` file and return ``{name: palette}``.

    Built-in theme names are reserved. A section without ``base`` inherits
    the default Cassette theme.
    """
    path = Path(path)
    parser = configparser.ConfigParser(interpolation=None)

    try:
        with path.open(encoding="utf-8") as file:
            parser.read_file(file)

    except configparser.Error as error:
        raise ValueError(f"Invalid theme file {path}: {error}") from error

    parsed = {}

    for section in parser.sections():
        name = section.strip().lower()

        if not name:
            raise ValueError(f"Theme file {path} has an empty theme name")

        if colors.is_builtin_theme(name):
            raise ValueError(
                f"Theme '{name}' in {path} is built in; "
                "choose another name and use 'base' to inherit it"
            )

        base_name = parser.get(
            section,
            "base",
            fallback=colors.DEFAULT_THEME,
            raw=True,
        ).strip().lower()
        base = colors.THEMES.get(base_name) or parsed.get(base_name)

        if base is None:
            raise ValueError(
                f"Theme '{name}' in {path} has unknown base '{base_name}'"
            )

        palette = {
            role: dict(base[role])
            for role in colors.ROLES
        }

        for key, value in parser.items(section, raw=True):
            key = key.strip().lower()

            if key == "base":
                continue

            if key not in colors.ROLES:
                raise ValueError(
                    f"Theme '{name}' in {path} has unknown option '{key}' "
                    f"(choose from base, {', '.join(colors.ROLES)})"
                )

            palette[key] = _parse_color(value, f"{name}.{key}")

        parsed[name] = palette

    return parsed


def load_theme_file(path, required: bool = False):
    """Register themes from ``path`` and return their names.

    A missing auto-discovered file is not an error. A missing file requested
    explicitly on the CLI or in the config is an error.
    """
    if path is None:
        return []

    path = Path(path).expanduser()

    if not path.is_file():
        if required:
            raise FileNotFoundError(f"Theme file not found: {path}")

        return []

    parsed = parse_theme_file(path)

    for name, palette in parsed.items():
        colors.register_theme(name, palette)

    return list(parsed)


def find_theme_file(explicit=None, config_path=None):
    """Locate ``themes.ini`` next to the config file or in config locations."""
    if explicit is not None and str(explicit).strip():
        return Path(explicit).expanduser()

    if config_path is not None:
        return Path(config_path).expanduser().parent / THEMES_FILENAME

    for candidate in config_candidates():
        path = candidate.parent / THEMES_FILENAME

        if path.is_file():
            return path

    return None
