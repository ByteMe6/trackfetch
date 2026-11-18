# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `--help` now uses the active color theme. Seven new theme roles control it: `heading` (`usage:` and section titles), `prog` (program name), `flag` (`--long`/`-s`), `metavar`, `choices`, `default` and `dim` (config paths and secondary notes). All four built-in themes define them; a custom theme without them falls back to related core roles instead of failing.
- The theme, color mode and `themes.ini` are chosen before the help text is built, so `--color-theme`, `--color`, `--themes-file` and the config file all apply to `-h`. An unknown theme still prints help with the default theme and warns on stderr.

### Changed
- `--config` and `-h`/`--help` moved into the Behavior group, so there is no longer a one-flag Help section.
- The Config section of `--help` now opens with "Lookup order, first found wins:" above the six paths.
- `import trackfetch` is lazy: constants, config and settings resolve immediately, while requests, mutagen, spotipy and the provider stack load on first use. `-h` and `--list-sources` no longer import the whole program.

### Fixed
- `trackfetch -h` no longer waits on work it does not need: the heavy modules are imported only when a command actually uses them.

## [2.2.8] - 2026-11-18

### Added
- Colorized terminal output with four built-in themes: Cassette (default), Neon Tape, Mono and Vinyl. Color covers labels, statuses, progress and separators; track titles, paths and error reasons stay plain. Output is plain when redirected, or with `NO_COLOR`, `TERM=dumb` and `--color never`.
- `--color {auto,always,never}` and the `color` config key. `auto` is the default: color on an interactive terminal, plain text in pipes and logs.
- `--color-theme THEME` and the `color_theme` config key to switch between the built-in themes or a custom theme.
- Custom themes in `themes.ini` next to `trackfetch.ini`, with inheritance through `base` and colors as `#RRGGBB`, xterm 256 indexes or ANSI names. `--themes-file` and the `themes_file` config key point at another file.
- `docs/color-themes.md` with a theme gallery, every configuration key, all theme roles, accepted color formats and precedence rules.
- Optional lyrics embedding for every output format: plain lyrics from LRCLIB are written to `USLT` (MP3), `©lyr` (M4A) or `LYRICS` (Opus), and synchronized lyrics to `SYLT`, the `SYNCEDLYRICS` freeform atom or the `SYNCEDLYRICS` Vorbis comment respectively. Both tags are written when timed lyrics exist, so players without timed-lyrics support still show the words. Missing lyrics never fail the download.
- `--lyrics`/`--no-lyrics` and the `lyrics_enabled` config key. Embedding is enabled by default for all formats and does not affect the audio data or existing non-lyrics tags.
- `--cache`/`--no-cache` and the `cache_enabled` config key to turn off `metadata-cache.json` reuse and rewriting.
- A compact `--help` with a short `usage:` line, every option listed exactly once, and the config-file lookup order in the epilog.
- `--help` groups options into Help, Input, Output, Metadata, Behavior and Appearance, aligns every description in a fixed column at any terminal width, wraps long flags without a blank line, and ends with a Config section (the six lookup paths in priority order) and an Examples section. Color is applied after wrapping, so `--color always` strips down to exactly the `--color never` output.
- Configurable free metadata providers: iTunes (the new default), Deezer, MusicBrainz with Cover Art Archive, VocaDB and optional Spotify. No API key is needed except for Spotify.
- `-s`/`--metadata-sources` with priority ordering, `none`, duplicate removal and unknown-name validation. YouTube stays a separate artwork fallback and is not part of the metadata ordering.
- `--disable-sources`, `--provider-opt NAME.KEY=VALUE`, `--match-threshold`, `--title-threshold` and `--list-sources`.
- Automatic temporary VocaDB promotion for CJK and Vocaloid-related input.
- Independent per-provider rate limits: iTunes 3.5 s, Deezer 0.25 s, MusicBrainz 1.1 s and VocaDB 0.5 s. The iTunes interval keeps a margin below the Search API ceiling of about 20 calls per minute.
- Provider health tracking: two consecutive real failures start a 30-second cooldown that doubles up to 600 seconds, then the provider is retried and restored to its configured priority. Empty results and missing artwork do not count as failures.
- Per-provider metadata cache in `metadata-cache.json` in the output directory, with graceful handling of corrupted files.
- Artwork fallback from provider artwork to Cover Art Archive to the YouTube thumbnail, without replacing valid high-quality artwork.
- New configuration keys for source priority, per-provider enabling, intervals, storefront country, YouTube fallback and matching thresholds.
- Tests for source resolution, configuration, matching, provider responses, rate limiting, failure recovery, caching, artwork and the new CLI options.

