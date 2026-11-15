import argparse
import json
import sys

import pytest
import requests
from conftest import make_track

import trackfetch as m


def make_args(**overrides):
    values = {
        "metadata_sources": None,
        "disable_sources": None,
        "provider_opt": None,
        "match_threshold": None,
        "title_threshold": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def make_config(
    sources,
    youtube=True,
    disabled=(),
    thresholds=(0.6, 0.8),
    none_selected=False,
):
    providers = {}

    for name in m.METADATA_PROVIDERS:
        entry = dict(m.PROVIDER_DEFAULTS[name])
        entry["enabled"] = name in sources
        entry["disabled"] = name in disabled
        providers[name] = entry

    return m.SourceConfig(
        sources,
        youtube,
        providers,
        thresholds[0],
        thresholds[1],
        none_selected,
    )


class FakeResponse:
    def __init__(self, payload=None, status_code=200, json_error=None):
        self.payload = payload
        self.status_code = status_code
        self.json_error = json_error

    def json(self):
        if self.json_error:
            raise self.json_error

        return self.payload


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        response = self.responses.pop(0)

        if isinstance(response, Exception):
            raise response

        return response


def make_runtime(session=None, cache=None, health=None):
    return m.MetadataRuntime(
        session=session or FakeSession(),
        cache=cache,
        health=health,
        limiter=m.RateLimiter(
            {name: 0.0 for name in m.METADATA_PROVIDERS}
        ),
    )


def run_cli(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["trackfetch", *map(str, args)])
    m.main()


class TestSourceResolution:
    def test_default_sources_are_itunes_only(self):
        config = m.build_source_config(make_args(), {})

        assert config.metadata_sources == ["itunes"]
        assert config.youtube_enabled is True
        assert config.is_enabled("itunes")
        assert not config.is_enabled("spotify")
        assert not config.is_enabled("deezer")

    def test_custom_priority_is_preserved(self):
        config = m.build_source_config(
            make_args(metadata_sources="deezer, itunes,musicbrainz"),
            {},
        )

        assert config.metadata_sources == ["deezer", "itunes", "musicbrainz"]

    def test_duplicate_sources_are_removed(self):
        config = m.build_source_config(
            make_args(metadata_sources="deezer,DEEZER,itunes,deezer"),
            {},
        )

        assert config.metadata_sources == ["deezer", "itunes"]

    def test_unknown_source_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown metadata source"):
            m.build_source_config(
                make_args(metadata_sources="deezer,napster"),
                {},
            )

    def test_youtube_is_not_a_metadata_provider(self):
        with pytest.raises(ValueError, match="artwork fallback"):
            m.build_source_config(
                make_args(metadata_sources="itunes,youtube"),
                {},
            )

    def test_explicit_config_enabling_appends_without_reordering(self):
        config = m.build_source_config(
            make_args(),
            {"deezer_enabled": "true"},
        )

        assert config.metadata_sources == ["itunes", "deezer"]

    def test_explicit_config_disabling_removes_provider(self):
        config = m.build_source_config(
            make_args(),
            {
                "metadata_sources": "deezer,itunes",
                "deezer_enabled": "false",
            },
        )

        assert config.metadata_sources == ["itunes"]

    def test_disable_sources_removes_provider(self):
        config = m.build_source_config(
            make_args(metadata_sources="deezer,itunes", disable_sources="itunes"),
            {},
        )

        assert config.metadata_sources == ["deezer"]

    def test_disable_sources_from_config(self):
        config = m.build_source_config(
            make_args(),
            {
                "metadata_sources": "deezer,itunes",
                "disable_sources": "deezer",
            },
        )

        assert config.metadata_sources == ["itunes"]

    def test_cli_sources_override_config_sources(self):
        config = m.build_source_config(
            make_args(metadata_sources="deezer"),
            {"metadata_sources": "itunes,musicbrainz"},
        )

        assert config.metadata_sources == ["deezer"]

    def test_cli_sources_override_config_enabled_flag(self):
        config = m.build_source_config(
            make_args(metadata_sources="spotify"),
            {"spotify_enabled": "false"},
        )

        assert config.metadata_sources == ["spotify"]

    def test_none_means_no_metadata_but_youtube_stays(self):
        config = m.build_source_config(
            make_args(metadata_sources="none"),
            {},
        )

        assert config.metadata_sources == []
        assert config.none_selected is True
        assert config.youtube_enabled is True

    def test_none_does_not_append_explicitly_enabled_providers(self):
        config = m.build_source_config(
            make_args(metadata_sources="none"),
            {"deezer_enabled": "true"},
        )

        assert config.metadata_sources == []

    def test_youtube_can_be_disabled_by_flag(self):
        config = m.build_source_config(
            make_args(disable_sources="youtube"),
            {},
        )

        assert config.youtube_enabled is False

    def test_youtube_can_be_disabled_in_config(self):
        config = m.build_source_config(
            make_args(),
            {"youtube_enabled": "false"},
        )

        assert config.youtube_enabled is False

    def test_provider_options_are_applied(self):
        config = m.build_source_config(
            make_args(
                provider_opt=[
                    "itunes.country=ua",
                    "deezer.min_interval=0.5",
                    "musicbrainz.min_interval=1.5",
                ]
            ),
            {},
        )

        assert config.providers["itunes"]["country"] == "ua"
        assert config.providers["deezer"]["min_interval"] == 0.5
        assert config.providers["musicbrainz"]["min_interval"] == 1.5

    def test_provider_opt_can_enable_provider(self):
        config = m.build_source_config(
            make_args(provider_opt=["vocadb.enabled=true"]),
            {},
        )

        assert config.metadata_sources == ["itunes", "vocadb"]

    def test_malformed_provider_option_is_rejected(self):
        for value in ("itunes", "itunes.", "itunes.country", "itunes.country="):
            with pytest.raises(ValueError):
                m.build_source_config(
                    make_args(provider_opt=[value]),
                    {},
                )

    def test_unknown_provider_option_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            m.build_source_config(
                make_args(provider_opt=["napster.enabled=true"]),
                {},
            )

        with pytest.raises(ValueError, match="Unknown option"):
            m.build_source_config(
                make_args(provider_opt=["itunes.volume=11"]),
                {},
            )

    def test_invalid_country_is_rejected(self):
        with pytest.raises(ValueError, match="two-letter"):
            m.build_source_config(
                make_args(provider_opt=["itunes.country=ukraine"]),
                {},
            )

    def test_negative_threshold_is_rejected(self):
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            m.build_source_config(
                make_args(match_threshold=-0.1),
                {},
            )

    def test_threshold_above_one_is_rejected(self):
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            m.build_source_config(
                make_args(title_threshold=1.1),
                {},
            )

    def test_thresholds_from_config(self):
        config = m.build_source_config(
            make_args(),
            {"match_threshold": "0.4", "title_threshold": "0.7"},
        )

        assert config.match_threshold == 0.4
        assert config.title_threshold == 0.7


class TestNumericValidation:
    @pytest.mark.parametrize("value", [0.0, 0.5, 1.0, "0.25"])
    def test_valid_thresholds_are_accepted(self, value):
        config = m.build_source_config(
            make_args(match_threshold=value, title_threshold=value),
            {},
        )

        assert config.match_threshold == float(value)
        assert config.title_threshold == float(value)

    @pytest.mark.parametrize(
        "value",
        [-0.1, 1.1, float("nan"), float("inf"), float("-inf"), "not-a-number"],
    )
    def test_invalid_match_threshold_is_rejected(self, value):
        with pytest.raises(ValueError, match="match_threshold"):
            m.build_source_config(make_args(match_threshold=value), {})

    @pytest.mark.parametrize(
        "value",
        [-0.1, 1.1, float("nan"), float("inf"), float("-inf"), "not-a-number"],
    )
    def test_invalid_title_threshold_is_rejected(self, value):
        with pytest.raises(ValueError, match="title_threshold"):
            m.build_source_config(make_args(title_threshold=value), {})

    @pytest.mark.parametrize(
        "value",
        ["-0.1", "1.1", "nan", "inf", "-inf", "not-a-number"],
    )
    def test_invalid_threshold_from_config_is_rejected(self, value):
        with pytest.raises(ValueError, match="match_threshold"):
            m.build_source_config(
                make_args(),
                {"match_threshold": value},
            )

    @pytest.mark.parametrize("value", ["0", "0.25", "3.0"])
    def test_valid_provider_intervals_are_accepted(self, value):
        config = m.build_source_config(
            make_args(),
            {"deezer_min_interval": value},
        )

        assert config.providers["deezer"]["min_interval"] == float(value)

    def test_zero_interval_is_preserved(self):
        config = m.build_source_config(make_args(), {})

        assert config.providers["spotify"]["min_interval"] == 0.0

    @pytest.mark.parametrize(
        "value",
        ["-1", "nan", "inf", "-inf", "not-a-number"],
    )
    def test_invalid_provider_interval_from_config_is_rejected(self, value):
        with pytest.raises(ValueError, match="deezer_min_interval"):
            m.build_source_config(
                make_args(),
                {"deezer_min_interval": value},
            )

    @pytest.mark.parametrize(
        "value",
        ["-1", "nan", "inf", "-inf", "not-a-number"],
    )
    def test_invalid_provider_interval_from_cli_is_rejected(self, value):
        with pytest.raises(ValueError, match="deezer.min_interval"):
            m.build_source_config(
                make_args(provider_opt=[f"deezer.min_interval={value}"]),
                {},
            )

    def test_provider_defaults_are_valid(self):
        config = m.build_source_config(make_args(), {})

        for name, defaults in m.PROVIDER_DEFAULTS.items():
            assert (
                config.providers[name]["min_interval"]
                == defaults["min_interval"]
            )


class TestCliPrecedence:
    def test_cli_selection_overrides_config_disable_sources(self):
        settings = {
            "metadata_sources": "itunes",
            "disable_sources": "deezer",
            "deezer_enabled": "false",
        }

        config = m.build_source_config(
            make_args(metadata_sources="deezer"),
            settings,
        )

        assert config.metadata_sources == ["deezer"]
        assert config.is_enabled("deezer")
        assert not config.providers["deezer"]["disabled"]

    def test_config_enabled_provider_is_disabled_by_cli(self):
        config = m.build_source_config(
            make_args(disable_sources="deezer"),
            {"metadata_sources": "deezer,itunes"},
        )

        assert config.metadata_sources == ["itunes"]
        assert not config.is_enabled("deezer")

    def test_cli_changes_config_source_order(self):
        config = m.build_source_config(
            make_args(metadata_sources="deezer,itunes"),
            {"metadata_sources": "itunes,deezer"},
        )

        assert config.metadata_sources == ["deezer", "itunes"]

    def test_cli_none_keeps_youtube_enabled(self):
        config = m.build_source_config(
            make_args(metadata_sources="none"),
            {
                "metadata_sources": "deezer,itunes",
                "deezer_enabled": "true",
            },
        )

        assert config.metadata_sources == []
        assert config.none_selected
        assert config.youtube_enabled

    def test_cli_selection_with_youtube_enabled(self):
        config = m.build_source_config(
            make_args(metadata_sources="deezer"),
            {"metadata_sources": "itunes", "youtube_enabled": "true"},
        )

        assert config.metadata_sources == ["deezer"]
        assert config.youtube_enabled

    def test_cli_selection_with_youtube_disabled(self):
        config = m.build_source_config(
            make_args(
                metadata_sources="deezer",
                disable_sources="youtube",
            ),
            {"metadata_sources": "itunes"},
        )

        assert config.metadata_sources == ["deezer"]
        assert not config.youtube_enabled

    def test_config_disabled_youtube_stays_disabled_with_cli_selection(self):
        config = m.build_source_config(
            make_args(metadata_sources="deezer"),
            {"metadata_sources": "itunes", "youtube_enabled": "false"},
        )

        assert config.metadata_sources == ["deezer"]
        assert not config.youtube_enabled

    def test_cli_disable_wins_over_cli_selection(self):
        config = m.build_source_config(
            make_args(
                metadata_sources="deezer,itunes",
                disable_sources="deezer",
            ),
            {},
        )

        assert config.metadata_sources == ["itunes"]
        assert not config.is_enabled("deezer")

    def test_cli_disable_wins_over_cli_provider_enable(self):
        config = m.build_source_config(
            make_args(
                provider_opt=["deezer.enabled=true"],
                disable_sources="deezer",
            ),
            {},
        )

        assert config.metadata_sources == ["itunes"]
        assert not config.is_enabled("deezer")

    def test_cli_provider_enable_overrides_config_disable_sources(self):
        config = m.build_source_config(
            make_args(provider_opt=["deezer.enabled=true"]),
            {
                "metadata_sources": "itunes",
                "disable_sources": "deezer",
            },
        )

        assert config.metadata_sources == ["itunes", "deezer"]
        assert config.is_enabled("deezer")

    def test_disabled_provider_is_never_queried(self, monkeypatch):
        calls = []

        def fake_deezer(runtime, artist, title, config):
            calls.append("deezer")
            return [{"title": title, "artist": artist}]

        def fake_itunes(runtime, artist, title, config):
            calls.append("itunes")
            return [{"title": title, "artist": artist, "source": "itunes"}]

        monkeypatch.setitem(m.PROVIDER_FUNCTIONS, "deezer", fake_deezer)
        monkeypatch.setitem(m.PROVIDER_FUNCTIONS, "itunes", fake_itunes)
        config = m.build_source_config(
            make_args(),
            {
                "metadata_sources": "deezer,itunes",
                "disable_sources": "deezer",
            },
        )

        result = m.resolve_metadata(
            "Daft Punk",
            "One More Time",
            config,
            make_runtime(),
        )

        assert result["source"] == "itunes"
        assert calls == ["itunes"]

    def test_config_remains_unchanged_after_cli_overrides(self):
        settings = {
            "metadata_sources": "itunes",
            "disable_sources": "deezer",
            "deezer_enabled": "false",
            "youtube_enabled": "true",
        }
        original = dict(settings)

        m.build_source_config(
            make_args(
                metadata_sources="deezer",
                disable_sources="youtube",
            ),
            settings,
        )

        assert settings == original

    def test_config_disabled_provider_is_not_promoted_by_cli_selection(self):
        config = m.build_source_config(
            make_args(metadata_sources="itunes"),
            {
                "metadata_sources": "itunes",
                "disable_sources": "vocadb",
            },
        )

        assert m.effective_metadata_sources(
            config, "初音ミク", "消失"
        ) == ["itunes"]


class TestVocadbPromotion:
    def test_cjk_promotes_vocadb_temporarily(self):
        config = make_config(["itunes", "vocadb"])

        assert m.effective_metadata_sources(config, "初音ミク", "消失") == [
            "vocadb",
            "itunes",
        ]
        assert config.metadata_sources == ["itunes", "vocadb"]

    def test_vocaloid_hint_promotes_vocadb(self):
        config = make_config(["itunes", "vocadb"])

        assert m.effective_metadata_sources(
            config,
            "Hatsune Miku",
            "Song",
        )[0] == "vocadb"

    def test_cjk_adds_vocadb_even_when_not_configured(self):
        config = make_config(["itunes"])

        assert m.effective_metadata_sources(config, "初音ミク", "消失") == [
            "vocadb",
            "itunes",
        ]

    def test_disabled_vocadb_is_not_promoted(self):
        config = make_config(["itunes"], disabled=("vocadb",))

        assert m.effective_metadata_sources(config, "初音ミク", "消失") == [
            "itunes"
        ]

    def test_none_is_not_promoted(self):
        config = make_config([], none_selected=True)

        assert m.effective_metadata_sources(config, "初音ミク", "消失") == []

    def test_promoted_vocadb_is_actually_queried(self, monkeypatch):
        calls = []

        def fake_vocadb(runtime, artist, title, config):
            calls.append("vocadb")
            return [
                {
                    "title": "初音ミクの消失",
                    "artist": "初音ミク",
                    "source": "vocadb",
                }
            ]

        def fake_itunes(runtime, artist, title, config):
            calls.append("itunes")
            return []

        monkeypatch.setitem(m.PROVIDER_FUNCTIONS, "vocadb", fake_vocadb)
        monkeypatch.setitem(m.PROVIDER_FUNCTIONS, "itunes", fake_itunes)
        config = make_config(["itunes"])
        runtime = make_runtime()

        result = m.resolve_metadata("初音ミク", "初音ミクの消失", config, runtime)

        assert result["source"] == "vocadb"
        assert calls == ["vocadb"]


class TestMatching:
    def test_exact_match(self):
        candidate = {"title": "One More Time", "artist": "Daft Punk"}

        scored = m.select_best_metadata(
            [candidate], "Daft Punk", "One More Time", 0.6, 0.8
        )

        assert scored["score"] == pytest.approx(1.0)

    def test_case_and_punctuation_differences(self):
        candidate = {"title": "one more time!", "artist": "DAFT PUNK"}

        assert m.select_best_metadata(
            [candidate], "Daft Punk", "One More Time", 0.6, 0.8
        )

    def test_unicode_title(self):
        candidate = {"title": "Мёртвый Анархист", "artist": "Король и Шут"}

        assert m.select_best_metadata(
            [candidate], "Король и Шут", "мёртвый анархист", 0.6, 0.8
        )

    def test_cjk_title(self):
        candidate = {"title": "初音ミクの消失", "artist": "初音ミク"}

        assert m.select_best_metadata(
            [candidate], "初音ミク", "初音ミクの消失", 0.6, 0.8
        )

    def test_meaningful_unicode_is_preserved(self):
        assert m.normalize("がっこう") == "がっこう"
        assert m.normalize("がっこう") != m.normalize("かっこう")
        assert m.normalize("Beyoncé") == "beyoncé"

    def test_unrelated_title_is_rejected(self):
        candidate = {
            "title": "Bohemian Rhapsody",
            "artist": "Queen",
        }

        assert m.select_best_metadata(
            [candidate], "Daft Punk", "One More Time", 0.6, 0.8
        ) is None

    def test_title_threshold_rejects_close_but_short_title(self):
        candidate = {"title": "One More Tim", "artist": "Daft Punk"}

        assert m.select_best_metadata(
            [candidate], "Daft Punk", "One More Time", 0.0, 0.99
        ) is None

    def test_missing_optional_metadata_does_not_invalidate(self):
        candidate = {"title": "One More Time", "artist": "Daft Punk"}

        scored = m.select_best_metadata(
            [candidate], "Daft Punk", "One More Time", 0.6, 0.8
        )

        assert scored
        assert scored.get("album") is None

    def test_best_candidate_wins(self):
        candidates = [
            {"title": "One More Time (Live)", "artist": "Other"},
            {"title": "One More Time", "artist": "Daft Punk"},
        ]

        scored = m.select_best_metadata(
            candidates, "Daft Punk", "One More Time", 0.6, 0.8
        )

        assert scored["artist"] == "Daft Punk"


class TestProviders:
    def test_itunes_success_and_country(self):
        session = FakeSession(
            FakeResponse(
                {
                    "results": [
                        {
                            "trackName": "One More Time",
                            "artistName": "Daft Punk",
                            "collectionName": "Discovery",
                            "releaseDate": "2001-03-12T00:00:00Z",
                            "trackNumber": 1,
                            "trackId": 123,
                            "artworkUrl100": "https://img/100x100bb.jpg",
                        }
                    ]
                }
            )
        )
        runtime = make_runtime(session)
        config = make_config(["itunes"])

        candidates = m.itunes_provider(
            runtime, "Daft Punk", "One More Time", config
        )

        assert candidates[0]["title"] == "One More Time"
        assert candidates[0]["cover_url"] == "https://img/600x600bb.jpg"
        assert candidates[0]["source"] == "itunes"
        assert session.calls[0]["params"]["country"] == "us"

    def test_itunes_custom_country(self):
        session = FakeSession(FakeResponse({"results": []}))
        runtime = make_runtime(session)
        config = make_config(["itunes"])
        config.providers["itunes"]["country"] = "ua"

        m.itunes_provider(runtime, "a", "b", config)

        assert session.calls[0]["params"]["country"] == "ua"

    def test_itunes_empty_results(self):
        runtime = make_runtime(FakeSession(FakeResponse({"results": []})))

        assert m.itunes_provider(
            runtime, "a", "b", make_config(["itunes"])
        ) == []

    def test_invalid_json_is_a_provider_error(self):
        session = FakeSession(FakeResponse(json_error=ValueError("bad")))
        runtime = make_runtime(session)

        with pytest.raises(m.ProviderError, match="invalid JSON"):
            m.itunes_provider(runtime, "a", "b", make_config(["itunes"]))

    def test_network_error_is_a_provider_error(self):
        session = FakeSession(
            requests.ConnectionError("offline")
        )
        runtime = make_runtime(session)

        with pytest.raises(m.ProviderError):
            m.itunes_provider(runtime, "a", "b", make_config(["itunes"]))

    def test_timeout_is_a_provider_error(self):
        session = FakeSession(requests.Timeout("slow"))
        runtime = make_runtime(session)

        with pytest.raises(m.ProviderError, match="timed out"):
            m.itunes_provider(runtime, "a", "b", make_config(["itunes"]))

    def test_http_error_is_a_provider_error(self):
        runtime = make_runtime(FakeSession(FakeResponse(status_code=500)))

        with pytest.raises(m.ProviderError, match="HTTP 500"):
            m.itunes_provider(runtime, "a", "b", make_config(["itunes"]))

    def test_401_and_403_are_auth_errors(self):
        for status in (401, 403):
            runtime = make_runtime(FakeSession(FakeResponse(status_code=status)))

            with pytest.raises(m.ProviderAuthError):
                m.deezer_provider(runtime, "a", "b", make_config(["deezer"]))

    def test_invalid_response_shape(self):
        runtime = make_runtime(FakeSession(FakeResponse({"unexpected": True})))

        with pytest.raises(m.ProviderError, match="invalid response"):
            m.itunes_provider(runtime, "a", "b", make_config(["itunes"]))

    def test_deezer_success(self):
        session = FakeSession(
            FakeResponse(
                {
                    "data": [
                        {
                            "id": 7,
                            "title": "One More Time",
                            "artist": {"name": "Daft Punk"},
                            "album": {
                                "title": "Discovery",
                                "artist": {"name": "Daft Punk"},
                                "cover_xl": "https://img/xl.jpg",
                            },
                        }
                    ]
                }
            )
        )
        candidates = m.deezer_provider(
            make_runtime(session),
            "Daft Punk",
            "One More Time",
            make_config(["deezer"]),
        )

        assert candidates[0]["cover_url"] == "https://img/xl.jpg"
        assert candidates[0]["album"] == "Discovery"

    def test_deezer_api_error(self):
        runtime = make_runtime(
            FakeSession(FakeResponse({"error": {"message": "quota"}}))
        )

        with pytest.raises(m.ProviderError, match="Deezer API error"):
            m.deezer_provider(runtime, "a", "b", make_config(["deezer"]))

    def test_musicbrainz_with_cover_art_archive(self):
        session = FakeSession(
            FakeResponse(
                {
                    "recordings": [
                        {
                            "id": "rec-1",
                            "title": "One More Time",
                            "artist-credit": [
                                {"name": "Daft Punk", "joinphrase": ""}
                            ],
                            "releases": [
                                {
                                    "id": "rel-1",
                                    "title": "Discovery",
                                    "date": "2001",
                                }
                            ],
                        }
                    ]
                }
            ),
            FakeResponse(
                {
                    "images": [
                        {
                            "front": True,
                            "image": "https://caa/front.jpg",
                            "width": 1200,
                            "height": 1200,
                        }
                    ]
                }
            ),
        )
        runtime = make_runtime(session)
        candidates = m.musicbrainz_provider(
            runtime, "Daft Punk", "One More Time", make_config(["musicbrainz"])
        )

        assert candidates[0]["album"] == "Discovery"
        assert candidates[0]["release_date"] == "2001"
        assert candidates[0]["cover_url"] == "https://caa/front.jpg"
        assert len(session.calls) == 2

    def test_musicbrainz_missing_cover_is_not_a_failure(self):
        session = FakeSession(
            FakeResponse(
                {
                    "recordings": [
                        {
                            "id": "rec-1",
                            "title": "One More Time",
                            "artist-credit": [{"name": "Daft Punk"}],
                            "releases": [{"id": "rel-1", "title": "Discovery"}],
                        }
                    ]
                }
            ),
            FakeResponse(status_code=404),
        )
        runtime = make_runtime(session)
        candidates = m.musicbrainz_provider(
            runtime, "Daft Punk", "One More Time", make_config(["musicbrainz"])
        )

        assert candidates[0]["title"] == "One More Time"
        assert candidates[0]["cover_url"] is None

    def test_cover_art_lookup_is_memoised(self):
        session = FakeSession(
            FakeResponse(
                {
                    "images": [
                        {
                            "front": True,
                            "image": "https://caa/front.jpg",
                        }
                    ]
                }
            )
        )
        runtime = make_runtime(session)
        config = make_config(["musicbrainz"])

        first = m.cover_art_archive_url(runtime, "rel-1", config)
        second = m.cover_art_archive_url(runtime, "rel-1", config)

        assert first == second == "https://caa/front.jpg"
        assert len(session.calls) == 1

    def test_vocadb_success_with_unicode(self):
        session = FakeSession(
            FakeResponse(
                {
                    "items": [
                        {
                            "id": 1,
                            "name": "初音ミクの消失",
                            "artistString": "初音ミク",
                            "publishDate": "2008-01-01",
                            "albums": [
                                {
                                    "name": "Album",
                                    "mainPicture": {
                                        "url": "/img/cover.jpg"
                                    },
                                }
                            ],
                        }
                    ]
                }
            )
        )
        candidates = m.vocadb_provider(
            make_runtime(session),
            "初音ミク",
            "初音ミクの消失",
            make_config(["vocadb"]),
        )

        assert candidates[0]["title"] == "初音ミクの消失"
        assert candidates[0]["artist"] == "初音ミク"
        assert candidates[0]["cover_url"] == "https://vocadb.net/img/cover.jpg"

    def test_spotify_missing_credentials_is_quiet(self, monkeypatch, capsys):
        monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
        monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)
        runtime = make_runtime()

        assert m.spotify_provider(
            runtime, "a", "b", make_config(["spotify"])
        ) == []
        assert capsys.readouterr().out == ""

    def test_spotify_401_sets_600_second_cooldown(self, monkeypatch):
        class Unauthorized(Exception):
            http_status = 401

        class BadSpotify:
            def search(self, **kwargs):
                raise Unauthorized("unauthorized")

        runtime = make_runtime()
        runtime.spotify_client = BadSpotify()
        runtime.spotify_initialized = True
        config = make_config(["spotify"])

        result = m.resolve_metadata("a", "b", config, runtime)

        assert result["source"] == "input"
        assert runtime.health.in_cooldown("spotify")
        assert runtime.health.state("spotify")["cooldown_seconds"] == 600.0


