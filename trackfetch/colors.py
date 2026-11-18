# SPDX-License-Identifier: GPL-3.0-or-later
"""Themeable ANSI color output.

Four themes are built in. The default is ``cassette``. Color is emitted only
for an interactive terminal; redirected output, dumb terminals and runs with
``NO_COLOR`` set stay plain. ``--color`` can force color on or off, and
``--color-theme`` selects a palette.
"""

import os
import sys

_RESET = "\x1b[0m"
_ATTRS = {
    "bold": 1,
    "dim": 2,
    "underline": 4,
}

# Roles: text, accent, accent_bright, progress, success, warning, error, skip,
# muted, frame. Each role has a 16-color, 256-color and truecolor value.
THEMES = {
    "cassette": {
        "text": {"16": None, "256": None, "truecolor": None},
        "accent": {"16": 36, "256": 73, "truecolor": (77, 182, 172)},
        "accent_bright": {"16": 96, "256": 80, "truecolor": (128, 203, 196)},
        "progress": {"16": 33, "256": 179, "truecolor": (224, 164, 88)},
        "success": {"16": 32, "256": 107, "truecolor": (143, 188, 106)},
        "warning": {"16": 93, "256": 215, "truecolor": (255, 183, 77)},
        "error": {"16": 31, "256": 167, "truecolor": (229, 115, 115)},
        "skip": {"16": 90, "256": 246, "truecolor": (161, 136, 127)},
        "muted": {"16": 2, "256": 243, "truecolor": (141, 120, 106)},
        "frame": {"16": 2, "256": 240, "truecolor": (90, 70, 54)},
    },
    "neon-tape": {
        "text": {"16": None, "256": None, "truecolor": None},
        "accent": {"16": 36, "256": 37, "truecolor": (0, 175, 175)},
        "accent_bright": {"16": 96, "256": 81, "truecolor": (95, 215, 255)},
        "progress": {"16": 35, "256": 177, "truecolor": (215, 135, 255)},
        "success": {"16": 32, "256": 71, "truecolor": (95, 175, 95)},
        "warning": {"16": 33, "256": 178, "truecolor": (215, 175, 0)},
        "error": {"16": 31, "256": 167, "truecolor": (215, 95, 95)},
        "skip": {"16": 90, "256": 245, "truecolor": (138, 138, 138)},
        "muted": {"16": 2, "256": 66, "truecolor": (107, 122, 138)},
        "frame": {"16": 2, "256": 237, "truecolor": (51, 71, 91)},
    },
    "mono": {
        "text": {"16": None, "256": None, "truecolor": None},
        "accent": {"16": 37, "256": 250, "truecolor": (201, 201, 201)},
        "accent_bright": {"16": 97, "256": 231, "truecolor": (255, 255, 255)},
        "progress": {"16": 37, "256": 245, "truecolor": (189, 189, 189)},
        "success": {"16": 97, "256": 231, "truecolor": (255, 255, 255)},
        "warning": {"16": 37, "256": 250, "truecolor": (176, 176, 176)},
        "error": {"16": 97, "256": 231, "truecolor": (255, 255, 255)},
        "skip": {"16": 90, "256": 243, "truecolor": (122, 122, 122)},
        "muted": {"16": 2, "256": 240, "truecolor": (106, 106, 106)},
        "frame": {"16": 2, "256": 238, "truecolor": (68, 68, 68)},
    },
    "vinyl": {
        "text": {"16": None, "256": None, "truecolor": None},
        "accent": {"16": 33, "256": 178, "truecolor": (212, 175, 55)},
        "accent_bright": {"16": 93, "256": 222, "truecolor": (240, 207, 106)},
        "progress": {"16": 35, "256": 170, "truecolor": (198, 95, 215)},
        "success": {"16": 32, "256": 108, "truecolor": (143, 188, 143)},
        "warning": {"16": 33, "256": 178, "truecolor": (217, 164, 65)},
        "error": {"16": 31, "256": 167, "truecolor": (217, 95, 95)},
        "skip": {"16": 90, "256": 246, "truecolor": (138, 122, 138)},
        "muted": {"16": 2, "256": 60, "truecolor": (117, 100, 125)},
        "frame": {"16": 2, "256": 239, "truecolor": (74, 54, 84)},
    },
}

DEFAULT_THEME = "cassette"
DEFAULT_COLOR_MODE = "auto"
_COLOR_MODES = ("auto", "always", "never")
ROLES = (
    "text",
    "accent",
    "accent_bright",
    "progress",
    "success",
    "warning",
    "error",
    "skip",
    "muted",
    "frame",
)
_BUILTIN_THEMES = frozenset(THEMES)

