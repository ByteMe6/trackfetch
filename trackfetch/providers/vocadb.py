# SPDX-License-Identifier: GPL-3.0-or-later
"""VocaDB metadata provider (useful for Vocaloid and CJK tracks)."""

from ..config import SourceConfig
from ..errors import ProviderError
from ..runtime import request_json


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
