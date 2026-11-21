# SPDX-License-Identifier: GPL-3.0-or-later
"""Command-line interface and run orchestration."""

import argparse
import configparser
import contextlib
import io
import math
import sys
import time
from pathlib import Path

from . import colors
from .config import build_source_config, config_str_value, format_source_list
from .constants import (
    AUDIO_FORMATS,
    CACHE_FILENAME,
    DEFAULT_AUDIO_QUALITY,
    DEFAULT_DELAY,
    DEFAULT_FORMAT,
    LYRICS_MIN_INTERVAL,
    LYRICS_TYPES,
    METADATA_PROVIDERS,
    VERSION,
)
from .files import append_line, parse_song, read_done, read_song_file
from .helpfmt import TrackFetchHelpFormatter
from .settings import apply_config, load_config, resolve_output
from .themes import find_theme_file, load_theme_file


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

def format_summary(label_text, value, role):
    """Color a summary label and value, muting zero counts."""
    value_style = role if value else "muted"
    return (
        f"{colors.paint(label_text, role, 'bold')} "
        f"{colors.paint(value, value_style)}"
    )


CONFIG_PATHS = (
    "--config PATH",
    "$TRACKFETCH_CONFIG",
    "./trackfetch.ini",
    "$XDG_CONFIG_HOME/trackfetch/trackfetch.ini",
    "~/.config/trackfetch/trackfetch.ini",
    "~/.trackfetch.ini",
)

EPILOG = "\n".join(
    (
        "Config:",
        "Lookup order, first found wins:",
        *(f"  {path}" for path in CONFIG_PATHS),
        "",
        "A flag wins over the config file, and the config file wins over "
        "the built-in default.",
        "",
        "Examples:",
        "  trackfetch songs.txt",
        "  trackfetch --track 'Daft Punk - One More Time'",
        "  trackfetch -o ~/Music -f m4a songs.txt",
        "  trackfetch --list-sources --color never",
    )
)


