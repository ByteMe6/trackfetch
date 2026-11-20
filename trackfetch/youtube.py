# SPDX-License-Identifier: GPL-3.0-or-later
"""YouTube search, scoring and audio downloading through yt-dlp."""

import json
import re
import subprocess
import unicodedata
from pathlib import Path
from urllib.parse import quote_plus

from unidecode import unidecode

from . import colors
from .constants import (
    AUDIO_FORMATS,
    DEFAULT_AUDIO_QUALITY,
    DEFAULT_TITLE_THRESHOLD,
    YOUTUBE_MIN_SCORE,
    YOUTUBE_MUSIC_DETAIL_CANDIDATES,
    YOUTUBE_MUSIC_MAX_DURATION_DIFF,
    YOUTUBE_MUSIC_SEARCH_LIMIT,
    YTDLP_REMOTE_COMPONENTS,
)
from .errors import YoutubeSearchError
from .matching import MIN_ARTIST_SIMILARITY, normalize, similarity

# Set by find_youtube_video() so callers can tell "nothing was found at all"
# apart from "results existed, but none was confident enough".
LAST_SEARCH_HAD_CANDIDATES = False

# yt-dlp phrases that specifically mean "age restriction". Anything else,
# such as "Video unavailable", "Private video" or a network error, must keep
# the existing failure handling and must not trigger a fallback.
AGE_RESTRICTION_PATTERNS = (
    "sign in to confirm your age",
    "confirm your age",
    "age-restricted",
    "age restricted",
    "age_verification_required",
    "age_check_required",
    "inappropriate for some users",
    "age-gate",
    "age gate",
    "age verification required",
    "requires age verification",
)


def is_age_restriction_error(text) -> bool:
    """Whether a yt-dlp error message is an age-restriction error.

    Only the specific age-gate phrases count. Login prompts for other
    reasons ("confirm you're not a bot"), unavailable/private videos and
    network failures return False.
    """
    if not text:
        return False

    lowered = str(text).lower()
    return any(pattern in lowered for pattern in AGE_RESTRICTION_PATTERNS)


VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


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


def _search_error(result):
    """Build the exception for a failed yt-dlp run, keeping its stderr."""
    returncode = getattr(result, "returncode", 0)
    stderr = (getattr(result, "stderr", "") or "").strip()
    error = YoutubeSearchError(
        f"yt-dlp search failed (exit {returncode})"
        + (f": {stderr}" if stderr else "")
    )
    error.stderr = stderr
    return error


def _run_ytdlp(command):
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _json_lines(output):
    videos = []

    for line in output.splitlines():
        try:
            data = json.loads(line)
            videos.append(data)
        except json.JSONDecodeError:
            pass

    return videos


def youtube_search(query: str, limit: int = 5):
    command = [
        "yt-dlp",
        "--remote-components",
        YTDLP_REMOTE_COMPONENTS,
        "--flat-playlist",
        "--dump-json",
        f"ytsearch{limit}:{query}",
    ]

    result = _run_ytdlp(command)

    if getattr(result, "returncode", 0) != 0:
        raise _search_error(result)

    return _json_lines(result.stdout)


def youtube_music_search(
    query: str,
    limit: int = YOUTUBE_MUSIC_SEARCH_LIMIT,
):
    """Search YouTube Music, which is not filtered like anonymous ytsearch.

    The Music search endpoint returns entries for playlists, channels and
    albums too, so only 11-character video ids are kept. The flat result has
    no artist or duration; callers must verify candidates with
    youtube_video_details().
    """
    url = (
        "https://music.youtube.com/search?q="
        + quote_plus(query)
        + "#songs"
    )
    command = [
        "yt-dlp",
        "--remote-components",
        YTDLP_REMOTE_COMPONENTS,
        "--flat-playlist",
        "-I",
        f"1:{limit}",
        "--dump-json",
        url,
    ]

    result = _run_ytdlp(command)

    if getattr(result, "returncode", 0) != 0:
        raise _search_error(result)

    return [
        data
        for data in _json_lines(result.stdout)
        if isinstance(data, dict)
        and VIDEO_ID_RE.match(str(data.get("id") or ""))
    ]


