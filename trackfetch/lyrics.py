# SPDX-License-Identifier: GPL-3.0-or-later
"""LRCLIB lyrics lookup and LRC parsing."""

import requests
from mutagen.id3 import SYLT, USLT

from .constants import (
    DEFAULT_MATCH_THRESHOLD,
    DEFAULT_TITLE_THRESHOLD,
    LRC_TIMESTAMP_RE,
    LRCLIB_SEARCH_URL,
    LYRICS_LANGUAGE,
    LYRICS_TIMEOUT,
    USER_AGENT,
)
from .errors import ProviderError
from .matching import score_metadata


def lrc_fraction_to_ms(fraction: str) -> int:
    """Convert the fractional part of an LRC timestamp to milliseconds."""
    if not fraction:
        return 0

    return int(fraction.ljust(3, "0")[:3])


def parse_synced_lyrics(text: str):
    """Parse LRC text into (line, timestamp in milliseconds) pairs."""
    entries = []

    for line in (text or "").splitlines():
        timestamps = LRC_TIMESTAMP_RE.findall(line)

        if not timestamps:
            # LRC metadata such as [ar:Artist] has no timestamp and is skipped.
            continue

        lyric = LRC_TIMESTAMP_RE.sub("", line).strip()

        if not lyric:
            continue

        for minutes, seconds, fraction in timestamps:
            timestamp = (
                int(minutes) * 60_000
                + int(seconds) * 1000
                + lrc_fraction_to_ms(fraction)
            )
            entries.append((lyric, timestamp))

    entries.sort(key=lambda entry: entry[1])

    return entries


def select_lyrics(results, artist: str, title: str):
    """Choose the best matching lyrics result and normalize its fields."""
    best = None

    for item in results or []:
        if not isinstance(item, dict) or item.get("instrumental"):
            continue

        candidate = {
            "title": item.get("trackName") or "",
            "artist": item.get("artistName") or "",
        }
        scored = score_metadata(
            artist,
            title,
            candidate,
            DEFAULT_MATCH_THRESHOLD,
            DEFAULT_TITLE_THRESHOLD,
        )

        if scored is None:
            continue

        plain = (item.get("plainLyrics") or "").strip()
        synced = (item.get("syncedLyrics") or "").strip()
        synced_entries = parse_synced_lyrics(synced)

        if not plain and synced_entries:
            # Some sources only return timed lyrics. USLT still has to hold the
            # full text, so strip the timestamps without inventing new ones.
            plain = "\n".join(line for line, _ in synced_entries)

        if not plain and not synced_entries:
            continue

        lyrics = {
            "plain": plain or None,
            "synced": synced or None,
            "score": scored["score"],
        }

        if best is None or lyrics["score"] > best["score"]:
            best = lyrics

    return best


def fetch_lyrics(
    artist: str,
    title: str,
    runtime=None,
    timeout: float = LYRICS_TIMEOUT,
):
    """Look up lyrics on LRCLIB, which returns plain and timed lyrics.

    Missing lyrics are a normal result, not an error. Transport and server
    errors raise ProviderError so the caller can report them without failing
    the download.
    """
    params = {
        "artist_name": artist,
        "track_name": title,
    }

    headers = {"User-Agent": USER_AGENT}

    try:
        if runtime is not None:
            runtime.limiter.wait("lrclib")
            response = runtime.session.get(
                LRCLIB_SEARCH_URL,
                params=params,
                headers=headers,
                timeout=timeout,
            )
        else:
            response = requests.get(
                LRCLIB_SEARCH_URL,
                params=params,
                headers=headers,
                timeout=timeout,
            )

    except requests.RequestException as error:
        raise ProviderError(f"lyrics request failed: {error}") from error

    status = getattr(response, "status_code", 200)

    if status == 404:
        return None

    if status >= 400:
        raise ProviderError(f"lyrics source returned HTTP {status}")

    try:
        results = response.json()

    except (TypeError, ValueError) as error:
        raise ProviderError("lyrics source returned invalid JSON") from error

    if isinstance(results, dict):
        results = results.get("data") or []

    return select_lyrics(results, artist, title)


def add_mp3_lyrics(audio, lyrics):
    """Add or replace USLT/SYLT frames without touching other ID3 tags."""
    if not lyrics:
        # No new lyrics is not a reason to delete lyrics that are already there.
        return

    plain = (lyrics.get("plain") or "").strip()
    synced_entries = parse_synced_lyrics(lyrics.get("synced") or "")

    if not plain and synced_entries:
        plain = "\n".join(line for line, _ in synced_entries)

    if not plain and not synced_entries:
        return

    audio.delall("USLT")
    audio.delall("SYLT")

    if plain:
        audio.add(
            USLT(
                encoding=3,
                lang=LYRICS_LANGUAGE,
                desc="",
                text=plain,
            )
        )

    if synced_entries:
        audio.add(
            SYLT(
                encoding=3,
                lang=LYRICS_LANGUAGE,
                format=2,
                type=1,
                desc="",
                text=synced_entries,
            )
        )
