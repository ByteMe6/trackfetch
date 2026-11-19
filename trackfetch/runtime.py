# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared per-run state: HTTP session, health tracking, rate limits, cache."""

import json
import time
from pathlib import Path

import requests

from .constants import CACHE_VERSION, USER_AGENT
from .errors import ProviderAuthError, ProviderError
from .matching import normalize


class ProviderHealth:
    """Per-provider consecutive-failure and cooldown tracking."""

    INITIAL_COOLDOWN = 30.0
    MAX_COOLDOWN = 600.0

    def __init__(self, clock=None):
        self.clock = clock or (lambda: time.monotonic())
        self.states = {}

    def state(self, name: str) -> dict:
        return self.states.setdefault(
            name,
            {
                "failures": 0,
                "cooldown_until": 0.0,
                "cooldown_seconds": 0.0,
            },
        )

    def failures(self, name: str) -> int:
        return self.state(name)["failures"]

    def in_cooldown(self, name: str) -> bool:
        return self.state(name)["cooldown_until"] > self.clock()

    def record_success(self, name: str):
        state = self.state(name)
        state["failures"] = 0
        state["cooldown_until"] = 0.0
        state["cooldown_seconds"] = 0.0

    def record_failure(self, name: str):
        state = self.state(name)
        state["failures"] += 1

        if state["failures"] < 2:
            return

        previous = state["cooldown_seconds"]

        if previous <= 0:
            cooldown = self.INITIAL_COOLDOWN
        else:
            cooldown = min(previous * 2, self.MAX_COOLDOWN)

        state["cooldown_seconds"] = cooldown
        state["cooldown_until"] = self.clock() + cooldown

    def force_cooldown(self, name: str, seconds: float):
        state = self.state(name)
        state["cooldown_seconds"] = seconds
        state["cooldown_until"] = self.clock() + seconds


class RateLimiter:
    """Independent minimum request interval per provider."""

    def __init__(self, intervals=None, clock=None):
        self.intervals = dict(intervals or {})
        self.clock = clock or (lambda: time.monotonic())
        self.last_request = {}

    def wait(self, name: str):
        interval = self.intervals.get(name, 0.0)

        if interval <= 0:
            self.last_request[name] = self.clock()
            return

        last = self.last_request.get(name)

        if last is not None:
            remaining = interval - (self.clock() - last)

            if remaining > 0:
                time.sleep(remaining)

        self.last_request[name] = self.clock()


class MetadataCache:
    """Per-provider metadata cache stored next to the downloaded files."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.entries = {}
        self.load()

    @staticmethod
    def key(artist: str, title: str) -> str:
        return f"{normalize(artist)}|{normalize(title)}"

    def load(self):
        if not self.path.is_file():
            return

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))

        except (OSError, ValueError, TypeError):
            self.entries = {}
            return

        if not isinstance(data, dict):
            self.entries = {}
            return

        entries = data.get("entries")

        if not isinstance(entries, dict):
            self.entries = {}
            return

        self.entries = entries

    def save(self):
        payload = {
            "version": CACHE_VERSION,
            "entries": self.entries,
        }

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ) + "\n",
                encoding="utf-8",
            )

        except OSError:
            pass

    def get(self, artist: str, title: str, provider: str):
        entry = self.entries.get(self.key(artist, title))

        if not isinstance(entry, dict):
            return None

        result = entry.get(provider)

        if not isinstance(result, dict) or not result.get("title"):
            return None

        return dict(result)

    def set(self, artist: str, title: str, provider: str, result: dict):
        if not isinstance(result, dict) or not result.get("title"):
            # An incomplete result must not replace a usable cached entry.
            return False

        key = self.key(artist, title)
        entry = self.entries.get(key)

        if not isinstance(entry, dict):
            entry = {}

        existing = entry.get(provider)

        if isinstance(existing, dict) and existing.get("title"):
            old_score = existing.get("score")
            new_score = result.get("score")

            try:
                if old_score is not None and (
                    new_score is None or float(new_score) < float(old_score)
                ):
                    return False
            except (TypeError, ValueError):
                pass

        stored = {
            field: result.get(field)
            for field in (
                "title",
                "artist",
                "album",
                "album_artist",
                "track_number",
                "release_date",
                "duration",
                "cover_url",
                "source",
                "source_id",
                "score",
            )
        }
        entry[provider] = stored
        self.entries[key] = entry
        self.save()

        return True

class MetadataRuntime:
    """Shared state for one TrackFetch run: HTTP, health, rate limits, cache."""

    def __init__(
        self,
        session=None,
        cache=None,
        health=None,
        limiter=None,
        spotify_args=None,
    ):
        self.session = session or requests.Session()
        headers = getattr(self.session, "headers", None)

        if headers is not None:
            headers.setdefault("User-Agent", USER_AGENT)

        self.cache = cache
        self.health = health or ProviderHealth()
        self.limiter = limiter or RateLimiter()
        self.spotify_args = spotify_args
        self.spotify_client = None
        self.spotify_initialized = False
        self.cover_art_cache = {}


def request_json(
    runtime,
    provider: str,
    url: str,
    params=None,
    headers=None,
    timeout=20,
):
    """Rate-limited JSON request with predictable provider errors."""
    request_headers = {"User-Agent": USER_AGENT}

    if headers:
        request_headers.update(headers)

    runtime.limiter.wait(provider)

    try:
        response = runtime.session.get(
            url,
            params=params,
            headers=request_headers,
            timeout=timeout,
        )

    except requests.Timeout as error:
        raise ProviderError(f"{provider} request timed out") from error

    except requests.RequestException as error:
        raise ProviderError(f"{provider} request failed: {error}") from error

    status = getattr(response, "status_code", 200)

    if status in (401, 403):
        raise ProviderAuthError(f"{provider} returned HTTP {status}")

    if status >= 400:
        raise ProviderError(f"{provider} returned HTTP {status}")

    try:
        return response.json()

    except (ValueError, TypeError) as error:
        raise ProviderError(
            f"{provider} returned invalid JSON"
        ) from error

