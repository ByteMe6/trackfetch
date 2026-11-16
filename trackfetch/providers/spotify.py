# SPDX-License-Identifier: GPL-3.0-or-later
"""Spotify metadata provider (optional, requires client credentials)."""

import os

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

from ..config import SourceConfig
from ..errors import ProviderAuthError, ProviderError
from ..matching import similarity


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
