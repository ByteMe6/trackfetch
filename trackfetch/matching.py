# SPDX-License-Identifier: GPL-3.0-or-later
"""Text normalization and metadata candidate scoring."""

import re
import unicodedata
from difflib import SequenceMatcher

NOISE_BRACKETS_RE = re.compile(
    r"[\(\[]\s*(?:"
    r"official\s+(?:music\s+)?video"
    r"|official\s+audio"
    r"|lyric\s+video"
    r"|lyrics?"
    r"|audio"
    r"|video"
    r"|visuali[sz]er"
    r"|remaster(?:ed)?"
    r"|live"
    r"|radio\s+edit"
    r"|extended\s+mix"
    r"|feat\.?\s+[^\)\]]*"
    r")\s*[\)\]]",
    re.IGNORECASE,
)
FEAT_RE = re.compile(r"\s+(?:feat\.?|featuring)\s+.*$", re.IGNORECASE)

# A metadata candidate whose artist barely resembles the input is usually a
# cover or a same-title song by another act. Keeping the user's own artist and
# title beats downloading the wrong track.
MIN_ARTIST_SIMILARITY = 0.45


def normalize(text: str) -> str:
    # NFC keeps meaningful Unicode characters (CJK, accented letters) intact.
    text = unicodedata.normalize("NFC", text).lower()
    # Russian ё and е are the same letter for search and matching purposes.
    text = text.replace("ё", "е")
    text = NOISE_BRACKETS_RE.sub(" ", text)
    text = FEAT_RE.sub(" ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(
        None,
        normalize(a),
        normalize(b)
    ).ratio()


def artist_similarity(input_artist: str, candidate_artist: str) -> float:
    """Compare an artist while allowing providers to list several artists."""
    if not candidate_artist:
        return 0.0

    best = similarity(input_artist, candidate_artist)

    for part in re.split(r"[,;&/]| feat\.? | featuring ", candidate_artist):
        part = part.strip()

        if part:
            best = max(best, similarity(input_artist, part))

    return best


def score_metadata(
    input_artist: str,
    input_title: str,
    candidate: dict,
    match_threshold: float,
    title_threshold: float,
):
    """Return a copy of the candidate with a score, or None if it is too weak."""
    candidate_title = candidate.get("title") or ""

    if not candidate_title:
        return None

    title_score = similarity(input_title, candidate_title)

    if title_score < title_threshold:
        return None

    candidate_artist = candidate.get("artist") or ""
    artist_score = artist_similarity(
        input_artist,
        candidate_artist,
    )

    # A close title alone must not turn a cover or an unrelated act into the
    # track. When both sides name an artist, they have to be at least roughly
    # the same, otherwise keeping the user's own artist/title is better.
    if input_artist and candidate_artist:
        if artist_score < MIN_ARTIST_SIMILARITY:
            return None

    overall = title_score * 0.70 + artist_score * 0.30

    if overall < match_threshold:
        return None

    scored = dict(candidate)
    scored["score"] = overall
    scored["title_score"] = title_score
    scored["artist_score"] = artist_score

    return scored


def select_best_metadata(
    candidates,
    input_artist: str,
    input_title: str,
    match_threshold: float,
    title_threshold: float,
):
    """Pick the highest scoring candidate that passes both thresholds."""
    best = None

    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue

        scored = score_metadata(
            input_artist,
            input_title,
            candidate,
            match_threshold,
            title_threshold,
        )
        swapped = score_metadata(
            input_title,
            input_artist,
            candidate,
            match_threshold,
            title_threshold,
        )

        for result in (scored, swapped):
            if result is None:
                continue

            if best is None or result["score"] > best["score"]:
                best = result

    return best


def fallback_metadata(artist: str, title: str) -> dict:
    return {
        "artist": artist,
        "title": title,
        "album": "",
        "album_artist": artist,
        "track_number": None,
        "release_date": None,
        "duration": None,
        "cover_url": None,
        "source": "input",
        "source_id": None,
        "score": 0.0,
    }
