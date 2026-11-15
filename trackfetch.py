#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later

import argparse
import base64
import configparser
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import requests
import spotipy
from mutagen.flac import Picture
from mutagen.id3 import (
    APIC,
    ID3,
    TALB,
    TDRC,
    TIT2,
    TPE1,
    TPE2,
    TRCK,
)
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggopus import OggOpus
from spotipy.oauth2 import SpotifyClientCredentials

YTDLP_REMOTE_COMPONENTS = "ejs:github"

CONFIG_SECTION = "trackfetch"
CONFIG_FILENAME = "trackfetch.ini"
CONFIG_ENV = "TRACKFETCH_CONFIG"

DEFAULT_FORMAT = "m4a"
DEFAULT_DELAY = 1.0
MAX_FILENAME_BYTES = 200

AUDIO_FORMATS = {
    "mp3": [],
    "m4a": [
        "-f",
        "bestaudio[ext=m4a]/bestaudio",
    ],
    "opus": [
        "-f",
        "bestaudio[acodec=opus]/bestaudio",
    ],
}

VERSION = "2.2.6"
USER_AGENT = (
    f"trackfetch/{VERSION} "
    "(https://github.com/ByteMe6/trackfetch)"
)

METADATA_PROVIDERS = (
    "spotify",
    "itunes",
    "deezer",
    "musicbrainz",
    "vocadb",
)
ARTWORK_FALLBACKS = ("youtube",)
DEFAULT_METADATA_SOURCES = ("itunes",)

PROVIDER_DEFAULTS = {
    "spotify": {
        "enabled": False,
        "min_interval": 0.0,
    },
    "itunes": {
        "enabled": True,
        "min_interval": 3.0,
        "country": "us",
    },
    "deezer": {
        "enabled": False,
        "min_interval": 0.25,
    },
    "musicbrainz": {
        "enabled": False,
        "min_interval": 1.1,
    },
    "vocadb": {
        "enabled": False,
        "min_interval": 0.5,
    },
}

DEFAULT_MATCH_THRESHOLD = 0.6
DEFAULT_TITLE_THRESHOLD = 0.8
YOUTUBE_DEFAULT_ENABLED = True

CACHE_FILENAME = "metadata-cache.json"
CACHE_VERSION = 1

PROVIDER_OPTIONS = {
    "spotify": {"enabled", "min_interval"},
    "itunes": {"enabled", "min_interval", "country"},
    "deezer": {"enabled", "min_interval"},
    "musicbrainz": {"enabled", "min_interval"},
    "vocadb": {"enabled", "min_interval"},
}

CJK_RE = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff"
    r"\uf900-\ufaff\uac00-\ud7af]"
)
VOCALOID_HINTS = (
    "vocaloid",
    "hatsune miku",
    "初音ミク",
    "镜音",
    "鏡音",
    "巡音",
    "gumi",
    "ia ",
    "kaito",
    "meiko",
    "v flower",
)


class ProviderError(Exception):
    """A provider request failed for a real, retryable reason."""


class ProviderAuthError(ProviderError):
    """A provider rejected the credentials."""


def normalize(text: str) -> str:
    # NFC keeps meaningful Unicode characters (CJK, accented letters) intact.
    text = unicodedata.normalize("NFC", text).lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(
        None,
        normalize(a),
        normalize(b)
    ).ratio()


def artist_similarity(input_artist: str, candidate_artist: str) -> float:
    """Compare an artist while allowing providers to list several artists."""
    if not candidate_artist:
        return 0.0

    best = similarity(input_artist, candidate_artist)

    for part in re.split(r"[,;&/]| feat\.? | featuring ", candidate_artist):
        part = part.strip()

        if part:
            best = max(best, similarity(input_artist, part))

    return best


def score_metadata(
    input_artist: str,
    input_title: str,
    candidate: dict,
    match_threshold: float,
    title_threshold: float,
):
    """Return a copy of the candidate with a score, or None if it is too weak."""
    candidate_title = candidate.get("title") or ""

    if not candidate_title:
        return None

    title_score = similarity(input_title, candidate_title)

    if title_score < title_threshold:
        return None

    artist_score = artist_similarity(
        input_artist,
        candidate.get("artist") or "",
    )
    overall = title_score * 0.70 + artist_score * 0.30

    if overall < match_threshold:
        return None

    scored = dict(candidate)
    scored["score"] = overall
    scored["title_score"] = title_score
    scored["artist_score"] = artist_score

    return scored


def select_best_metadata(
    candidates,
    input_artist: str,
    input_title: str,
    match_threshold: float,
    title_threshold: float,
):
    """Pick the highest scoring candidate that passes both thresholds."""
    best = None

    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue

        scored = score_metadata(
            input_artist,
            input_title,
            candidate,
            match_threshold,
            title_threshold,
        )

        if scored is None:
            continue

        if best is None or scored["score"] > best["score"]:
            best = scored

    return best


def fallback_metadata(artist: str, title: str) -> dict:
    return {
        "artist": artist,
        "title": title,
        "album": "",
        "album_artist": artist,
        "track_number": None,
        "release_date": None,
        "cover_url": None,
        "source": "input",
        "source_id": None,
        "score": 0.0,
    }


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
    ):
        self.metadata_sources = list(metadata_sources)
        self.youtube_enabled = bool(youtube_enabled)
        self.providers = providers
        self.match_threshold = match_threshold
        self.title_threshold = title_threshold
        self.none_selected = bool(none_selected)

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
        ]
    )

    return "\n".join(lines)