class TestRateLimiting:
    def test_independent_provider_intervals(self, monkeypatch):
        now = [0.0]
        sleeps = []

        def fake_sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds

        monkeypatch.setattr(m.time, "sleep", fake_sleep)
        limiter = m.RateLimiter(
            {"itunes": 3.0, "deezer": 0.25},
            clock=lambda: now[0],
        )

        limiter.wait("itunes")
        now[0] += 1.0
        limiter.wait("deezer")
        assert sleeps == []

        now[0] += 0.5
        limiter.wait("itunes")
        assert sleeps == [pytest.approx(1.5)]

    def test_custom_intervals(self, monkeypatch):
        now = [0.0]
        sleeps = []

        def fake_sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds

        monkeypatch.setattr(m.time, "sleep", fake_sleep)
        limiter = m.RateLimiter({"deezer": 2.0}, clock=lambda: now[0])

        limiter.wait("deezer")
        limiter.wait("deezer")

        assert sleeps == [pytest.approx(2.0)]

    def test_zero_interval_never_blocks(self, monkeypatch):
        sleeps = []
        monkeypatch.setattr(m.time, "sleep", sleeps.append)
        limiter = m.RateLimiter({"vocadb": 0.0})

        limiter.wait("vocadb")
        limiter.wait("vocadb")

        assert sleeps == []


