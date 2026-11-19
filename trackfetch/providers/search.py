# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared query relaxation for metadata providers.

Provider search endpoints require every query token to match. A single typo
therefore returns no candidates at all, before local scoring gets a chance to
compare anything. These helpers retry with progressively looser free-text
queries and stop as soon as an existing scorer accepts a result.
"""

from ..matching import select_best_metadata

MIN_TITLE_TOKENS = 2
MAX_RELAXED_QUERIES = 5


def query_variants(artist: str, title: str):
    """Return free-text query variants, most specific first."""
    artist = " ".join((artist or "").split())
    title = " ".join((title or "").split())
    variants = []

    def add(value):
        value = " ".join((value or "").split())

        if value and value not in variants:
            variants.append(value)

    add(f"{artist} {title}")
    add(f"{title} {artist}")
    add(title)

    words = title.split()

    for end in range(len(words) - 1, MIN_TITLE_TOKENS - 1, -1):
        add(" ".join(words[:end]))

    return variants[:MAX_RELAXED_QUERIES]


def has_match(candidates, artist: str, title: str, config):
    """Whether any candidate passes the configured match thresholds."""
    return (
        select_best_metadata(
            candidates,
            artist,
            title,
            config.match_threshold,
            config.title_threshold,
        )
        is not None
    )


def candidate_key(candidate: dict):
    return (
        candidate.get("source"),
        candidate.get("source_id"),
        candidate.get("artist"),
        candidate.get("title"),
    )


def search_variants(fetch, artist: str, title: str, config, strict_query=None):
    """Try the strict query, then relaxed variants, until a match is found.

    ``fetch`` receives one query string and returns a candidate list. The
    first variant with a candidate that passes both thresholds wins; if none
    passes, every collected candidate is returned so the resolver can still
    score the full set.
    """
    collected = []
    seen = set()

    def consider(query):
        candidates = fetch(query)

        for candidate in candidates or []:
            if not isinstance(candidate, dict):
                continue

            key = candidate_key(candidate)

            if key in seen:
                continue

            seen.add(key)
            collected.append(candidate)

        if candidates and has_match(candidates, artist, title, config):
            return candidates

        return None

    if strict_query:
        matched = consider(strict_query)

        if matched is not None:
            return matched

    for query in query_variants(artist, title):
        matched = consider(query)

        if matched is not None:
            return matched

    return collected
