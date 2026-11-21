# SPDX-License-Identifier: GPL-3.0-or-later
"""SoundCloud fallback for YouTube videos blocked by an age restriction.

This is a search for an independently available copy of a track on another
platform. It never tries to bypass YouTube's age verification: no cookies, no
credentials and no alternate YouTube clients are used here.

The module is deliberately independent from the CLI and from the pipeline so
that the matching rules can be tested with plain dictionaries instead of live
network calls.
"""

import json
import re
import subprocess
import sys
import unicodedata

from unidecode import unidecode

from . import colors
from .constants import (
    SOUNDCLOUD_ARTIST_WEIGHT,
    SOUNDCLOUD_DEFAULT_AMBIGUOUS,
    SOUNDCLOUD_DEFAULT_ENABLED,
    SOUNDCLOUD_DETAILS_LIMIT,
    SOUNDCLOUD_DETAILS_TIMEOUT,
    SOUNDCLOUD_DURATION_TOLERANCE,
    SOUNDCLOUD_DURATION_WEIGHT,
    SOUNDCLOUD_EXTRA_WEIGHT,
    SOUNDCLOUD_MIN_MARGIN,
    SOUNDCLOUD_MIN_SCORE,
    SOUNDCLOUD_MIN_TITLE_SCORE,
    SOUNDCLOUD_PREVIEW_RATIO,
    SOUNDCLOUD_PREVIEW_SECONDS,
    SOUNDCLOUD_SEARCH_LIMIT,
    SOUNDCLOUD_SEARCH_TIMEOUT,
    SOUNDCLOUD_TITLE_WEIGHT,
)
from .errors import SoundcloudError
from .matching import normalize, similarity


def _transliterate(text) -> str:
    """Latin-script form with the apostrophes Unidecode adds removed."""
    return unidecode(text or "").replace("'", "")


def _cross_script_similarity(a: str, b: str) -> float:
    return max(
        similarity(a, b),
        similarity(_transliterate(a), _transliterate(b)),
    )


def _contains_artist(artist: str, text: str) -> bool:
    if not artist or not text:
        return False

    forms = zip(
        (artist, _transliterate(artist)),
        (text, _transliterate(text)),
        strict=False,
    )

    for artist_form, text_form in forms:
        normalized_artist = normalize(artist_form)
        normalized_text = normalize(text_form)

        if normalized_artist and normalized_artist in normalized_text:
            return True

    return False


# Words that mark a different version of a song. A result containing one of
# them is only accepted when the requested title contains it as well.
VERSION_MARKERS = (
    "remix",
    "rmx",
    "bootleg",
    "mashup",
    "cover",
    "karaoke",
    "instrumental",
    "nightcore",
    "sped up",
    "slowed",
    "reverb",
    "live",
    "concert",
    "acoustic",
    "piano version",
    "8d audio",
)

# Metadata fields that explicitly forbid a normal stream/download. An
# accessible stream alone is not treated as permission, but an explicit
# block from SoundCloud is always honored.
BLOCKED_POLICIES = ("BLOCK", "SNIP", "PREVIEW")

# The same track can appear more than once during one run (for example when
# the user retries an entry). Only the first attempt is allowed to search.
_ATTEMPTED = set()

STATUS_SELECTED = "selected"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_LOW_CONFIDENCE = "low-confidence"
STATUS_NO_MATCH = "no-match"
STATUS_ERROR = "error"
STATUS_DISABLED = "disabled"


def reset_attempts():
    """Forget which fallbacks were already tried (used by tests)."""
    _ATTEMPTED.clear()


reset_soundcloud_attempts = reset_attempts


def _duration(value):
    """Return a positive duration in seconds, or None when it is unusable."""
    if value is None or isinstance(value, bool):
        return None

    try:
        number = float(value)

    except (TypeError, ValueError):
        return None

    if number <= 0:
        return None

    return number


def _run_ytdlp(command, timeout):
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )

    except subprocess.TimeoutExpired:
        raise SoundcloudError(
            f"yt-dlp timed out after {timeout}s"
        ) from None

    except OSError as error:
        raise SoundcloudError(f"could not run yt-dlp: {error}") from error


def _error_text(result):
    return (getattr(result, "stderr", "") or "").strip()


