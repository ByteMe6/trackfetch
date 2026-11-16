# SPDX-License-Identifier: GPL-3.0-or-later
"""iTunes Search API metadata provider."""

import re

from ..config import SourceConfig
from ..errors import ProviderError
from ..runtime import request_json


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