### Changed
- The default audio format is `mp3` again, so a fresh run plays everywhere without an explicit `-f`; `m4a` and `opus` keep YouTube's original audio when you want it.
- The single `trackfetch.py` module is now a package split by responsibility: `config`/`settings`, `runtime`, `providers/<name>`, `resolver`, `youtube`, `images`, `lyrics`, `tags`, `files`, `pipeline` and `cli`. The public `import trackfetch` API is unchanged, and `python -m trackfetch` now works as well.
- The default metadata source is now iTunes, so Spotify credentials are optional and Spotify is disabled unless explicitly selected or enabled.
- `get_spotify()` now returns `None` quietly when credentials are missing instead of exiting.
- Metadata results use one normalized structure with source, identifier, artwork and match score.
- `brew install trackfetch` no longer compiles `ffmpeg` on macOS: the formula installs a static prebuilt `ffmpeg` next to the prebuilt binary, so the first install takes seconds even where Homebrew has no bottle for it.

### Fixed
- A CLI metadata selection now overrides conflicting `disable_sources` and `*_enabled=false` configuration, while an explicit CLI disable still wins over a CLI selection. The config file is never rewritten.
- `match_threshold` and `title_threshold` values outside `0.0`-`1.0`, NaN and infinities are now rejected instead of being silently clamped.
- Provider `min_interval` values that are NaN, infinite or negative are rejected consistently from the CLI, the config file and `--provider-opt`.
- Downloaded artwork is identified by its actual signature, so PNG, GIF and WebP files get the correct extension and MIME type instead of always being labelled JPEG. M4A skips GIF/WebP artwork rather than mislabelling it.
- An incomplete metadata result can no longer overwrite a usable entry in `metadata-cache.json`.
- A negative, NaN or infinite `--delay` now gives a clear error instead of a Python traceback.
- A UTF-8 BOM in the input file no longer ends up in the artist, the title and the file name.
- Duplicate tracks are removed before downloading, so they are not counted twice and `done.txt` stays clean.
- A song that was already downloaded is no longer counted as a success.
- File names are truncated by bytes, so a long title with multi-byte characters no longer fails with "File name too long".
- Pointing `-o` at an existing file now gives a clear error instead of a Python traceback.
- The run summary is flushed before the downloads start, so it no longer appears after the first song's progress output.
- An input file with no usable songs now says `No songs to download` instead of ending silently with an empty summary.
- The `Already completed` count now says that it comes from `done.txt`.

## [2.2.7] - 2026-11-15

### Added
- `--no-logs` option and the `no_logs` config key: trackfetch stops reading `done.txt` and stops writing `done.txt` and `failed.txt`. Progress from earlier runs is not restored while this mode is on.

## [2.2.6] - 2026-11-10

### Added
- `--help` now shows the default values and where the config file is looked up.

### Fixed
- Lines in an input file that are not `Artist - Title` are no longer skipped silently: trackfetch prints how many lines it skipped and which ones they were.
- Inline tracks that cannot be parsed, such as `"Artist - "` or `" - Title"`, now report an error instead of being silently skipped.
- A missing input file now hints at the `Artist - Title` format, so a wrong separator is not mistaken for a missing file.
- The README no longer claims that every option can be set in the config file, and it lists all the config file locations.

## [2.2.5] - 2026-11-10

### Added
- Tracks can be named inline, without a text file: `trackfetch "Daft Punk - One More Time" "Radiohead - Paranoid Android"`, or with the new `--track` option, which can be repeated. Files and inline tracks can be mixed in one run.