def soundcloud_search(query: str, limit: int = SOUNDCLOUD_SEARCH_LIMIT):
    """Return the raw yt-dlp ``scsearch`` results for a query."""
    query = " ".join((query or "").split())

    if not query:
        return []

    command = [
        "yt-dlp",
        "--flat-playlist",
        "--dump-json",
        f"scsearch{limit}:{query}",
    ]
    result = _run_ytdlp(command, SOUNDCLOUD_SEARCH_TIMEOUT)

    if getattr(result, "returncode", 0) != 0:
        raise SoundcloudError(
            f"yt-dlp SoundCloud search failed (exit {result.returncode})"
            + (f": {_error_text(result)}" if _error_text(result) else "")
        )

    entries = []

    for line in (result.stdout or "").splitlines():
        line = line.strip()

        if not line:
            continue

        try:
            data = json.loads(line)

        except ValueError:
            continue

        if isinstance(data, dict):
            entries.append(data)

    return entries


def soundcloud_track_details(url: str):
    """Fetch full metadata for one SoundCloud track without downloading it."""
    if not url:
        raise SoundcloudError("SoundCloud track has no URL")

    command = [
        "yt-dlp",
        "--skip-download",
        "--no-playlist",
        "--dump-single-json",
        url,
    ]
    result = _run_ytdlp(command, SOUNDCLOUD_DETAILS_TIMEOUT)

    if getattr(result, "returncode", 0) != 0:
        raise SoundcloudError(
            f"yt-dlp SoundCloud metadata failed (exit {result.returncode})"
            + (f": {_error_text(result)}" if _error_text(result) else "")
        )

    try:
        data = json.loads(result.stdout or "")

    except ValueError:
        raise SoundcloudError(
            "yt-dlp returned invalid SoundCloud metadata"
        ) from None

    if not isinstance(data, dict):
        raise SoundcloudError("yt-dlp returned invalid SoundCloud metadata")

    return data


def parse_search_result(data):
    """Translate one yt-dlp SoundCloud entry into a compact candidate.

    Returns None when the entry has no usable identity. Missing optional
    fields are kept as None so that scoring can decide how much they matter.
    """
    if not isinstance(data, dict):
        return None

    title = (data.get("track") or data.get("title") or "").strip()
    webpage_url = (data.get("webpage_url") or "").strip()
    track_id = str(data.get("id") or "").strip()

    if not title or not (webpage_url or track_id):
        return None

    artists = data.get("artists")

    if isinstance(artists, list):
        artists = [
            str(name).strip()
            for name in artists
            if isinstance(name, str) and name.strip()
        ]

    else:
        artists = []

    artist = (data.get("artist") or "").strip() or None

    return {
        "id": track_id or None,
        "title": title,
        "raw_title": (data.get("title") or title).strip(),
        "artist": artist,
        "artists": artists,
        "uploader": (data.get("uploader") or "").strip() or None,
        "duration": _duration(data.get("duration")),
        "webpage_url": webpage_url or None,
        "license": (data.get("license") or "").strip() or None,
        "thumbnails": data.get("thumbnails"),
        "thumbnail": data.get("thumbnail"),
        "streamable": data.get("streamable"),
        "downloadable": data.get("downloadable"),
        "policy": data.get("policy"),
        "is_preview": bool(data.get("is_preview") or data.get("preview")),
        "playlist_index": data.get("playlist_index"),
    }


def merge_details(candidate, details):
    """Overlay a details payload on a search candidate without losing fields."""
    if not isinstance(details, dict):
        return dict(candidate)

    merged = dict(candidate)

    for key in (
        "id",
        "artist",
        "duration",
        "license",
        "thumbnails",
        "thumbnail",
        "streamable",
        "downloadable",
        "policy",
        "webpage_url",
    ):
        if details.get(key) is not None:
            merged[key] = details[key]

    for key in ("title", "track"):
        if details.get(key):
            merged[key] = str(details[key]).strip()

    if isinstance(details.get("artists"), list):
        merged["artists"] = [
            str(name).strip()
            for name in details["artists"]
            if isinstance(name, str) and name.strip()
        ]

    if details.get("is_preview") or details.get("preview"):
        merged["is_preview"] = True

    if is_formats_preview(details):
        merged["is_preview"] = True

    merged["duration"] = _duration(merged.get("duration"))

    return merged


