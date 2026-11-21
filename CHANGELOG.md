# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [2.3.3] - 2026-11-21

### Fixed
- When the fallback retried with the input names, it still scored the
  candidates against the duration from the *mismatched* metadata record.
  A correct full-length upload was then penalized for not matching another
  track's length (2:22 vs 2:41 scored 0.74 and was skipped). The retry now
  leaves duration out of scoring, because that number describes a different
  recording.
- `soundcloud_ambiguous = best` now also resolves a result that is merely
  below `soundcloud_min_score` instead of only ties. It prints a warning
  with the score and title, so an unattended run can finish while the log
  still shows what was picked and why.

## [2.3.2] - 2026-11-21

### Added
- `--soundcloud-trigger blocked` and `soundcloud_trigger = blocked`: also
  treat YouTube's login walls as a reason to look for another copy. This
  covers `Sign in to confirm you're not a bot`, which is common and is not
  an age restriction, plus members-only and payment-gated videos.
  `age-or-missing` now includes these walls as well; `age` stays strict.
- The fallback retries SoundCloud with the artist and title exactly as they
  appear in the input file when the first search finds nothing usable. A
  metadata provider can resolve a different act (for example "MintiLove"
  instead of "Neverlove"), and searching the wrong name only returns
  previews and unrelated uploads.

### Fixed
- The download's own stderr is now used to classify the failure. A YouTube
  bot check often lets `--dump-single-json` through and only fails at the
  download step, so the metadata-only probe alone missed it. Progress output
  is still streamed, not buffered.
- Real download failures no longer get mislabelled as age restrictions from
  a stale probe result.

## [2.3.1] - 2026-11-21

### Added
- `--soundcloud-trigger WHEN` and `soundcloud_trigger`: `age` keeps the safe
  default of trying SoundCloud only for an age restriction,
  `age-or-missing` also covers a YouTube search that found nothing usable,
  and `any` covers every failed search or download.
- `--soundcloud-ambiguous MODE` and `soundcloud_ambiguous`: `skip` keeps the
  old behaviour of never downloading an ambiguous match without a terminal,
  while `best` takes the highest scoring result. Non-interactive runs such as
  `nohup trackfetch retry.txt` need `best` to make progress on their own.

### Changed
- The `--list-sources` summary and the run header now report the SoundCloud
  trigger and the ambiguity mode instead of always claiming
  "age-restricted YouTube only".

## [2.3.0] - 2026-11-21

### Added
- A SoundCloud fallback for YouTube videos that fail specifically with an age
  restriction. trackfetch searches SoundCloud with yt-dlp's `scsearch`, reads
  metadata for up to five results with `--dump-single-json`, scores title
  (40%), artist (30%), duration (20%) and metadata consistency (10%), rejects
  previews, remixes, covers, live and instrumental versions, and downloads only
  a single confident match. Ambiguous results are printed (and offered as a
  numbered choice in an interactive terminal) instead of being downloaded
  blindly. Every other YouTube error keeps the existing handling. Configure it
  with `--soundcloud/--no-soundcloud`, `--soundcloud-min-score` and
  `--soundcloud-min-margin`, or the matching config keys. This is a search for
  an independently available copy, not a bypass of YouTube's age verification.

### Fixed
- When the three plain YouTube searches find nothing usable, trackfetch now
  falls back to the YouTube Music search, which is not filtered for some
  topics the way anonymous YouTube search is. Every candidate is verified
  against its full video details (close title, matching artist or channel,
  and known durations within 10 seconds), so unrelated tracks are still
  rejected.
- YouTube search now falls back from `<artist> <title>` to `<title>` and
  `<title> Topic` when the first query returns nothing or no confident match.
  This finds songs that YouTube hides from the artist query for an anonymous
  client, while most songs still cost a single yt-dlp call.
- Artist matching now also compares transliterated (Latin) forms of the artist,
  video title and channel, so a Latin artist name matches Cyrillic uploads and
  vice versa. Channel names are used as evidence, and `- Topic` uploads get an
  extra bonus.
- Title-only results now need artist evidence (the artist in the title or
  channel, or a duration within five seconds), which keeps covers, audiobooks
  and same-title songs by other artists out.
- YouTube candidates below `YOUTUBE_MIN_SCORE` are rejected instead of always
  taking the best-scored result.