class ProviderHealth:
    """Per-provider consecutive-failure and cooldown tracking."""

    INITIAL_COOLDOWN = 30.0
    MAX_COOLDOWN = 600.0

    def __init__(self, clock=None):
        self.clock = clock or (lambda: time.monotonic())
        self.states = {}

    def state(self, name: str) -> dict:
        return self.states.setdefault(
            name,
            {
                "failures": 0,
                "cooldown_until": 0.0,
                "cooldown_seconds": 0.0,
            },
        )

    def failures(self, name: str) -> int:
        return self.state(name)["failures"]

    def in_cooldown(self, name: str) -> bool:
        return self.state(name)["cooldown_until"] > self.clock()

    def record_success(self, name: str):
        state = self.state(name)
        state["failures"] = 0
        state["cooldown_until"] = 0.0
        state["cooldown_seconds"] = 0.0

    def record_failure(self, name: str):
        state = self.state(name)
        state["failures"] += 1

        if state["failures"] < 2:
            return

        previous = state["cooldown_seconds"]

        if previous <= 0:
            cooldown = self.INITIAL_COOLDOWN
        else:
            cooldown = min(previous * 2, self.MAX_COOLDOWN)

        state["cooldown_seconds"] = cooldown
        state["cooldown_until"] = self.clock() + cooldown

    def force_cooldown(self, name: str, seconds: float):
        state = self.state(name)
        state["cooldown_seconds"] = seconds
        state["cooldown_until"] = self.clock() + seconds


class RateLimiter:
    """Independent minimum request interval per provider."""

    def __init__(self, intervals=None, clock=None):
        self.intervals = dict(intervals or {})
        self.clock = clock or (lambda: time.monotonic())
        self.last_request = {}

    def wait(self, name: str):
        interval = self.intervals.get(name, 0.0)

        if interval <= 0:
            self.last_request[name] = self.clock()
            return

        last = self.last_request.get(name)

        if last is not None:
            remaining = interval - (self.clock() - last)

            if remaining > 0:
                time.sleep(remaining)

        self.last_request[name] = self.clock()


