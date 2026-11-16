# SPDX-License-Identifier: GPL-3.0-or-later
"""Maps provider names to their lookup functions."""

from .deezer import deezer_provider
from .itunes import itunes_provider
from .musicbrainz import musicbrainz_provider
from .spotify import spotify_provider
from .vocadb import vocadb_provider

PROVIDER_FUNCTIONS = {
    "spotify": spotify_provider,
    "itunes": itunes_provider,
    "deezer": deezer_provider,
    "musicbrainz": musicbrainz_provider,
    "vocadb": vocadb_provider,
}