- `cover`, `remix` and the other bad-word markers are matched as whole words,
  so titles such as "Discovery" are no longer penalised.
- A non-zero yt-dlp search exit code is reported as `yt-dlp search failed`,
  distinct from `no YouTube result` and `no confident YouTube match` in
  `failed.txt`.

## [2.2.11] - 2026-11-19

### Added
- `-v` / `--version` prints the installed version and exits.
- Provider searches now survive typos, case differences, missing hyphens and
  `ё`/`е` spelling. The strict query runs first; if nothing matches, trackfetch
  retries with `artist title`, `title artist`, the title alone, and the title
  without its trailing words. The existing match thresholds decide when to
  stop, so a relaxed query cannot pull in an unrelated song.
- Metadata matching ignores bracketed noise such as `(Official Video)`,
  `[Remastered]`, `(Live)` and `feat. ...`, and also accepts a swapped
  artist/title pair.
- When every configured provider misses, trackfetch now tries two free
  fallbacks, `deezer` and then `musicbrainz`. They are skipped when disabled
  with `--disable-sources` or the config, and with `-s none`.
- Metadata candidates now carry the track duration (iTunes, Deezer,
  MusicBrainz, Spotify), and it is stored in the metadata cache. YouTube
  scoring adds +0.05 when a video is within 3 seconds of it and +0.02 within
  10 seconds.
- LRCLIB lyrics lookup now searches by track name first, then with relaxed
  queries, and ranks results locally by title, artist and duration, preferring
  timed lyrics on ties. Status lines are now `Lyrics: synced (...)`,
  `Lyrics: plain only (no synced version)` and `Lyrics: not found`.
- `--lyrics-type {inline,sidecar,plain}` and the `lyrics_type` config key.
  `inline` keeps the current behaviour and writes LRC timestamps into the plain
  lyrics tag. `sidecar` keeps the tag clean and writes a separate `<file>.lrc`
  next to the audio. `plain` writes only plain text to the tags.

### Fixed
- A same-title cover by a different artist could replace the requested track
  after query relaxation. A metadata candidate now also needs at least a rough
  artist match, so a cover is rejected and the user's own artist and title are
  kept instead of pointing YouTube at the wrong song.
- A channel name in front of `Artist - Song` (for example
  `Some Channel “Artist - Song”`) could score above the official upload. The
  artist part is now only trusted when the video title starts with the
  requested artist.

## [2.2.10] - 2026-11-19

### Added
- `--audio-quality 0-9` for MP3 VBR quality. The default is now `5` (about
  130 kbps), which keeps the size close to the source instead of inflating a
  128 kbps AAC/Opus track to a ~260 kbps MP3 with `0`.
- Cover art is normalized with Pillow before embedding: images larger than
  640 px or 100 KiB are downscaled and re-encoded as JPEG. iTunes artwork is
  requested at 640×640 instead of 600×600. Pillow is now declared for pip,
  Nix, AUR and Homebrew installs.

### Fixed
- Timed lyrics are now also stored in `USLT`, `©lyr` and `LYRICS` as LRC text
  when SYLT/freeform timed lyrics exist. Retro Music and other Android players
  read LRC from the plain lyrics field and ignore SYLT, so synchronized lyrics
  now appear there too.
- An output directory that cannot be created (for example `/home/...` on
  macOS) now gives a clear error instead of a traceback, with a hint to use
  `~` or `/Users/<name>`.

## [2.2.9] - 2026-11-19

