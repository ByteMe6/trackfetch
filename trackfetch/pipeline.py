# SPDX-License-Identifier: GPL-3.0-or-later
"""The per-song download pipeline."""

import shutil
import tempfile
from pathlib import Path

from . import colors, soundcloud, youtube
from .config import build_source_config
from .constants import (
    DEFAULT_AUDIO_QUALITY,
    DEFAULT_LYRICS_TYPE,
    LYRICS_DEFAULT_ENABLED,
    SOUNDCLOUD_DEFAULT_AMBIGUOUS,
    SOUNDCLOUD_DEFAULT_TRIGGER,
)
from .errors import YoutubeSearchError
from .files import make_filename
from .images import download_best_cover
from .lyrics import fetch_lyrics, write_lrc_sidecar
from .providers.resolver import resolve_metadata
from .providers.spotify import find_spotify_track, get_track_metadata
from .tags import add_metadata
from .youtube import download_audio, find_youtube_video, probe_age_restriction


def _download_and_tag(
    metadata,
    video,
    video_url,
    output,
    title_only,
    audio_format,
    audio_quality,
    source_config,
    runtime,
    lyrics_type,
    youtube_enabled,
):
    """Download one chosen result, tag it and move it into place.

    Returns ``(ok, reason, download_failed)``. ``download_failed`` is True
    only when yt-dlp itself returned no audio, so the caller can decide
    whether the result is an age restriction worth a fallback.
    """
    filename = make_filename(
        metadata,
        title_only,
        audio_format,
    )

    final_path = output / filename

    if final_path.exists():
        print(f"{colors.skip('SKIP:')} already exists: {filename}")
        return True, "exists", False

    with tempfile.TemporaryDirectory() as temp:
        temp_dir = Path(temp)

        audio_path = download_audio(
            video_url,
            temp_dir,
            audio_format,
            audio_quality,
        )

        if not audio_path:
            return False, "yt-dlp download failed", True

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
                    duration=metadata.get("duration"),
                )

            except Exception as error:
                lyrics_error = True
                print(
                    f"{colors.label('Lyrics:')} "
                    f"{colors.muted(f'not found ({error})')}"
                )

            if lyrics:
                timed = bool(lyrics.get("synced"))

                if timed:
                    place = (
                        "sidecar + tags"
                        if lyrics_type == "sidecar"
                        else "embedded"
                    )
                    print(
                        f"{colors.label('Lyrics:')} "
                        f"{colors.success(f'synced ({place})')}"
                    )

                else:
                    print(
                        f"{colors.label('Lyrics:')} "
                        f"{colors.muted('plain only (no synced version)')}"
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
            return False, f"metadata error: {error}", False

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
            return False, f"move error: {error}", False

    print(f"{colors.success('SUCCESS:')} {filename}")

    return True, "downloaded", False


def _soundcloud_artwork(candidate):
    """Return the largest SoundCloud artwork URL, or None."""
    thumbnails = candidate.get("thumbnails")

    if isinstance(thumbnails, list):
        ordered = sorted(
            (
                item
                for item in thumbnails
                if isinstance(item, dict) and item.get("url")
            ),
            key=lambda item: (
                (item.get("width") or 0) * (item.get("height") or 0),
                (item.get("width") or 0) + (item.get("height") or 0),
            ),
            reverse=True,
        )

        if ordered:
            return ordered[0]["url"]

    thumbnail = candidate.get("thumbnail")

    if isinstance(thumbnail, str) and thumbnail:
        return thumbnail

    return None


def _soundcloud_fallback(
    metadata,
    output,
    title_only,
    audio_format,
    audio_quality,
    source_config,
    runtime,
    lyrics_type,
    age_restricted=None,
):
    """Search SoundCloud and download at most once.

    Nothing is downloaded until a single candidate is either confident or
    explicitly chosen by the user. Returns ``(ok, reason)``.
    """
    if age_restricted is True:
        print(
            colors.warning(
                "AGE-RESTRICTED: YouTube requires sign-in for this video."
            )
        )

    else:
        print(
            colors.muted(
                "YouTube had no usable result; looking for the track "
                "on SoundCloud."
            )
        )

    result = soundcloud.find_soundcloud_fallback(
        metadata["artist"],
        metadata["title"],
        metadata.get("duration"),
        enabled=source_config.soundcloud_enabled,
        min_score=source_config.soundcloud_min_score,
        min_margin=source_config.soundcloud_min_margin,
        ambiguous=getattr(
            source_config,
            "soundcloud_ambiguous",
            SOUNDCLOUD_DEFAULT_AMBIGUOUS,
        ),
    )

    if not result.selected or not result.candidate:
        return False, soundcloud.describe_failure(result)

    # The search results were already enriched with --dump-single-json
    # metadata, so the selected candidate is verified without another call.
    candidate = result.candidate

    blocked = soundcloud.blocked_reason(candidate)

    if blocked:
        print(colors.error(f"FAILED: SoundCloud track {blocked}"))
        return False, f"SoundCloud {blocked}"

    preview = soundcloud.preview_reason(
        candidate,
        metadata.get("duration"),
    )

    if preview:
        print(colors.error(f"FAILED: SoundCloud track is {preview}"))
        return False, f"SoundCloud {preview}"

    webpage_url = candidate.get("webpage_url")

    if not webpage_url:
        print(f"{colors.error('FAILED:')} Invalid SoundCloud result")
        return False, "invalid SoundCloud result"

    print(
        f"{colors.label('Selected:')} "
        f"{candidate.get('title', 'Unknown')} "
        f"{colors.muted('(SoundCloud)')}"
    )

    # Keep the provider artwork; only add SoundCloud art when the metadata
    # source had none, so the tags stay consistent with the rest of the run.
    tagged_metadata = metadata

    if not metadata.get("cover_url"):
        artwork = _soundcloud_artwork(candidate)

        if artwork:
            tagged_metadata = dict(metadata)
            tagged_metadata["cover_url"] = artwork

    ok, reason, _failed = _download_and_tag(
        tagged_metadata,
        {
            "title": candidate.get("title"),
            "thumbnails": candidate.get("thumbnails"),
            "thumbnail": candidate.get("thumbnail"),
        },
        webpage_url,
        output,
        title_only,
        audio_format,
        audio_quality,
        source_config,
        runtime,
        lyrics_type,
        # SoundCloud artwork replaces the YouTube thumbnail fallback.
        False,
    )

    return ok, reason


def _fallback_allowed(reason, source_config, age_restricted=None):
    """Decide whether the SoundCloud fallback may run for this failure.

    The trigger is configurable: ``age`` keeps the safe default of only an
    age restriction, ``age-or-missing`` also covers a YouTube search that
    found nothing usable, and ``any`` covers every failed search or
    download. Error handling is otherwise unchanged.
    """
    if source_config is None or not source_config.soundcloud_enabled:
        return False

    trigger = getattr(
        source_config,
        "soundcloud_trigger",
        SOUNDCLOUD_DEFAULT_TRIGGER,
    )

    if trigger == "age":
        return age_restricted is True

    if trigger == "age-or-missing":
        if age_restricted is True:
            return True

        return reason in ("no confident YouTube match", "no YouTube result")

    return trigger == "any"


def _maybe_soundcloud_fallback(
    reason,
    metadata,
    output,
    title_only,
    audio_format,
    audio_quality,
    source_config,
    runtime,
    lyrics_type,
    age_restricted=None,
):
    """Run the SoundCloud fallback when the trigger allows it.

    Returns the normal ``(ok, reason)`` pair, falling back to the original
    failure reason when SoundCloud is not allowed or finds nothing.
    """
    if not _fallback_allowed(reason, source_config, age_restricted):
        return False, reason

    return _soundcloud_fallback(
        metadata,
        output,
        title_only,
        audio_format,
        audio_quality,
        source_config,
        runtime,
        lyrics_type,
        age_restricted=age_restricted,
    )


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

    if (output / filename).exists():
        print(f"{colors.skip('SKIP:')} already exists: {filename}")
        return True, "exists"

    if not youtube_enabled:
        print(f"{colors.error('FAILED:')} YouTube is disabled")
        return False, "YouTube disabled"

    youtube.LAST_SEARCH_HAD_CANDIDATES = False

    try:
        video = find_youtube_video(
            metadata["artist"],
            metadata["title"],
            metadata.get("duration"),
        )

    except YoutubeSearchError as error:
        print(f"{colors.error('FAILED:')} yt-dlp search failed: {error}")
        return False, "yt-dlp search failed"

    if not video:
        if youtube.LAST_SEARCH_HAD_CANDIDATES:
            reason = "no confident YouTube match"
            print(f"{colors.error('FAILED:')} No confident YouTube match")

        else:
            reason = "no YouTube result"
            print(f"{colors.error('FAILED:')} No YouTube result")

        return _maybe_soundcloud_fallback(
            reason,
            metadata,
            output,
            title_only,
            audio_format,
            audio_quality,
            source_config,
            runtime,
            lyrics_type,
        )

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

    ok, reason, download_failed = _download_and_tag(
        metadata,
        video,
        video_url,
        output,
        title_only,
        audio_format,
        audio_quality,
        source_config,
        runtime,
        lyrics_type,
        youtube_enabled,
    )

    if ok or not download_failed:
        return ok, reason

    # A metadata-only probe identifies an age restriction without touching
    # YouTube authentication. Other failures only reach SoundCloud when the
    # user explicitly widened the trigger.
    age_restricted = probe_age_restriction(video_url)

    return _maybe_soundcloud_fallback(
        reason,
        metadata,
        output,
        title_only,
        audio_format,
        audio_quality,
        source_config,
        runtime,
        lyrics_type,
        age_restricted=age_restricted,
    )