def youtube_video_details(video_id):
    """Fetch full metadata for one video id."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    command = [
        "yt-dlp",
        "--remote-components",
        YTDLP_REMOTE_COMPONENTS,
        "--skip-download",
        "--no-playlist",
        "--dump-single-json",
        url,
    ]

    result = _run_ytdlp(command)

    if getattr(result, "returncode", 0) != 0:
        raise _search_error(result)

    try:
        return json.loads(result.stdout)

    except json.JSONDecodeError:
        raise YoutubeSearchError(
            f"yt-dlp returned invalid details for {video_id}"
        ) from None


def _transliterate(text) -> str:
    """Return a Latin-script form, dropping the apostrophes Unidecode adds.

    Unidecode renders some Cyrillic letters with an apostrophe, turning the
    transliteration into separate words after normalization. Removing the
    apostrophes keeps the artist name as one token.
    """
    return unidecode(text or "").replace("'", "")


def _forms(text):
    """Return the original and Latin-script forms of a string."""
    text = text or ""
    return (text, _transliterate(text))


def _cross_script_similarity(a: str, b: str) -> float:
    """Compare strings in their original scripts and in Latin."""
    return max(
        similarity(a, b),
        similarity(_transliterate(a), _transliterate(b)),
    )


def _contains_artist(artist: str, text: str) -> bool:
    """Whether the artist appears in text in either the original script or Latin."""
    if not artist or not text:
        return False

    for artist_form, text_form in zip(_forms(artist), _forms(text), strict=False):
        normalized_artist = normalize(artist_form)
        normalized_text = normalize(text_form)

        if normalized_artist and normalized_artist in normalized_text:
            return True

    return False


def _artist_score(artist: str, title: str, video_title: str, channel: str):
    """Compare the artist with the title, the channel and their Latin forms."""
    video_title = video_title or ""
    channel = channel or ""

    best = max(
        similarity(artist, video_title),
        similarity(_transliterate(artist), _transliterate(video_title)),
    )
    title_boost = 0.0

    # Many videos are "Artist - Song" or "Artist Song (Official Video)". When
    # the normalized title starts with the artist, that is a strong artist
    # signal, and the title is compared with the leftover words. Transcoding
    # to Latin makes this work across scripts, so a Latin artist name can
    # match a Cyrillic "Artist - Song" upload. A channel name like
    # "Metal Family “Artist - Song»" does not start with the artist, so it is
    # not inflated.
    for artist_form, title_form in zip(_forms(artist), _forms(video_title), strict=False):
        normalized_artist = normalize(artist_form)
        normalized_video = normalize(title_form)

        if normalized_artist and normalized_video.startswith(normalized_artist):
            remainder = normalized_video[len(normalized_artist):].strip(" -")

            if remainder:
                best = 1.0
                title_boost = max(
                    title_boost,
                    similarity(title, remainder),
                    similarity(_transliterate(title), remainder),
                )

    channel_score = 0.0

    if channel:
        channel_score = max(
            similarity(artist, channel),
            similarity(_transliterate(artist), _transliterate(channel)),
        )

        for artist_form, channel_form in zip(_forms(artist), _forms(channel), strict=False):
            normalized_artist = normalize(artist_form)
            normalized_channel = normalize(channel_form)

            if normalized_artist and normalized_channel.startswith(normalized_artist):
                channel_score = 1.0

    return max(best, channel_score), title_boost, channel_score


def _duration_difference(video_duration, duration):
    if duration is None or video_duration is None:
        return None

    try:
        return abs(float(video_duration) - float(duration))

    except (TypeError, ValueError):
        return None


def _has_artist_evidence(video, artist: str, title: str, duration) -> bool:
    """Whether a title-only search result can be trusted.

    A query without the artist can return covers, other artists' songs with the
    same title, or audiobooks. The artist must appear in the title or channel,
    or the duration must be close to the expected one.
    """
    video_title = video.get("title", "")
    channel = video.get("channel") or video.get("uploader") or ""

    if _contains_artist(artist, video_title) or _contains_artist(artist, channel):
        return True

    difference = _duration_difference(video.get("duration"), duration)

    return difference is not None and difference <= 5


def score_youtube_result(
    video,
    artist: str,
    title: str,
    duration=None,
):
    video_title = video.get("title", "")
    channel = video.get("channel") or video.get("uploader") or ""

    title_score = similarity(title, video_title)
    artist_score, title_boost, channel_score = _artist_score(
        artist,
        title,
        video_title,
        channel,
    )
    title_score = max(title_score, title_boost)

    score = (
        title_score * 0.70
        + artist_score * 0.30
    )

    # A channel that matches the artist is extra evidence, and a "- Topic"
    # channel is the cleanest signal that YouTube itself uploaded the track.
    if channel and channel_score >= 0.6:
        if normalize(channel).endswith("topic"):
            score += 0.15

        else:
            score += 0.10

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
        # Whole words only: "Discovery" must not trigger "cover".
        if re.search(rf"(?<!\w){re.escape(word)}(?!\w)", detected_video):
            score -= 0.20

    difference = _duration_difference(video.get("duration"), duration)

    if difference is not None:
        if difference <= 3:
            score += 0.05

        elif difference <= 10:
            score += 0.02

    return score


def _search_queries(artist: str, title: str):
    """Return the query ladder: artist+title, then title-only variants."""
    queries = []

    for query in (f"{artist} {title}", title, f"{title} Topic"):
        query = " ".join((query or "").split())

        if query and query not in queries:
            queries.append(query)

    return queries


def _details_artist_names(details):
    names = []
    artist = details.get("artist")

    if artist:
        names.append(artist)

    artists = details.get("artists")

    if isinstance(artists, list):
        names.extend(name for name in artists if name)

    for key in ("channel", "uploader"):
        value = details.get(key)

        if value:
            names.append(value)

    return names


def _details_artist_similarity(artist, details):
    return max(
        (
            _cross_script_similarity(artist, name)
            for name in _details_artist_names(details)
        ),
        default=0.0,
    )


def _music_fallback(artist: str, title: str, duration=None):
    """Try YouTube Music when the three plain searches found nothing usable.

    YouTube filters anonymous ytsearch results for some topics. The Music
    search endpoint is not filtered, but its flat results carry no artist or
    duration, so each plausible title is verified with a details call before
    it can be used.
    """
    global LAST_SEARCH_HAD_CANDIDATES

    query = " ".join(f"{artist} {title}".split())
    print(colors.muted(f"Searching YouTube Music: {query}"))

    flat = youtube_music_search(query)

    if not flat:
        return None

    LAST_SEARCH_HAD_CANDIDATES = True
    ranked = []

    for video in flat:
        title_score = _cross_script_similarity(
            title,
            video.get("title", ""),
        )

        if title_score >= DEFAULT_TITLE_THRESHOLD:
            ranked.append((title_score, video.get("id")))

    ranked.sort(key=lambda item: item[0], reverse=True)

    best_video = None
    best_score = -999.0

    for _, video_id in ranked[:YOUTUBE_MUSIC_DETAIL_CANDIDATES]:
        try:
            details = youtube_video_details(video_id)

        # A single failing details call must not lose the other candidates.
        except YoutubeSearchError:
            continue

        if _details_artist_similarity(artist, details) < MIN_ARTIST_SIMILARITY:
            continue

        difference = _duration_difference(
            details.get("duration"),
            duration,
        )

        if (
            difference is not None
            and difference > YOUTUBE_MUSIC_MAX_DURATION_DIFF
        ):
            continue

        score = score_youtube_result(details, artist, title, duration)
        print(
            colors.muted(
                f"  YouTube score {score:.2f}: "
                f"{details.get('title', 'Unknown')}"
            )
        )

        if score > best_score:
            best_score = score
            best_video = details

    if best_video:
        print(
            f"{colors.label('Selected:')} "
            f"{best_video.get('title', 'Unknown')}"
        )

    return best_video


def find_youtube_video(artist: str, title: str, duration=None):
    global LAST_SEARCH_HAD_CANDIDATES

    LAST_SEARCH_HAD_CANDIDATES = False
    seen = set()
    scored = []

    for index, query in enumerate(_search_queries(artist, title)):
        print(colors.muted(f"Searching YouTube: {query}"))

        videos = youtube_search(query, limit=5)
        added = False

        for video in videos or []:
            key = video.get("id") or (
                video.get("title"),
                video.get("channel") or video.get("uploader"),
            )

            if key in seen:
                continue

            seen.add(key)
            added = True

            score = score_youtube_result(
                video,
                artist,
                title,
                duration,
            )
            scored.append((score, video, index == 0))

            print(
                colors.muted(
                    f"  YouTube score {score:.2f}: "
                    f"{video.get('title', 'Unknown')}"
                )
            )

        if not videos or not added:
            continue

        LAST_SEARCH_HAD_CANDIDATES = True
        best_video = None
        best_score = -999.0

        for score, video, artist_query in scored:
            if score < YOUTUBE_MIN_SCORE:
                continue

            if not artist_query and not _has_artist_evidence(
                video,
                artist,
                title,
                duration,
            ):
                continue

            if score > best_score:
                best_score = score
                best_video = video

        if best_video:
            print(
                f"{colors.label('Selected:')} "
                f"{best_video.get('title', 'Unknown')}"
            )

            return best_video

    return _music_fallback(artist, title, duration)


def probe_age_restriction(video_url, timeout=60):
    """Return whether fetching this video fails *specifically* on age.

    A metadata-only yt-dlp call reproduces the same gate as the download.
    It never attempts authentication, cookies or alternate clients: the
    answer is simply "is this error an age restriction". Malformed output,
    timeouts, network errors and every other failure return False so the
    existing handling stays in charge.
    """
    if not video_url:
        return False

    command = [
        "yt-dlp",
        "--skip-download",
        "--no-playlist",
        "--dump-single-json",
        video_url,
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )

    except (subprocess.TimeoutExpired, OSError):
        return False

    if getattr(result, "returncode", 0) == 0:
        return False

    return is_age_restriction_error(
        getattr(result, "stderr", "") or ""
    )


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