class TestFailureRecovery:
    def test_two_failures_start_thirty_second_cooldown(self):
        now = [0.0]
        health = m.ProviderHealth(clock=lambda: now[0])

        health.record_failure("deezer")
        assert not health.in_cooldown("deezer")

        health.record_failure("deezer")
        assert health.in_cooldown("deezer")
        assert health.state("deezer")["cooldown_seconds"] == 30.0

    def test_cooldown_doubles_and_caps(self):
        now = [0.0]
        health = m.ProviderHealth(clock=lambda: now[0])

        health.record_failure("deezer")
        health.record_failure("deezer")

        expected = [30.0, 60.0, 120.0, 240.0, 480.0, 600.0]

        for cooldown in expected[1:]:
            now[0] += health.state("deezer")["cooldown_seconds"]
            health.record_failure("deezer")
            assert health.state("deezer")["cooldown_seconds"] == cooldown

    def test_retry_after_cooldown(self):
        now = [0.0]
        health = m.ProviderHealth(clock=lambda: now[0])
        health.record_failure("deezer")
        health.record_failure("deezer")

        now[0] += 29.0
        assert health.in_cooldown("deezer")

        now[0] += 2.0
        assert not health.in_cooldown("deezer")

    def test_success_resets_failure_count(self):
        health = m.ProviderHealth()
        health.record_failure("deezer")
        health.record_success("deezer")

        assert health.failures("deezer") == 0
        assert not health.in_cooldown("deezer")

    def test_empty_results_do_not_count_as_failures(self, monkeypatch):
        runtime = make_runtime(FakeSession(FakeResponse({"results": []})))
        config = make_config(["itunes"])

        result = m.resolve_metadata("a", "b", config, runtime)

        assert result["source"] == "input"
        assert runtime.health.failures("itunes") == 0

    def test_priority_is_restored_after_recovery(self, monkeypatch, tmp_path):
        now = [0.0]
        calls = []
        state = {"deezer_ok": False}

        def fake_deezer(runtime, artist, title, config):
            calls.append("deezer")

            if not state["deezer_ok"]:
                raise m.ProviderError("offline")

            return [
                {
                    "title": "One More Time",
                    "artist": "Daft Punk",
                    "album": "Discovery",
                    "source": "deezer",
                }
            ]

        def fake_itunes(runtime, artist, title, config):
            calls.append("itunes")
            return [
                {
                    "title": "One More Time",
                    "artist": "Daft Punk",
                    "album": "Discovery",
                    "source": "itunes",
                }
            ]

        monkeypatch.setitem(m.PROVIDER_FUNCTIONS, "deezer", fake_deezer)
        monkeypatch.setitem(m.PROVIDER_FUNCTIONS, "itunes", fake_itunes)

        health = m.ProviderHealth(clock=lambda: now[0])
        cache = m.MetadataCache(tmp_path / m.CACHE_FILENAME)
        runtime = make_runtime(cache=cache, health=health)
        config = make_config(["deezer", "itunes"])

        assert m.resolve_metadata("Daft Punk", "One More Time", config, runtime)["source"] == "itunes"
        assert m.resolve_metadata("Daft Punk", "One More Time", config, runtime)["source"] == "itunes"
        assert health.in_cooldown("deezer")

        state["deezer_ok"] = True
        now[0] += 31.0

        result = m.resolve_metadata("Daft Punk", "One More Time", config, runtime)

        assert result["source"] == "deezer"
        assert calls[-1] == "deezer"
        assert health.failures("deezer") == 0


