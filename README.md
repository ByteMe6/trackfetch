<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/ByteMe6/trackfetch/master/.github/assets/banner-dark.svg">
  <img alt="trackfetch: a text file of songs in, tagged MP3s with cover art out" src="https://raw.githubusercontent.com/ByteMe6/trackfetch/master/.github/assets/banner-light.svg" width="100%">
</picture>

<p align="center">
  <a href="https://github.com/ByteMe6/trackfetch/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/ByteMe6/trackfetch?style=flat-square&label=release&labelColor=15122B&color=FFB547"></a>
  <a href="https://pypi.org/project/trackfetch/"><img alt="PyPI" src="https://img.shields.io/pypi/v/trackfetch?style=flat-square&label=pypi&labelColor=15122B&color=FFB547"></a>
  <a href="https://github.com/ByteMe6/trackfetch/actions/workflows/release.yml"><img alt="Build status" src="https://img.shields.io/github/actions/workflow/status/ByteMe6/trackfetch/release.yml?branch=master&style=flat-square&label=build&labelColor=15122B"></a>
  <a href="#install"><img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-FFB547?style=flat-square&labelColor=15122B"></a>
  <a href="#standalone-binary"><img alt="Linux, macOS and Windows on x86_64 and ARM64" src="https://img.shields.io/badge/linux%20%C2%B7%20macos%20%C2%B7%20windows-x86__64%20%2B%20arm64-FFB547?style=flat-square&labelColor=15122B"></a>
  <a href="https://github.com/ByteMe6/trackfetch/blob/master/LICENSE"><img alt="License: GPL-3.0-or-later" src="https://img.shields.io/badge/license-GPL--3.0--or--later-FFB547?style=flat-square&labelColor=15122B"></a>
</p>

<p align="center">
  <b>English</b> · <a href="https://github.com/ByteMe6/trackfetch/blob/master/README.uk.md">Українська</a> · <a href="https://github.com/ByteMe6/trackfetch/blob/master/README.ru.md">Русский</a>
</p>

<p align="center">
  <a href="#install">Install</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#playlists-from-streaming-services">Playlists from streaming services</a> ·
  <a href="#usage">Usage</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#troubleshooting">Troubleshooting</a>
</p>

<br>

<img alt="Terminal recording: trackfetch skips two songs that are already downloaded, finds Daft Punk - One More Time on Spotify, scores five YouTube results, downloads the best one and saves a tagged MP3" src="https://raw.githubusercontent.com/ByteMe6/trackfetch/master/.github/assets/demo.svg" width="100%">

<br>

trackfetch reads a plain text file with one `Artist - Title` per line. For every song it looks up metadata and cover art in the configured free sources, picks the best-matching audio on YouTube, and saves an MP3 with complete ID3 tags. Runs are resumable, so you can stop a 1,000-song list at any point and pick it up later.

- **Configurable metadata.** Use iTunes (the default), Deezer, MusicBrainz, VocaDB and optional Spotify. Put them in any priority order with `-s`, or turn them off one by one.
- **Album art.** Artwork comes from the winning metadata source, then the Cover Art Archive for MusicBrainz, then the YouTube thumbnail. It is downscaled to at most 640×640 and re-encoded when it is larger than 100 KiB.
- **The right upload.** trackfetch scores five YouTube results per song. Official audio wins; covers, karaoke, nightcore, sped-up, slowed, remix and reaction videos lose.
- **Your choice of format.** MP3 for any player, or Opus and M4A that keep YouTube's original audio without re-encoding.
- **Resumable.** Finished songs are logged in `done.txt` and skipped next time. Failures go to `failed.txt` with the reason.
- **Plays everywhere.** Tags are written as ID3v2.3, which Windows Explorer, Apple Music, Android, car stereos and most other players read.
- **Any alphabet.** Cyrillic and other non-Latin titles are matched correctly and kept in filenames. Characters that are illegal in filenames are replaced.
- **No Python needed.** Standalone binaries for Linux, macOS and Windows on x86_64 and ARM64.

## Install