def build_parser():
    """Build the argument parser (shared with the help tests)."""
    parser = argparse.ArgumentParser(
        prog="trackfetch",
        usage="%(prog)s [OPTIONS] [INPUT ...]",
        description=(
            "Download music using configurable free metadata "
            "sources and YouTube audio"
        ),
        epilog=EPILOG,
        formatter_class=TrackFetchHelpFormatter,
        add_help=False,
    )

    # Python 3.14+ colors help itself when stdout is a TTY; that would clash
    # with our own theme coloring and inflate the measured widths.
    parser.color = False

    input_group = parser.add_argument_group("Input")

    input_group.add_argument(
        "inputs",
        nargs="*",
        metavar="INPUT",
        help=(
            "Text file with Artist - Title, "
            "or an inline 'Artist - Title' track"
        ),
    )

    input_group.add_argument(
        "--track",
        action="append",
        nargs="+",
        metavar="ARTIST - TITLE",
        help=(
            "Track to download inline, "
            "can be given several times"
        ),
    )

    output_group = parser.add_argument_group("Output")

    output_group.add_argument(
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

    output_group.add_argument(
        "-f",
        "--format",
        choices=list(AUDIO_FORMATS),
        default=None,
        help="Audio format (default: mp3)",
    )

    output_group.add_argument(
        "--audio-quality",
        type=int,
        choices=range(10),
        metavar="0-9",
        default=None,
        help=(
            "MP3 VBR quality: 0 is best/largest, 9 is smallest "
            f"(default: {DEFAULT_AUDIO_QUALITY})"
        ),
    )

    output_group.add_argument(
        "--title-only",
        action="store_true",
        default=None,
        help="Use only title in filename (default: off)",
    )

    metadata_group = parser.add_argument_group("Metadata")

    metadata_group.add_argument(
        "-s",
        "--metadata-sources",
        default=None,
        metavar="SOURCES",
        help=(
            "Comma-separated metadata priority, for example "
            "'deezer,itunes,musicbrainz' or 'none' "
            "(default: itunes). If every source misses, free fallbacks "
            "deezer and musicbrainz are tried unless disabled"
        ),
    )

    metadata_group.add_argument(
        "--disable-sources",
        default=None,
        metavar="SOURCES",
        help=(
            "Comma-separated sources to disable, "
            "for example 'spotify,youtube'"
        ),
    )

    metadata_group.add_argument(
        "--provider-opt",
        action="append",
        default=None,
        metavar="NAME.KEY=VALUE",
        help=(
            "Provider-specific setting, for example "
            "--provider-opt itunes.country=ua"
        ),
    )

    metadata_group.add_argument(
        "--match-threshold",
        type=float,
        default=None,
        metavar="SCORE",
        help="Minimum overall match score, 0.0-1.0 (default: 0.6)",
    )

    metadata_group.add_argument(
        "--title-threshold",
        type=float,
        default=None,
        metavar="SCORE",
        help="Minimum title similarity, 0.0-1.0 (default: 0.8)",
    )

    metadata_group.add_argument(
        "--soundcloud",
        action=argparse.BooleanOptionalAction,
        default=None,
        dest="soundcloud_enabled",
        help=(
            "Try SoundCloud when YouTube blocks a video with an age "
            "restriction; never used for other errors (default: on)"
        ),
    )

    metadata_group.add_argument(
        "--soundcloud-trigger",
        choices=("age", "blocked", "age-or-missing", "any"),
        default=None,
        metavar="WHEN",
        help=(
            "When to try SoundCloud: age (age restriction only, default), "
            "blocked (age restriction or a YouTube bot/login wall), "
            "age-or-missing (blocked, plus no confident YouTube match) or "
            "any (any failed search or download)"
        ),
    )

    metadata_group.add_argument(
        "--soundcloud-ambiguous",
        choices=("skip", "best"),
        default=None,
        metavar="MODE",
        help=(
            "Several equally good SoundCloud results: skip them (default) "
            "or take the highest scoring one without asking, which is what "
            "non-interactive runs need"
        ),
    )

    metadata_group.add_argument(
        "--soundcloud-min-score",
        type=float,
        default=None,
        metavar="SCORE",
        help=(
            "Minimum SoundCloud match score before downloading without "
            "asking, 0.0-1.0 (default: 0.75)"
        ),
    )

    metadata_group.add_argument(
        "--soundcloud-min-margin",
        type=float,
        default=None,
        metavar="SCORE",
        help=(
            "Score gap required between the best two SoundCloud results "
            "before picking one automatically, 0.0-1.0 (default: 0.08)"
        ),
    )

    metadata_group.add_argument(
        "--list-sources",
        action="store_true",
        default=None,
        help="List available metadata sources and exit",
    )

    metadata_group.add_argument(
        "--spotify-client-id",
        default=None,
        help="Spotify client ID (overrides the config file and the env)",
    )

    metadata_group.add_argument(
        "--spotify-client-secret",
        default=None,
        help="Spotify client secret (overrides the config file and the env)",
    )

    behavior_group = parser.add_argument_group("Behavior")

    behavior_group.add_argument(
        "-h",
        "--help",
        action="help",
        default=argparse.SUPPRESS,
        help="Show this help message and exit",
    )

    behavior_group.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"trackfetch {VERSION}",
        help="Show the version and exit",
    )

    behavior_group.add_argument(
        "--config",
        type=Path,
        default=None,
        help=(
            "Path to a config file "
            "(default: auto-detected, see below)"
        ),
    )

    behavior_group.add_argument(
        "--delay",
        type=float,
        default=None,
        help="Delay between songs in seconds (default: 1.0)",
    )

    behavior_group.add_argument(
        "--no-logs",
        action="store_true",
        default=None,
        help=(
            "Do not read done.txt and do not write done.txt or failed.txt; "
            "progress from earlier runs is ignored (default: off)"
        ),
    )

    behavior_group.add_argument(
        "--lyrics",
        action=argparse.BooleanOptionalAction,
        default=None,
        dest="lyrics_enabled",
        help=(
            "Embed lyrics from LRCLIB into the tags: ID3 USLT/SYLT for MP3, "
            "©lyr for M4A, LYRICS for Opus. Searches by title, then relaxed "
            "queries, and ranks by title, artist and duration (default: on)"
        ),
    )

    behavior_group.add_argument(
        "--lyrics-type",
        choices=LYRICS_TYPES,
        default=None,
        help=(
            "Timed lyrics placement: inline keeps LRC timestamps in the "
            "plain lyrics tag (default), sidecar writes a separate "
            "<file>.lrc and keeps tags plain, plain writes only plain text "
            "to the tags"
        ),
    )

    behavior_group.add_argument(
        "--cache",
        action=argparse.BooleanOptionalAction,
        default=None,
        dest="cache_enabled",
        help=(
            "Reuse and update metadata-cache.json in the output directory "
            "(default: on)"
        ),
    )

    appearance_group = parser.add_argument_group("Appearance")

    appearance_group.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default=None,
        help=(
            "Colorize terminal output: auto (default), always or never. "
            "Color is on by default and off when output is redirected"
        ),
    )

    appearance_group.add_argument(
        "--color-theme",
        default=None,
        metavar="THEME",
        help=(
            "Color theme: cassette (default), neon-tape, mono, vinyl "
            "or a theme from themes.ini"
        ),
    )

    appearance_group.add_argument(
        "--themes-file",
        type=Path,
        default=None,
        help=(
            "Custom theme file (default: themes.ini next to the config file)"
        ),
    )

    return parser