class TestMetadataCache:
    def test_cache_is_created_and_read(self, tmp_path):
        path = tmp_path / m.CACHE_FILENAME
        cache = m.MetadataCache(path)
        cache.set(
            "Daft Punk",
            "One More Time",
            "itunes",
            {
                "title": "One More Time",
                "artist": "Daft Punk",
                "source": "itunes",
            },
        )

        assert path.is_file()
        assert m.MetadataCache(path).get(
            "daft punk", "one  more time", "itunes"
        )["title"] == "One More Time"

    def test_entries_are_independent_per_provider(self, tmp_path):
        cache = m.MetadataCache(tmp_path / m.CACHE_FILENAME)
        cache.set("A", "B", "itunes", {"title": "B", "source": "itunes"})
        cache.set("A", "B", "deezer", {"title": "B", "source": "deezer"})

        assert cache.get("A", "B", "itunes")["source"] == "itunes"
        assert cache.get("A", "B", "deezer")["source"] == "deezer"

    def test_incomplete_result_does_not_overwrite_better_entry(self, tmp_path):
        path = tmp_path / m.CACHE_FILENAME
        cache = m.MetadataCache(path)
        cache.set(
            "A",
            "B",
            "itunes",
            {"title": "B", "artist": "A", "source": "itunes"},
        )

        assert cache.set("A", "B", "itunes", {"title": None}) is False
        assert cache.get("A", "B", "itunes")["title"] == "B"

    def test_lower_scored_result_does_not_replace_better_entry(self, tmp_path):
        cache = m.MetadataCache(tmp_path / m.CACHE_FILENAME)
        cache.set(
            "A",
            "B",
            "itunes",
            {"title": "B", "artist": "A", "score": 0.9},
        )

        assert cache.set(
            "A",
            "B",
            "itunes",
            {"title": "B", "artist": "A", "score": 0.5},
        ) is False
        assert cache.get("A", "B", "itunes")["score"] == 0.9

    def test_unrelated_entries_survive_a_new_write(self, tmp_path):
        path = tmp_path / m.CACHE_FILENAME
        cache = m.MetadataCache(path)
        cache.set("A", "B", "itunes", {"title": "B", "source": "itunes"})
        cache.set("C", "D", "deezer", {"title": "D", "source": "deezer"})
        cache.set("A", "B", "deezer", {"title": "B", "source": "deezer"})

        reloaded = m.MetadataCache(path)

        assert reloaded.get("A", "B", "itunes")["source"] == "itunes"
        assert reloaded.get("A", "B", "deezer")["source"] == "deezer"
        assert reloaded.get("C", "D", "deezer")["source"] == "deezer"

    def test_corrupted_cache_is_handled(self, tmp_path):
        path = tmp_path / m.CACHE_FILENAME
        path.write_text("not json at all", encoding="utf-8")

        cache = m.MetadataCache(path)

        assert cache.entries == {}
        assert cache.get("A", "B", "itunes") is None

    def test_invalid_cache_shape_is_handled(self, tmp_path):
        path = tmp_path / m.CACHE_FILENAME
        path.write_text(json.dumps({"entries": []}), encoding="utf-8")

        assert m.MetadataCache(path).entries == {}

    def test_disabled_provider_cache_is_not_used(
        self, monkeypatch, tmp_path
    ):
        calls = []

        def fake_itunes(runtime, artist, title, config):
            calls.append("itunes")
            return [{"title": title, "artist": artist, "source": "itunes"}]

        monkeypatch.setitem(m.PROVIDER_FUNCTIONS, "itunes", fake_itunes)
        cache = m.MetadataCache(tmp_path / m.CACHE_FILENAME)
        cache.set(
            "Daft Punk",
            "One More Time",
            "deezer",
            {
                "title": "Wrong cached result",
                "artist": "Daft Punk",
                "source": "deezer",
                "score": 1.0,
            },
        )
        runtime = make_runtime(cache=cache)
        config = m.build_source_config(
            make_args(),
            {
                "metadata_sources": "deezer,itunes",
                "disable_sources": "deezer",
            },
        )

        result = m.resolve_metadata(
            "Daft Punk",
            "One More Time",
            config,
            runtime,
        )

        assert result["source"] == "itunes"
        assert calls == ["itunes"]

    def test_cached_priority_result_is_used(self, monkeypatch, tmp_path):
        calls = []

        def fake_itunes(runtime, artist, title, config):
            calls.append("itunes")
            return [
                {
                    "title": "One More Time",
                    "artist": "Daft Punk",
                    "source": "itunes",
                }
            ]

        monkeypatch.setitem(m.PROVIDER_FUNCTIONS, "itunes", fake_itunes)
        cache = m.MetadataCache(tmp_path / m.CACHE_FILENAME)
        runtime = make_runtime(cache=cache)
        config = make_config(["itunes"])

        first = m.resolve_metadata("Daft Punk", "One More Time", config, runtime)
        second = m.resolve_metadata("Daft Punk", "One More Time", config, runtime)

        assert first["source"] == "itunes"
        assert second["source"] == "itunes"
        assert calls == ["itunes"]


