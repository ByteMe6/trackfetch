# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- `brew install trackfetch` no longer compiles `ffmpeg` on macOS: the formula installs a static prebuilt `ffmpeg` next to the prebuilt binary, so the first install takes seconds even where Homebrew has no bottle for it.

### Fixed
- A negative `--delay` now gives a clear error instead of a Python traceback.
- A UTF-8 BOM in the input file no longer ends up in the artist, the title and the file name.
- Duplicate tracks are removed before downloading, so they are not counted twice and `done.txt` stays clean.
- A song that was already downloaded is no longer counted as a success.
- File names are truncated by bytes, so a long title with multi-byte characters no longer fails with "File name too long".
- Pointing `-o` at an existing file now gives a clear error instead of a Python traceback.
- The run summary is flushed before the downloads start, so it no longer appears after the first song's progress output.
- An input file with no usable songs now says `No songs to download` instead of ending silently with an empty summary.
- The `Already completed` count now says that it comes from `done.txt`.

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

[Unreleased]: https://github.com/ByteMe6/trackfetch/compare/v2.1.0...HEAD
[2.1.0]: https://github.com/ByteMe6/trackfetch/releases/tag/v2.1.0
[2.0.0]: https://github.com/ByteMe6/trackfetch/releases/tag/v2.0.0
[1.0.0]: https://github.com/ByteMe6/trackfetch/releases/tag/v1.0.0