def _title_variants(candidate):
    """Return the plausible song-title forms of a SoundCloud upload.

    Uploads are commonly named ``Artist - Track``, ``Artist - Track (Official
    Audio)`` or just ``Track``. Comparing every form avoids penalizing a
    correct upload for the extra artist prefix.
    """
    raw = candidate.get("raw_title") or candidate.get("title") or ""
    track = candidate.get("title") or ""
    variants = []

    for value in (track, raw):
        value = unicodedata.normalize("NFC", value).strip()

        if value and value not in variants:
            variants.append(value)

        if " - " in value:
            remainder = value.split(" - ", 1)[1].strip()

            if remainder and remainder not in variants:
                variants.append(remainder)

        if " – " in value:
            remainder = value.split(" – ", 1)[1].strip()

            if remainder and remainder not in variants:
                variants.append(remainder)

    return variants


def _candidate_artist_names(candidate):
    names = []

    for name in [candidate.get("artist"), *(candidate.get("artists") or [])]:
        if name and name not in names:
            names.append(name)

    uploader = candidate.get("uploader")

    if uploader and uploader not in names:
        names.append(uploader)

    # ``Artist - Track`` also carries artist evidence in the title prefix.
    raw = candidate.get("raw_title") or candidate.get("title") or ""

    for separator in (" - ", " – "):
        if separator in raw:
            prefix = raw.split(separator, 1)[0].strip()

            if prefix and prefix not in names:
                names.append(prefix)

            break

    return names


def _tokens(text):
    return normalize(text).split()


def _strip_artist_prefix(tokens, artist):
    """Drop leading tokens that belong to the artist name.

    ``Artist - Song`` and ``Artist Song`` both name the artist before the
    song. Those tokens are not evidence of a different title. Both the
    original script and the Latin transliteration are considered, so a Latin
    upload of a Cyrillic artist still has its prefix removed.
    """
    artist_tokens = set(_tokens(artist)) | set(_tokens(_transliterate(artist)))

    if not artist_tokens:
        return tokens

    index = 0

    while index < len(tokens) and tokens[index] in artist_tokens:
        index += 1

    return tokens[index:]


def _contiguous_index(haystack, needle):
    if not needle or len(needle) > len(haystack):
        return None

    for start in range(len(haystack) - len(needle) + 1):
        if haystack[start:start + len(needle)] == needle:
            return start

    return None


def _fuzzy_window(needle, haystack, threshold=0.8):
    """Find the best same-length window of ``haystack`` similar to ``needle``.

    Used for transliteration variance: "gorbachiov" and "gorbachev" are the
    same title, but neither the tokens nor a naive similarity of the whole
    upload title line up. Returns ``(index, score)`` or None.
    """
    if not needle or not haystack or len(needle) > len(haystack):
        return None

    best = None

    for start in range(len(haystack) - len(needle) + 1):
        window = " ".join(haystack[start:start + len(needle)])
        score = similarity(" ".join(needle), window)

        if score >= threshold and (best is None or score > best[1]):
            best = (start, score)

    return best


