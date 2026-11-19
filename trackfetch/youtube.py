# SPDX-License-Identifier: GPL-3.0-or-later
"""YouTube search, scoring and audio downloading through yt-dlp."""

import json
import subprocess
import unicodedata
from pathlib import Path

from . import colors
from .constants import (
    AUDIO_FORMATS,
    DEFAULT_AUDIO_QUALITY,
    YTDLP_REMOTE_COMPONENTS,
)
from .matching import normalize, similarity


def youtube_thumbnail_urls(video):
    """Return thumbnail URLs for a YouTube result, best first."""
    urls = []
    thumbnails = (video or {}).get("thumbnails")

    if isinstance(thumbnails, list):
        ordered = sorted(
            (
                item for item in thumbnails
                if isinstance(item, dict) and item.get("url")
            ),
            key=lambda item: (
                (item.get("width") or 0) * (item.get("height") or 0)
            ),
            reverse=True,
        )

        urls.extend(item["url"] for item in ordered)

    thumbnail = (video or {}).get("thumbnail")

    if isinstance(thumbnail, str) and thumbnail:
        urls.append(thumbnail)

    video_id = (video or {}).get("id")

    if video_id:
        urls.append(
            f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"
        )
        urls.append(
            f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
        )

    result = []

    for url in urls:
        if url not in result:
            result.append(url)

    return result


def youtube_search(query: str, limit: int = 5):
    command = [
        "yt-dlp",
        "--remote-components",
        YTDLP_REMOTE_COMPONENTS,
        "--flat-playlist",
        "--dump-json",
        f"ytsearch{limit}:{query}",
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    videos = []

    for line in result.stdout.splitlines():
        try:
            data = json.loads(line)
            videos.append(data)
        except json.JSONDecodeError:
            pass

    return videos


def score_youtube_result(
    video,
    artist: str,
    title: str,
    duration=None,
):
    video_title = video.get("title", "")

    title_score = similarity(title, video_title)
    artist_score = similarity(artist, video_title)

    # Many videos are "Artist - Song" or "Artist Song (Official Video)". When
    # the normalized title starts with the artist, that is a strong artist
    # signal, and the title is compared with the leftover words. A channel
    # name like "Metal Family “Artist - Song»" does not start with the artist,
    # so it keeps the whole-title comparison and is not inflated.
    normalized_video = normalize(video_title)
    normalized_artist = normalize(artist)

    if normalized_artist and normalized_video.startswith(normalized_artist):
        remainder = normalized_video[len(normalized_artist):].strip(" -")

        if remainder:
            artist_score = 1.0
            title_score = max(title_score, similarity(title, remainder))

    score = (
        title_score * 0.70
        + artist_score * 0.30
    )

    # Noise stripping is for matching. Bonus and penalty markers still need
    # to see the original words, including ones inside brackets.
    detected_video = unicodedata.normalize("NFC", video_title).lower()

    if "official audio" in detected_video:
        score += 0.08

    if "audio" in detected_video:
        score += 0.03

    bad_words = [
        "cover",
        "караоке",
        "karaoke",
        "nightcore",
        "sped up",
        "slowed",
        "remix",
        "reaction",
    ]

    for word in bad_words:
        if word in detected_video:
            score -= 0.20

    video_duration = video.get("duration")

    if duration is not None and video_duration is not None:
        try:
            difference = abs(float(video_duration) - float(duration))

        except (TypeError, ValueError):
            difference = None

        if difference is not None:
            if difference <= 3:
                score += 0.05

            elif difference <= 10:
                score += 0.02

    return score


def find_youtube_video(artist: str, title: str, duration=None):
    query = f"{artist} {title}"

    print(colors.muted(f"Searching YouTube: {query}"))

    videos = youtube_search(query, limit=5)

    if not videos:
        return None

    best_video = None
    best_score = -999.0

    for video in videos:
        score = score_youtube_result(
            video,
            artist,
            title,
            duration,
        )

        print(
            colors.muted(
                f"  YouTube score {score:.2f}: "
                f"{video.get('title', 'Unknown')}"
            )
        )

        if score > best_score:
            best_score = score
            best_video = video

    if best_video:
        print(
            f"{colors.label('Selected:')} "
            f"{best_video.get('title', 'Unknown')}"
        )

    return best_video

def download_audio(
    video_url: str,
    temp_dir: Path,
    audio_format: str = "mp3",
    audio_quality: int = DEFAULT_AUDIO_QUALITY,
):
    template = str(temp_dir / "audio.%(ext)s")

    command = [
        "yt-dlp",
        *AUDIO_FORMATS[audio_format],
        "-x",
        "--audio-format",
        audio_format,
        "--audio-quality",
        str(audio_quality),
        "--remote-components",
        YTDLP_REMOTE_COMPONENTS,
        "--no-playlist",
        "-o",
        template,
        video_url,
    ]

    result = subprocess.run(command)

    if result.returncode != 0:
        return None

    files = list(temp_dir.glob(f"audio.{audio_format}"))

    if not files:
        return None

    return files[0]