def early_color_mode(argv):
    """Read --color before parsing so -h can honor it.

    ``argparse`` prints help and exits from inside ``parse_args``, before the
    parsed value is available, so the mode has to be known up front.
    """
    for index, arg in enumerate(argv):
        if arg == "--color" and index + 1 < len(argv):
            return argv[index + 1]

        if arg.startswith("--color="):
            return arg.split("=", 1)[1]

    return colors.DEFAULT_COLOR_MODE


def _help_preparse(argv):
    """Parse only the options that decide how help itself is rendered."""
    pre = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    pre.add_argument("--color")
    pre.add_argument("--color-theme")
    pre.add_argument("--themes-file")
    pre.add_argument("--config", type=Path)

    try:
        with contextlib.redirect_stderr(io.StringIO()):
            options, _unknown = pre.parse_known_args(argv)

    except SystemExit:
        return None

    return options


def _warn(message):
    print(f"WARNING: {message}", file=sys.stderr)


def help_requested(argv):
    """Return whether this run only asks for help."""
    return any(arg in ("-h", "--help") for arg in argv)


def prepare_help_style(argv):
    """Apply color mode and theme before argparse renders ``-h``.

    The precedence matches the rest of the program: a flag wins over the
    config file, which wins over the built-in default. Any problem falls back
    to the default theme with a warning on stderr, so help always prints.
    """
    if not help_requested(argv):
        return

    options = _help_preparse(argv)

    if options is None:
        return

    try:
        settings, config_path = load_config(options.config)

    except (FileNotFoundError, configparser.Error) as error:
        _warn(f"Ignoring config for help output: {error}")
        settings, config_path = {}, None

    mode = (
        options.color
        or config_str_value(settings, "color")
        or colors.DEFAULT_COLOR_MODE
    )

    try:
        colors.set_color_mode(mode)

    except ValueError as error:
        _warn(f"{error}; using {colors.DEFAULT_COLOR_MODE} for help")
        colors.set_color_mode(colors.DEFAULT_COLOR_MODE)

    explicit_themes_file = (
        options.themes_file
        or config_str_value(settings, "themes_file")
    )

    try:
        theme_path = find_theme_file(explicit_themes_file, config_path)
        load_theme_file(theme_path, required=bool(explicit_themes_file))

    except (OSError, ValueError) as error:
        _warn(f"Ignoring themes for help output: {error}")

    theme = (
        options.color_theme
        or config_str_value(settings, "color_theme")
        or colors.DEFAULT_THEME
    )

    try:
        colors.set_theme(theme)

    except ValueError as error:
        _warn(f"{error}; using {colors.DEFAULT_THEME} for help")
        colors.set_theme(colors.DEFAULT_THEME)