def _title_variant_score(variant, title, artist):
    """Compare one title variant, penalizing words the song does not have.

    A shared word is not enough: ``Artist - Another Song`` is a different
    song from ``Song`` even though it contains the title. Extra words after
    the title are common upload suffixes (``- Kissvk.com``, ``[HQ]``), while
    extra words *before* it usually mean another song, so only the leading
    case is penalized.
    """
    expected = _tokens(title)

    if not expected:
        return 0.0

    variant_tokens = _strip_artist_prefix(_tokens(variant), artist)
    # The Latin form catches a Latin-only upload of a Cyrillic title (and
    # the reverse), where no original-script token can ever match.
    expected_latin = _tokens(_transliterate(title))
    variant_latin = _strip_artist_prefix(
        _tokens(_transliterate(variant)),
        artist,
    )

    if not variant_tokens and not variant_latin:
        return 0.0

    ratio = _cross_script_similarity(title, variant)

    start = _contiguous_index(variant_tokens, expected)

    if start is None and expected_latin:
        latin_start = _contiguous_index(variant_latin, expected_latin)

        if latin_start is not None:
            start = latin_start
            expected = expected_latin
            variant_tokens = variant_latin

    if start is None:
        # Title words can transliterate differently ("Горбачёв" becomes
        # "gorbachiov" while an uploader typed "gorbachev"). Slide a window
        # over the Latin tokens and accept a close one.
        fuzzy = _fuzzy_window(
            expected_latin,
            variant_latin,
        )

        if fuzzy is not None:
            index, score = fuzzy
            start = index
            expected = expected_latin
            variant_tokens = variant_latin
            ratio = max(ratio, score)

    if start is None and _transliterate(title) != title:
        # A Latin-only upload of a Cyrillic title (or the reverse) has no
        # shared tokens, but a high transliterated similarity is still good
        # evidence. The floor keeps an unrelated same-script title out.
        if ratio >= 0.8:
            return ratio

    if start is None:
        # The title words are present but out of order or interrupted.
        expected_set = set(expected)
        variant_set = set(variant_tokens)
        overlap = len(expected_set & variant_set)

        if overlap == 0:
            return 0.0

        recall = overlap / len(expected_set)
        precision = overlap / len(variant_set)
        f1 = (
            2 * recall * precision / (recall + precision)
            if recall + precision
            else 0.0
        )
        return max(ratio, f1) * 0.75

    if start > 0:
        # Words before the title: "Another Song" is not "Song".
        return ratio * 0.35

    trailing = len(variant_tokens) - (start + len(expected))

    if trailing > 3:
        return ratio * 0.7

    # The title is a contiguous prefix. Upload suffixes ("- Kissvk.com",
    # "[HQ]") are common and, across scripts, drag the raw similarity down
    # even though the song itself matches exactly. Comparing the matched
    # prefix avoids that.
    prefix = " ".join(variant_tokens[start:start + len(expected)])
    return max(ratio, _cross_script_similarity(title, prefix))


def _title_score(candidate, title, artist=""):
    variants = _title_variants(candidate)

    if not variants:
        return 0.0

    return max(
        _title_variant_score(variant, title, artist)
        for variant in variants
    )


def _artist_score(candidate, artist):
    names = _candidate_artist_names(candidate)

    if not names:
        return 0.0

    score = max(
        _cross_script_similarity(artist, name)
        for name in names
    )

    for name in names:
        # The uploader handle ("nuclear_gandhi") is weak evidence; only an
        # explicit artist field or a title prefix gets the containment boost.
        if name == candidate.get("uploader"):
            continue

        if _contains_artist(artist, name):
            score = max(score, 0.92)

    return min(score, 1.0)


def _version_markers(text):
    """Return the version markers present in raw text.

    ``matching.normalize`` exists for similarity and deliberately removes
    noise brackets such as ``(live)``. Markers must survive that removal, so
    this uses a light normalization that only lowercases and folds
    punctuation into spaces, leaving every word visible.
    """
    text = unicodedata.normalize("NFC", text or "").lower()
    text = text.replace("ё", "е")
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    normalized = f" {text} "
    found = set()

    for marker in VERSION_MARKERS:
        if f" {marker} " in normalized:
            found.add(marker)

    return found


def is_version_mismatch(candidate, title):
    """Whether the upload is a remix, cover, live take and so on.

    A marker in the requested title is intentional: asking for a remix must
    still find the remix. Markers that only exist on the candidate side mean
    it is a different recording.
    """
    candidate_text = " ".join(
        [
            candidate.get("raw_title") or "",
            candidate.get("title") or "",
        ]
    )
    requested = _version_markers(title or "")
    present = _version_markers(candidate_text)

    return bool(present - requested)


def preview_reason(candidate, expected_duration):
    """Return why a candidate looks like a preview, or None.

    The 30-second SoundCloud preview of a 2:41 track is the motivating case.
    Duration metadata can be missing, so an absent value is never a reason to
    reject on its own.
    """
    duration = _duration(candidate.get("duration"))

    if candidate.get("is_preview"):
        return "marked as a preview"

    if duration is None:
        return None

    if duration <= 15:
        return "too short to be the full track"

    expected = _duration(expected_duration)

    if expected is not None:
        if expected >= 60 and duration < expected * SOUNDCLOUD_PREVIEW_RATIO:
            return "shorter than the expected track"

        if expected >= 30 and duration > expected * 3:
            return "much longer than the expected track"

    elif duration < SOUNDCLOUD_PREVIEW_SECONDS:
        return "short upload without a known duration to compare"

    return None


