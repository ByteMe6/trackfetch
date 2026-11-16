# SPDX-License-Identifier: GPL-3.0-or-later
"""Command-line interface and run orchestration."""

import argparse
import configparser
import math
import sys
import time
from pathlib import Path

from .config import build_source_config, config_str_value, format_source_list
from .constants import (
    AUDIO_FORMATS,
    CACHE_FILENAME,
    DEFAULT_DELAY,
    DEFAULT_FORMAT,
    LYRICS_MIN_INTERVAL,
    METADATA_PROVIDERS,
)
from .files import append_line, parse_song, read_done, read_song_file
from .pipeline import process_song
from .runtime import MetadataCache, MetadataRuntime, RateLimiter
from .settings import apply_config, load_config, resolve_output


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
    try:
        sys.stdout.reconfigure(line_buffering=True)

    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(
        description=(
            "Download music using configurable free metadata "
            "sources and YouTube audio"
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
        "-s",
        "--metadata-sources",
        default=None,
        metavar="SOURCES",
        help=(
            "Comma-separated metadata priority, for example "
            "'deezer,itunes,musicbrainz' or 'none' "
            "(default: itunes)"
        ),
    )

    parser.add_argument(
        "--disable-sources",
        default=None,
        metavar="SOURCES",
        help=(
            "Comma-separated sources to disable, "
            "for example 'spotify,youtube'"
        ),
    )

    parser.add_argument(
        "--provider-opt",
        action="append",
        default=None,
        metavar="NAME.KEY=VALUE",
        help=(
            "Provider-specific setting, for example "
            "--provider-opt itunes.country=ua"
        ),
    )

    parser.add_argument(
        "--match-threshold",
        type=float,
        default=None,
        metavar="SCORE",
        help="Minimum overall match score, 0.0-1.0 (default: 0.6)",
    )

    parser.add_argument(
        "--title-threshold",
        type=float,
        default=None,
        metavar="SCORE",
        help="Minimum title similarity, 0.0-1.0 (default: 0.8)",
    )

    parser.add_argument(
        "--list-sources",
        action="store_true",
        default=None,
        help="List available metadata sources and exit",
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

    parser.add_argument(
        "--no-logs",
        action="store_true",
        default=None,
        help=(
            "Do not read done.txt and do not write done.txt or failed.txt; "
            "progress from earlier runs is ignored (default: off)"
        ),
    )

    parser.add_argument(
        "--lyrics",
        action=argparse.BooleanOptionalAction,
        default=None,
        dest="lyrics_enabled",
        help=(
            "Embed lyrics from LRCLIB into MP3 tags as USLT and, when "
            "timed lyrics are available, SYLT (default: on)"
        ),
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

    try:
        source_config = build_source_config(args, settings)

    except ValueError as error:
        print(f"ERROR: {error}")
        sys.exit(1)

    if args.list_sources:
        print(format_source_list(source_config))
        return

    if args.output is None:
        args.output = resolve_output(None, settings)

    if args.format is None:
        args.format = DEFAULT_FORMAT

    if args.title_only is None:
        args.title_only = False

    if args.delay is None:
        args.delay = DEFAULT_DELAY

    if args.no_logs is None:
        args.no_logs = False

    if not math.isfinite(args.delay):
        print(f"ERROR: Delay must be a finite number: {args.delay}")
        sys.exit(1)

    if args.delay < 0:
        print(f"ERROR: Delay must not be negative: {args.delay}")
        sys.exit(1)

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

    if args.output.exists() and not args.output.is_dir():
        print(f"ERROR: Output path is not a directory: {args.output}")
        sys.exit(1)

    songs = []
    skipped_lines = []

    for source in sources:
        if isinstance(source, Path):
            file_songs, file_skipped = read_song_file(source)

            songs.extend(file_songs)

            skipped_lines.extend(
                (source, line) for line in file_skipped
            )

        else:
            song = parse_song(source)

            if song:
                songs.append(song)

    if not songs:
        print("No songs to download.")
        sys.exit(0)

    unique_songs = []
    seen_songs = set()

    for artist, title in songs:
        key = f"{artist} - {title}"

        if key in seen_songs:
            continue

        seen_songs.add(key)
        unique_songs.append((artist, title))

    duplicates = len(songs) - len(unique_songs)

    songs = unique_songs

    args.output.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not args.no_logs:
        done_file = args.output / "done.txt"
        failed_file = args.output / "failed.txt"

        done = read_done(done_file)
    else:
        done_file = None
        failed_file = None
        done = set()

    print(f"Found {len(songs)} songs")

    if duplicates:
        print(f"Removed {duplicates} duplicate(s)")

    if not args.no_logs:
        print(f"Already completed: {len(done)} (from done.txt)")

    if skipped_lines:
        print(
            f"WARNING: skipped {len(skipped_lines)} line(s) "
            f"that are not 'Artist - Title':"
        )

        for path, line in skipped_lines[:5]:
            print(f"  {path}: {line}")

        if len(skipped_lines) > 5:
            print(f"  ... and {len(skipped_lines) - 5} more")

    if config_path:
        print(f"Config: {config_path}")

    print(f"Output: {args.output}")

    print(
        "Metadata sources: "
        + (", ".join(source_config.metadata_sources) or "none")
    )
    print(
        "YouTube artwork fallback: "
        + ("enabled" if source_config.youtube_enabled else "disabled")
    )
    print(
        "Lyrics embedding: "
        + ("enabled (MP3 only)" if source_config.lyrics_enabled else "disabled")
    )

    sys.stdout.flush()

    runtime = MetadataRuntime(
        cache=MetadataCache(args.output / CACHE_FILENAME),
        limiter=RateLimiter(
            {
                name: source_config.interval(name)
                for name in METADATA_PROVIDERS
            }
            | {"lrclib": LYRICS_MIN_INTERVAL}
        ),
        spotify_args=args,
    )

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
            None,
            artist,
            title,
            args.output,
            args.title_only,
            args.format,
            source_config=source_config,
            runtime=runtime,
        )

        if ok:
            if not args.no_logs:
                append_line(
                    done_file,
                    song_key,
                )

            done.add(song_key)

            if reason == "exists":
                skipped += 1

            else:
                success += 1

        else:
            if not args.no_logs:
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

    if not args.no_logs:
        print(f"DONE FILE: {done_file}")
        print(f"FAILED FILE: {failed_file}")