def main():
    try:
        sys.stdout.reconfigure(line_buffering=True)

    except (AttributeError, ValueError):
        pass

    try:
        colors.set_color_mode(early_color_mode(sys.argv[1:]))

    except ValueError:
        pass

    prepare_help_style(sys.argv[1:])

    parser = build_parser()

    args = parser.parse_args()

    colors.set_color_mode(args.color or colors.DEFAULT_COLOR_MODE)
    colors.set_theme(colors.DEFAULT_THEME)

    try:
        settings, config_path = load_config(args.config)

    except FileNotFoundError as error:
        print(colors.error(f"ERROR: {error}"))
        sys.exit(1)

    except configparser.Error as error:
        print(colors.error(f"ERROR: Invalid config file: {error}"))
        sys.exit(1)

    explicit_themes_file = (
        args.themes_file
        or config_str_value(settings, "themes_file")
    )

    try:
        theme_path = find_theme_file(explicit_themes_file, config_path)
        load_theme_file(theme_path, required=bool(explicit_themes_file))

    except (OSError, ValueError) as error:
        print(colors.error(f"ERROR: {error}"))
        sys.exit(1)

    try:
        apply_config(args, parser, settings)

    except ValueError as error:
        print(colors.error(f"ERROR: {error}"))
        sys.exit(1)

    args.color = args.color or colors.DEFAULT_COLOR_MODE
    args.color_theme = args.color_theme or colors.DEFAULT_THEME
    colors.set_color_mode(args.color)

    try:
        colors.set_theme(args.color_theme)

    except ValueError as error:
        print(colors.error(f"ERROR: {error}"))
        sys.exit(1)

    try:
        source_config = build_source_config(args, settings)

    except ValueError as error:
        print(colors.error(f"ERROR: {error}"))
        sys.exit(1)

    if args.list_sources:
        print(format_source_list(source_config))
        return

    if args.output is None:
        args.output = resolve_output(None, settings)

    if args.format is None:
        args.format = DEFAULT_FORMAT

    if args.audio_quality is None:
        args.audio_quality = DEFAULT_AUDIO_QUALITY

    if args.title_only is None:
        args.title_only = False

    if args.delay is None:
        args.delay = DEFAULT_DELAY

    if args.no_logs is None:
        args.no_logs = False

    if not math.isfinite(args.delay):
        print(colors.error(f"ERROR: Delay must be a finite number: {args.delay}"))
        sys.exit(1)

    if args.delay < 0:
        print(colors.error(f"ERROR: Delay must not be negative: {args.delay}"))
        sys.exit(1)

    try:
        sources = collect_sources(args, settings)

    except ValueError as error:
        print(colors.error(f"ERROR: {error}"))
        sys.exit(1)

    if not sources:
        print(
            colors.error(
                "ERROR: No input. "
                "Pass a file or an inline 'Artist - Title' track, "
                "or set 'input' in the config file."
            )
        )
        sys.exit(1)

    if args.output.exists() and not args.output.is_dir():
        print(colors.error(f"ERROR: Output path is not a directory: {args.output}"))
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
        print(colors.warning("No songs to download."))
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

    try:
        args.output.mkdir(
            parents=True,
            exist_ok=True,
        )
    except OSError as error:
        print(
            colors.error(
                f"ERROR: Cannot create output directory "
                f"{args.output}: {error.strerror or error}"
            )
        )

        if sys.platform == "darwin" and str(args.output).startswith("/home/"):
            print(
                colors.muted(
                    "On macOS home directories live under /Users; "
                    "use ~ or /Users/<name>."
                )
            )

        sys.exit(1)

    if not args.no_logs:
        done_file = args.output / "done.txt"
        failed_file = args.output / "failed.txt"

        done = read_done(done_file)
    else:
        done_file = None
        failed_file = None
        done = set()

    print(f"{colors.label('Found')} {len(songs)} songs")

    if duplicates:
        print(f"{colors.label('Removed')} {duplicates} duplicate(s)")

    if not args.no_logs:
        print(
            f"{colors.label('Already completed:')} {len(done)} "
            f"{colors.muted('(from done.txt)')}"
        )

    if skipped_lines:
        print(
            colors.warning(
                f"WARNING: skipped {len(skipped_lines)} line(s) "
                f"that are not 'Artist - Title':"
            )
        )

        for path, line in skipped_lines[:5]:
            print(f"  {colors.muted(path)}: {line}")

        if len(skipped_lines) > 5:
            print(colors.muted(f"  ... and {len(skipped_lines) - 5} more"))

    if config_path:
        print(f"{colors.label('Config:')} {config_path}")

    print(f"{colors.label('Output:')} {args.output}")

    print(
        f"{colors.label('Metadata sources:')} "
        + colors.accent(", ".join(source_config.metadata_sources) or "none")
    )
    print(
        f"{colors.label('YouTube artwork fallback:')} "
        + (
            colors.success("enabled")
            if source_config.youtube_enabled
            else colors.muted("disabled")
        )
    )
    print(
        f"{colors.label('Lyrics embedding:')} "
        + (
            colors.success("enabled (all formats)")
            if source_config.lyrics_enabled
            else colors.muted("disabled")
        )
    )
    trigger_labels = {
        "age": "age-restricted YouTube only",
        "blocked": "age restriction or YouTube login wall",
        "age-or-missing": "blocked, or no YouTube match",
        "any": "any failed YouTube search or download",
    }
    print(
        f"{colors.label('SoundCloud fallback:')} "
        + (
            colors.success(
                "enabled ("
                + trigger_labels.get(
                    source_config.soundcloud_trigger,
                    source_config.soundcloud_trigger,
                )
                + ")"
            )
            if source_config.soundcloud_enabled
            else colors.muted("disabled")
        )
    )
    print(
        f"{colors.label('SoundCloud ambiguity:')} "
        + (
            colors.success("take the best result")
            if source_config.soundcloud_ambiguous == "best"
            else colors.muted("ask on a terminal, otherwise skip")
        )
    )

    sys.stdout.flush()

    # Imported here so a plain -h or --list-sources run never pays for
    # requests, mutagen, spotipy and the provider stack.
    from .pipeline import process_song
    from .runtime import MetadataCache, MetadataRuntime, RateLimiter

    runtime = MetadataRuntime(
        cache=(
            MetadataCache(args.output / CACHE_FILENAME)
            if source_config.cache_enabled
            else None
        ),
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
        print(colors.frame("=" * 60))
        print(colors.progress(f"[{number}/{len(songs)}]"))
        print(colors.paint(song_key, "text", "bold"))

        if song_key in done:
            print(colors.skip("SKIP: already completed"))
            skipped += 1
            continue

        ok, reason = process_song(
            None,
            artist,
            title,
            args.output,
            args.title_only,
            args.format,
            args.audio_quality,
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
    print(colors.frame("=" * 60))
    print(colors.heading("FINISHED"))
    print(format_summary("SUCCESS:", success, "success"))
    print(format_summary("SKIPPED:", skipped, "skip"))
    print(format_summary("FAILED:", failed, "error"))

    if not args.no_logs:
        print(f"{colors.label('DONE FILE:')} {colors.muted(done_file)}")
        print(f"{colors.label('FAILED FILE:')} {colors.muted(failed_file)}")
