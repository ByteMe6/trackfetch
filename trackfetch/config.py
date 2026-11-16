# SPDX-License-Identifier: GPL-3.0-or-later
"""Source configuration: provider priority, thresholds and promotion rules.

Config-file discovery and CLI/config precedence live in ``settings.py``.
"""

import math
import re

from .constants import (
    ARTWORK_FALLBACKS,
    CJK_RE,
    DEFAULT_MATCH_THRESHOLD,
    DEFAULT_METADATA_SOURCES,
    DEFAULT_TITLE_THRESHOLD,
    LYRICS_DEFAULT_ENABLED,
    METADATA_PROVIDERS,
    PROVIDER_DEFAULTS,
    PROVIDER_OPTIONS,
    VOCALOID_HINTS,
    YOUTUBE_DEFAULT_ENABLED,
)


class SourceConfig:
    """The resolved, immutable-in-practice source configuration for one run."""

    def __init__(
        self,
        metadata_sources,
        youtube_enabled,
        providers,
        match_threshold,
        title_threshold,
        none_selected=False,
        lyrics_enabled=LYRICS_DEFAULT_ENABLED,
    ):
        self.metadata_sources = list(metadata_sources)
        self.youtube_enabled = bool(youtube_enabled)
        self.providers = providers
        self.match_threshold = match_threshold
        self.title_threshold = title_threshold
        self.none_selected = bool(none_selected)
        self.lyrics_enabled = bool(lyrics_enabled)

    def interval(self, name: str) -> float:
        return self.providers[name]["min_interval"]

    def is_enabled(self, name: str) -> bool:
        return bool(self.providers[name].get("enabled"))


def split_source_names(value: str):
    return [
        item.strip().lower()
        for item in (value or "").split(",")
        if item.strip()
    ]


def normalize_metadata_sources(value: str):
    """Validate and de-duplicate a metadata provider list, preserving order."""
    names = []

    for name in split_source_names(value):
        if name in ARTWORK_FALLBACKS:
            raise ValueError(
                f"'{name}' is an artwork fallback, not a metadata provider"
            )

        if name not in METADATA_PROVIDERS:
            raise ValueError(
                f"Unknown metadata source '{name}' "
                f"(choose from {', '.join(METADATA_PROVIDERS)} or none)"
            )

        if name not in names:
            names.append(name)

    return names


def normalize_disable_sources(value: str):
    names = []

    for name in split_source_names(value):
        if name not in METADATA_PROVIDERS and name not in ARTWORK_FALLBACKS:
            raise ValueError(
                f"Unknown source '{name}' "
                f"(choose from {', '.join(METADATA_PROVIDERS + ARTWORK_FALLBACKS)})"
            )

        if name not in names:
            names.append(name)

    return names


def parse_bool(value: str, label: str) -> bool:
    lowered = (value or "").strip().lower()

    if lowered in ("1", "true", "yes", "on"):
        return True

    if lowered in ("0", "false", "no", "off"):
        return False

    raise ValueError(
        f"Invalid boolean for '{label}': {value!r} "
        "(use true or false)"
    )


def parse_interval(value: str, label: str) -> float:
    try:
        interval = float(value)

    except (TypeError, ValueError) as error:
        raise ValueError(
            f"Invalid number for '{label}': {value!r}"
        ) from error

    if not math.isfinite(interval):
        raise ValueError(
            f"'{label}' must be a finite number: {value!r}"
        )

    if interval < 0:
        raise ValueError(f"'{label}' must not be negative: {value!r}")

    return interval


def parse_provider_options(values):
    """Parse --provider-opt NAME.KEY=VALUE arguments into typed settings."""
    options = []

    for raw in values or []:
        text = str(raw).strip()

        if "=" not in text:
            raise ValueError(
                f"Invalid --provider-opt '{raw}': expected NAME.KEY=VALUE"
            )

        target, value = text.split("=", 1)

        if "." not in target:
            raise ValueError(
                f"Invalid --provider-opt '{raw}': expected NAME.KEY=VALUE"
            )

        name, key = target.split(".", 1)
        name = name.strip().lower()
        key = key.strip().lower()
        value = value.strip()

        if name not in METADATA_PROVIDERS:
            raise ValueError(
                f"Unknown provider in --provider-opt: '{name}' "
                f"(choose from {', '.join(METADATA_PROVIDERS)})"
            )

        if key not in PROVIDER_OPTIONS[name]:
            allowed = ", ".join(sorted(PROVIDER_OPTIONS[name]))
            raise ValueError(
                f"Unknown option '{key}' for provider '{name}' "
                f"(choose from {allowed})"
            )

        if value == "":
            raise ValueError(
                f"Empty value in --provider-opt '{raw}'"
            )

        if key == "enabled":
            parsed = parse_bool(value, f"{name}.{key}")

        elif key == "min_interval":
            parsed = parse_interval(value, f"{name}.{key}")

        else:
            parsed = value.lower()

        options.append((name, key, parsed))

    return options


