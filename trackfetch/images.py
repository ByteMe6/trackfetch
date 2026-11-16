# SPDX-License-Identifier: GPL-3.0-or-later
"""Cover art detection, downloading and fallbacks."""

from pathlib import Path

import requests

from .constants import USER_AGENT
from .youtube import youtube_thumbnail_urls

IMAGE_FORMATS = {
    "jpeg": ("image/jpeg", ".jpg"),
    "png": ("image/png", ".png"),
    "gif": ("image/gif", ".gif"),
    "webp": ("image/webp", ".webp"),
}

def detect_image_format(data: bytes):
    """Return the image format from its signature, or None if unsupported."""
    if not data:
        return None

    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"

    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"

    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"

    if (
        len(data) >= 12
        and data.startswith(b"RIFF")
        and data[8:12] == b"WEBP"
    ):
        return "webp"

    return None


def image_mime_type(data: bytes):
    format_name = detect_image_format(data)

    if format_name is None:
        return None

    return IMAGE_FORMATS[format_name][0]


def is_image_bytes(data: bytes) -> bool:
    """Check common image signatures before writing a cover file."""
    return detect_image_format(data) is not None


def download_cover(url: str, destination: Path):
    response = requests.get(
        url,
        timeout=30,
        headers={
            "User-Agent": USER_AGENT
        },
    )

    response.raise_for_status()

    format_name = detect_image_format(response.content)

    if format_name is None:
        raise ValueError("response is not a valid image")

    destination = Path(destination)
    destination.write_bytes(response.content)

    return format_name

def download_best_cover(metadata, video, cover_path, youtube_enabled):
    """Download provider artwork, then fall back to a YouTube thumbnail.

    Returns the path of the saved image with an extension that matches the
    actual image signature, or None when no usable image was downloaded.
    """
    candidates = []

    if metadata.get("cover_url"):
        candidates.append(
            (metadata["cover_url"], metadata.get("source") or "metadata")
        )

    if youtube_enabled:
        for url in youtube_thumbnail_urls(video):
            candidates.append((url, "YouTube"))

    last_error = None
    cover_path = Path(cover_path)

    for url, source in candidates:
        try:
            download_cover(url, cover_path)

            # Trust the bytes on disk over the URL or the Content-Type header,
            # so the saved extension always matches the actual image format.
            image_data = cover_path.read_bytes()
            format_name = detect_image_format(image_data)

            if format_name is None:
                raise ValueError("response is not a valid image")

            final_path = cover_path.with_suffix(
                IMAGE_FORMATS[format_name][1]
            )

            if cover_path != final_path:
                cover_path.replace(final_path)

            if final_path.stat().st_size > 0:
                print(f"{source} cover downloaded")
                return final_path

        except Exception as error:
            last_error = error

    if last_error is not None:
        print(f"WARNING: cover download failed: {last_error}")

    return None