class TestArtwork:
    def test_itunes_artwork_is_upscaled(self):
        assert m.upscale_itunes_artwork(
            "https://img/100x100bb.jpg"
        ) == "https://img/600x600bb.jpg"

    def test_youtube_thumbnail_prefers_largest(self):
        video = {
            "thumbnails": [
                {"url": "small", "width": 120, "height": 90},
                {"url": "large", "width": 1280, "height": 720},
            ]
        }

        assert m.youtube_thumbnail_urls(video)[0] == "large"

    def test_youtube_thumbnail_from_id(self):
        urls = m.youtube_thumbnail_urls({"id": "abc"})

        assert urls[0] == "https://i.ytimg.com/vi/abc/maxresdefault.jpg"

    def test_image_validation(self):
        assert m.is_image_bytes(b"\xff\xd8\xff\xe0data")
        assert m.is_image_bytes(b"\x89PNG\r\n\x1a\n")
        assert m.is_image_bytes(b"GIF87a")
        assert m.is_image_bytes(b"GIF89a")
        assert m.is_image_bytes(b"RIFF\x00\x00\x00\x00WEBP")
        assert not m.is_image_bytes(b"<html>not an image</html>")
        assert not m.is_image_bytes(b"")
        assert not m.is_image_bytes(b"RIFF\x00\x00\x00\x00WAVE")
        assert not m.is_image_bytes(b"WEBP\x00\x00\x00\x00RIFF")

    @pytest.mark.parametrize(
        ("data", "expected"),
        [
            (b"\xff\xd8\xff\xe0data", "jpeg"),
            (b"\x89PNG\r\n\x1a\n", "png"),
            (b"GIF87a", "gif"),
            (b"GIF89a", "gif"),
            (b"RIFF\x00\x00\x00\x00WEBP", "webp"),
        ],
    )
    def test_image_format_detection(self, data, expected):
        assert m.detect_image_format(data) == expected

    def test_image_extensions_and_mime_types_match_signature(self):
        assert m.IMAGE_FORMATS["jpeg"] == ("image/jpeg", ".jpg")
        assert m.IMAGE_FORMATS["png"] == ("image/png", ".png")
        assert m.IMAGE_FORMATS["gif"] == ("image/gif", ".gif")
        assert m.IMAGE_FORMATS["webp"] == ("image/webp", ".webp")

    def test_download_cover_uses_signature_not_content_type(
        self, monkeypatch, tmp_path
    ):
        class Response:
            content = b"\x89PNG\r\n\x1a\nrest"
            headers = {"Content-Type": "image/jpeg"}

            def raise_for_status(self):
                pass

        monkeypatch.setattr(
            m.requests,
            "get",
            lambda *a, **k: Response(),
        )
        destination = tmp_path / "cover.jpg"

        format_name = m.download_cover("https://img/cover.jpg", destination)

        assert format_name == "png"
        assert destination.read_bytes() == Response.content

    @pytest.mark.parametrize(
        "content",
        [b"", b"<html>not an image</html>", b"RIFF\x00\x00\x00\x00WAVE"],
    )
    def test_download_cover_rejects_invalid_images(
        self, monkeypatch, tmp_path, content
    ):
        class Response:
            def raise_for_status(self):
                pass

        response = Response()
        response.content = content
        monkeypatch.setattr(
            m.requests,
            "get",
            lambda *a, **k: response,
        )

        with pytest.raises(ValueError, match="valid image"):
            m.download_cover("https://img/cover.jpg", tmp_path / "cover")

    @pytest.mark.parametrize(
        ("content", "extension"),
        [
            (b"\xff\xd8\xff\xe0data", ".jpg"),
            (b"\x89PNG\r\n\x1a\nrest", ".png"),
            (b"GIF89a-rest", ".gif"),
            (b"RIFF\x00\x00\x00\x00WEBP-rest", ".webp"),
        ],
    )
    def test_download_best_cover_uses_actual_extension(
        self, monkeypatch, tmp_path, content, extension
    ):
        class Response:
            pass

        response = Response()
        response.content = content

        def raise_for_status():
            pass

        response.raise_for_status = raise_for_status
        monkeypatch.setattr(
            m.requests,
            "get",
            lambda *a, **k: response,
        )
        metadata = {
            "cover_url": "https://img/cover.jpg",
            "source": "itunes",
        }

        path = m.download_best_cover(
            metadata,
            None,
            tmp_path / "cover",
            False,
        )

        assert path == tmp_path / f"cover{extension}"
        assert path.read_bytes() == content
        assert not (tmp_path / "cover").exists()

    def test_download_best_cover_falls_back_after_invalid_image(
        self, monkeypatch, tmp_path
    ):
        class Response:
            def __init__(self, content, status=200):
                self.content = content
                self.status_code = status

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise requests.HTTPError("bad image")

        responses = [
            Response(b"<html>broken</html>"),
            Response(b"\x89PNG\r\n\x1a\nrest"),
        ]

        def fake_get(url, **kwargs):
            return responses.pop(0)

        monkeypatch.setattr(m.requests, "get", fake_get)
        metadata = {
            "cover_url": "https://img/cover.jpg",
            "source": "itunes",
        }
        video = {
            "id": "abc",
            "thumbnails": [{"url": "https://yt/thumb.jpg"}],
        }

        path = m.download_best_cover(
            metadata,
            video,
            tmp_path / "cover",
            True,
        )

        assert path == tmp_path / "cover.png"


