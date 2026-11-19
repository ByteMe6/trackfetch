# SPDX-License-Identifier: GPL-3.0-or-later
"""MusicBrainz + Cover Art Archive metadata provider."""

from ..config import SourceConfig
from ..constants import USER_AGENT
from ..errors import ProviderAuthError, ProviderError
from ..runtime import request_json
from .duration import milliseconds_to_seconds
from .search import search_variants


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


def musicbrainz_candidates(runtime, query: str, config: SourceConfig):
    data = request_json(
        runtime,
        "musicbrainz",
        "https://musicbrainz.org/ws/2/recording",
        params={
            "query": query,
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
                "duration": milliseconds_to_seconds(recording.get("length")),
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


def musicbrainz_provider(runtime, artist: str, title: str, config: SourceConfig):
    return search_variants(
        lambda query: musicbrainz_candidates(runtime, query, config),
        artist,
        title,
        config,
        strict_query=f'artist:"{artist}" AND recording:"{title}"',
    )
