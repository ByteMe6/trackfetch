# trackfetch

> Download songs listed in a text file as tagged MP3, M4A or Opus files, using configurable free metadata sources and YouTube audio.
> Requires `yt-dlp` and `ffmpeg`. Spotify is optional and only used when selected.
> More information: <https://github.com/ByteMe6/trackfetch#usage>.

- Download every song from a file with one `Artist - Title` per line into the current directory:

`trackfetch {{path/to/songs.txt}}`

- Download songs into a specific directory:

`trackfetch {{path/to/songs.txt}} {{[-o|--output]}} {{path/to/directory}}`

- Keep YouTube's original audio instead of converting it to MP3:

`trackfetch {{path/to/songs.txt}} {{[-f|--format]}} {{opus|m4a}}`

- Download a few tracks without a text file:

`trackfetch {{"Artist - Title"}} {{"Another Artist - Another Title"}}`

- Name the files by song title only, instead of `Artist - Title`:

`trackfetch {{path/to/songs.txt}} --title-only`

- Use a custom metadata priority:

`trackfetch {{path/to/songs.txt}} {{[-s|--metadata-sources]}} {{deezer,itunes,musicbrainz,vocadb}}`

- Disable a source (disabling YouTube also disables audio downloads):

`trackfetch {{path/to/songs.txt}} --disable-sources {{youtube}}`

- List the available metadata providers and artwork fallbacks:

`trackfetch --list-sources`

- Set a provider-specific option:

`trackfetch {{path/to/songs.txt}} --provider-opt {{itunes.country=ua}}`

- Use a config file for the defaults:

`trackfetch {{path/to/songs.txt}} {{[--config]}} {{path/to/config.ini}}`

- Wait a number of seconds between songs to avoid rate limiting:

`trackfetch {{path/to/songs.txt}} --delay {{3}}`

- Retry the songs that failed in a previous run:

`cut {{[-d|--delimiter]}} '|' {{[-f|--fields]}} 1 {{path/to/directory}}/failed.txt > {{path/to/retry.txt}} && trackfetch {{path/to/retry.txt}} {{[-o|--output]}} {{path/to/directory}}`
