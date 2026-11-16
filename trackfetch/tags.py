# SPDX-License-Identifier: GPL-3.0-or-later
"""Write tags and cover art into MP3, Opus and M4A files."""

import base64
from pathlib import Path

from mutagen.flac import Picture
from mutagen.id3 import APIC, ID3, TALB, TDRC, TIT2, TPE1, TPE2, TRCK
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggopus import OggOpus

from .images import detect_image_format, image_mime_type
from .lyrics import add_mp3_lyrics


def add_metadata(
    audio_path: Path,
    cover_path: Path,
    metadata: dict,
    lyrics=None,
):
    if audio_path.suffix == ".opus":
        add_opus_metadata(
            audio_path,
            cover_path,
            metadata,
        )
    elif audio_path.suffix == ".m4a":
        add_m4a_metadata(
            audio_path,
            cover_path,
            metadata,
        )
    else:
        add_mp3_metadata(
            audio_path,
            cover_path,
            metadata,
            lyrics,
        )


def add_mp3_metadata(
    mp3_path: Path,
    cover_path: Path,
    metadata: dict,
    lyrics=None,
):
    try:
        audio = ID3(mp3_path)
    except Exception:
        audio = ID3()

    for tag in [
        "APIC",
        "TIT2",
        "TPE1",
        "TALB",
        "TPE2",
        "TRCK",
        "TDRC",
    ]:
        audio.delall(tag)

    audio.add(
        TIT2(
            encoding=3,
            text=metadata["title"],
        )
    )

    audio.add(
        TPE1(
            encoding=3,
            text=metadata["artist"],
        )
    )

    if metadata["album"]:
        audio.add(
            TALB(
                encoding=3,
                text=metadata["album"],
            )
        )

    if metadata["album_artist"]:
        audio.add(
            TPE2(
                encoding=3,
                text=metadata["album_artist"],
            )
        )

    if metadata["track_number"]:
        audio.add(
            TRCK(
                encoding=3,
                text=str(metadata["track_number"]),
            )
        )

    if metadata["release_date"]:
        audio.add(
            TDRC(
                encoding=3,
                text=str(metadata["release_date"]),
            )
        )

    if cover_path.exists():
        image_data = cover_path.read_bytes()
        mime = image_mime_type(image_data)

        if mime is not None:
            audio.add(
                APIC(
                    encoding=3,
                    mime=mime,
                    type=3,
                    desc="Cover",
                    data=image_data,
                )
            )

    add_mp3_lyrics(audio, lyrics)

    audio.save(
        mp3_path,
        v2_version=3,
    )


def add_opus_metadata(
    opus_path: Path,
    cover_path: Path,
    metadata: dict,
):
    audio = OggOpus(opus_path)

    fields = {
        "TITLE": metadata["title"],
        "ARTIST": metadata["artist"],
        "ALBUM": metadata["album"],
        "ALBUMARTIST": metadata["album_artist"],
        "TRACKNUMBER": metadata["track_number"],
        "DATE": metadata["release_date"],
    }

    for key in [*fields, "METADATA_BLOCK_PICTURE"]:
        if key in audio:
            del audio[key]

    for key, value in fields.items():
        if value:
            audio[key] = str(value)

    if cover_path.exists():
        image_data = cover_path.read_bytes()
        mime = image_mime_type(image_data)

        if mime is not None:
            picture = Picture()
            picture.type = 3
            picture.mime = mime
            picture.desc = "Cover"
            picture.data = image_data

            audio["METADATA_BLOCK_PICTURE"] = base64.b64encode(
                picture.write()
            ).decode("ascii")

    audio.save()


def add_m4a_metadata(
    m4a_path: Path,
    cover_path: Path,
    metadata: dict,
):
    audio = MP4(m4a_path)

    fields = {
        "\xa9nam": metadata["title"],
        "\xa9ART": metadata["artist"],
        "\xa9alb": metadata["album"],
        "aART": metadata["album_artist"],
        "\xa9day": metadata["release_date"],
    }

    for key in [*fields, "trkn", "covr"]:
        if key in audio:
            del audio[key]

    for key, value in fields.items():
        if value:
            audio[key] = [str(value)]

    if metadata["track_number"]:
        audio["trkn"] = [
            (int(metadata["track_number"]), 0)
        ]

    if cover_path.exists():
        image_data = cover_path.read_bytes()
        format_name = detect_image_format(image_data)

        # MP4 cover art supports JPEG and PNG. Embedding a GIF or WebP as
        # JPEG would mislabel the bytes, so leave it out for this format.
        if format_name == "jpeg":
            audio["covr"] = [
                MP4Cover(image_data, imageformat=MP4Cover.FORMAT_JPEG)
            ]
        elif format_name == "png":
            audio["covr"] = [
                MP4Cover(image_data, imageformat=MP4Cover.FORMAT_PNG)
            ]

    audio.save()