_mode = DEFAULT_COLOR_MODE
_theme = DEFAULT_THEME
_custom_themes = set()
_windows_ansi_ready = False


def theme_names():
    """Return the built-in theme names in display order."""
    return tuple(THEMES)


def is_builtin_theme(name: str) -> bool:
    return str(name).strip().lower() in _BUILTIN_THEMES


def register_theme(name: str, palette) -> None:
    """Add a custom theme parsed from ``themes.ini``."""
    name = str(name).strip().lower()

    if not name:
        raise ValueError("A color theme needs a name")

    if name in THEMES and name not in _custom_themes:
        raise ValueError(
            f"Color theme '{name}' is built in; choose another name"
        )

    missing = [role for role in ROLES if role not in palette]

    if missing:
        raise ValueError(
            f"Color theme '{name}' is missing: {', '.join(missing)}"
        )

    for role in ROLES:
        entry = palette[role]

        if not isinstance(entry, dict) or set(entry) != {
            "16",
            "256",
            "truecolor",
        }:
            raise ValueError(
                f"Color theme '{name}' has an invalid value for '{role}'"
            )

    THEMES[name] = palette
    _custom_themes.add(name)


def set_theme(name: str) -> None:
    """Select one of the built-in or loaded custom color themes."""
    name = str(name).strip().lower()

    if name not in THEMES:
        raise ValueError(
            f"Unknown color theme '{name}' "
            f"(choose from {', '.join(THEMES)})"
        )

    global _theme
    _theme = name


def get_theme() -> str:
    return _theme


def set_color_mode(mode: str) -> None:
    """Choose how color is decided: ``auto``, ``always`` or ``never``."""
    if mode not in _COLOR_MODES:
        raise ValueError(
            f"Invalid color mode '{mode}' "
            f"(choose from {', '.join(_COLOR_MODES)})"
        )

    global _mode
    _mode = mode


def get_color_mode() -> str:
    return _mode


def _color_depth() -> str:
    """Pick the richest color format the terminal advertises."""
    if os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
        return "truecolor"

    if "256color" in os.environ.get("TERM", ""):
        return "256"

    return "16"


def _enable_windows_ansi() -> None:
    """Turn on virtual-terminal processing for classic Windows consoles."""
    global _windows_ansi_ready

    if os.name != "nt" or _windows_ansi_ready:
        return

    _windows_ansi_ready = True

    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()

        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)

    except Exception:
        pass


def color_enabled(stream=None) -> bool:
    """Return whether color should be written to ``stream`` (stdout)."""
    if _mode == "never":
        return False

    if _mode == "auto":
        if os.environ.get("NO_COLOR"):
            return False

        if os.environ.get("TERM") == "dumb":
            return False

        stream = sys.stdout if stream is None else stream

        try:
            if not stream.isatty():
                return False

        except (AttributeError, ValueError):
            return False

    _enable_windows_ansi()

    return True


def _role_code(role: str, depth: str):
    value = THEMES[_theme][role][depth]

    if value is None:
        return None

    if depth == "truecolor":
        return f"38;2;{value[0]};{value[1]};{value[2]}"

    if depth == "256":
        return f"38;5;{value}"

    return str(value)


def paint(text, *styles, stream=None) -> str:
    """Wrap ``text`` in theme roles and attributes, or leave it plain."""
    if not styles or not color_enabled(stream):
        return str(text)

    depth = _color_depth()
    codes = []

    for style in styles:
        if style in _ATTRS:
            codes.append(str(_ATTRS[style]))

        elif style in THEMES[_theme]:
            code = _role_code(style, depth)

            if code:
                codes.append(code)

        else:
            raise ValueError(f"Unknown color style: {style!r}")

    if not codes:
        return str(text)

    return f"\x1b[{';'.join(codes)}m{text}{_RESET}"


def accent(value) -> str:
    return paint(value, "accent")


def accent_bright(value) -> str:
    return paint(value, "accent_bright")


def progress(value) -> str:
    return paint(value, "progress", "bold")


def success(value) -> str:
    return paint(value, "success", "bold")


def warning(value) -> str:
    return paint(value, "warning")


def error(value) -> str:
    return paint(value, "error", "bold")


def skip(value) -> str:
    return paint(value, "skip")


def muted(value) -> str:
    return paint(value, "muted")


def frame(value) -> str:
    return paint(value, "frame")


def heading(value) -> str:
    return paint(value, "accent_bright", "bold")


def label(value) -> str:
    return paint(value, "accent", "bold")


def bold(value) -> str:
    return paint(value, "bold")