def _blocked_reason(candidate):
    if candidate.get("streamable") is False:
        return "not streamable"

    if candidate.get("downloadable") is False:
        return "downloads disabled by the uploader"

    policy = str(candidate.get("policy") or "").upper()

    if policy in BLOCKED_POLICIES:
        return f"blocked by SoundCloud ({policy.lower()})"

    return None


def blocked_reason(candidate):
    """Public wrapper: why SoundCloud will not provide this track, or None."""
    return _blocked_reason(candidate or {})


def duration_score(candidate, expected_duration):
    """Score duration similarity, or None when either side is unknown."""
    duration = _duration(candidate.get("duration"))
    expected = _duration(expected_duration)

    if duration is None or expected is None:
        return None

    difference = abs(duration - expected)

    if difference <= 3:
        return 1.0

    if difference <= SOUNDCLOUD_DURATION_TOLERANCE:
        return 0.9

    ratio = difference / max(duration, expected)

    if ratio <= 0.10:
        return 0.6

    if ratio <= 0.20:
        return 0.3

    return 0.0


def _extra_score(candidate, artist, title):
    """Small bonus for explicit artist evidence and clean metadata."""
    evidence = 0.0

    explicit = [candidate.get("artist"), *(candidate.get("artists") or [])]
    explicit = [name for name in explicit if name]

    if explicit and _artist_score({"artists": explicit}, artist) >= 0.6:
        evidence = 1.0

    elif _contains_artist(artist, candidate.get("uploader") or ""):
        evidence = 0.7

    elif _contains_artist(artist, candidate.get("raw_title") or ""):
        evidence = 0.4

    # A titled upload with no artist information anywhere is weaker.
    if not any(_candidate_artist_names(candidate)):
        evidence = 0.0

    return evidence


def score_candidate(candidate, artist, title, duration=None):
    """Score one candidate and attach rejection details.

    The weights follow the task brief: title 40%, artist 30%, duration 20%,
    additional metadata 10%. Duration is neutral when either side lacks it;
    previews and version mismatches are rejected explicitly instead of only
    losing points.
    """
    scored = dict(candidate)
    title_value = _title_score(candidate, title, artist)
    artist_value = _artist_score(candidate, artist)
    duration_value = duration_score(candidate, duration)
    extra_value = _extra_score(candidate, artist, title)

    effective_duration = 0.5 if duration_value is None else duration_value

    total = (
        title_value * SOUNDCLOUD_TITLE_WEIGHT
        + artist_value * SOUNDCLOUD_ARTIST_WEIGHT
        + effective_duration * SOUNDCLOUD_DURATION_WEIGHT
        + extra_value * SOUNDCLOUD_EXTRA_WEIGHT
    )

    reason = None

    if not (candidate.get("title") or "").strip():
        reason = "no title metadata"

    elif title_value < SOUNDCLOUD_MIN_TITLE_SCORE:
        reason = "title does not match"

    elif is_version_mismatch(candidate, title):
        reason = "remix, cover or another version"

    if reason is None:
        reason = preview_reason(candidate, duration)

    if reason is None:
        reason = _blocked_reason(candidate)

    if reason is None and candidate.get("is_live"):
        reason = "live stream"

    scored.update(
        {
            "score": round(total, 4),
            "title_score": round(title_value, 4),
            "artist_score": round(artist_value, 4),
            "duration_score": (
                None if duration_value is None else round(duration_value, 4)
            ),
            "extra_score": round(extra_value, 4),
            "reject_reason": reason,
        }
    )

    return scored


def rank_candidates(candidates, artist, title, duration=None):
    """Score and rank parsed candidates, best first."""
    scored = [
        score_candidate(candidate, artist, title, duration)
        for candidate in candidates or []
        if isinstance(candidate, dict)
    ]
    scored.sort(key=lambda item: item.get("score", 0.0), reverse=True)
    return scored


