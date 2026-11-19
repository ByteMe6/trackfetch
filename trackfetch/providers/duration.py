# SPDX-License-Identifier: GPL-3.0-or-later
"""Provider duration normalization helpers."""


def milliseconds_to_seconds(value) -> int | None:
    """Convert a millisecond duration to whole seconds, or None."""
    if value is None or isinstance(value, bool):
        return None

    try:
        number = float(value)

    except (TypeError, ValueError):
        return None

    if number < 0:
        return None

    return int(round(number / 1000))


def seconds(value) -> int | None:
    """Normalize a duration that is already expressed in seconds."""
    if value is None or isinstance(value, bool):
        return None

    try:
        number = float(value)

    except (TypeError, ValueError):
        return None

    if number < 0:
        return None

    return int(round(number))
