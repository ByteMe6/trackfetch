#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later

import argparse
import base64
import configparser
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import requests
import spotipy
from mutagen.flac import Picture
from mutagen.id3 import (
    APIC,
    ID3,
    TALB,
    TDRC,
    TIT2,
    TPE1,
    TPE2,
    TRCK,
)
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggopus import OggOpus
from spotipy.oauth2 import SpotifyClientCredentials

YTDLP_REMOTE_COMPONENTS = "ejs:github"

CONFIG_SECTION = "trackfetch"
CONFIG_FILENAME = "trackfetch.ini"
CONFIG_ENV = "TRACKFETCH_CONFIG"

DEFAULT_FORMAT = "m4a"
DEFAULT_DELAY = 1.0

AUDIO_FORMATS = {
    "mp3": [],
    "m4a": [
        "-f",
        "bestaudio[ext=m4a]/bestaudio",
    ],
    "opus": [
        "-f",
        "bestaudio[acodec=opus]/bestaudio",
    ],
}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(
        None,
        normalize(a),
        normalize(b)
    ).ratio()


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = re.sub(r"\s+", " ", name).strip()

    return name[:200]


def parse_song(line: str):
    if " - " not in line:
        return None

    artist, title = line.split(" - ", 1)

    artist = artist.strip()
    title = title.strip()

    if not artist or not title:
        return None

    return artist, title


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
    client_id, client_secret = spotify_credentials(args)

    if not client_id or not client_secret:
        print("\nERROR: Spotify credentials not found.")
        print("Set them in the config file:")
        print("[trackfetch]")
        print("spotify_client_id = '...'")
        print("spotify_client_secret = '...'")
        print("or in the environment:")
        print("export SPOTIFY_CLIENT_ID='...'")
        print("export SPOTIFY_CLIENT_SECRET='...'")
        sys.exit(1)

    return spotipy.Spotify(
        auth_manager=SpotifyClientCredentials(
            client_id=client_id,
            client_secret=client_secret,
        ),
        requests_timeout=30,
        retries=3,
    )


def find_spotify_track(sp, artist: str, title: str):
    query = f'artist:"{artist}" track:"{title}"'

    try:
        results = sp.search(
            q=query,
            type="track",
            limit=10,
        )
    except Exception as error:
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


def download_cover(url: str, destination: Path):
    response = requests.get(
        url,
        timeout=30,
        headers={
            "User-Agent": "trackfetch/2.2.6"
        },
    )

    response.raise_for_status()

    destination.write_bytes(response.content)


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
):
    video_title = video.get("title", "")

    title_score = similarity(title, video_title)

    artist_score = similarity(artist, video_title)

    score = (
        title_score * 0.70
        + artist_score * 0.30
    )

    normalized_video = normalize(video_title)

    if "official audio" in normalized_video:
        score += 0.08

    if "audio" in normalized_video:
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
        if word in normalized_video:
            score -= 0.20

    return score


def find_youtube_video(artist: str, title: str):
    query = f"{artist} {title}"

    print(f"Searching YouTube: {query}")

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
        )

        print(
            f"  YouTube score {score:.2f}: "
            f"{video.get('title', 'Unknown')}"
        )

        if score > best_score:
            best_score = score
            best_video = video

    if best_video:
        print(
            f"Selected: "
            f"{best_video.get('title', 'Unknown')}"
        )

    return best_video


