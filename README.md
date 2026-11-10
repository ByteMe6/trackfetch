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

trackfetch reads a plain text file with one `Artist - Title` per line. For every song it looks up the official metadata and cover art on Spotify, picks the best-matching audio on YouTube, and saves an MP3 with complete ID3 tags. Runs are resumable, so you can stop a 1,000-song list at any point and pick it up later.

- **Exact metadata.** The title, every credited artist, album, album artist, track number and release date come from Spotify, not from a YouTube video title.
- **Album art.** The largest Spotify cover is embedded in every file.
- **The right upload.** trackfetch scores five YouTube results per song. Official audio wins; covers, karaoke, nightcore, sped-up, slowed, remix and reaction videos lose.
- **Your choice of format.** MP3 for any player, or Opus and M4A that keep YouTube's original audio without re-encoding.
- **Resumable.** Finished songs are logged in `done.txt` and skipped next time. Failures go to `failed.txt` with the reason.
- **Plays everywhere.** Tags are written as ID3v2.3, which Windows Explorer, Apple Music, Android, car stereos and most other players read.
- **Any alphabet.** Cyrillic and other non-Latin titles are matched correctly and kept in filenames. Characters that are illegal in filenames are replaced.
- **No Python needed.** Standalone binaries for Linux, macOS and Windows on x86_64 and ARM64.

## Install

Pick one. Homebrew and Nix also install yt-dlp, FFmpeg and Deno for you; with the other methods, install them yourself ([see below](#dependencies)). Every method needs a free Spotify API key ([set it up below](#spotify-credentials)).

### Homebrew

macOS and Linux:

```bash
brew install ByteMe6/tap/trackfetch
```

On Intel Macs, Homebrew builds the dependencies from source, so the first install takes a while.

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
trackfetch [-h] [-o OUTPUT] [--config CONFIG] [-f {mp3,m4a,opus}] [--title-only] [--delay DELAY] [--spotify-client-id ID] [--spotify-client-secret SECRET] [input]
```

| Option | Default | What it does |
| --- | --- | --- |
| `input` | required | Text file with one `Artist - Title` per line. Can also be set in the [config file](#configuration-file). |
| `-o`, `--output` | current directory | Folder to save the files in. It's created if it doesn't exist. |
| `--config` | auto-detected | Path to a [config file](#configuration-file). |
| `-f`, `--format` | `m4a` | Audio format: `mp3`, `m4a` or `opus`. See [Audio formats](#audio-formats). |
| `--title-only` | off | Name files `Title.m4a` instead of `Artist - Title.m4a` |
| `--delay` | `1.0` | Seconds to wait between songs. Raise it for long lists. |
| `--spotify-client-id` | `$SPOTIFY_CLIENT_ID` | Spotify API client ID. See [Spotify credentials](#spotify-credentials). |
| `--spotify-client-secret` | `$SPOTIFY_CLIENT_SECRET` | Spotify API client secret. |

```bash
trackfetch songs.txt -o ~/Music/RoadTrip          # save to a specific folder
trackfetch songs.txt -o /media/usb --title-only   # short names for a car stereo
trackfetch big-list.txt --delay 3                 # go easy on rate limits
trackfetch songs.txt --format opus                # original YouTube audio, no re-encode
```

### Configuration file

Put your defaults in an INI file and forget the flags:

```ini
[trackfetch]
output = ~/Music/trackfetch
format = m4a
title_only = false
delay = 1.0
input = ~/songs.txt
spotify_client_id = your-client-id
spotify_client_secret = your-client-secret
```

Every option above can be set there, under the `[trackfetch]` section. The
precedence is always the same:

1. the command-line flag,
2. the config file,
3. the built-in default (the current directory for the output folder).

trackfetch looks for the config file in this order: the path given with
`--config`, the path in `$TRACKFETCH_CONFIG`, `trackfetch.ini` in the current
directory, `$XDG_CONFIG_HOME/trackfetch/trackfetch.ini` (usually
`~/.config/trackfetch/trackfetch.ini`) and `~/.trackfetch.ini`.

### Spotify credentials

trackfetch needs a Spotify client ID and secret to read the metadata. Give
them in whichever way suits you:

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
| `m4a` (default) | YouTube's **original** AAC audio when available, copied without re-encoding | Apple devices, iTunes, most players |
| `opus` | YouTube's **original** Opus audio, copied without re-encoding. The best quality you can get | most modern players, Android, browsers; not iTunes or older devices |
| `mp3` | YouTube's audio **re-encoded** to the best VBR MP3. A second lossy encode, so slightly below the source | everything, including old players and car stereos |

All three get the same tags and embedded cover art. `done.txt` doesn't track the format, so use a separate `-o` folder for each format.

### Input file

```text
# Lines starting with "#" are comments. Blank lines are ignored.
Daft Punk - One More Time
Sufjan Stevens - Mystery of Love - Remastered   ← only the first " - " separates artist and title
```

The separator is space, hyphen, space (` - `). Lines without it are skipped. See [`examples/songs.txt`](https://github.com/ByteMe6/trackfetch/blob/master/examples/songs.txt).

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

### Cheat sheet

A [tldr](https://tldr.sh/) page is in [`docs/tldr/trackfetch.md`](https://github.com/ByteMe6/trackfetch/blob/master/docs/tldr/trackfetch.md). To use it with [tealdeer](https://github.com/tealdeer-rs/tealdeer), copy it into your custom pages folder as `trackfetch.page.md`.

## How it works

1. **Find the song on Spotify.** trackfetch searches for `artist:"…" track:"…"` and falls back to a looser search if nothing comes back. Every result is scored by fuzzy similarity, 70% title and 30% artist, and the best one supplies the official spelling, all credited artists, the album details and the cover.
2. **Find the audio on YouTube.** It searches YouTube for the official artist and title and scores the top five results:

   | Signal | Effect on the score |
   | --- | --- |
   | Similarity to the song title | × 0.70 |
   | Similarity to the artist | × 0.30 |
   | `official audio` in the video title | +0.08 |
   | `audio` in the video title | +0.03 |
   | `cover`, `karaoke`, `караоке`, `nightcore`, `sped up`, `slowed`, `remix`, `reaction` | −0.20 each |

3. **Download.** yt-dlp downloads only the winning video and converts it to MP3.
4. **Tag.** trackfetch replaces any existing tags with these ID3v2.3 frames:

   | Frame | Content |
   | --- | --- |
   | `TIT2` | Title |
   | `TPE1` | Artists |
   | `TALB` | Album |
   | `TPE2` | Album artist |
   | `TRCK` | Track number |
   | `TDRC` | Release date |
   | `APIC` | Front cover, up to 640×640 |

If Spotify has no match, the song is still downloaded and tagged with the artist and title from your file.

## Troubleshooting

<details>
<summary><b><code>ERROR: Spotify credentials not found.</code></b></summary>

`SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` aren't set in this terminal. See [Spotify credentials](#spotify-credentials).

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

## License

trackfetch is free software, released under the [GNU General Public License v3.0 or later](https://github.com/ByteMe6/trackfetch/blob/master/LICENSE). You can use, study, change and share it. If you distribute a modified version, it must stay under the same license.
