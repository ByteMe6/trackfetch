# SPDX-License-Identifier: GPL-3.0-or-later
"""Deezer Search API metadata provider."""

from ..config import SourceConfig
from ..errors import ProviderError
from ..runtime import request_json


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