def select_candidate(
    ranked,
    min_score=SOUNDCLOUD_MIN_SCORE,
    min_margin=SOUNDCLOUD_MIN_MARGIN,
):
    """Pick one candidate, or explain why the user has to choose.

    Returns ``(candidate, reason)``. ``candidate`` is None for every status
    other than "selected".
    """
    approved = [
        item for item in ranked or []
        if not item.get("reject_reason")
    ]

    if not approved:
        return None, STATUS_NO_MATCH

    best = approved[0]

    if best.get("score", 0.0) < min_score:
        return None, STATUS_LOW_CONFIDENCE

    if (
        len(approved) > 1
        and best.get("score", 0.0) - approved[1].get("score", 0.0)
        < min_margin
    ):
        return None, STATUS_AMBIGUOUS

    return best, STATUS_SELECTED


def format_duration(seconds):
    duration = _duration(seconds)

    if duration is None:
        return "?:??"

    total = int(round(duration))
    return f"{total // 60}:{total % 60:02d}"


def format_candidate(candidate, number=None):
    prefix = f"{number}. " if number is not None else ""
    uploader = candidate.get("uploader") or candidate.get("artist") or "unknown"
    duration = format_duration(candidate.get("duration"))

    return (
        f"{prefix}{candidate.get('title', 'Unknown')} "
        f"{colors.muted(f'({duration}, {uploader})')}"
    )


def fetch_candidate_details(
    candidates,
    limit=SOUNDCLOUD_DETAILS_LIMIT,
    details_func=None,
):
    """Overlay ``--dump-single-json`` metadata on the first few candidates.

    The flat search result already carries title, duration and uploader, but
    the details call adds the license, explicit block flags and the exact
    duration. A failed call keeps the search payload, so one unavailable
    track never hides the others. No audio is downloaded here.
    """
    if details_func is None:
        details_func = soundcloud_track_details

    enriched = []

    for index, candidate in enumerate(candidates or []):
        if index >= limit or not isinstance(candidate, dict):
            enriched.append(candidate)
            continue

        url = candidate.get("webpage_url")

        if not url:
            enriched.append(candidate)
            continue

        try:
            enriched.append(merge_details(candidate, details_func(url)))

        except SoundcloudError as error:
            print(
                colors.muted(
                    "  SoundCloud metadata unavailable, using search data: "
                    f"{error}"
                )
            )
            enriched.append(candidate)

    return enriched


def _print_options(candidates):
    print(
        colors.warning(
            "Multiple SoundCloud results are plausible:"
        )
    )

    for number, candidate in enumerate(candidates, start=1):
        line = format_candidate(candidate, number)
        url = candidate.get("webpage_url")

        if url:
            line += f" {colors.muted(url)}"

        print(f"  {line}")

        if candidate.get("duration_score") is not None:
            print(
                colors.muted(
                    f"     match {candidate.get('score', 0):.2f} "
                    f"(title {candidate.get('title_score', 0):.2f}, "
                    f"artist {candidate.get('artist_score', 0):.2f}, "
                    f"duration {candidate.get('duration_score', 0):.2f})"
                )
            )


def prompt_for_candidate(
    candidates,
    input_func=input,
    stream=None,
):
    """Let the user pick a candidate, or skip when there is no terminal.

    Non-interactive runs (cron, redirected stdin, test harnesses) never
    download blindly: the options are printed and None is returned.
    """
    if not candidates:
        return None

    _print_options(candidates)
    stream = sys.stdin if stream is None else stream

    try:
        interactive = bool(stream.isatty())

    except (AttributeError, ValueError):
        interactive = False

    if not interactive:
        print(
            colors.muted(
                "SoundCloud skipped: choose a result interactively "
                "to download one."
            )
        )
        return None

    try:
        answer = input_func(
            "Choose a SoundCloud result "
            f"[1-{len(candidates)}, Enter to skip]: "
        )

    except (EOFError, KeyboardInterrupt):
        print()
        return None

    answer = (answer or "").strip()

    if not answer:
        return None

    try:
        index = int(answer)

    except ValueError:
        print(colors.muted("Not a number; skipping SoundCloud."))
        return None

    if not 1 <= index <= len(candidates):
        print(colors.muted("Out of range; skipping SoundCloud."))
        return None

    return candidates[index - 1]


class FallbackResult:
    """Outcome of a SoundCloud fallback attempt."""

    def __init__(self, status, candidate=None, candidates=None, error=None):
        self.status = status
        self.candidate = candidate
        self.candidates = list(candidates or [])
        self.error = error

    @property
    def selected(self):
        return self.status == STATUS_SELECTED

    def __repr__(self):
        return (
            f"FallbackResult(status={self.status!r}, "
            f"candidate={self.candidate!r})"
        )


