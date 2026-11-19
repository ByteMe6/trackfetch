# SPDX-License-Identifier: GPL-3.0-or-later
"""iTunes Search API metadata provider."""

import re

from ..config import SourceConfig
from ..errors import ProviderError
from ..runtime import request_json
from .duration import milliseconds_to_seconds
from .search import search_variants


def upscale_itunes_artwork(url):
    if not url:
        return None

    return re.sub(r"\d+x\d+bb\.", "640x640bb.", url)


def itunes_candidates(runtime, query: str, config: SourceConfig):
    country = config.providers["itunes"].get("country", "us")
    data = request_json(
        runtime,
        "itunes",
        "https://itunes.apple.com/search",
        params={
            "term": query,
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
                "duration": milliseconds_to_seconds(
                    item.get("trackTimeMillis")
                ),
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


def itunes_provider(runtime, artist: str, title: str, config: SourceConfig):
    return search_variants(
        lambda query: itunes_candidates(runtime, query, config),
        artist,
        title,
        config,
    )
