# SPDX-License-Identifier: GPL-3.0-or-later
"""File naming, song parsing and done/failed log helpers."""

import re
from pathlib import Path

from .constants import MAX_FILENAME_BYTES


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = re.sub(r"\s+", " ", name).strip()

    encoded = name.encode("utf-8")

    if len(encoded) > MAX_FILENAME_BYTES:
        encoded = encoded[:MAX_FILENAME_BYTES]
        name = encoded.decode("utf-8", errors="ignore")

    return name


def parse_song(line: str):
    if " - " not in line:
        return None

    artist, title = line.split(" - ", 1)

    artist = artist.strip()
    title = title.strip()

    if not artist or not title:
        return None

    return artist, title

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


def read_song_file(path: Path):
    """Read Artist - Title pairs from a text file.

    Returns a (songs, skipped) tuple, where skipped holds the lines that
    could not be parsed.
    """
    songs = []
    skipped = []

    for line in path.read_text(
        encoding="utf-8-sig",
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