def _rank_with_details(
    candidates,
    artist,
    title,
    duration,
    details_limit,
    details_func,
):
    """Enrich candidates with metadata and rank them, or return []."""
    if not candidates:
        return []

    enriched = fetch_candidate_details(
        candidates,
        limit=details_limit,
        details_func=details_func,
    )
    return rank_candidates(enriched, artist, title, duration)


def find_soundcloud_fallback(
    artist,
    title,
    duration=None,
    *,
    enabled=SOUNDCLOUD_DEFAULT_ENABLED,
    min_score=SOUNDCLOUD_MIN_SCORE,
    min_margin=SOUNDCLOUD_MIN_MARGIN,
    ambiguous=SOUNDCLOUD_DEFAULT_AMBIGUOUS,
    limit=SOUNDCLOUD_SEARCH_LIMIT,
    chooser=None,
    attempt_key=None,
    details_limit=SOUNDCLOUD_DETAILS_LIMIT,
    details_func=None,
    fallback_names=None,
):
    """Search SoundCloud and return the best candidate or user options.

    The flat search results are enriched with ``--dump-single-json`` metadata
    (up to ``details_limit`` tracks) before scoring. The function never
    downloads audio: the caller downloads only the candidate returned as
    selected.

    ``fallback_names`` carries the artist and title as the user wrote them in
    the input file. A metadata provider can resolve a different artist (for
    example "MintiLove" instead of "Neverlove"), and searching SoundCloud
    with that wrong name finds only unrelated uploads. When the first search
    finds no confident match, the original names are tried before giving up.
    """
    if not enabled:
        return FallbackResult(STATUS_DISABLED)

    key = attempt_key or f"{normalize(artist)}|{normalize(title)}"

    if key in _ATTEMPTED:
        print(colors.muted("SoundCloud fallback already attempted; skipping."))
        return FallbackResult(STATUS_DISABLED, error="already attempted")

    _ATTEMPTED.add(key)

    query = " ".join(f"{artist} {title}".split())
    print(colors.muted(f"Searching SoundCloud: {query}"))

    try:
        entries = soundcloud_search(query, limit=limit)

    except SoundcloudError as error:
        print(colors.warning(f"WARNING: SoundCloud search failed: {error}"))
        return FallbackResult(STATUS_ERROR, error=str(error))

    candidates = [
        candidate
        for candidate in (
            parse_search_result(entry) for entry in entries
        )
        if candidate is not None
    ]

    if not candidates:
        print(colors.muted("No SoundCloud results."))

    ranked = _rank_with_details(
        candidates,
        artist,
        title,
        duration,
        details_limit,
        details_func,
    )
    # The metadata artist can be a different act. Only when the first pass
    # has no usable result, try the names from the input file as well.
    if fallback_names and not any(
        not item.get("reject_reason") for item in ranked
    ):
        other_artist, other_title = fallback_names

        if (
            normalize(other_artist) != normalize(artist)
            or normalize(other_title) != normalize(title)
        ):
            print(
                colors.muted(
                    "Retrying SoundCloud with the original input names: "
                    f"{' '.join(f'{other_artist} {other_title}'.split())}"
                )
            )

            try:
                other_entries = soundcloud_search(
                    " ".join(f"{other_artist} {other_title}".split()),
                    limit=limit,
                )

            except SoundcloudError as error:
                other_entries = []
                print(
                    colors.warning(
                        f"WARNING: SoundCloud search failed: {error}"
                    )
                )

            other_candidates = [
                parsed
                for parsed in (
                    parse_search_result(entry) for entry in other_entries
                )
                if parsed is not None
            ]

            # The duration came from the mismatched metadata record, so it
            # describes a different recording. Keep it out of scoring rather
            # than penalizing a correct full-length upload for not matching
            # the wrong track's length.
            other_ranked = _rank_with_details(
                other_candidates,
                other_artist,
                other_title,
                None,
                details_limit,
                details_func,
            )

            if other_ranked:
                ranked = other_ranked

    approved = [item for item in ranked if not item.get("reject_reason")]
    candidate, status = select_candidate(
        ranked,
        min_score=min_score,
        min_margin=min_margin,
    )

    for item in ranked:
        reason = item.get("reject_reason")
        suffix = f" [{reason}]" if reason else ""
        print(
            colors.muted(
                f"  SoundCloud score {item.get('score', 0):.2f}: "
                f"{item.get('title', 'Unknown')}{suffix}"
            )
        )

    if status == STATUS_NO_MATCH:
        print(colors.muted("No suitable SoundCloud match."))
        return FallbackResult(STATUS_NO_MATCH, candidates=ranked)

    if status == STATUS_LOW_CONFIDENCE:
        best = approved[0]
        print(
            colors.muted(
                "Best SoundCloud match is below the confidence threshold "
                f"({best.get('score', 0):.2f} < {min_score:.2f})."
            )
        )

        if ambiguous == "best":
            print(
                colors.warning(
                    "Taking the highest scoring SoundCloud result anyway "
                    f"({best.get('score', 0):.2f}, "
                    f"{best.get('title', 'Unknown')}) because "
                    "soundcloud_ambiguous is 'best'. "
                    "Check the file if it matters."
                )
            )
            chosen = dict(best)
            chosen.pop("reject_reason", None)
            return FallbackResult(
                STATUS_SELECTED,
                candidate=chosen,
                candidates=ranked,
            )

        result = FallbackResult(
            STATUS_LOW_CONFIDENCE,
            candidates=approved,
        )

    elif status == STATUS_AMBIGUOUS:
        print(colors.muted("Several SoundCloud results are close."))

        if ambiguous == "best" and approved:
            # soundcloud_ambiguous=best asks for the top result instead of a
            # question, which keeps unattended runs moving. It is a setting,
            # not a detected lack of terminal, so do not claim otherwise.
            print(
                colors.muted(
                    "Taking the highest scoring SoundCloud result "
                    "(soundcloud_ambiguous=best)."
                )
            )
            best = dict(approved[0])
            best.pop("reject_reason", None)
            return FallbackResult(
                STATUS_SELECTED,
                candidate=best,
                candidates=ranked,
            )

        result = FallbackResult(STATUS_AMBIGUOUS, candidates=approved)

    else:
        result = FallbackResult(
            STATUS_SELECTED,
            candidate=candidate,
            candidates=ranked,
        )

    if result.selected:
        return result

    chooser = prompt_for_candidate if chooser is None else chooser

    try:
        choice = chooser(approved)

    except (EOFError, KeyboardInterrupt):
        print()
        choice = None

    if not isinstance(choice, dict):
        return result

    chosen = dict(choice)
    chosen.pop("reject_reason", None)
    return FallbackResult(
        STATUS_SELECTED,
        candidate=chosen,
        candidates=ranked,
    )


