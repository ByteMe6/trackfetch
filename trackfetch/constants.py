# SPDX-License-Identifier: GPL-3.0-or-later
"""Static defaults and provider tables shared across TrackFetch."""

import re

YTDLP_REMOTE_COMPONENTS = "ejs:github"

CONFIG_SECTION = "trackfetch"
CONFIG_FILENAME = "trackfetch.ini"
CONFIG_ENV = "TRACKFETCH_CONFIG"
THEMES_FILENAME = "themes.ini"

DEFAULT_FORMAT = "mp3"
DEFAULT_AUDIO_QUALITY = 5
LYRICS_TYPES = ("inline", "sidecar", "plain")
DEFAULT_LYRICS_TYPE = "inline"
DEFAULT_DELAY = 1.0
MAX_FILENAME_BYTES = 200
MAX_COVER_SIZE = 640
MAX_COVER_BYTES = 100 * 1024

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

VERSION = "2.2.10"
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
        # The Search API allows about 20 calls per minute; 3.5 s keeps a
        # small margin below that ceiling.
        "min_interval": 3.5,
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
LYRICS_DEFAULT_ENABLED = True
LYRICS_LANGUAGE = "und"
LYRICS_TIMEOUT = 15
LYRICS_MIN_INTERVAL = 0.5
LRCLIB_SEARCH_URL = "https://lrclib.net/api/search"

M4A_LYRICS_KEY = "\xa9lyr"
M4A_SYNCED_LYRICS_KEY = "----:com.apple.iTunes:SYNCEDLYRICS"
OPUS_LYRICS_KEY = "LYRICS"
OPUS_SYNCED_LYRICS_KEY = "SYNCEDLYRICS"

LRC_TIMESTAMP_RE = re.compile(
    r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]"
)

CACHE_FILENAME = "metadata-cache.json"
CACHE_VERSION = 1
CACHE_DEFAULT_ENABLED = True

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