## [2.2.0] - 2026-11-10

### Added
- Config file support: an INI file with a `[trackfetch]` section can set `input`, `output`, `format`, `title_only`, `delay` and the Spotify credentials. It is looked up in `--config`, `$TRACKFETCH_CONFIG`, `./trackfetch.ini`, `$XDG_CONFIG_HOME/trackfetch/trackfetch.ini` and `~/.trackfetch.ini`.
- `--config` option to point at a config file, and `--spotify-client-id`/`--spotify-client-secret` options.
- Spotify credentials are now read from the config file first and from `SPOTIFY_CLIENT_ID`/`SPOTIFY_CLIENT_SECRET` as a fallback.

### Changed
- Option precedence is now: command-line flag, then config file, then the built-in default.
- The default output folder is now the current directory instead of `~/Music/trackfetch`.
- The default audio format is now `m4a` instead of `mp3`.

## [2.1.0] - 2026-10-08

### Added
- `-f`/`--format` option to choose `mp3` (default), `m4a` or `opus`. Opus and M4A keep YouTube's original audio without re-encoding; every format gets the same tags and embedded cover art.
- Install with Homebrew (`brew install ByteMe6/tap/trackfetch`), from PyPI (`pipx install trackfetch`) or with Nix (`nix run github:ByteMe6/trackfetch`).
- Releases are published to PyPI automatically.
- An AUR package definition in `packaging/aur/`.

## [2.0.0] - 2026-10-06

### Added
- Ukrainian and Russian translations of the README.
- A section on exporting playlists from Spotify, Apple Music, YouTube Music and other services with TuneMyMusic.
- A tldr page in `docs/tldr/trackfetch.md`.
- Offline pytest suite (81 tests, 100% coverage) that runs in CI on Linux, macOS and Windows.

### Changed
- **Renamed from musicdl to trackfetch**, because the musicdl name is already taken by another project on PyPI. The command, Python module, release binaries and repository URL all changed; old GitHub links redirect. The default output folder is now `~/Music/trackfetch`. To keep using an existing folder and its `done.txt`, pass `-o ~/Music/musicdl`.
- trackfetch is now licensed under the GPL-3.0-or-later instead of MIT. Version 1.0.0 remains available under MIT.

## [1.0.0] - 2026-10-06

### Added
- Batch download from a text file of `Artist - Title` lines, with `#` comments and blank lines ignored.
- Spotify metadata lookup with strict and loose search plus fuzzy best-match scoring.
- Scored YouTube candidate selection that prefers official audio and penalises covers, karaoke, nightcore, sped-up and slowed edits, remixes and reaction videos.
- Best-quality MP3 extraction through yt-dlp and FFmpeg.
- ID3v2.3 tags: title, artist, album, album artist, track number, release date and embedded front cover.
- Resumable runs via `done.txt`, and a failure log with reasons in `failed.txt`.
- `--output`, `--title-only` and `--delay` options.
- PyInstaller spec, plus prebuilt binaries for Linux, macOS and Windows on x86_64 and ARM64.
- Automated releases: pushing a new version to `master` builds and publishes all binaries.

[Unreleased]: https://github.com/ByteMe6/trackfetch/compare/v2.2.8...HEAD
[2.2.8]: https://github.com/ByteMe6/trackfetch/releases/tag/v2.2.8
[2.2.7]: https://github.com/ByteMe6/trackfetch/releases/tag/v2.2.7
[2.2.6]: https://github.com/ByteMe6/trackfetch/releases/tag/v2.2.6
[2.2.5]: https://github.com/ByteMe6/trackfetch/releases/tag/v2.2.5
[2.2.0]: https://github.com/ByteMe6/trackfetch/releases/tag/v2.2.0
[2.1.0]: https://github.com/ByteMe6/trackfetch/releases/tag/v2.1.0
[2.0.0]: https://github.com/ByteMe6/trackfetch/releases/tag/v2.0.0
[1.0.0]: https://github.com/ByteMe6/trackfetch/releases/tag/v1.0.0