def threshold_value(value, default: float, label: str) -> float:
    if value is None:
        return default

    try:
        number = float(value)

    except (TypeError, ValueError) as error:
        raise ValueError(f"Invalid value for '{label}': {value!r}") from error

    if not math.isfinite(number):
        raise ValueError(
            f"'{label}' must be a finite number between 0.0 and 1.0: {value!r}"
        )

    if not 0.0 <= number <= 1.0:
        raise ValueError(
            f"'{label}' must be between 0.0 and 1.0: {value!r}"
        )

    return number


def build_source_config(args, settings):
    """Resolve CLI flags, config settings and built-in defaults.

    Precedence is CLI > config.ini > built-in defaults. The result does not
    permanently change any user configuration.
    """
    settings = settings or {}

    providers = {}
    config_enabled = set()
    config_disabled = set()

    for name in METADATA_PROVIDERS:
        defaults = PROVIDER_DEFAULTS[name]
        entry = dict(defaults)
        entry["disabled"] = False

        enabled_key = f"{name}_enabled"
        interval_key = f"{name}_min_interval"

        if enabled_key in settings and str(settings[enabled_key]).strip():
            enabled = parse_bool(settings[enabled_key], enabled_key)
            entry["enabled"] = enabled

            if enabled:
                config_enabled.add(name)
            else:
                config_disabled.add(name)

        if interval_key in settings and str(settings[interval_key]).strip():
            entry["min_interval"] = parse_interval(
                settings[interval_key],
                interval_key,
            )

        if name == "itunes" and settings.get("itunes_country", "").strip():
            country = settings["itunes_country"].strip().lower()

            if not re.fullmatch(r"[a-z]{2}", country):
                raise ValueError(
                    f"Invalid value for 'itunes_country': "
                    f"{settings['itunes_country']!r} (use a two-letter code)"
                )

            entry["country"] = country

        providers[name] = entry

    cli_enabled = set()
    cli_disabled = set()

    for name, key, value in parse_provider_options(
        getattr(args, "provider_opt", None)
    ):
        if key == "enabled":
            providers[name]["enabled"] = value

            if value:
                cli_enabled.add(name)
                cli_disabled.discard(name)
            else:
                cli_disabled.add(name)
                cli_enabled.discard(name)

        elif key == "min_interval":
            providers[name]["min_interval"] = value

        elif key == "country":
            if not re.fullmatch(r"[a-z]{2}", value):
                raise ValueError(
                    f"Invalid value for '{name}.country': {value!r} "
                    "(use a two-letter code)"
                )

            providers[name]["country"] = value

    cli_raw = getattr(args, "metadata_sources", None)
    cli_sources_given = cli_raw is not None
    raw_sources = (
        cli_raw
        if cli_sources_given
        else config_str_value(settings, "metadata_sources")
    )

    none_selected = False

    if raw_sources is None:
        sources = list(DEFAULT_METADATA_SOURCES)

    elif (raw_sources or "").strip().lower() == "none":
        sources = []
        none_selected = True

    else:
        sources = normalize_metadata_sources(raw_sources)

    config_disabled_sources = set(
        normalize_disable_sources(
            config_str_value(settings, "disable_sources") or ""
        )
    )
    cli_disabled_sources = set(
        normalize_disable_sources(
            getattr(args, "disable_sources", None) or ""
        )
    )
    all_disabled_sources = config_disabled_sources | cli_disabled_sources

    config_disables = config_disabled | (
        config_disabled_sources - set(ARTWORK_FALLBACKS)
    )
    cli_disables = cli_disabled | (
        cli_disabled_sources - set(ARTWORK_FALLBACKS)
    )

    if cli_sources_given:
        # A CLI selection is an explicit override of the configured source
        # list and of any configured disabling of those providers. Only an
        # explicit CLI disable may remove a selected provider.
        remove = set(cli_disables)
        # A config disable still blocks VocaDB promotion unless the provider
        # was also explicitly selected or enabled on the CLI.
        disabled_for_promotion = set(cli_disables) | (
            config_disables - set(sources) - set(cli_enabled)
        )
    else:
        # An explicit CLI provider enable still wins over config disabling,
        # but never over an explicit CLI disable.
        remove = (config_disables - set(cli_enabled)) | set(cli_disables)
        disabled_for_promotion = set(remove)

    sources = [name for name in sources if name not in remove]

    if not none_selected:
        append_enabled = set(cli_enabled)

        if not cli_sources_given:
            append_enabled.update(config_enabled)

        for name in METADATA_PROVIDERS:
            if name in append_enabled and name not in sources and name not in remove:
                sources.append(name)

    for name in METADATA_PROVIDERS:
        providers[name]["enabled"] = name in sources
        providers[name]["disabled"] = name in disabled_for_promotion

    youtube_enabled = YOUTUBE_DEFAULT_ENABLED

    if "youtube_enabled" in settings and str(settings["youtube_enabled"]).strip():
        youtube_enabled = parse_bool(
            settings["youtube_enabled"],
            "youtube_enabled",
        )

    if "youtube" in all_disabled_sources:
        youtube_enabled = False

    lyrics_enabled = LYRICS_DEFAULT_ENABLED

    if "lyrics_enabled" in settings and str(settings["lyrics_enabled"]).strip():
        lyrics_enabled = parse_bool(
            settings["lyrics_enabled"],
            "lyrics_enabled",
        )

    cli_lyrics = getattr(args, "lyrics_enabled", None)

    if cli_lyrics is not None:
        lyrics_enabled = bool(cli_lyrics)

    match_threshold = threshold_value(
        getattr(args, "match_threshold", None),
        threshold_value(
            settings.get("match_threshold"),
            DEFAULT_MATCH_THRESHOLD,
            "match_threshold",
        ),
        "match_threshold",
    )
    title_threshold = threshold_value(
        getattr(args, "title_threshold", None),
        threshold_value(
            settings.get("title_threshold"),
            DEFAULT_TITLE_THRESHOLD,
            "title_threshold",
        ),
        "title_threshold",
    )

    return SourceConfig(
        sources,
        youtube_enabled,
        providers,
        match_threshold,
        title_threshold,
        none_selected,
        lyrics_enabled,
    )