class MetadataCache:
    """Per-provider metadata cache stored next to the downloaded files."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.entries = {}
        self.load()

    @staticmethod
    def key(artist: str, title: str) -> str:
        return f"{normalize(artist)}|{normalize(title)}"

    def load(self):
        if not self.path.is_file():
            return

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))

        except (OSError, ValueError, TypeError):
            self.entries = {}
            return

        if not isinstance(data, dict):
            self.entries = {}
            return

        entries = data.get("entries")

        if not isinstance(entries, dict):
            self.entries = {}
            return

        self.entries = entries

    def save(self):
        payload = {
            "version": CACHE_VERSION,
            "entries": self.entries,
        }

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ) + "\n",
                encoding="utf-8",
            )

        except OSError:
            pass

    def get(self, artist: str, title: str, provider: str):
        entry = self.entries.get(self.key(artist, title))

        if not isinstance(entry, dict):
            return None

        result = entry.get(provider)

        if not isinstance(result, dict) or not result.get("title"):
            return None

        return dict(result)

    def set(self, artist: str, title: str, provider: str, result: dict):
        if not isinstance(result, dict) or not result.get("title"):
            # An incomplete result must not replace a usable cached entry.
            return False

        key = self.key(artist, title)
        entry = self.entries.get(key)

        if not isinstance(entry, dict):
            entry = {}

        existing = entry.get(provider)

        if isinstance(existing, dict) and existing.get("title"):
            old_score = existing.get("score")
            new_score = result.get("score")

            try:
                if old_score is not None and (
                    new_score is None or float(new_score) < float(old_score)
                ):
                    return False
            except (TypeError, ValueError):
                pass

        stored = {
            field: result.get(field)
            for field in (
                "title",
                "artist",
                "album",
                "album_artist",
                "track_number",
                "release_date",
                "cover_url",
                "source",
                "source_id",
                "score",
            )
        }
        entry[provider] = stored
        self.entries[key] = entry
        self.save()

        return True


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = re.sub(r"\s+", " ", name).strip()

    encoded = name.encode("utf-8")

    if len(encoded) > MAX_FILENAME_BYTES:
        encoded = encoded[:MAX_FILENAME_BYTES]
        name = encoded.decode("utf-8", errors="ignore")

    return name


def parse_song(line: str):
    if " - " not in line:
        return None

    artist, title = line.split(" - ", 1)

    artist = artist.strip()
    title = title.strip()

    if not artist or not title:
        return None

    return artist, title


def spotify_credentials(args=None):
    """Spotify credentials: flag > config file > environment variable."""
    client_id = None
    client_secret = None

    if args is not None:
        client_id = getattr(args, "spotify_client_id", None)
        client_secret = getattr(args, "spotify_client_secret", None)

    client_id = client_id or os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = client_secret or os.getenv("SPOTIFY_CLIENT_SECRET")

    return client_id, client_secret


def get_spotify(args=None):
    """Build a Spotify client, or return None quietly without credentials."""
    client_id, client_secret = spotify_credentials(args)

    if not client_id or not client_secret:
        return None

    return spotipy.Spotify(
        auth_manager=SpotifyClientCredentials(
            client_id=client_id,
            client_secret=client_secret,
        ),
        requests_timeout=30,
        retries=3,
    )


def find_spotify_track(
    sp,
    artist: str,
    title: str,
    raise_errors: bool = False,
):
    query = f'artist:"{artist}" track:"{title}"'

    try:
        results = sp.search(
            q=query,
            type="track",
            limit=10,
        )
    except Exception as error:
        if raise_errors:
            raise

        print(f"WARNING: Spotify search error: {error}")
        return None

    tracks = results.get("tracks", {}).get("items", [])

    if not tracks:
        try:
            results = sp.search(
                q=f"{artist} {title}",
                type="track",
                limit=10,
            )
            tracks = results.get("tracks", {}).get("items", [])
        except Exception:
            if raise_errors:
                raise

            return None

    if not tracks:
        return None

    best_track = None
    best_score = -1.0

    for track in tracks:
        spotify_title = track["name"]
        spotify_artists = " ".join(
            item["name"]
            for item in track["artists"]
        )

        title_score = similarity(title, spotify_title)
        artist_score = similarity(artist, spotify_artists)

        score = title_score * 0.70 + artist_score * 0.30

        if score > best_score:
            best_score = score
            best_track = track

    print(f"Spotify match score: {best_score:.2f}")

    return best_track


def get_track_metadata(track, fallback_artist, fallback_title):
    if track is None:
        return {
            "artist": fallback_artist,
            "title": fallback_title,
            "album": "",
            "album_artist": fallback_artist,
            "track_number": None,
            "release_date": None,
            "cover_url": None,
        }

    artist = ", ".join(
        item["name"]
        for item in track["artists"]
    )

    album = track.get("album", {})

    album_artist = ", ".join(
        item["name"]
        for item in album.get("artists", [])
    )

    images = album.get("images", [])

    return {
        "artist": artist,
        "title": track["name"],
        "album": album.get("name", ""),
        "album_artist": album_artist or artist,
        "track_number": track.get("track_number"),
        "release_date": album.get("release_date"),
        "cover_url": images[0]["url"] if images else None,
    }


IMAGE_FORMATS = {
    "jpeg": ("image/jpeg", ".jpg"),
    "png": ("image/png", ".png"),
    "gif": ("image/gif", ".gif"),
    "webp": ("image/webp", ".webp"),
}


def detect_image_format(data: bytes):
    """Return the image format from its signature, or None if unsupported."""
    if not data:
        return None

    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"

    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"

    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"

    if (
        len(data) >= 12
        and data.startswith(b"RIFF")
        and data[8:12] == b"WEBP"
    ):
        return "webp"

    return None


def image_mime_type(data: bytes):
    format_name = detect_image_format(data)

    if format_name is None:
        return None

    return IMAGE_FORMATS[format_name][0]


def is_image_bytes(data: bytes) -> bool:
    """Check common image signatures before writing a cover file."""
    return detect_image_format(data) is not None


def download_cover(url: str, destination: Path):
    response = requests.get(
        url,
        timeout=30,
        headers={
            "User-Agent": USER_AGENT
        },
    )

    response.raise_for_status()

    format_name = detect_image_format(response.content)

    if format_name is None:
        raise ValueError("response is not a valid image")

    destination = Path(destination)
    destination.write_bytes(response.content)

    return format_name


def youtube_thumbnail_urls(video):
    """Return thumbnail URLs for a YouTube result, best first."""
    urls = []
    thumbnails = (video or {}).get("thumbnails")

    if isinstance(thumbnails, list):
        ordered = sorted(
            (
                item for item in thumbnails
                if isinstance(item, dict) and item.get("url")
            ),
            key=lambda item: (
                (item.get("width") or 0) * (item.get("height") or 0)
            ),
            reverse=True,
        )

        urls.extend(item["url"] for item in ordered)

    thumbnail = (video or {}).get("thumbnail")

    if isinstance(thumbnail, str) and thumbnail:
        urls.append(thumbnail)

    video_id = (video or {}).get("id")

    if video_id:
        urls.append(
            f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"
        )
        urls.append(
            f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
        )

    result = []

    for url in urls:
        if url not in result:
            result.append(url)

    return result


def youtube_search(query: str, limit: int = 5):
    command = [
        "yt-dlp",
        "--remote-components",
        YTDLP_REMOTE_COMPONENTS,
        "--flat-playlist",
        "--dump-json",
        f"ytsearch{limit}:{query}",
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    videos = []

    for line in result.stdout.splitlines():
        try:
            data = json.loads(line)
            videos.append(data)
        except json.JSONDecodeError:
            pass

    return videos


def score_youtube_result(
    video,
    artist: str,
    title: str,
):
    video_title = video.get("title", "")

    title_score = similarity(title, video_title)

    artist_score = similarity(artist, video_title)

    score = (
        title_score * 0.70
        + artist_score * 0.30
    )

    normalized_video = normalize(video_title)

    if "official audio" in normalized_video:
        score += 0.08

    if "audio" in normalized_video:
        score += 0.03

    bad_words = [
        "cover",
        "караоке",
        "karaoke",
        "nightcore",
        "sped up",
        "slowed",
        "remix",
        "reaction",
    ]

    for word in bad_words:
        if word in normalized_video:
            score -= 0.20

    return score


def find_youtube_video(artist: str, title: str):
    query = f"{artist} {title}"

    print(f"Searching YouTube: {query}")

    videos = youtube_search(query, limit=5)

    if not videos:
        return None

    best_video = None
    best_score = -999.0

    for video in videos:
        score = score_youtube_result(
            video,
            artist,
            title,
        )

        print(
            f"  YouTube score {score:.2f}: "
            f"{video.get('title', 'Unknown')}"
        )

        if score > best_score:
            best_score = score
            best_video = video

    if best_video:
        print(
            f"Selected: "
            f"{best_video.get('title', 'Unknown')}"
        )

    return best_video


class MetadataRuntime:
    """Shared state for one TrackFetch run: HTTP, health, rate limits, cache."""

    def __init__(
        self,
        session=None,
        cache=None,
        health=None,
        limiter=None,
        spotify_args=None,
    ):
        self.session = session or requests.Session()
        headers = getattr(self.session, "headers", None)

        if headers is not None:
            headers.setdefault("User-Agent", USER_AGENT)

        self.cache = cache
        self.health = health or ProviderHealth()
        self.limiter = limiter or RateLimiter()
        self.spotify_args = spotify_args
        self.spotify_client = None
        self.spotify_initialized = False
        self.cover_art_cache = {}


def request_json(
    runtime,
    provider: str,
    url: str,
    params=None,
    headers=None,
    timeout=20,
):
    """Rate-limited JSON request with predictable provider errors."""
    request_headers = {"User-Agent": USER_AGENT}

    if headers:
        request_headers.update(headers)

    runtime.limiter.wait(provider)

    try:
        response = runtime.session.get(
            url,
            params=params,
            headers=request_headers,
            timeout=timeout,
        )

    except requests.Timeout as error:
        raise ProviderError(f"{provider} request timed out") from error

    except requests.RequestException as error:
        raise ProviderError(f"{provider} request failed: {error}") from error

    status = getattr(response, "status_code", 200)

    if status in (401, 403):
        raise ProviderAuthError(f"{provider} returned HTTP {status}")

    if status >= 400:
        raise ProviderError(f"{provider} returned HTTP {status}")

    try:
        return response.json()

    except (ValueError, TypeError) as error:
        raise ProviderError(
            f"{provider} returned invalid JSON"
        ) from error


def is_spotify_auth_error(error) -> bool:
    status = getattr(error, "http_status", None)

    if status in (401, 403):
        return True

    text = str(error)

    return "401" in text or "403" in text


def spotify_provider(runtime, artist: str, title: str, config: SourceConfig):
    if not runtime.spotify_initialized:
        try:
            runtime.spotify_client = get_spotify(runtime.spotify_args)

        except Exception as error:
            runtime.spotify_initialized = True

            if is_spotify_auth_error(error):
                raise ProviderAuthError(str(error)) from error

            raise ProviderError(f"Spotify authentication error: {error}") from error

        runtime.spotify_initialized = True

    if runtime.spotify_client is None:
        # Missing credentials are an optional-provider state, not a failure.
        return []

    try:
        track = find_spotify_track(
            runtime.spotify_client,
            artist,
            title,
            raise_errors=True,
        )

    except Exception as error:
        if is_spotify_auth_error(error):
            raise ProviderAuthError(str(error)) from error

        raise ProviderError(f"Spotify search error: {error}") from error

    if track is None:
        return []

    metadata = get_track_metadata(track, artist, title)

    return [
        {
            "title": metadata["title"],
            "artist": metadata["artist"],
            "album": metadata["album"],
            "album_artist": metadata["album_artist"],
            "track_number": metadata["track_number"],
            "release_date": metadata["release_date"],
            "cover_url": metadata["cover_url"],
            "source": "spotify",
            "source_id": track.get("id"),
        }
    ]


def upscale_itunes_artwork(url):
    if not url:
        return None

    return re.sub(r"\d+x\d+bb\.", "600x600bb.", url)


def itunes_provider(runtime, artist: str, title: str, config: SourceConfig):
    country = config.providers["itunes"].get("country", "us")
    data = request_json(
        runtime,
        "itunes",
        "https://itunes.apple.com/search",
        params={
            "term": f"{artist} {title}",
            "media": "music",
            "entity": "song",
            "limit": 25,
            "country": country,
        },
    )

    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ProviderError("iTunes returned an invalid response")

    candidates = []

    for item in data["results"]:
        if not isinstance(item, dict) or not item.get("trackName"):
            continue

        candidates.append(
            {
                "title": item.get("trackName"),
                "artist": item.get("artistName") or "",
                "album": item.get("collectionName") or "",
                "album_artist": item.get("artistName") or "",
                "track_number": item.get("trackNumber"),
                "release_date": item.get("releaseDate"),
                "cover_url": upscale_itunes_artwork(
                    item.get("artworkUrl100")
                    or item.get("artworkUrl60")
                    or item.get("artworkUrl30")
                ),
                "source": "itunes",
                "source_id": item.get("trackId"),
            }
        )

    return candidates


def deezer_provider(runtime, artist: str, title: str, config: SourceConfig):
    data = request_json(
        runtime,
        "deezer",
        "https://api.deezer.com/search",
        params={
            "q": f'artist:"{artist}" track:"{title}"',
            "limit": 25,
        },
    )

    if not isinstance(data, dict):
        raise ProviderError("Deezer returned an invalid response")

    if data.get("error"):
        raise ProviderError(
            f"Deezer API error: {data['error']}"
        )

    items = data.get("data")

    if not isinstance(items, list):
        raise ProviderError("Deezer returned an invalid response")

    candidates = []

    for item in items:
        if not isinstance(item, dict) or not item.get("title"):
            continue

        album = item.get("album") or {}
        album_artist = (album.get("artist") or {}).get("name")
        artist_name = (item.get("artist") or {}).get("name") or ""

        candidates.append(
            {
                "title": item.get("title"),
                "artist": artist_name,
                "album": album.get("title") or "",
                "album_artist": album_artist or artist_name,
                "track_number": None,
                "release_date": item.get("release_date"),
                "cover_url": (
                    album.get("cover_xl")
                    or album.get("cover_big")
                    or album.get("cover_medium")
                    or album.get("cover")
                ),
                "source": "deezer",
                "source_id": item.get("id"),
            }
        )

    return candidates


def musicbrainz_artist(recording) -> str:
    parts = []

    for credit in recording.get("artist-credit") or []:
        if not isinstance(credit, dict):
            continue

        parts.append(credit.get("name") or "")
        parts.append(credit.get("joinphrase") or "")

    return "".join(parts).strip()


def cover_art_archive_url(runtime, release_id, config: SourceConfig):
    """Look up front cover art for a MusicBrainz release, with memoisation."""
    if not release_id:
        return None

    if release_id in runtime.cover_art_cache:
        return runtime.cover_art_cache[release_id]

    try:
        data = request_json(
            runtime,
            "musicbrainz",
            f"https://coverartarchive.org/release/{release_id}",
        )

    except ProviderAuthError:
        runtime.cover_art_cache[release_id] = None
        return None

    except ProviderError:
        runtime.cover_art_cache[release_id] = None
        return None

    images = data.get("images") if isinstance(data, dict) else None

    if not isinstance(images, list):
        runtime.cover_art_cache[release_id] = None
        return None

    front = [
        image
        for image in images
        if isinstance(image, dict) and image.get("front")
    ]
    chosen = None

    for image in front or [item for item in images if isinstance(item, dict)]:
        if not image.get("image"):
            continue

        if chosen is None:
            chosen = image

        elif (
            (image.get("width") or 0) * (image.get("height") or 0)
            > (chosen.get("width") or 0) * (chosen.get("height") or 0)
        ):
            chosen = image

    url = chosen.get("image") if chosen else None
    runtime.cover_art_cache[release_id] = url

    return url


def musicbrainz_provider(runtime, artist: str, title: str, config: SourceConfig):
    data = request_json(
        runtime,
        "musicbrainz",
        "https://musicbrainz.org/ws/2/recording",
        params={
            "query": f'artist:"{artist}" AND recording:"{title}"',
            "fmt": "json",
            "limit": 10,
        },
        headers={"User-Agent": USER_AGENT},
    )

    recordings = data.get("recordings") if isinstance(data, dict) else None

    if not isinstance(recordings, list):
        raise ProviderError("MusicBrainz returned an invalid response")

    candidates = []

    for recording in recordings:
        if not isinstance(recording, dict) or not recording.get("title"):
            continue

        releases = recording.get("releases") or []
        release = releases[0] if releases and isinstance(releases[0], dict) else {}
        release_id = release.get("id")
        release_date = release.get("date")

        if not release_date:
            for medium in release.get("media") or []:
                if isinstance(medium, dict):
                    for track in medium.get("tracks") or []:
                        if isinstance(track, dict) and track.get("first-release-date"):
                            release_date = track["first-release-date"]
                            break

        candidates.append(
            {
                "title": recording.get("title"),
                "artist": musicbrainz_artist(recording),
                "album": release.get("title") or "",
                "album_artist": musicbrainz_artist(recording),
                "track_number": None,
                "release_date": release_date,
                "cover_url": cover_art_archive_url(
                    runtime,
                    release_id,
                    config,
                ),
                "source": "musicbrainz",
                "source_id": recording.get("id"),
            }
        )

    return candidates


def absolute_vocadb_url(url):
    if not url:
        return None

    if url.startswith("//"):
        return "https:" + url

    if url.startswith("/"):
        return "https://vocadb.net" + url

    return url


def vocadb_picture_url(item, album=None):
    for source in (item, album or {}):
        if not isinstance(source, dict):
            continue

        picture = source.get("mainPicture")

        if isinstance(picture, dict):
            url = (
                picture.get("url")
                or picture.get("original")
                or picture.get("largeThumbUrl")
            )

            if url:
                return absolute_vocadb_url(url)

        for key in ("coverPicture", "picture", "coverUrl"):
            if source.get(key):
                return absolute_vocadb_url(source[key])

    return None


def vocadb_provider(runtime, artist: str, title: str, config: SourceConfig):
    data = request_json(
        runtime,
        "vocadb",
        "https://vocadb.net/api/songs",
        params={
            "query": f"{artist} {title}",
            "nameMatchMode": "Auto",
            "maxResults": 20,
            "contentType": "Song",
        },
    )

    items = data.get("items") if isinstance(data, dict) else None

    if not isinstance(items, list):
        raise ProviderError("VocaDB returned an invalid response")

    candidates = []

    for item in items:
        if not isinstance(item, dict) or not item.get("name"):
            continue

        artist_name = item.get("artistString") or ""

        if not artist_name:
            artist_name = ", ".join(
                credit.get("name") or ""
                for credit in item.get("artists") or []
                if isinstance(credit, dict)
            ).strip(", ")

        albums = item.get("albums") or []
        album = albums[0] if albums and isinstance(albums[0], dict) else {}

        candidates.append(
            {
                "title": item.get("name"),
                "artist": artist_name,
                "album": album.get("name") or "",
                "album_artist": artist_name,
                "track_number": None,
                "release_date": (
                    item.get("publishDate")
                    or item.get("releaseDate")
                    or album.get("releaseDate")
                ),
                "cover_url": vocadb_picture_url(item, album),
                "source": "vocadb",
                "source_id": item.get("id"),
            }
        )

    return candidates


PROVIDER_FUNCTIONS = {
    "spotify": spotify_provider,
    "itunes": itunes_provider,
    "deezer": deezer_provider,
    "musicbrainz": musicbrainz_provider,
    "vocadb": vocadb_provider,
}


def cached_metadata(runtime, artist, title, provider, config):
    if runtime.cache is None:
        return None

    cached = runtime.cache.get(artist, title, provider)

    if cached is None:
        return None

    return select_best_metadata(
        [cached],
        artist,
        title,
        config.match_threshold,
        config.title_threshold,
    )


def resolve_metadata(artist: str, title: str, config: SourceConfig, runtime):
    """Return the first suitable metadata result in configured priority order."""
    if runtime is None:
        runtime = MetadataRuntime()

    fallback = fallback_metadata(artist, title)

    for provider in effective_metadata_sources(config, artist, title):
        if runtime.health.in_cooldown(provider):
            cached = cached_metadata(
                runtime,
                artist,
                title,
                provider,
                config,
            )

            if cached is not None:
                return cached

            continue

        state = runtime.health.state(provider)

        if state["failures"] == 0:
            cached = cached_metadata(
                runtime,
                artist,
                title,
                provider,
                config,
            )

            if cached is not None:
                return cached

        try:
            candidates = PROVIDER_FUNCTIONS[provider](
                runtime,
                artist,
                title,
                config,
            )

        except ProviderAuthError:
            runtime.health.force_cooldown(provider, 600.0)
            cached = cached_metadata(
                runtime,
                artist,
                title,
                provider,
                config,
            )

            if cached is not None:
                return cached

            continue

        except ProviderError:
            runtime.health.record_failure(provider)
            cached = cached_metadata(
                runtime,
                artist,
                title,
                provider,
                config,
            )

            if cached is not None:
                return cached

            continue

        except (KeyError, TypeError, ValueError, AttributeError, IndexError):
            # A malformed but successful-looking API response is a failure,
            # not a reason to abort the whole run.
            runtime.health.record_failure(provider)
            cached = cached_metadata(
                runtime,
                artist,
                title,
                provider,
                config,
            )

            if cached is not None:
                return cached

            continue

        best = select_best_metadata(
            candidates,
            artist,
            title,
            config.match_threshold,
            config.title_threshold,
        )

        # A valid response, even with no match, resets the failure counter.
        runtime.health.record_success(provider)

        if best is not None:
            if runtime.cache is not None:
                runtime.cache.set(artist, title, provider, best)

            return best

    return fallback


def download_audio(
    video_url: str,
    temp_dir: Path,
    audio_format: str = "mp3",
):
    template = str(temp_dir / "audio.%(ext)s")

    command = [
        "yt-dlp",
        *AUDIO_FORMATS[audio_format],
        "-x",
        "--audio-format",
        audio_format,
        "--audio-quality",
        "0",
        "--remote-components",
        YTDLP_REMOTE_COMPONENTS,
        "--no-playlist",
        "-o",
        template,
        video_url,
    ]

    result = subprocess.run(command)

    if result.returncode != 0:
        return None

    files = list(temp_dir.glob(f"audio.{audio_format}"))

    if not files:
        return None

    return files[0]


def add_metadata(
    audio_path: Path,
    cover_path: Path,
    metadata: dict,
):
    if audio_path.suffix == ".opus":
        add_opus_metadata(
            audio_path,
            cover_path,
            metadata,
        )
    elif audio_path.suffix == ".m4a":
        add_m4a_metadata(
            audio_path,
            cover_path,
            metadata,
        )
    else:
        add_mp3_metadata(
            audio_path,
            cover_path,
            metadata,
        )


def add_mp3_metadata(
    mp3_path: Path,
    cover_path: Path,
    metadata: dict,
):
    try:
        audio = ID3(mp3_path)
    except Exception:
        audio = ID3()

    for tag in [
        "APIC",
        "TIT2",
        "TPE1",
        "TALB",
        "TPE2",
        "TRCK",
        "TDRC",
    ]:
        audio.delall(tag)

    audio.add(
        TIT2(
            encoding=3,
            text=metadata["title"],
        )
    )

    audio.add(
        TPE1(
            encoding=3,
            text=metadata["artist"],
        )
    )

    if metadata["album"]:
        audio.add(
            TALB(
                encoding=3,
                text=metadata["album"],
            )
        )

    if metadata["album_artist"]:
        audio.add(
            TPE2(
                encoding=3,
                text=metadata["album_artist"],
            )
        )

    if metadata["track_number"]:
        audio.add(
            TRCK(
                encoding=3,
                text=str(metadata["track_number"]),
            )
        )

    if metadata["release_date"]:
        audio.add(
            TDRC(
                encoding=3,
                text=str(metadata["release_date"]),
            )
        )

    if cover_path.exists():
        image_data = cover_path.read_bytes()
        mime = image_mime_type(image_data)

        if mime is not None:
            audio.add(
                APIC(
                    encoding=3,
                    mime=mime,
                    type=3,
                    desc="Cover",
                    data=image_data,
                )
            )

    audio.save(
        mp3_path,
        v2_version=3,
    )


def add_opus_metadata(
    opus_path: Path,
    cover_path: Path,
    metadata: dict,
):
    audio = OggOpus(opus_path)

    fields = {
        "TITLE": metadata["title"],
        "ARTIST": metadata["artist"],
        "ALBUM": metadata["album"],
        "ALBUMARTIST": metadata["album_artist"],
        "TRACKNUMBER": metadata["track_number"],
        "DATE": metadata["release_date"],
    }

    for key in [*fields, "METADATA_BLOCK_PICTURE"]:
        if key in audio:
            del audio[key]

    for key, value in fields.items():
        if value:
            audio[key] = str(value)

    if cover_path.exists():
        image_data = cover_path.read_bytes()
        mime = image_mime_type(image_data)

        if mime is not None:
            picture = Picture()
            picture.type = 3
            picture.mime = mime
            picture.desc = "Cover"
            picture.data = image_data

            audio["METADATA_BLOCK_PICTURE"] = base64.b64encode(
                picture.write()
            ).decode("ascii")

    audio.save()


def add_m4a_metadata(
    m4a_path: Path,
    cover_path: Path,
    metadata: dict,
):
    audio = MP4(m4a_path)

    fields = {
        "\xa9nam": metadata["title"],
        "\xa9ART": metadata["artist"],
        "\xa9alb": metadata["album"],
        "aART": metadata["album_artist"],
        "\xa9day": metadata["release_date"],
    }

    for key in [*fields, "trkn", "covr"]:
        if key in audio:
            del audio[key]

    for key, value in fields.items():
        if value:
            audio[key] = [str(value)]

    if metadata["track_number"]:
        audio["trkn"] = [
            (int(metadata["track_number"]), 0)
        ]

    if cover_path.exists():
        image_data = cover_path.read_bytes()
        format_name = detect_image_format(image_data)

        # MP4 cover art supports JPEG and PNG. Embedding a GIF or WebP as
        # JPEG would mislabel the bytes, so leave it out for this format.
        if format_name == "jpeg":
            audio["covr"] = [
                MP4Cover(image_data, imageformat=MP4Cover.FORMAT_JPEG)
            ]
        elif format_name == "png":
            audio["covr"] = [
                MP4Cover(image_data, imageformat=MP4Cover.FORMAT_PNG)
            ]

    audio.save()


def make_filename(metadata, title_only, audio_format="mp3"):
    if title_only:
        name = metadata["title"]
    else:
        name = (
            f"{metadata['artist']} - "
            f"{metadata['title']}"
        )

    return sanitize_filename(name) + "." + audio_format


def read_done(done_file: Path):
    if not done_file.exists():
        return set()

    return {
        line.strip()
        for line in done_file.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()
        if line.strip()
    }


def append_line(path: Path, text: str):
    with path.open(
        "a",
        encoding="utf-8",
    ) as file:
        file.write(text + "\n")


def download_best_cover(metadata, video, cover_path, youtube_enabled):
    """Download provider artwork, then fall back to a YouTube thumbnail.

    Returns the path of the saved image with an extension that matches the
    actual image signature, or None when no usable image was downloaded.
    """
    candidates = []

    if metadata.get("cover_url"):
        candidates.append(
            (metadata["cover_url"], metadata.get("source") or "metadata")
        )

    if youtube_enabled:
        for url in youtube_thumbnail_urls(video):
            candidates.append((url, "YouTube"))

    last_error = None
    cover_path = Path(cover_path)

    for url, source in candidates:
        try:
            download_cover(url, cover_path)

            # Trust the bytes on disk over the URL or the Content-Type header,
            # so the saved extension always matches the actual image format.
            image_data = cover_path.read_bytes()
            format_name = detect_image_format(image_data)

            if format_name is None:
                raise ValueError("response is not a valid image")

            final_path = cover_path.with_suffix(
                IMAGE_FORMATS[format_name][1]
            )

            if cover_path != final_path:
                cover_path.replace(final_path)

            if final_path.stat().st_size > 0:
                print(f"{source} cover downloaded")
                return final_path

        except Exception as error:
            last_error = error

    if last_error is not None:
        print(f"WARNING: cover download failed: {last_error}")

    return None


def process_song(
    sp,
    input_artist,
    input_title,
    output,
    title_only,
    audio_format="mp3",
    source_config=None,
    runtime=None,
):
    if source_config is None and runtime is None:
        track = find_spotify_track(
            sp,
            input_artist,
            input_title,
        )

        metadata = get_track_metadata(
            track,
            input_artist,
            input_title,
        )
        metadata.setdefault("source", "spotify")
        youtube_enabled = True

    else:
        if source_config is None:
            source_config = build_source_config(None, {})

        metadata = resolve_metadata(
            input_artist,
            input_title,
            source_config,
            runtime,
        )
        youtube_enabled = source_config.youtube_enabled

    print(
        f"Metadata: "
        f"{metadata['artist']} - "
        f"{metadata['title']}"
    )

    filename = make_filename(
        metadata,
        title_only,
        audio_format,
    )

    final_path = output / filename

    if final_path.exists():
        print(f"SKIP: already exists: {filename}")
        return True, "exists"

    if not youtube_enabled:
        print("FAILED: YouTube is disabled")
        return False, "YouTube disabled"

    video = find_youtube_video(
        metadata["artist"],
        metadata["title"],
    )

    if not video:
        print("FAILED: No YouTube result")
        return False, "no YouTube result"

    video_url = (
        video.get("webpage_url")
        or video.get("url")
    )

    if not video_url:
        video_id = video.get("id")

        if video_id:
            video_url = (
                "https://www.youtube.com/watch?v="
                + video_id
            )

    if not video_url:
        print("FAILED: Invalid YouTube result")
        return False, "invalid YouTube result"

    with tempfile.TemporaryDirectory() as temp:
        temp_dir = Path(temp)

        audio_path = download_audio(
            video_url,
            temp_dir,
            audio_format,
        )

        if not audio_path:
            return False, "yt-dlp download failed"

        cover_path = download_best_cover(
            metadata,
            video,
            temp_dir / "cover",
            youtube_enabled,
        )

        if cover_path is None:
            cover_path = temp_dir / "cover.jpg"

        try:
            add_metadata(
                audio_path,
                cover_path,
                metadata,
            )

        except Exception as error:
            return False, f"metadata error: {error}"

        try:
            shutil.move(
                str(audio_path),
                str(final_path),
            )

        except Exception as error:
            return False, f"move error: {error}"

    print(f"SUCCESS: {filename}")

    return True, "downloaded"


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


def config_str_value(settings, key):
    """Read a plain string setting, or None when it is missing or blank."""
    value = (settings.get(key) or "").strip()

    if not value:
        return None

    return value


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


def read_song_file(path: Path):
    """Read Artist - Title pairs from a text file.

    Returns a (songs, skipped) tuple, where skipped holds the lines that
    could not be parsed.
    """
    songs = []
    skipped = []

    for line in path.read_text(
        encoding="utf-8-sig",
        errors="replace",
    ).splitlines():

        line = line.strip()

        if not line or line.startswith("#"):
            continue

        song = parse_song(line)

        if song:
            songs.append(song)

        else:
            skipped.append(line)

    return songs, skipped


def collect_sources(args, settings):
    """Build the ordered list of inputs: file paths and inline tracks.

    Every item is either a Path to a text file or an inline
    "Artist - Title" string.
    """
    sources = []

    config_input = config_str_value(settings, "input")

    if config_input:
        path = Path(config_input).expanduser()

        if not path.is_file():
            raise ValueError(f"Input file not found: {path}")

        sources.append(path)

    for item in args.inputs:
        path = Path(item).expanduser()

        if path.is_file():
            sources.append(path)

        elif " - " in item:
            if not parse_song(item):
                raise ValueError(
                    f"Could not parse track: {item} "
                    f"(expected 'Artist - Title')"
                )

            sources.append(item)

        else:
            raise ValueError(
                f"Input file not found: {item} "
                f"(if this is a track, use the 'Artist - Title' format)"
            )

    for group in args.track or []:
        for spec in group:
            if not parse_song(spec):
                raise ValueError(
                    f"Could not parse track: {spec} "
                    f"(expected 'Artist - Title')"
                )

            sources.append(spec)

    return sources


def main():
    try:
        sys.stdout.reconfigure(line_buffering=True)

    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(
        description=(
            "Download music using configurable free metadata "
            "sources and YouTube audio"
        ),
        epilog=(
            "A config file with the defaults can be used as well. It is "
            "looked up in --config, $TRACKFETCH_CONFIG, ./trackfetch.ini, "
            "$XDG_CONFIG_HOME/trackfetch/trackfetch.ini, "
            "~/.config/trackfetch/trackfetch.ini and ~/.trackfetch.ini. "
            "A command-line flag wins over the config file, and the config "
            "file wins over the built-in default."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "inputs",
        nargs="*",
        metavar="INPUT",
        help=(
            "Text file with Artist - Title, "
            "or an inline 'Artist - Title' track"
        ),
    )

    parser.add_argument(
        "--track",
        action="append",
        nargs="+",
        metavar="ARTIST - TITLE",
        help=(
            "Track to download inline, "
            "can be given several times"
        ),
    )

    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help=(
            "Output directory "
            "(overrides the config file, "
            "defaults to the current directory)"
        ),
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=(
            "Path to a config file "
            "(default: auto-detected, see below)"
        ),
    )

    parser.add_argument(
        "-f",
        "--format",
        choices=list(AUDIO_FORMATS),
        default=None,
        help="Audio format (default: m4a)",
    )

    parser.add_argument(
        "--title-only",
        action="store_true",
        default=None,
        help="Use only title in filename (default: off)",
    )

    parser.add_argument(
        "--delay",
        type=float,
        default=None,
        help="Delay between songs in seconds (default: 1.0)",
    )

    parser.add_argument(
        "-s",
        "--metadata-sources",
        default=None,
        metavar="SOURCES",
        help=(
            "Comma-separated metadata priority, for example "
            "'deezer,itunes,musicbrainz' or 'none' "
            "(default: itunes)"
        ),
    )

    parser.add_argument(
        "--disable-sources",
        default=None,
        metavar="SOURCES",
        help=(
            "Comma-separated sources to disable, "
            "for example 'spotify,youtube'"
        ),
    )

    parser.add_argument(
        "--provider-opt",
        action="append",
        default=None,
        metavar="NAME.KEY=VALUE",
        help=(
            "Provider-specific setting, for example "
            "--provider-opt itunes.country=ua"
        ),
    )

    parser.add_argument(
        "--match-threshold",
        type=float,
        default=None,
        metavar="SCORE",
        help="Minimum overall match score, 0.0-1.0 (default: 0.6)",
    )

    parser.add_argument(
        "--title-threshold",
        type=float,
        default=None,
        metavar="SCORE",
        help="Minimum title similarity, 0.0-1.0 (default: 0.8)",
    )

    parser.add_argument(
        "--list-sources",
        action="store_true",
        default=None,
        help="List available metadata sources and exit",
    )

    parser.add_argument(
        "--spotify-client-id",
        default=None,
        help="Spotify client ID (overrides the config file and the env)",
    )

    parser.add_argument(
        "--spotify-client-secret",
        default=None,
        help="Spotify client secret (overrides the config file and the env)",
    )

    args = parser.parse_args()

    try:
        settings, config_path = load_config(args.config)

    except FileNotFoundError as error:
        print(f"ERROR: {error}")
        sys.exit(1)

    except configparser.Error as error:
        print(f"ERROR: Invalid config file: {error}")
        sys.exit(1)

    try:
        apply_config(args, parser, settings)

    except ValueError as error:
        print(f"ERROR: {error}")
        sys.exit(1)

    try:
        source_config = build_source_config(args, settings)

    except ValueError as error:
        print(f"ERROR: {error}")
        sys.exit(1)

    if args.list_sources:
        print(format_source_list(source_config))
        return

    if args.output is None:
        args.output = resolve_output(None, settings)

    if args.format is None:
        args.format = DEFAULT_FORMAT

    if args.title_only is None:
        args.title_only = False

    if args.delay is None:
        args.delay = DEFAULT_DELAY

    if not math.isfinite(args.delay):
        print(f"ERROR: Delay must be a finite number: {args.delay}")
        sys.exit(1)

    if args.delay < 0:
        print(f"ERROR: Delay must not be negative: {args.delay}")
        sys.exit(1)

    try:
        sources = collect_sources(args, settings)

    except ValueError as error:
        print(f"ERROR: {error}")
        sys.exit(1)

    if not sources:
        print(
            "ERROR: No input. "
            "Pass a file or an inline 'Artist - Title' track, "
            "or set 'input' in the config file."
        )
        sys.exit(1)

    if args.output.exists() and not args.output.is_dir():
        print(f"ERROR: Output path is not a directory: {args.output}")
        sys.exit(1)

    songs = []
    skipped_lines = []

    for source in sources:
        if isinstance(source, Path):
            file_songs, file_skipped = read_song_file(source)

            songs.extend(file_songs)

            skipped_lines.extend(
                (source, line) for line in file_skipped
            )

        else:
            song = parse_song(source)

            if song:
                songs.append(song)

    if not songs:
        print("No songs to download.")
        sys.exit(0)

    unique_songs = []
    seen_songs = set()

    for artist, title in songs:
        key = f"{artist} - {title}"

        if key in seen_songs:
            continue

        seen_songs.add(key)
        unique_songs.append((artist, title))

    duplicates = len(songs) - len(unique_songs)

    songs = unique_songs

    args.output.mkdir(
        parents=True,
        exist_ok=True,
    )

    done_file = args.output / "done.txt"
    failed_file = args.output / "failed.txt"

    done = read_done(done_file)

    print(f"Found {len(songs)} songs")

    if duplicates:
        print(f"Removed {duplicates} duplicate(s)")

    print(f"Already completed: {len(done)} (from done.txt)")

    if skipped_lines:
        print(
            f"WARNING: skipped {len(skipped_lines)} line(s) "
            f"that are not 'Artist - Title':"
        )

        for path, line in skipped_lines[:5]:
            print(f"  {path}: {line}")

        if len(skipped_lines) > 5:
            print(f"  ... and {len(skipped_lines) - 5} more")

    if config_path:
        print(f"Config: {config_path}")

    print(f"Output: {args.output}")

    print(
        "Metadata sources: "
        + (", ".join(source_config.metadata_sources) or "none")
    )
    print(
        "YouTube artwork fallback: "
        + ("enabled" if source_config.youtube_enabled else "disabled")
    )

    sys.stdout.flush()

    runtime = MetadataRuntime(
        cache=MetadataCache(args.output / CACHE_FILENAME),
        limiter=RateLimiter(
            {
                name: source_config.interval(name)
                for name in METADATA_PROVIDERS
            }
        ),
        spotify_args=args,
    )

    success = 0
    skipped = 0
    failed = 0

    for number, (artist, title) in enumerate(
        songs,
        start=1,
    ):
        song_key = f"{artist} - {title}"

        print()
        print("=" * 60)
        print(f"[{number}/{len(songs)}]")
        print(song_key)

        if song_key in done:
            print("SKIP: already completed")
            skipped += 1
            continue

        ok, reason = process_song(
            None,
            artist,
            title,
            args.output,
            args.title_only,
            args.format,
            source_config=source_config,
            runtime=runtime,
        )

        if ok:
            append_line(
                done_file,
                song_key,
            )

            done.add(song_key)

            if reason == "exists":
                skipped += 1

            else:
                success += 1

        else:
            append_line(
                failed_file,
                f"{song_key} | {reason}",
            )

            failed += 1

        if number < len(songs):
            time.sleep(args.delay)

    print()
    print("=" * 60)
    print("FINISHED")
    print(f"SUCCESS: {success}")
    print(f"SKIPPED: {skipped}")
    print(f"FAILED: {failed}")
    print(f"DONE FILE: {done_file}")
    print(f"FAILED FILE: {failed_file}")


if __name__ == "__main__":
    main()