Pick one. Homebrew and Nix also install yt-dlp, FFmpeg and Deno for you; with the other methods, install them yourself ([see below](#dependencies)). The default iTunes source needs no API key. A free Spotify API key is optional and only needed if you select Spotify ([set it up below](#spotify-credentials)).

### Homebrew

macOS and Linux:

```bash
brew install ByteMe6/tap/trackfetch
```

On macOS the formula installs the prebuilt `trackfetch` binary and a static prebuilt `ffmpeg` inside the formula, so `ffmpeg`, the dependency Homebrew used to build for hours on Intel Macs and newer macOS versions, is never compiled. `yt-dlp` and `deno` come from Homebrew as usual.

### Nix

Linux and Apple Silicon Macs, with flakes enabled:

```bash
nix run github:ByteMe6/trackfetch -- songs.txt   # run without installing
nix profile install github:ByteMe6/trackfetch    # install
```

### pipx

```bash
pipx install trackfetch
```

### Standalone binary

No Python required. Download the file for your system from the [latest release](https://github.com/ByteMe6/trackfetch/releases/latest):

| | x86_64 | ARM64 |
| --- | --- | --- |
| **Linux** | [`trackfetch-linux-x86_64`](https://github.com/ByteMe6/trackfetch/releases/latest/download/trackfetch-linux-x86_64) | [`trackfetch-linux-arm64`](https://github.com/ByteMe6/trackfetch/releases/latest/download/trackfetch-linux-arm64) |
| **macOS** | [`trackfetch-macos-x86_64`](https://github.com/ByteMe6/trackfetch/releases/latest/download/trackfetch-macos-x86_64) (Intel) | [`trackfetch-macos-arm64`](https://github.com/ByteMe6/trackfetch/releases/latest/download/trackfetch-macos-arm64) (Apple Silicon) |
| **Windows** | [`trackfetch-windows-x86_64.exe`](https://github.com/ByteMe6/trackfetch/releases/latest/download/trackfetch-windows-x86_64.exe) | [`trackfetch-windows-arm64.exe`](https://github.com/ByteMe6/trackfetch/releases/latest/download/trackfetch-windows-arm64.exe) |

On Linux and macOS, make it executable and put it on your `PATH`:

```bash
chmod +x trackfetch-linux-x86_64
sudo mv trackfetch-linux-x86_64 /usr/local/bin/trackfetch
```

On macOS, if Gatekeeper blocks the unsigned binary, run `xattr -d com.apple.quarantine trackfetch-macos-*` once. Checksums are in `SHA256SUMS.txt` on each release.

### From source

```bash
git clone https://github.com/ByteMe6/trackfetch.git
cd trackfetch
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

### Dependencies

With pipx, a standalone binary or a source install, put these on your `PATH`:

| Tool | Used for | Install |
| --- | --- | --- |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Searching and downloading from YouTube | `pipx install yt-dlp` · `brew install yt-dlp` · `winget install yt-dlp` |
| [FFmpeg](https://ffmpeg.org/) | Converting the audio to MP3 | `sudo apt install ffmpeg` · `brew install ffmpeg` · `winget install ffmpeg` |
| [Deno](https://deno.com/) | JavaScript runtime that yt-dlp needs for YouTube | `curl -fsSL https://deno.land/install.sh \| sh` · `brew install deno` · `winget install DenoLand.Deno` |

[Pillow](https://python-pillow.org/) (the `PIL` module) is used to shrink cover art. It is installed automatically with pip/pipx and bundled inside the prebuilt binaries, so you do not need to add it to `PATH`.

## Spotify credentials

trackfetch uses Spotify's Client Credentials flow: no Spotify login, no access to your account.

1. Open the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) and click **Create app**.
2. Enter any name and description. For the redirect URI, enter `http://127.0.0.1:8888/callback`. trackfetch never uses it, but the form requires one.
3. Open the app's **Settings** and copy the **Client ID** and **Client Secret**.
4. Set them as environment variables:

<details open>
<summary><b>bash / zsh</b></summary>

```bash
export SPOTIFY_CLIENT_ID='your-client-id'
export SPOTIFY_CLIENT_SECRET='your-client-secret'
```

</details>

<details>
<summary><b>fish</b></summary>

```fish
set -Ux SPOTIFY_CLIENT_ID 'your-client-id'
set -Ux SPOTIFY_CLIENT_SECRET 'your-client-secret'
```

</details>

<details>
<summary><b>PowerShell</b></summary>

```powershell
[Environment]::SetEnvironmentVariable('SPOTIFY_CLIENT_ID', 'your-client-id', 'User')
[Environment]::SetEnvironmentVariable('SPOTIFY_CLIENT_SECRET', 'your-client-secret', 'User')
```

</details>

> [!CAUTION]
> Spotipy caches the access token in a `.cache` file in the current directory. Don't commit it or share it.

## Quick start

```bash
cat > songs.txt <<'EOF'
# My playlist
Daft Punk - One More Time
Radiohead - Paranoid Android
Korol i Shut - Мёртвый Анархист
EOF

trackfetch songs.txt
```

The files land in the current directory.

## Playlists from streaming services

You don't have to type the list by hand. [TuneMyMusic](https://www.tunemymusic.com/) exports playlists from Spotify, Apple Music, YouTube Music, Deezer, Tidal, SoundCloud and other services to a text file that trackfetch reads as is:

1. On [tunemymusic.com](https://www.tunemymusic.com/), choose the service your playlist is on as the source.
2. Select the playlists you want.
3. Choose **Export to file** as the destination and save it as **TXT**.
4. Run trackfetch on the exported file:

```bash
trackfetch "My Playlist.txt" -o ~/Music/"My Playlist"
```

## Usage

```text
trackfetch [-h] [-v] [--track ARTIST - TITLE ...] [-o OUTPUT] [--config CONFIG] [-f {mp3,m4a,opus}] [--title-only] [--delay DELAY] [-s SOURCES] [--music-sources SOURCES] [--disable-sources SOURCES] [--provider-opt NAME.KEY=VALUE] [--match-threshold SCORE] [--title-threshold SCORE] [--list-sources] [--spotify-client-id ID] [--spotify-client-secret SECRET] [--no-logs] [--color {auto,always,never}] [--color-theme THEME] [--themes-file PATH] [--lyrics | --no-lyrics] [--lyrics-type {inline,sidecar,plain}] [INPUT ...]
```

| Option | Default | What it does |
| --- | --- | --- |
| `INPUT` | optional | Text file with one `Artist - Title` per line, or an inline `Artist - Title` track. Can also be set in the [config file](#configuration-file). |
| `--track` | — | Track to download inline, `Artist - Title`. Can be given several times. |
| `-o`, `--output` | current directory | Folder to save the files in. It's created if it doesn't exist. |
| `-v`, `--version` | — | Show the installed version and exit. |
| `--config` | auto-detected | Path to a [config file](#configuration-file). |
| `-f`, `--format` | `mp3` | Audio format: `mp3`, `m4a` or `opus`. See [Audio formats](#audio-formats). |
| `--title-only` | off | Name files `Title.m4a` instead of `Artist - Title.m4a` |
| `--delay` | `1.0` | Seconds to wait between songs. Raise it for long lists. |
| `-s`, `--metadata-sources` | `itunes` | Comma-separated metadata priority, for example `deezer,itunes,musicbrainz`. `none` disables metadata lookups but keeps YouTube. A CLI selection overrides configured disabling for the selected providers. |
| `--music-sources` | `youtube,soundcloud` | Comma-separated music priority: `youtube` or `soundcloud`. The default keeps YouTube primary and SoundCloud as the trigger-controlled fallback; `soundcloud,youtube` tries SoundCloud first. A CLI list overrides configured disabling for the named providers. |
| `--youtube`, `--no-youtube` | on | Enable YouTube audio and its thumbnail fallback. `--no-youtube` leaves SoundCloud as the only music source. |
| `--disable-sources` | — | Comma-separated sources to disable, for example `spotify,youtube` or `soundcloud`. Takes precedence over a CLI selection for the same provider. |
| `--soundcloud`, `--no-soundcloud` | on | Enable SoundCloud as a music source. It is tried after YouTube by default, when `--soundcloud-trigger` allows it. |
| `--soundcloud-trigger WHEN` | `age` | `age` (age-restricted videos only), `blocked` (also YouTube bot/login walls and members-only), `age-or-missing` (`blocked`, plus no confident YouTube match) or `any` (any failed search or download). |
| `--soundcloud-ambiguous MODE` | `skip` | `skip` never downloads an ambiguous match without a terminal; `best` takes the highest scoring result, which non-interactive runs need. |
| `--soundcloud-min-score` | `0.75` | Minimum candidate score before trackfetch downloads without asking. |
| `--soundcloud-min-margin` | `0.08` | Score gap required between the best two SoundCloud results before picking one automatically. |
| `--provider-opt` | — | Provider setting as `NAME.KEY=VALUE`, for example `itunes.country=ua`. Can be repeated. |
| `--match-threshold` | `0.6` | Minimum overall match score, from `0.0` to `1.0`. Values outside that range, NaN and infinities are rejected. |
| `--title-threshold` | `0.8` | Minimum title similarity, from `0.0` to `1.0`. Values outside that range, NaN and infinities are rejected. |
| `--list-sources` | — | Show available metadata providers and artwork fallbacks, then exit. Makes no network requests. |
| `--spotify-client-id` | `$SPOTIFY_CLIENT_ID` | Spotify API client ID. See [Spotify credentials](#spotify-credentials). |
| `--spotify-client-secret` | `$SPOTIFY_CLIENT_SECRET` | Spotify API client secret. |
| `--no-logs` | off | Do not read `done.txt` and do not write `done.txt` or `failed.txt`. Progress from earlier runs is ignored, so finished songs are not skipped. |
| `--color` | `auto` | Colorize output: `auto`, `always` or `never`. `auto` uses color on an interactive terminal and plain text when redirected. `--color always` also colors pipes and log files. |
| `--color-theme` | `cassette` | Built-in theme (`cassette`, `neon-tape`, `mono`, `vinyl`) or a custom theme from `themes.ini`. |
| `--themes-file` | next to the config | Path to a custom `themes.ini`. The default file sits next to `trackfetch.ini`. |
| `--lyrics` / `--no-lyrics` | on | Embed lyrics fetched from LRCLIB into the file tags. Plain text goes to `USLT` (MP3), `©lyr` (M4A) or `LYRICS` (Opus); timed lyrics also go to the format's timed tag. Missing lyrics never fail the download. |
| `--lyrics-type` | `inline` | How timed lyrics are stored: `inline` puts the raw LRC into the plain lyrics tag (with timestamps), `sidecar` keeps the tag plain and writes a separate `<file>.lrc` next to the audio, `plain` writes only plain text to the tags and keeps timed lyrics in the format's timed tag. |
| `--cache` / `--no-cache` | on | Reuse and update `metadata-cache.json` in the output directory. Disable to always query the providers. |

```bash
trackfetch songs.txt -o ~/Music/RoadTrip          # save to a specific folder
trackfetch songs.txt -o /media/usb --title-only   # short names for a car stereo
trackfetch big-list.txt --delay 3                 # go easy on rate limits
trackfetch songs.txt --format opus                # original YouTube audio, no re-encode
trackfetch "Daft Punk - One More Time"             # one track, no file needed
trackfetch "A - B" "C - D" --track "E - F"         # a few tracks in one go
trackfetch big-list.txt -s deezer,itunes,musicbrainz
trackfetch big-list.txt --disable-sources spotify  # skip Spotify explicitly
trackfetch --list-sources
```

### Color themes

Output is colored by default with the **Cassette** theme. Color is used for
structure — labels, statuses, progress and separators — while titles, paths
and error reasons stay plain. Pick another built-in theme or turn color off:

| Setting | Default | What it does |
| --- | --- | --- |
| `--color` / `color` | `auto` | `auto`, `always` or `never`. `auto` colors a terminal and stays plain in pipes. |
| `--color-theme` / `color_theme` | `cassette` | `cassette`, `neon-tape`, `mono`, `vinyl`, or a custom theme name. |
| `--themes-file` / `themes_file` | next to the config | Custom `themes.ini` with your own themes and colors. |

`trackfetch -h` uses the same theme as the rest of the output, including the
section titles, flags, metavars, choices and `(default: ...)` notes. The theme
is chosen before the help text is built, so `trackfetch --color always
--color-theme vinyl -h` is already colored, and a theme set in the config
applies to help as well.

<table>
  <tr>
    <td align="center">
      <a href="docs/theme-previews/cassette.svg"><img src="docs/theme-previews/cassette-mini.svg" width="300" alt="Cassette theme"></a><br>
      <sub><b>Cassette</b> — default</sub>
    </td>
    <td align="center">
      <a href="docs/theme-previews/neon-tape.svg"><img src="docs/theme-previews/neon-tape-mini.svg" width="300" alt="Neon Tape theme"></a><br>
      <sub><b>Neon Tape</b> — cyan and magenta</sub>
    </td>
  </tr>
  <tr>
    <td align="center">
      <a href="docs/theme-previews/mono.svg"><img src="docs/theme-previews/mono-mini.svg" width="300" alt="Mono theme"></a><br>
      <sub><b>Mono</b> — no hue</sub>
    </td>
    <td align="center">
      <a href="docs/theme-previews/vinyl.svg"><img src="docs/theme-previews/vinyl-mini.svg" width="300" alt="Vinyl theme"></a><br>
      <sub><b>Vinyl</b> — magenta and gold</sub>
    </td>
  </tr>
</table>

```bash
trackfetch songs.txt --color never                 # clean logs and pipes
trackfetch songs.txt --color-theme mono            # another built-in theme
trackfetch songs.txt --color-theme sunset          # theme from themes.ini
```

Custom themes, every role, color formats, file locations and precedence are
documented in **[Color themes](docs/color-themes.md)**. A custom theme is just
an INI section next to your config; a ready-to-copy example is in
[`examples/themes.ini`](examples/themes.ini):

```ini
# ~/.config/trackfetch/themes.ini
[sunset]
base = cassette
accent = #ff8800
progress = 208
success = bright-green
```

```ini
# ~/.config/trackfetch/trackfetch.ini
[trackfetch]
color = auto
color_theme = sunset
```

Set `NO_COLOR=1` or `color = never` for plain output. `--color always`
overrides both `NO_COLOR` and `TERM=dumb`.

### Metadata sources

The default metadata source is **iTunes**, which needs no API key. YouTube is
always handled separately: it supplies the audio and is the last artwork
fallback. The other providers are off unless you select or enable them:

| Source | Credentials | Minimum interval | Notes |
| --- | --- | --- | --- |
| `itunes` | none | 3.5 s | Storefront country defaults to `us`. About 20 Search API calls per minute are allowed, so the interval keeps a small margin below that ceiling. |
| `deezer` | none | 0.25 s | Public search |
| `musicbrainz` | none | 1.1 s | Cover art comes from the Cover Art Archive |
| `vocadb` | none | 0.5 s | Japanese, Chinese, Korean and Vocaloid metadata |
| `spotify` | client ID and secret | — | Optional, disabled by default |

The order in `-s` is the lookup priority. If the first provider has no suitable
match, trackfetch tries the next one. The first result that passes both
matching thresholds wins. Command-line choices override the config file for
that run: `-s deezer` enables Deezer even if the config disables it, while
`--disable-sources deezer` still disables it. Both thresholds must be finite
numbers from `0.0` to `1.0`; invalid values stop with an error instead of being
silently clamped.

Search survives typos, different casing, missing hyphens and `ё`/`е` spelling
differences. Every provider first tries its precise query. If nothing matches,
trackfetch retries with looser free-text queries: `artist title`, then
`title artist`, then the title alone, then the title without its trailing words.
The same scoring thresholds decide when to stop, so a relaxed query cannot
sneak in an unrelated song.

After every configured provider misses, trackfetch also tries two free fallback
sources, `deezer` and then `musicbrainz`. Fallbacks are skipped when the user
disabled them with `--disable-sources` or the config file, and when metadata is
turned off completely with `-s none`.

```bash
trackfetch songs.txt -s deezer,itunes,musicbrainz,vocadb
trackfetch songs.txt -s none                       # no metadata, YouTube audio only
trackfetch songs.txt --provider-opt itunes.country=ua
trackfetch songs.txt --provider-opt musicbrainz.min_interval=1.5
trackfetch songs.txt --match-threshold 0.7 --title-threshold 0.85
```

CJK titles and recognizable Vocaloid hints temporarily promote VocaDB for that
lookup. The configured order is not changed. Music providers are separate:
YouTube and SoundCloud are configured with `music_sources`, so turning metadata
lookups off with `-s none` still downloads audio.

Provider failures are handled internally: after two consecutive real failures
(for example a timeout or an HTTP server error) the provider cools down for
30 seconds. The cooldown doubles on each further failure, up to 600 seconds.
A valid empty search, a missing match or missing artwork is not a failure. The
provider is retried after the cooldown and returns to its configured priority
when it recovers.

Metadata is cached per provider in `metadata-cache.json` in the output
directory. Cached entries also keep the track duration, which is used later for
the YouTube and lyrics matching. A lower-priority cached result never prevents
a higher-priority provider from being retried after recovery.

Artwork is identified by its actual bytes, not by the URL or the HTTP
`Content-Type` header. JPEG, PNG, GIF and WebP keep their real extension and
MIME type. MP3 and Opus can embed all four; M4A supports JPEG and PNG, so GIF or
WebP artwork is skipped for that container instead of being mislabelled as
JPEG.

### Music sources

YouTube and SoundCloud are the music providers. They are chosen separately from
the metadata providers, in priority order:

```ini
[trackfetch]
# Default: YouTube first, SoundCloud only when the trigger allows it
music_sources = youtube,soundcloud
```

- `youtube,soundcloud` (default) keeps the old behaviour: YouTube is primary,
  and SoundCloud is the fallback for the failures selected by
  `soundcloud_trigger`.
- `soundcloud,youtube` tries SoundCloud first and uses YouTube only when
  SoundCloud finds no usable track.
- `youtube` disables SoundCloud completely; `soundcloud` disables YouTube and
  its thumbnail fallback.
- At least one music source must remain. Disabling both stops with an error.

The same options work from the command line:

```bash
trackfetch songs.txt --music-sources soundcloud,youtube
trackfetch songs.txt --music-sources youtube          # no SoundCloud at all
trackfetch songs.txt --no-youtube                     # SoundCloud only
trackfetch songs.txt --no-soundcloud                  # YouTube only
trackfetch songs.txt --disable-sources soundcloud     # same as --no-soundcloud
```

A CLI `--music-sources` list overrides the configured list and configured
`youtube_enabled`/`soundcloud_enabled` flags for the providers it names. An
explicit `--no-youtube`, `--no-soundcloud` or `--disable-sources` still wins.
When a priority list is set explicitly, it is authoritative: only disable
flags remove entries, while a stale `youtube_enabled = true` or
`soundcloud_enabled = true` does not add a provider back. On the command line,
`--youtube` and `--soundcloud` append a provider that is not in the list
already.

### Lyrics

For every output format trackfetch also looks up lyrics on
[LRCLIB](https://lrclib.net/) and embeds them in the tag container. Each format
uses its own standard tag.

| Format | Plain text | Timed lyrics |
| --- | --- | --- |
| `mp3` | ID3 `USLT` | ID3 `SYLT`, only when the source returns synchronized lyrics |
| `m4a` | `©lyr` atom | `SYNCEDLYRICS` freeform atom (`com.apple.iTunes`), raw LRC |
| `opus` | Vorbis comment `LYRICS` | Vorbis comment `SYNCEDLYRICS`, raw LRC |

When only plain lyrics are available, only the plain tag is written. Timestamps
are never invented.

`--lyrics-type` controls what happens when timed lyrics are available:

- `inline` (default) writes the raw LRC into the plain lyrics tag as well. This
  keeps the timestamps visible in players that parse LRC from that tag, but
  players that display the tag verbatim show `[00:01.00]` prefixes.
- `sidecar` keeps the plain lyrics tag clean and writes `<file>.lrc` next to
  the audio. Players that read a sibling LRC file show synchronized lyrics,
  while everyone else sees plain text. The `.lrc` file has to travel with the
  audio when files are moved.
- `plain` writes only plain text to the tags and keeps timed lyrics solely in
  the format's timed tag.

The source is LRCLIB, which needs no API key. Lyrics embedding is enabled by
default for all three formats and can be turned off with `--no-lyrics` or
`lyrics_enabled = false` in the config file. The placement can also be set with
`lyrics_type = inline|sidecar|plain`.

LRCLIB is searched by track name first, without the artist, then with looser
free-text queries (the same relaxation used for metadata). Results are ranked
locally by title, artist and duration, and a version within a few seconds of
the real track length wins. When two results are equally good, the one with
timed lyrics is preferred. A typical run prints one of:

- `Lyrics: synced (embedded)` or `Lyrics: synced (sidecar + tags)`
- `Lyrics: plain only (no synced version)`
- `Lyrics: not found`

Missing lyrics, a timeout or an HTTP error never fails the download. The file
is still saved with its usual metadata. If a file already contains lyrics and
no new lyrics are found, the existing tags are left untouched. When new lyrics
are found, the old lyrics tags are replaced instead of duplicated. Existing
tags and cover art, and the audio data itself, are never rewritten or
re-encoded.

```bash
trackfetch songs.txt                              # embed lyrics (default, any format)
trackfetch songs.txt --format mp3 --no-lyrics     # keep the tags lyrics-free
```

### Inline tracks

Skip the file and name the tracks right on the command line:

```bash
trackfetch "Daft Punk - One More Time"
trackfetch "Daft Punk - One More Time" "Radiohead - Paranoid Android"
trackfetch --track "Daft Punk - One More Time" --track "Radiohead - Paranoid Android"
```

A file and inline tracks can be mixed: `trackfetch songs.txt --track "Blur - Song 2"`.
The separator is the same ` - ` as in the file, and the first ` - ` splits the
artist from the title.

### Configuration file

Put your defaults in an INI file and forget the flags:

```ini
[trackfetch]
output = ~/Music/trackfetch
format = m4a
title_only = false
delay = 1.0
input = ~/songs.txt

# Metadata source priority
metadata_sources = deezer,itunes,musicbrainz,vocadb

# Music source priority
music_sources = youtube,soundcloud

# Sources to exclude
disable_sources = spotify

# Provider settings
spotify_enabled = false
spotify_client_id = your-client-id
spotify_client_secret = your-client-secret
no_logs = false

# Terminal colors
color = auto
color_theme = cassette
# themes_file = ~/.config/trackfetch/themes.ini

itunes_enabled = true
itunes_country = us
itunes_min_interval = 3.5

deezer_enabled = true
deezer_min_interval = 0.25

musicbrainz_enabled = true
musicbrainz_min_interval = 1.1

vocadb_enabled = true
vocadb_min_interval = 0.5

# Music providers (independent of metadata)
youtube_enabled = true
soundcloud_enabled = true

# SoundCloud fallback for age-restricted YouTube videos
soundcloud_trigger = age
soundcloud_ambiguous = skip
soundcloud_min_score = 0.75
soundcloud_min_margin = 0.08

# Lyrics embedding into file tags
lyrics_enabled = true
lyrics_type = inline

# Metadata cache (metadata-cache.json in the output directory)
cache_enabled = true

# Matching thresholds
match_threshold = 0.6
title_threshold = 0.8
```

Most options above can be set there under the `[trackfetch]` section. Source
priority and the provider settings use the keys shown in the example;
`--track` and `--list-sources` only make sense on the command line. The
precedence is always the same:

1. the command-line flag,
2. the config file,
3. the built-in default (the current directory for the output folder).

For source selection, a CLI `-s` list overrides both `metadata_sources` and
conflicting `disable_sources`/`*_enabled=false` entries for the providers it
names. An explicit CLI disable from `--disable-sources` or
`--provider-opt NAME.enabled=false` wins over a CLI selection. Music providers
follow the same rules with `music_sources`, `youtube_enabled` and
`soundcloud_enabled`. The config file itself is never rewritten.

trackfetch looks for the config file in this order: the path given with
`--config`, the path in `$TRACKFETCH_CONFIG`, `trackfetch.ini` in the current
directory, `$XDG_CONFIG_HOME/trackfetch/trackfetch.ini`,
`~/.config/trackfetch/trackfetch.ini` and `~/.trackfetch.ini`.

A relative path in the config file, such as `output = songs`, is relative to
the directory you run trackfetch from. A `[DEFAULT]` section works as well.

### Spotify credentials

Spotify is optional and is not queried unless it is selected with
`-s spotify` or `spotify_enabled = true`. Without credentials trackfetch skips
Spotify quietly and uses the other sources. Give the credentials in whichever
way suits you:

```bash
# in the config file
[trackfetch]
spotify_client_id = your-client-id
spotify_client_secret = your-client-secret
```

```bash
# in the environment
export SPOTIFY_CLIENT_ID='your-client-id'
export SPOTIFY_CLIENT_SECRET='your-client-secret'
```

```bash
# on the command line
trackfetch songs.txt --spotify-client-id your-id --spotify-client-secret your-secret
```

The flag wins over the config file, and the config file wins over the
environment variable.

### Audio formats

| Format | What you get | Plays on |
| --- | --- | --- |
| `mp3` (default) | YouTube's audio **re-encoded** to the best VBR MP3. A second lossy encode, so slightly below the source | everything, including old players and car stereos |
| `m4a` | YouTube's **original** AAC audio when available, copied without re-encoding | Apple devices, iTunes, most players |
| `opus` | YouTube's **original** Opus audio, copied without re-encoding. The best quality you can get | most modern players, Android, browsers; not iTunes or older devices |

All three get the same metadata tags, embedded cover art and embedded lyrics. `done.txt` doesn't track the format, so use a separate `-o` folder for each format.

### Input file

```text
# Lines starting with "#" are comments. Blank lines are ignored.
Daft Punk - One More Time
Sufjan Stevens - Mystery of Love - Remastered   ← only the first " - " separates artist and title
```

The separator is space, hyphen, space (` - `). Lines without it are skipped,
and trackfetch prints how many lines it skipped and which ones they were. See [`examples/songs.txt`](https://github.com/ByteMe6/trackfetch/blob/master/examples/songs.txt).

### Output folder

```text
./
├── Daft Punk - One More Time.m4a
├── Radiohead - Paranoid Android.m4a
├── done.txt      ← finished songs, skipped on the next run
└── failed.txt    ← "Artist - Title | reason" for each song that failed
```

**Retry failures** by stripping the reasons from `failed.txt` and running it again:

```bash
cut -d '|' -f 1 ./failed.txt > retry.txt
trackfetch retry.txt
```

**Re-download a song** by deleting its MP3 and its line in `done.txt`.

With `--no-logs`, trackfetch does not read `done.txt` and does not write
`done.txt` or `failed.txt`. Progress is therefore not restored between runs:
songs finished in an earlier run are downloaded again, and the failure log is
neither created nor updated. `failed.txt` is a write-only log in every mode, so
the flag only makes trackfetch stop producing it.

### Cheat sheet

A [tldr](https://tldr.sh/) page is in [`docs/tldr/trackfetch.md`](https://github.com/ByteMe6/trackfetch/blob/master/docs/tldr/trackfetch.md). To use it with [tealdeer](https://github.com/tealdeer-rs/tealdeer), copy it into your custom pages folder as `trackfetch.page.md`.

## How it works

1. **Find the metadata.** trackfetch queries the configured providers in priority order. Every result is scored by fuzzy similarity, 70% title and 30% artist. Both the overall `match_threshold` and the `title_threshold` must pass, so an unrelated result is rejected instead of being used. If every query misses, provider searches are retried with looser phrasing, and the configured providers are followed by the `deezer` and `musicbrainz` fallbacks. The winning result supplies the title, artists, album details, release date, duration and artwork.
2. **Find the audio.** With the default `music_sources = youtube,soundcloud`, it searches YouTube first and scores the top five results:

   | Signal | Effect on the score |
   | --- | --- |
   | Similarity to the song title | × 0.70 |
   | Similarity to the artist | × 0.30 |
   | `official audio` in the video title | +0.08 |
   | `audio` in the video title | +0.03 |
   | Duration within 3 seconds of the metadata duration | +0.05 |
   | Duration within 10 seconds | +0.02 |
   | `cover`, `karaoke`, `караоке`, `nightcore`, `sped up`, `slowed`, `remix`, `reaction` | −0.20 each |

   If the artist query finds nothing, trackfetch retries with `<title>` and then `<title> Topic`; title-only results need artist evidence, so covers and same-title songs by other artists are rejected. When all three find nothing usable, it falls back to the YouTube Music search, which is not filtered for some topics the way anonymous YouTube search is. Each YouTube Music candidate is checked against its full video details: the title must be close, the artist (or channel) must match, and known durations may differ by at most 10 seconds.

3. **Download.** yt-dlp downloads only the winning video and converts it to the chosen format. `m4a` and `opus` keep YouTube's original audio, `mp3` re-encodes it.
4. **SoundCloud fallback.** When SoundCloud is second in `music_sources` (the default) and YouTube fails in the way `soundcloud_trigger` allows — by default only an age restriction (`Sign in to confirm your age`) — trackfetch searches SoundCloud for an independently available copy with yt-dlp's `scsearch`. With `music_sources = soundcloud,youtube` the order is reversed: SoundCloud is searched first and YouTube is tried only when SoundCloud finds no usable track. This is not a bypass of YouTube's age verification: no cookies, credentials or alternate clients are used, and every other YouTube error (network, unavailable, private, invalid URL) keeps the normal failure handling. Up to five results are scored, 40% title, 30% artist, 20% duration and 10% metadata consistency. Previews (including the 30-second sample), remixes, covers, live and instrumental versions are rejected. Only a single result above `soundcloud_min_score` and clearly ahead of the runner-up is downloaded automatically. When several results are equally plausible, `soundcloud_ambiguous` decides: `skip` prints the options and asks on a terminal (a piped or `nohup` run skips the song), while `best` takes the highest scoring result without asking. Metadata is fetched with `--dump-single-json` before anything is downloaded, and a fallback is attempted at most once per song.
5. **Tag.** trackfetch replaces any existing tags with these ID3v2.3 frames:

   | Frame | Content |
   | --- | --- |
   | `TIT2` | Title |
   | `TPE1` | Artists |
   | `TALB` | Album |
   | `TPE2` | Album artist |
   | `TRCK` | Track number |
   | `TDRC` | Release date |
   | `APIC` | Front cover, up to 640×640 |

If no metadata source has a suitable match, the song is still downloaded and tagged with the artist and title from your file. If the metadata result has no artwork, trackfetch tries the Cover Art Archive (for MusicBrainz) and then the YouTube thumbnail, so a missing cover never loses otherwise valid metadata.

## Troubleshooting

<details>
<summary><b>Spotify is selected but no credentials are configured</b></summary>

trackfetch skips Spotify quietly and continues with the remaining sources. To use Spotify, set `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` in the config file or the environment. See [Spotify credentials](#spotify-credentials).

</details>

<details>
<summary><b>A provider is skipped temporarily</b></summary>

After two consecutive network, timeout, server or parsing failures a provider is paused: 30 seconds at first, doubling up to 600 seconds. trackfetch keeps using the other sources and retries the provider when the cooldown expires. Empty search results and missing artwork do not trigger a cooldown.

</details>

<details>
<summary><b>Every song fails with <code>no YouTube result</code> or <code>yt-dlp download failed</code></b></summary>

YouTube changes often. Update yt-dlp first with `pipx upgrade yt-dlp` or `yt-dlp -U`. Recent versions of yt-dlp also need Deno: check that `deno --version` works in the same terminal.

</details>

<details>
<summary><b><code>ERROR: Postprocessing: ffprobe and ffmpeg not found</code></b></summary>

Install FFmpeg and check that `ffmpeg -version` works in the same terminal.

</details>

<details>
<summary><b>The wrong version of a song was downloaded</b></summary>

Make the line in your file more specific, for example by using the exact title as Spotify spells it. Then delete the MP3 and its line in `done.txt` and run trackfetch again. If it keeps picking the wrong upload, [open an issue](https://github.com/ByteMe6/trackfetch/issues/new?template=bug_report.yml) with the `YouTube score` lines from the output.

</details>

<details>
<summary><b>HTTP 429 or other rate-limit errors</b></summary>

Raise `--delay`, for example to `3`. Stopped runs continue where they left off.

</details>

## Development

```bash
pip install -e ".[test]" ruff
ruff check .
pytest --cov=trackfetch
```

The tests stub every network and subprocess call, so they run offline in under a second. To build a standalone binary yourself, run `pip install pyinstaller && pyinstaller trackfetch.spec`; it ends up in `dist/`.

See [CONTRIBUTING.md](https://github.com/ByteMe6/trackfetch/blob/master/CONTRIBUTING.md) before opening a pull request.

### Releasing

Every push to `master` runs the tests on Linux, macOS and Windows. When `version` in [`pyproject.toml`](https://github.com/ByteMe6/trackfetch/blob/master/pyproject.toml) has no matching `vX.Y.Z` tag yet, the [Build & Release](https://github.com/ByteMe6/trackfetch/blob/master/.github/workflows/release.yml) workflow also builds all six binaries and publishes a release, using that version's section of [`CHANGELOG.md`](https://github.com/ByteMe6/trackfetch/blob/master/CHANGELOG.md) as the notes.

To release, move the changes under `[Unreleased]` in the changelog to a new `## [X.Y.Z] - YYYY-MM-DD` section, bump `version`, and push.

> [!IMPORTANT]
> Bump the version in a commit that doesn't edit `.github/workflows/`. GitHub doesn't let the workflow token tag a commit that changes workflow files, so the release step would fail with a 403.

## Disclaimer

trackfetch is for personal use with content you have the right to download. You are responsible for following copyright law where you live and the terms of service of YouTube and Spotify. trackfetch isn't affiliated with or endorsed by Spotify, YouTube or TuneMyMusic. If you can, support the artists you listen to.

## Contributors

<a href="https://github.com/ByteMe6/trackfetch/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=ByteMe6/trackfetch" />
</a>

## License

trackfetch is free software, released under the [GNU General Public License v3.0 or later](https://github.com/ByteMe6/trackfetch/blob/master/LICENSE). You can use, study, change and share it. If you distribute a modified version, it must stay under the same license.
