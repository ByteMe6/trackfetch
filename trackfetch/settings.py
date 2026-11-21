# SPDX-License-Identifier: GPL-3.0-or-later
"""Config file discovery, parsing and CLI/config precedence."""

import argparse
import configparser
import os
from pathlib import Path

from .config import config_str_value, parse_bool
from .constants import CONFIG_ENV, CONFIG_FILENAME, CONFIG_SECTION


def config_candidates():
    """Config file locations, in the order they are looked up."""
    candidates = []

    env = os.getenv(CONFIG_ENV)

    if env:
        candidates.append(Path(env).expanduser())

    candidates.append(Path.cwd() / CONFIG_FILENAME)

    xdg = os.getenv("XDG_CONFIG_HOME")

    if xdg:
        candidates.append(
            Path(xdg).expanduser() / "trackfetch" / CONFIG_FILENAME
        )

    candidates.append(
        Path.home() / ".config" / "trackfetch" / CONFIG_FILENAME
    )
    candidates.append(Path.home() / CONFIG_FILENAME)

    return candidates


def find_config_file(explicit=None):
    """Return the config file to use, or None if there is none."""
    if explicit is not None:
        return Path(explicit).expanduser()

    for candidate in config_candidates():
        if candidate.is_file():
            return candidate

    return None


def load_config(explicit=None):
    """Read settings from a config file.

    Returns a (settings, path) tuple. Settings is empty when no config file
    exists. Raises FileNotFoundError when an explicitly requested file is
    missing, and configparser.Error when the file cannot be parsed.
    """
    config_path = find_config_file(explicit)

    if config_path is None:
        return {}, None

    if not config_path.is_file():
        if config_path.exists():
            raise FileNotFoundError(
                f"Config path is not a file: {config_path}"
            )

        raise FileNotFoundError(f"Config file not found: {config_path}")

    parser = configparser.ConfigParser()

    with config_path.open(encoding="utf-8") as file:
        parser.read_file(file)

    settings = dict(parser.defaults())

    if parser.has_section(CONFIG_SECTION):
        settings.update(dict(parser[CONFIG_SECTION]))

    return settings, config_path



def config_path_value(settings, key):
    """Read a path-like setting, or None when it is missing or blank."""
    value = config_str_value(settings, key)

    if value is None:
        return None

    return Path(value).expanduser()


def resolve_output(cli_output, settings):
    """Pick the output directory: flag > config file > current directory."""
    if cli_output is not None:
        return Path(cli_output).expanduser()

    from_config = config_path_value(settings, "output")

    if from_config is not None:
        return from_config

    return Path.cwd()


def coerce_config_value(action, raw):
    """Convert a raw config value into the type the CLI option expects."""
    if action.type is Path:
        return Path(raw).expanduser()

    if action.type is float:
        return float(raw)

    if action.type is int:
        return int(raw)

    if isinstance(action, argparse._StoreTrueAction):
        return raw.lower() in ("1", "true", "yes", "on")

    if isinstance(action, argparse.BooleanOptionalAction):
        return parse_bool(raw, action.dest)

    return raw


def apply_config(args, parser, settings):
    """Fill options that were not given on the command line from the config.

    The flag always wins, the config file is the second source, and the
    built-in default is the last one.
    """
    for action in parser._actions:
        dest = action.dest

        if dest in (
            "help",
            "version",
            "config",
            "inputs",
            "track",
            "metadata_sources",
            "disable_sources",
            "provider_opt",
            "match_threshold",
            "title_threshold",
            "soundcloud_min_score",
            "soundcloud_min_margin",
            "soundcloud_trigger",
            "soundcloud_ambiguous",
            "list_sources",
        ):
            continue

        if getattr(args, dest, None) is not None:
            continue

        raw = config_str_value(settings, dest)

        if raw is None:
            continue

        try:
            value = coerce_config_value(action, raw)

        except (TypeError, ValueError) as error:
            raise ValueError(
                f"Invalid value for '{dest}' in config file: {raw} ({error})"
            ) from error

        if action.choices and value not in action.choices:
            raise ValueError(
                f"Unknown value for '{dest}' in config file: {raw} "
                f"(choose from {', '.join(action.choices)})"
            )

        setattr(args, dest, value)
