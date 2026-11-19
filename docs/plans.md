# Plans

## LRC sidecar files

Status: implemented as `--lyrics-type sidecar` / `lyrics_type = sidecar`.

Write timed lyrics to a separate `<audio-stem>.lrc` file next to the
downloaded track, in addition to the embedded tags.

- Keep plain text in `USLT`, `©lyr` and `LYRICS` so players that display the
  lyrics field verbatim show clean text.
- Keep timed lyrics in `SYLT` and `SYNCEDLYRICS` for players that read them.
- The sidecar lets players that look for an LRC file next to the audio show
  synchronized lyrics without embedding timestamps in the plain text field.
- Trade-off: the `.lrc` file has to travel with the audio when files are moved
  or copied.