### Added
- Colorized terminal output with four built-in themes: Cassette (default), Neon Tape, Mono and Vinyl. Color covers labels, statuses, progress and separators; track titles, paths and error reasons stay plain. Output is plain when redirected, or with `NO_COLOR`, `TERM=dumb` and `--color never`.
- `--color {auto,always,never}` and the `color` config key. `auto` is the default: color on an interactive terminal, plain text in pipes and logs.
- `--color-theme THEME` and the `color_theme` config key to switch between the built-in themes or a custom theme.
- Custom themes in `themes.ini` next to `trackfetch.ini`, with inheritance through `base` and colors as `#RRGGBB`, xterm 256 indexes or ANSI names. `--themes-file` and the `themes_file` config key point at another file.
- `docs/color-themes.md` with a theme gallery, every configuration key, all theme roles, accepted color formats and precedence rules.
- `--help` uses the active color theme. Seven theme roles control it: `heading` (`usage:` and section titles), `prog` (program name), `flag` (`--long`/`-s`), `metavar`, `choices`, `default` and `dim` (config paths and secondary notes). All four built-in themes define them, and a custom theme without them falls back to related core roles instead of failing.
- The theme, color mode and `themes.ini` are chosen before the help text is built, so `--color-theme`, `--color`, `--themes-file` and the config file all apply to `-h`. An unknown theme still prints help with the default theme and warns on stderr.
- Optional lyrics embedding for every output format: plain lyrics from LRCLIB are written to `USLT` (MP3), `©lyr` (M4A) or `LYRICS` (Opus), and synchronized lyrics to `SYLT`, the `SYNCEDLYRICS` freeform atom or the `SYNCEDLYRICS` Vorbis comment respectively. Both tags are written when timed lyrics exist, so players without timed-lyrics support still show the words. Missing lyrics never fail the download.
- `--lyrics`/`--no-lyrics` and the `lyrics_enabled` config key. Embedding is enabled by default for all formats and does not affect the audio data or existing non-lyrics tags.
- `--cache`/`--no-cache` and the `cache_enabled` config key to turn off `metadata-cache.json` reuse and rewriting.
- A compact `--help` with a short `usage:` line, every option listed exactly once, and the config-file lookup order in the epilog.
- `--help` groups options into Input, Output, Metadata, Behavior and Appearance, aligns every description in a fixed column at any terminal width, wraps long flags without a blank line, and ends with a Config section (the six lookup paths in priority order, introduced by "Lookup order, first found wins:") and an Examples section. Color is applied after wrapping, so `--color always` strips down to exactly the `--color never` output.
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
- `--config` and `-h`/`--help` live in the Behavior group, so there is no one-flag Help section.
- `import trackfetch` is lazy: constants, config and settings resolve immediately, while requests, mutagen, spotipy and the provider stack load on first use. `-h` and `--list-sources` no longer import the whole program.
- The default audio format is `mp3` again, so a fresh run plays everywhere without an explicit `-f`; `m4a` and `opus` keep YouTube's original audio when you want it.
- The single `trackfetch.py` module is now a package split by responsibility: `config`/`settings`, `runtime`, `providers/<name>`, `resolver`, `youtube`, `images`, `lyrics`, `tags`, `files`, `pipeline` and `cli`. The public `import trackfetch` API is unchanged, and `python -m trackfetch` now works as well.
- The default metadata source is now iTunes, so Spotify credentials are optional and Spotify is disabled unless explicitly selected or enabled.
- `get_spotify()` now returns `None` quietly when credentials are missing instead of exiting.
- Metadata results use one normalized structure with source, identifier, artwork and match score.
- `brew install trackfetch` no longer compiles `ffmpeg` on macOS: the formula installs a static prebuilt `ffmpeg` next to the prebuilt binary, so the first install takes seconds even where Homebrew has no bottle for it.

### Fixed
- `trackfetch -h` no longer imports the pipeline, requests, mutagen or spotipy it does not need.
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

[Unreleased]: https://github.com/ByteMe6/trackfetch/compare/v2.3.0...HEAD
[2.3.0]: https://github.com/ByteMe6/trackfetch/releases/tag/v2.3.0
[2.2.11]: https://github.com/ByteMe6/trackfetch/releases/tag/v2.2.11
[2.2.10]: https://github.com/ByteMe6/trackfetch/releases/tag/v2.2.10
[2.2.9]: https://github.com/ByteMe6/trackfetch/releases/tag/v2.2.9
[2.2.7]: https://github.com/ByteMe6/trackfetch/releases/tag/v2.2.7
[2.2.6]: https://github.com/ByteMe6/trackfetch/releases/tag/v2.2.6
[2.2.5]: https://github.com/ByteMe6/trackfetch/releases/tag/v2.2.5
[2.2.0]: https://github.com/ByteMe6/trackfetch/releases/tag/v2.2.0
[2.1.0]: https://github.com/ByteMe6/trackfetch/releases/tag/v2.1.0
[2.0.0]: https://github.com/ByteMe6/trackfetch/releases/tag/v2.0.0
[1.0.0]: https://github.com/ByteMe6/trackfetch/releases/tag/v1.0.0
