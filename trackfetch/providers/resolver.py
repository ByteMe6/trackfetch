# SPDX-License-Identifier: GPL-3.0-or-later
"""Provider selection, cooldowns and cache-aware metadata resolution."""

from ..config import SourceConfig, effective_metadata_sources
from ..errors import ProviderAuthError, ProviderError
from ..matching import fallback_metadata, select_best_metadata
from ..runtime import MetadataRuntime
from .registry import PROVIDER_FUNCTIONS

FALLBACK_METADATA_SOURCES = ("deezer", "musicbrainz")


def metadata_sources_for(config: SourceConfig, artist: str, title: str):
    """Configured providers plus safe free fallbacks.

    Fallbacks are only used after every configured provider missed, and never
    when the user disabled them or explicitly selected no metadata at all.
    """
    sources = effective_metadata_sources(config, artist, title)

    if config.none_selected:
        return sources

    for name in FALLBACK_METADATA_SOURCES:
        if name in sources or config.is_enabled(name):
            continue

        if config.providers[name].get("disabled"):
            continue

        sources.append(name)

    return sources


def cached_metadata(runtime, artist, title, provider, config):
    if runtime.cache is None:
        return None

    cached = runtime.cache.get(artist, title, provider)

    if cached is None:
        return None

    return select_best_metadata(
        [cached],
        artist,
        title,
        config.match_threshold,
        config.title_threshold,
    )


def resolve_metadata(artist: str, title: str, config: SourceConfig, runtime):
    """Return the first suitable metadata result in configured priority order.

    Free fallbacks are considered only after every configured provider missed.
    """
    if runtime is None:
        runtime = MetadataRuntime()

    fallback = fallback_metadata(artist, title)

    for provider in metadata_sources_for(config, artist, title):
        if runtime.health.in_cooldown(provider):
            cached = cached_metadata(
                runtime,
                artist,
                title,
                provider,
                config,
            )

            if cached is not None:
                return cached

            continue

        state = runtime.health.state(provider)

        if state["failures"] == 0:
            cached = cached_metadata(
                runtime,
                artist,
                title,
                provider,
                config,
            )

            if cached is not None:
                return cached

        try:
            candidates = PROVIDER_FUNCTIONS[provider](
                runtime,
                artist,
                title,
                config,
            )

        except ProviderAuthError:
            runtime.health.force_cooldown(provider, 600.0)
            cached = cached_metadata(
                runtime,
                artist,
                title,
                provider,
                config,
            )

            if cached is not None:
                return cached

            continue

        except ProviderError:
            runtime.health.record_failure(provider)
            cached = cached_metadata(
                runtime,
                artist,
                title,
                provider,
                config,
            )

            if cached is not None:
                return cached

            continue

        except (KeyError, TypeError, ValueError, AttributeError, IndexError):
            # A malformed but successful-looking API response is a failure,
            # not a reason to abort the whole run.
            runtime.health.record_failure(provider)
            cached = cached_metadata(
                runtime,
                artist,
                title,
                provider,
                config,
            )

            if cached is not None:
                return cached

            continue

        best = select_best_metadata(
            candidates,
            artist,
            title,
            config.match_threshold,
            config.title_threshold,
        )

        # A valid response, even with no match, resets the failure counter.
        runtime.health.record_success(provider)

        if best is not None:
            if runtime.cache is not None:
                runtime.cache.set(artist, title, provider, best)

            return best

    return fallback