def is_formats_preview(details):
    """Whether yt-dlp's format list looks like a short SoundCloud preview."""
    formats = (details or {}).get("formats")

    if not isinstance(formats, list):
        return False

    return any(
        str((item or {}).get("format_id") or "").lower().startswith("preview")
        for item in formats
        if isinstance(item, dict)
    )


def describe_failure(result):
    """A short, user-facing reason for a failed fallback."""
    if result is None:
        return "SoundCloud fallback failed"

    return {
        STATUS_NO_MATCH: "no SoundCloud match",
        STATUS_LOW_CONFIDENCE: "no confident SoundCloud match",
        STATUS_AMBIGUOUS: "ambiguous SoundCloud matches",
        STATUS_ERROR: "SoundCloud search failed",
        STATUS_DISABLED: "SoundCloud fallback unavailable",
    }.get(result.status, "SoundCloud fallback failed")


__all__ = [
    "FallbackResult",
    "STATUS_AMBIGUOUS",
    "STATUS_DISABLED",
    "STATUS_ERROR",
    "STATUS_LOW_CONFIDENCE",
    "STATUS_NO_MATCH",
    "STATUS_SELECTED",
    "duration_score",
    "fetch_candidate_details",
    "find_soundcloud_fallback",
    "format_candidate",
    "format_duration",
    "is_formats_preview",
    "is_version_mismatch",
    "merge_details",
    "parse_search_result",
    "preview_reason",
    "prompt_for_candidate",
    "rank_candidates",
    "reset_attempts",
    "score_candidate",
    "select_candidate",
    "soundcloud_search",
    "soundcloud_track_details",
]