def has_vocadb_hint(artist: str, title: str) -> bool:
    text = f"{artist} {title}"
    lowered = text.lower()

    if CJK_RE.search(text):
        return True

    return any(hint in lowered for hint in VOCALOID_HINTS)


def effective_metadata_sources(config: SourceConfig, artist: str, title: str):
    """Apply the temporary VocaDB promotion without changing the config."""
    sources = [
        name
        for name in config.metadata_sources
        if config.is_enabled(name)
    ]
    vocadb = config.providers["vocadb"]

    if config.none_selected:
        # An explicit empty list such as `-s none` stays empty.
        return []

    if not has_vocadb_hint(artist, title) or vocadb.get("disabled"):
        return sources

    if "vocadb" in sources:
        sources.remove("vocadb")

    return ["vocadb", *sources]


def format_source_list(config: SourceConfig) -> str:
    lines = ["Available sources:", "", "Metadata providers:"]

    for name in METADATA_PROVIDERS:
        entry = config.providers[name]
        status = "enabled" if entry.get("enabled") else "disabled"
        credentials = "required" if name == "spotify" else "not required"
        details = [f"min_interval={entry['min_interval']}s"]

        if name == "itunes":
            details.insert(0, f"country={entry.get('country', 'us')}")

        lines.append(
            f"  {name:<12} {status:<9} credentials: {credentials:<13} "
            f"{', '.join(details)}"
        )

    lines.extend(["", "Artwork fallbacks:"])

    for name in ARTWORK_FALLBACKS:
        status = "enabled" if config.youtube_enabled else "disabled"
        lines.append(
            f"  {name:<12} {status:<9} credentials: not required  "
            f"used when metadata has no artwork"
        )

    lines.extend(
        [
            "",
            f"Metadata priority: {', '.join(config.metadata_sources) or 'none'}",
            f"Match threshold: {config.match_threshold}",
            f"Title threshold: {config.title_threshold}",
            "Lyrics embedding: "
            + (
                "enabled (LRCLIB, MP3 only)"
                if config.lyrics_enabled
                else "disabled"
            ),
        ]
    )

    return "\n".join(lines)


def config_str_value(settings, key):
    """Read a plain string setting, or None when it is missing or blank."""
    value = (settings.get(key) or "").strip()

    if not value:
        return None

    return value