def download_audio(
    video_url: str,
    temp_dir: Path,
    audio_format: str = "mp3",
):
    template = str(temp_dir / "audio.%(ext)s")

    command = [
        "yt-dlp",
        *AUDIO_FORMATS[audio_format],
        "-x",
        "--audio-format",
        audio_format,
        "--audio-quality",
        "0",
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


def add_metadata(
    audio_path: Path,
    cover_path: Path,
    metadata: dict,
):
    if audio_path.suffix == ".opus":
        add_opus_metadata(
            audio_path,
            cover_path,
            metadata,
        )
    elif audio_path.suffix == ".m4a":
        add_m4a_metadata(
            audio_path,
            cover_path,
            metadata,
        )
    else:
        add_mp3_metadata(
            audio_path,
            cover_path,
            metadata,
        )


def add_mp3_metadata(
    mp3_path: Path,
    cover_path: Path,
    metadata: dict,
):
    try:
        audio = ID3(mp3_path)
    except Exception:
        audio = ID3()

    for tag in [
        "APIC",
        "TIT2",
        "TPE1",
        "TALB",
        "TPE2",
        "TRCK",
        "TDRC",
    ]:
        audio.delall(tag)

    audio.add(
        TIT2(
            encoding=3,
            text=metadata["title"],
        )
    )

    audio.add(
        TPE1(
            encoding=3,
            text=metadata["artist"],
        )
    )

    if metadata["album"]:
        audio.add(
            TALB(
                encoding=3,
                text=metadata["album"],
            )
        )

    if metadata["album_artist"]:
        audio.add(
            TPE2(
                encoding=3,
                text=metadata["album_artist"],
            )
        )

    if metadata["track_number"]:
        audio.add(
            TRCK(
                encoding=3,
                text=str(metadata["track_number"]),
            )
        )

    if metadata["release_date"]:
        audio.add(
            TDRC(
                encoding=3,
                text=str(metadata["release_date"]),
            )
        )

    if cover_path.exists():
        image_data = cover_path.read_bytes()

        audio.add(
            APIC(
                encoding=3,
                mime="image/jpeg",
                type=3,
                desc="Cover",
                data=image_data,
            )
        )

    audio.save(
        mp3_path,
        v2_version=3,
    )


def add_opus_metadata(
    opus_path: Path,
    cover_path: Path,
    metadata: dict,
):
    audio = OggOpus(opus_path)

    fields = {
        "TITLE": metadata["title"],
        "ARTIST": metadata["artist"],
        "ALBUM": metadata["album"],
        "ALBUMARTIST": metadata["album_artist"],
        "TRACKNUMBER": metadata["track_number"],
        "DATE": metadata["release_date"],
    }

    for key in [*fields, "METADATA_BLOCK_PICTURE"]:
        if key in audio:
            del audio[key]

    for key, value in fields.items():
        if value:
            audio[key] = str(value)

    if cover_path.exists():
        picture = Picture()
        picture.type = 3
        picture.mime = "image/jpeg"
        picture.desc = "Cover"
        picture.data = cover_path.read_bytes()

        audio["METADATA_BLOCK_PICTURE"] = base64.b64encode(
            picture.write()
        ).decode("ascii")

    audio.save()


def add_m4a_metadata(
    m4a_path: Path,
    cover_path: Path,
    metadata: dict,
):
    audio = MP4(m4a_path)

    fields = {
        "\xa9nam": metadata["title"],
        "\xa9ART": metadata["artist"],
        "\xa9alb": metadata["album"],
        "aART": metadata["album_artist"],
        "\xa9day": metadata["release_date"],
    }

    for key in [*fields, "trkn", "covr"]:
        if key in audio:
            del audio[key]

    for key, value in fields.items():
        if value:
            audio[key] = [str(value)]

    if metadata["track_number"]:
        audio["trkn"] = [
            (int(metadata["track_number"]), 0)
        ]

    if cover_path.exists():
        audio["covr"] = [
            MP4Cover(
                cover_path.read_bytes(),
                imageformat=MP4Cover.FORMAT_JPEG,
            )
        ]

    audio.save()


def make_filename(metadata, title_only, audio_format="mp3"):
    if title_only:
        name = metadata["title"]
    else:
        name = (
            f"{metadata['artist']} - "
            f"{metadata['title']}"
        )

    return sanitize_filename(name) + "." + audio_format


def read_done(done_file: Path):
    if not done_file.exists():
        return set()

    return {
        line.strip()
        for line in done_file.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()
        if line.strip()
    }


def append_line(path: Path, text: str):
    with path.open(
        "a",
        encoding="utf-8",
    ) as file:
        file.write(text + "\n")


def process_song(
    sp,
    input_artist,
    input_title,
    output,
    title_only,
    audio_format="mp3",
):
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

    print(
        f"Metadata: "
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
        print(f"SKIP: already exists: {filename}")
        return True, "exists"

    video = find_youtube_video(
        metadata["artist"],
        metadata["title"],
    )

    if not video:
        print("FAILED: No YouTube result")
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
        print("FAILED: Invalid YouTube result")
        return False, "invalid YouTube result"

    with tempfile.TemporaryDirectory() as temp:
        temp_dir = Path(temp)

        audio_path = download_audio(
            video_url,
            temp_dir,
            audio_format,
        )

        if not audio_path:
            return False, "yt-dlp download failed"

        cover_path = temp_dir / "cover.jpg"

        if metadata["cover_url"]:
            try:
                download_cover(
                    metadata["cover_url"],
                    cover_path,
                )

                print("Spotify cover downloaded")

            except Exception as error:
                print(
                    f"WARNING: cover download failed: "
                    f"{error}"
                )

        try:
            add_metadata(
                audio_path,
                cover_path,
                metadata,
            )

        except Exception as error:
            return False, f"metadata error: {error}"

        try:
            shutil.move(
                str(audio_path),
                str(final_path),
            )

        except Exception as error:
            return False, f"move error: {error}"

    print(f"SUCCESS: {filename}")

    return True, "downloaded"


def config_candidates():
    """Config file locations, in the order they are looked up."""
    candidates = []

    env = os.getenv(CONFIG_ENV)

    if env:
        candidates.append(Path(env).expanduser())

    candidates.append(Path.cwd() / CONFIG_FILENAME)

    xdg = os.getenv("XDG_CONFIG_HOME")

    if xdg:
        candidates.append(
            Path(xdg).expanduser() / "trackfetch" / CONFIG_FILENAME
        )

    candidates.append(
        Path.home() / ".config" / "trackfetch" / CONFIG_FILENAME
    )
    candidates.append(Path.home() / CONFIG_FILENAME)

    return candidates


def find_config_file(explicit=None):
    """Return the config file to use, or None if there is none."""
    if explicit is not None:
        return Path(explicit).expanduser()

    for candidate in config_candidates():
        if candidate.is_file():
            return candidate

    return None


def load_config(explicit=None):
    """Read settings from a config file.

    Returns a (settings, path) tuple. Settings is empty when no config file
    exists. Raises FileNotFoundError when an explicitly requested file is
    missing, and configparser.Error when the file cannot be parsed.
    """
    config_path = find_config_file(explicit)

    if config_path is None:
        return {}, None

    if not config_path.is_file():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    parser = configparser.ConfigParser()

    with config_path.open(encoding="utf-8") as file:
        parser.read_file(file)

    settings = dict(parser.defaults())

    if parser.has_section(CONFIG_SECTION):
        settings.update(dict(parser[CONFIG_SECTION]))

    return settings, config_path


def config_str_value(settings, key):
    """Read a plain string setting, or None when it is missing or blank."""
    value = (settings.get(key) or "").strip()

    if not value:
        return None

    return value


def config_path_value(settings, key):
    """Read a path-like setting, or None when it is missing or blank."""
    value = config_str_value(settings, key)

    if value is None:
        return None

    return Path(value).expanduser()


def resolve_output(cli_output, settings):
    """Pick the output directory: flag > config file > current directory."""
    if cli_output is not None:
        return Path(cli_output).expanduser()

    from_config = config_path_value(settings, "output")

    if from_config is not None:
        return from_config

    return Path.cwd()


def coerce_config_value(action, raw):
    """Convert a raw config value into the type the CLI option expects."""
    if action.type is Path:
        return Path(raw).expanduser()

    if action.type is float:
        return float(raw)

    if action.type is int:
        return int(raw)

    if isinstance(action, argparse._StoreTrueAction):
        return raw.lower() in ("1", "true", "yes", "on")

    return raw


def apply_config(args, parser, settings):
    """Fill options that were not given on the command line from the config.

    The flag always wins, the config file is the second source, and the
    built-in default is the last one.
    """
    for action in parser._actions:
        dest = action.dest

        if dest in ("help", "version", "config", "inputs", "track"):
            continue

        if getattr(args, dest, None) is not None:
            continue

        raw = config_str_value(settings, dest)

        if raw is None:
            continue

        try:
            value = coerce_config_value(action, raw)

        except (TypeError, ValueError) as error:
            raise ValueError(
                f"Invalid value for '{dest}' in config file: {raw} ({error})"
            ) from error

        if action.choices and value not in action.choices:
            raise ValueError(
                f"Unknown value for '{dest}' in config file: {raw} "
                f"(choose from {', '.join(action.choices)})"
            )

        setattr(args, dest, value)


def read_song_file(path: Path):
    """Read Artist - Title pairs from a text file.

    Returns a (songs, skipped) tuple, where skipped holds the lines that
    could not be parsed.
    """
    songs = []
    skipped = []

    for line in path.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines():

        line = line.strip()

        if not line or line.startswith("#"):
            continue

        song = parse_song(line)

        if song:
            songs.append(song)

        else:
            skipped.append(line)

    return songs, skipped


def collect_sources(args, settings):
    """Build the ordered list of inputs: file paths and inline tracks.

    Every item is either a Path to a text file or an inline
    "Artist - Title" string.
    """
    sources = []

    config_input = config_str_value(settings, "input")

    if config_input:
        path = Path(config_input).expanduser()

        if not path.is_file():
            raise ValueError(f"Input file not found: {path}")

        sources.append(path)

    for item in args.inputs:
        path = Path(item).expanduser()

        if path.is_file():
            sources.append(path)

        elif " - " in item:
            if not parse_song(item):
                raise ValueError(
                    f"Could not parse track: {item} "
                    f"(expected 'Artist - Title')"
                )

            sources.append(item)

        else:
            raise ValueError(
                f"Input file not found: {item} "
                f"(if this is a track, use the 'Artist - Title' format)"
            )

    for group in args.track or []:
        for spec in group:
            if not parse_song(spec):
                raise ValueError(
                    f"Could not parse track: {spec} "
                    f"(expected 'Artist - Title')"
                )

            sources.append(spec)

    return sources


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Download music using Spotify metadata "
            "and YouTube audio"
        ),
        epilog=(
            "A config file with the defaults can be used as well. It is "
            "looked up in --config, $TRACKFETCH_CONFIG, ./trackfetch.ini, "
            "$XDG_CONFIG_HOME/trackfetch/trackfetch.ini, "
            "~/.config/trackfetch/trackfetch.ini and ~/.trackfetch.ini. "
            "A command-line flag wins over the config file, and the config "
            "file wins over the built-in default."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "inputs",
        nargs="*",
        metavar="INPUT",
        help=(
            "Text file with Artist - Title, "
            "or an inline 'Artist - Title' track"
        ),
    )

    parser.add_argument(
        "--track",
        action="append",
        nargs="+",
        metavar="ARTIST - TITLE",
        help=(
            "Track to download inline, "
            "can be given several times"
        ),
    )

    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help=(
            "Output directory "
            "(overrides the config file, "
            "defaults to the current directory)"
        ),
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=(
            "Path to a config file "
            "(default: auto-detected, see below)"
        ),
    )

    parser.add_argument(
        "-f",
        "--format",
        choices=list(AUDIO_FORMATS),
        default=None,
        help="Audio format (default: m4a)",
    )

    parser.add_argument(
        "--title-only",
        action="store_true",
        default=None,
        help="Use only title in filename (default: off)",
    )

    parser.add_argument(
        "--delay",
        type=float,
        default=None,
        help="Delay between songs in seconds (default: 1.0)",
    )

    parser.add_argument(
        "--spotify-client-id",
        default=None,
        help="Spotify client ID (overrides the config file and the env)",
    )

    parser.add_argument(
        "--spotify-client-secret",
        default=None,
        help="Spotify client secret (overrides the config file and the env)",
    )

    args = parser.parse_args()

    try:
        settings, config_path = load_config(args.config)

    except FileNotFoundError as error:
        print(f"ERROR: {error}")
        sys.exit(1)

    except configparser.Error as error:
        print(f"ERROR: Invalid config file: {error}")
        sys.exit(1)

    try:
        apply_config(args, parser, settings)

    except ValueError as error:
        print(f"ERROR: {error}")
        sys.exit(1)

    if args.output is None:
        args.output = resolve_output(None, settings)

    if args.format is None:
        args.format = DEFAULT_FORMAT

    if args.title_only is None:
        args.title_only = False

    if args.delay is None:
        args.delay = DEFAULT_DELAY

    try:
        sources = collect_sources(args, settings)

    except ValueError as error:
        print(f"ERROR: {error}")
        sys.exit(1)

    if not sources:
        print(
            "ERROR: No input. "
            "Pass a file or an inline 'Artist - Title' track, "
            "or set 'input' in the config file."
        )
        sys.exit(1)

    args.output.mkdir(
        parents=True,
        exist_ok=True,
    )

    done_file = args.output / "done.txt"
    failed_file = args.output / "failed.txt"

    songs = []
    skipped = []

    for source in sources:
        if isinstance(source, Path):
            file_songs, file_skipped = read_song_file(source)

            songs.extend(file_songs)

            skipped.extend(
                (source, line) for line in file_skipped
            )

        else:
            song = parse_song(source)

            if song:
                songs.append(song)

    done = read_done(done_file)

    print(f"Found {len(songs)} songs")
    print(f"Already completed: {len(done)}")

    if skipped:
        print(
            f"WARNING: skipped {len(skipped)} line(s) "
            f"that are not 'Artist - Title':"
        )

        for path, line in skipped[:5]:
            print(f"  {path}: {line}")

        if len(skipped) > 5:
            print(f"  ... and {len(skipped) - 5} more")

    if config_path:
        print(f"Config: {config_path}")

    print(f"Output: {args.output}")

    sp = get_spotify(args)

    success = 0
    skipped = 0
    failed = 0

    for number, (artist, title) in enumerate(
        songs,
        start=1,
    ):
        song_key = f"{artist} - {title}"

        print()
        print("=" * 60)
        print(f"[{number}/{len(songs)}]")
        print(song_key)

        if song_key in done:
            print("SKIP: already completed")
            skipped += 1
            continue

        ok, reason = process_song(
            sp,
            artist,
            title,
            args.output,
            args.title_only,
            args.format,
        )

        if ok:
            append_line(
                done_file,
                song_key,
            )

            success += 1

            if reason == "exists":
                skipped += 1

        else:
            append_line(
                failed_file,
                f"{song_key} | {reason}",
            )

            failed += 1

        if number < len(songs):
            time.sleep(args.delay)

    print()
    print("=" * 60)
    print("FINISHED")
    print(f"SUCCESS: {success}")
    print(f"SKIPPED: {skipped}")
    print(f"FAILED: {failed}")
    print(f"DONE FILE: {done_file}")
    print(f"FAILED FILE: {failed_file}")


if __name__ == "__main__":
    main()