class TestCli:
    def test_list_sources_does_not_need_input(self, monkeypatch, capsys):
        run_cli(monkeypatch, "--list-sources")

        output = capsys.readouterr().out
        assert "itunes" in output
        assert "youtube" in output
        assert "Metadata priority: itunes" in output

    def test_list_sources_reflects_cli_priority(self, monkeypatch, capsys):
        run_cli(
            monkeypatch,
            "-s",
            "deezer,itunes",
            "--list-sources",
        )

        assert "Metadata priority: deezer, itunes" in capsys.readouterr().out

    def test_unknown_metadata_source_exits(self, monkeypatch, capsys):
        with pytest.raises(SystemExit) as exc:
            run_cli(monkeypatch, "-s", "napster", "--list-sources")

        assert exc.value.code == 1
        assert "Unknown metadata source" in capsys.readouterr().out

    def test_malformed_provider_option_exits(self, monkeypatch, capsys):
        with pytest.raises(SystemExit) as exc:
            run_cli(monkeypatch, "--provider-opt", "itunes.country", "--list-sources")

        assert exc.value.code == 1
        assert "Invalid --provider-opt" in capsys.readouterr().out

    def test_invalid_thresholds_are_rejected(self, monkeypatch, capsys):
        with pytest.raises(SystemExit) as exc:
            run_cli(
                monkeypatch,
                "--match-threshold",
                "5",
                "--list-sources",
            )

        assert exc.value.code == 1
        assert "must be between 0.0 and 1.0" in capsys.readouterr().out

    def test_valid_thresholds_are_shown(self, monkeypatch, capsys):
        run_cli(
            monkeypatch,
            "--match-threshold",
            "0",
            "--title-threshold",
            "1",
            "--list-sources",
        )

        output = capsys.readouterr().out
        assert "Match threshold: 0.0" in output
        assert "Title threshold: 1.0" in output

    def test_invalid_threshold_type_is_rejected_by_argparse(
        self, monkeypatch, capsys
    ):
        with pytest.raises(SystemExit) as exc:
            run_cli(monkeypatch, "--match-threshold", "abc", "--list-sources")

        assert exc.value.code == 2


