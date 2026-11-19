# SPDX-License-Identifier: GPL-3.0-or-later
"""The per-song download pipeline."""

import shutil
import tempfile
from pathlib import Path

from . import colors
from .config import build_source_config
from .constants import (
    DEFAULT_AUDIO_QUALITY,
    DEFAULT_LYRICS_TYPE,
    LYRICS_DEFAULT_ENABLED,
)
from .files import make_filename
from .images import download_best_cover
from .lyrics import fetch_lyrics, write_lrc_sidecar
from .providers.resolver import resolve_metadata
from .providers.spotify import find_spotify_track, get_track_metadata
from .tags import add_metadata
from .youtube import download_audio, find_youtube_video


def process_song(
    sp,
    input_artist,
    input_title,
    output,
    title_only,
    audio_format="mp3",
    audio_quality=DEFAULT_AUDIO_QUALITY,
    source_config=None,
    runtime=None,
    lyrics_type=None,
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

    if lyrics_type is None:
        lyrics_type = (
            source_config.lyrics_type
            if source_config is not None
            else DEFAULT_LYRICS_TYPE
        )

    print(
        f"{colors.label('Metadata:')} "
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
        print(f"{colors.skip('SKIP:')} already exists: {filename}")
        return True, "exists"

    if not youtube_enabled:
        print(f"{colors.error('FAILED:')} YouTube is disabled")
        return False, "YouTube disabled"

    video = find_youtube_video(
        metadata["artist"],
        metadata["title"],
    )

    if not video:
        print(f"{colors.error('FAILED:')} No YouTube result")
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
        print(f"{colors.error('FAILED:')} Invalid YouTube result")
        return False, "invalid YouTube result"

    with tempfile.TemporaryDirectory() as temp:
        temp_dir = Path(temp)

        audio_path = download_audio(
            video_url,
            temp_dir,
            audio_format,
            audio_quality,
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

        lyrics = None
        lyrics_enabled = (
            LYRICS_DEFAULT_ENABLED
            if source_config is None
            else source_config.lyrics_enabled
        )

        if lyrics_enabled:
            lyrics_error = False

            try:
                lyrics = fetch_lyrics(
                    metadata["artist"],
                    metadata["title"],
                    runtime,
                )

            except Exception as error:
                lyrics_error = True
                print(
                    f"{colors.label('Lyrics:')} "
                    f"{colors.muted(f'not found ({error})')}"
                )

            if lyrics:
                timed = bool(lyrics.get("synced"))
                kinds = "plain + timed" if timed else "plain"
                place = (
                    "sidecar + tags"
                    if lyrics_type == "sidecar" and timed
                    else "embedded"
                )
                print(
                    f"{colors.label('Lyrics:')} "
                    f"{colors.success(f'{place} ({kinds})')}"
                )

            elif not lyrics_error:
                print(f"{colors.label('Lyrics:')} {colors.muted('not found')}")

        try:
            add_metadata(
                audio_path,
                cover_path,
                metadata,
                lyrics,
                lyrics_type,
            )

        except Exception as error:
            return False, f"metadata error: {error}"

        try:
            shutil.move(
                str(audio_path),
                str(final_path),
            )

            try:
                write_lrc_sidecar(final_path, lyrics, lyrics_type)

            except OSError as error:
                print(
                    colors.warning(
                        f"WARNING: could not write LRC file: {error}"
                    )
                )

        except Exception as error:
            return False, f"move error: {error}"

    print(f"{colors.success('SUCCESS:')} {filename}")

    return True, "downloaded"