class TestYoutubeFallback:
    def test_youtube_disabled_prevents_download(self, monkeypatch, tmp_path):
        calls = []
        monkeypatch.setattr(
            m,
            "find_youtube_video",
            lambda artist, title: calls.append((artist, title)),
        )
        config = make_config([], youtube=False, none_selected=True)

        ok, reason = m.process_song(
            None,
            "Daft Punk",
            "One More Time",
            tmp_path,
            False,
            "m4a",
            source_config=config,
            runtime=make_runtime(),
        )

        assert (ok, reason) == (False, "YouTube disabled")
        assert calls == []

    def test_cli_youtube_disable_prevents_network_calls(
        self, monkeypatch, tmp_path
    ):
        calls = []
        monkeypatch.setattr(
            m,
            "find_youtube_video",
            lambda artist, title: calls.append((artist, title)),
        )
        config = m.build_source_config(
            make_args(disable_sources="youtube"),
            {},
        )

        ok, reason = m.process_song(
            None,
            "Daft Punk",
            "One More Time",
            tmp_path,
            False,
            "m4a",
            source_config=config,
            runtime=make_runtime(),
        )

        assert (ok, reason) == (False, "YouTube disabled")
        assert calls == []

    def test_config_youtube_disable_prevents_network_calls(
        self, monkeypatch, tmp_path
    ):
        calls = []
        monkeypatch.setattr(
            m,
            "find_youtube_video",
            lambda artist, title: calls.append((artist, title)),
        )
        config = m.build_source_config(
            make_args(),
            {"youtube_enabled": "false"},
        )

        ok, reason = m.process_song(
            None,
            "Daft Punk",
            "One More Time",
            tmp_path,
            False,
            "m4a",
            source_config=config,
            runtime=make_runtime(),
        )

        assert (ok, reason) == (False, "YouTube disabled")
        assert calls == []

    def test_none_metadata_still_uses_youtube(self, monkeypatch, tmp_path):
        from conftest import FIXTURES
        import shutil

        video = {"title": "A - B", "id": "abc"}
        monkeypatch.setattr(m, "find_youtube_video", lambda a, t: video)
        monkeypatch.setattr(
            m,
            "download_audio",
            lambda url, temp_dir, fmt: shutil.copy(
                FIXTURES / f"silence.{fmt}",
                temp_dir / f"audio.{fmt}",
            ),
        )
        monkeypatch.setattr(
            m,
            "download_cover",
            lambda url, dest: dest.write_bytes(b"\xff\xd8\xff\xe0jpeg"),
        )
        config = make_config([], none_selected=True)

        ok, reason = m.process_song(
            None,
            "A",
            "B",
            tmp_path,
            False,
            "m4a",
            source_config=config,
            runtime=make_runtime(),
        )

        assert (ok, reason) == (True, "downloaded")
        assert (tmp_path / "A - B.m4a").exists()
