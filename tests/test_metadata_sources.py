import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

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
    soundcloud=True,
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
        soundcloud_enabled=soundcloud,
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

    def test_soundcloud_is_enabled_by_default(self):
        config = m.build_source_config(make_args(), {})

        assert config.soundcloud_enabled is True
        assert config.soundcloud_min_score == m.SOUNDCLOUD_MIN_SCORE
        assert config.soundcloud_min_margin == m.SOUNDCLOUD_MIN_MARGIN

    def test_soundcloud_can_be_disabled_by_flag(self):
        config = m.build_source_config(
            make_args(soundcloud_enabled=False),
            {},
        )

        assert config.soundcloud_enabled is False

    def test_soundcloud_can_be_disabled_in_config(self):
        config = m.build_source_config(
            make_args(),
            {"soundcloud_enabled": "false"},
        )

        assert config.soundcloud_enabled is False

    def test_soundcloud_can_be_disabled_with_disable_sources(self):
        config = m.build_source_config(
            make_args(disable_sources="soundcloud"),
            {},
        )

        assert config.soundcloud_enabled is False

    def test_soundcloud_thresholds_can_be_configured(self):
        config = m.build_source_config(
            make_args(
                soundcloud_min_score=0.9,
                soundcloud_min_margin=0.02,
            ),
            {},
        )

        assert config.soundcloud_min_score == 0.9
        assert config.soundcloud_min_margin == 0.02

        from_config = m.build_source_config(
            make_args(),
            {
                "soundcloud_min_score": "0.8",
                "soundcloud_min_margin": "0.15",
            },
        )

        assert from_config.soundcloud_min_score == 0.8
        assert from_config.soundcloud_min_margin == 0.15

    def test_invalid_soundcloud_threshold_is_rejected(self):
        with pytest.raises(ValueError):
            m.build_source_config(
                make_args(soundcloud_min_score=1.5),
                {},
            )

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


class TestMusicSources:
    """Priority and disabling of the music providers (YouTube/SoundCloud)."""

    def test_default_priority_keeps_youtube_first(self):
        config = m.build_source_config(make_args(), {})

        assert config.music_sources == ["youtube", "soundcloud"]
        assert config.primary_music_source == "youtube"
        assert config.is_music_enabled("youtube")
        assert config.is_music_enabled("soundcloud")

    def test_custom_priority_is_preserved(self):
        config = m.build_source_config(
            make_args(music_sources="soundcloud, youtube"),
            {},
        )

        assert config.music_sources == ["soundcloud", "youtube"]
        assert config.primary_music_source == "soundcloud"

    def test_duplicate_music_sources_are_removed(self):
        config = m.build_source_config(
            make_args(music_sources="soundcloud,SOUNDCLOUD,youtube"),
            {},
        )

        assert config.music_sources == ["soundcloud", "youtube"]

    def test_unknown_music_source_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown music source"):
            m.build_source_config(
                make_args(music_sources="youtube,napster"),
                {},
            )

    @pytest.mark.parametrize("value", ["", " , "])
    def test_empty_music_source_list_is_rejected(self, value):
        with pytest.raises(ValueError, match="At least one music source"):
            m.build_source_config(make_args(music_sources=value), {})

    def test_music_source_from_config(self):
        config = m.build_source_config(
            make_args(),
            {"music_sources": "soundcloud,youtube"},
        )

        assert config.music_sources == ["soundcloud", "youtube"]

    def test_cli_music_priority_overrides_config(self):
        config = m.build_source_config(
            make_args(music_sources="youtube,soundcloud"),
            {"music_sources": "soundcloud,youtube"},
        )

        assert config.music_sources == ["youtube", "soundcloud"]

    def test_soundcloud_can_be_removed_from_priority(self):
        config = m.build_source_config(
            make_args(music_sources="youtube"),
            {},
        )

        assert config.music_sources == ["youtube"]
        assert config.soundcloud_enabled is False

    def test_youtube_can_be_removed_from_priority(self):
        config = m.build_source_config(
            make_args(music_sources="soundcloud"),
            {},
        )

        assert config.music_sources == ["soundcloud"]
        assert config.youtube_enabled is False
        assert config.primary_music_source == "soundcloud"

    def test_config_flags_remove_music_sources(self):
        no_youtube = m.build_source_config(
            make_args(),
            {"youtube_enabled": "false"},
        )
        no_soundcloud = m.build_source_config(
            make_args(),
            {"soundcloud_enabled": "false"},
        )

        assert no_youtube.music_sources == ["soundcloud"]
        assert no_soundcloud.music_sources == ["youtube"]

    def test_disable_sources_removes_music_sources(self):
        no_youtube = m.build_source_config(
            make_args(disable_sources="youtube"),
            {},
        )
        no_soundcloud = m.build_source_config(
            make_args(disable_sources="soundcloud"),
            {},
        )

        assert no_youtube.music_sources == ["soundcloud"]
        assert no_soundcloud.music_sources == ["youtube"]

    def test_both_disabled_is_rejected(self):
        with pytest.raises(ValueError, match="At least one music source"):
            m.build_source_config(
                make_args(music_sources="youtube", disable_sources="youtube"),
                {},
            )

        with pytest.raises(ValueError, match="At least one music source"):
            m.build_source_config(
                make_args(),
                {
                    "youtube_enabled": "false",
                    "soundcloud_enabled": "false",
                },
            )

    def test_cli_no_youtube_flag_removes_it(self):
        config = m.build_source_config(
            make_args(youtube_enabled=False),
            {},
        )

        assert config.music_sources == ["soundcloud"]

    def test_cli_yes_youtube_flag_appends_it(self):
        config = m.build_source_config(
            make_args(
                music_sources="soundcloud",
                youtube_enabled=True,
            ),
            {},
        )

        assert config.music_sources == ["soundcloud", "youtube"]

    def test_cli_list_overrides_config_disable(self):
        config = m.build_source_config(
            make_args(music_sources="youtube,soundcloud"),
            {
                "youtube_enabled": "false",
                "disable_sources": "soundcloud",
            },
        )

        assert config.music_sources == ["youtube", "soundcloud"]

    def test_explicit_music_list_ignores_config_enable(self):
        from_cli = m.build_source_config(
            make_args(music_sources="soundcloud"),
            {"youtube_enabled": "true"},
        )
        from_config = m.build_source_config(
            make_args(),
            {
                "music_sources": "youtube",
                "soundcloud_enabled": "true",
            },
        )

        assert from_cli.music_sources == ["soundcloud"]
        assert from_config.music_sources == ["youtube"]

    def test_cli_disable_wins_over_cli_list(self):
        config = m.build_source_config(
            make_args(
                music_sources="youtube,soundcloud",
                disable_sources="youtube",
            ),
            {},
        )

        assert config.music_sources == ["soundcloud"]

    def test_soundcloud_trigger_does_not_change_priority(self):
        config = m.build_source_config(
            make_args(
                music_sources="youtube,soundcloud",
                soundcloud_trigger="any",
            ),
            {},
        )

        assert config.music_sources == ["youtube", "soundcloud"]
        assert config.soundcloud_trigger == "any"


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
    def test_cover_by_another_artist_is_rejected(self):
        cover = {"title": "Гимн Рок-н-ролла", "artist": "Денис Малыхин"}

        assert m.select_best_metadata(
            [cover], "крик", "гимн рок н рола", 0.6, 0.8
        ) is None

    def test_artist_similarity_boundary_is_applied(self):
        assert m.matching.MIN_ARTIST_SIMILARITY == 0.45

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

    def test_yo_is_folded_to_ye(self):
        assert m.normalize("Мёртвый") == m.normalize("Мертвый")
        assert m.similarity("Мёртвый Анархист", "Мертвый Анархист") == 1.0

    def test_noise_suffixes_are_ignored(self):
        assert m.normalize("Song (Official Video)") == "song"
        assert m.normalize("Song [Remastered]") == "song"
        assert m.normalize("Song (Official Music Video)") == "song"
        assert m.normalize("Song (Live)") == "song"
        assert m.normalize("Song feat. Guest") == "song"
        assert m.normalize("Song (feat. Guest)") == "song"

    def test_swapped_artist_and_title_are_matched(self):
        candidate = {"title": "One More Time", "artist": "Daft Punk"}

        scored = m.select_best_metadata(
            [candidate], "One More Time", "Daft Punk", 0.6, 0.8
        )

        assert scored is not None
        assert scored["artist"] == "Daft Punk"
        assert scored["title_score"] == pytest.approx(1.0)
        assert scored["artist_score"] == pytest.approx(1.0)

    def test_better_of_normal_and_swapped_score_wins(self):
        candidate = {"title": "One More Time", "artist": "Daft Punk"}

        scored = m.select_best_metadata(
            [candidate], "Daft Punk", "One More Time", 0.6, 0.8
        )

        assert scored["score"] == pytest.approx(1.0)


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
                            "trackTimeMillis": 320400,
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
        assert candidates[0]["cover_url"] == "https://img/640x640bb.jpg"
        assert candidates[0]["source"] == "itunes"
        assert candidates[0]["duration"] == 320
        assert session.calls[0]["params"]["country"] == "us"

    def test_itunes_custom_country(self):
        session = FakeSession(
            FakeResponse({"results": []}),
            FakeResponse({"results": []}),
            FakeResponse({"results": []}),
        )
        runtime = make_runtime(session)
        config = make_config(["itunes"])
        config.providers["itunes"]["country"] = "ua"

        m.itunes_provider(runtime, "a", "b", config)

        assert session.calls[0]["params"]["country"] == "ua"

    def test_itunes_empty_results(self):
        runtime = make_runtime(
            FakeSession(
                FakeResponse({"results": []}),
                FakeResponse({"results": []}),
                FakeResponse({"results": []}),
            )
        )

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
                            "duration": 320,
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
        assert candidates[0]["duration"] == 320

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
                            "length": 320400,
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
        assert candidates[0]["duration"] == 320
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


class TestDurationHelpers:
    def test_milliseconds_are_rounded_to_seconds(self):
        assert m.providers.duration.milliseconds_to_seconds(320400) == 320
        assert m.providers.duration.milliseconds_to_seconds(320600) == 321
        assert m.providers.duration.milliseconds_to_seconds("320400") == 320

    def test_milliseconds_ignore_missing_and_invalid_values(self):
        assert m.providers.duration.milliseconds_to_seconds(None) is None
        assert m.providers.duration.milliseconds_to_seconds(True) is None
        assert m.providers.duration.milliseconds_to_seconds("nope") is None
        assert m.providers.duration.milliseconds_to_seconds(-1000) is None

    def test_seconds_are_rounded_to_whole_seconds(self):
        assert m.providers.duration.seconds(320) == 320
        assert m.providers.duration.seconds("320.6") == 321

    def test_seconds_ignore_missing_and_invalid_values(self):
        assert m.providers.duration.seconds(None) is None
        assert m.providers.duration.seconds(False) is None
        assert m.providers.duration.seconds("nope") is None
        assert m.providers.duration.seconds(-1) is None


class TestQueryRelaxation:
    def test_variants_are_progressive_and_deduplicated(self):
        assert m.providers.search.query_variants(
            "КриК", "гимн рок н рола"
        ) == [
            "КриК гимн рок н рола",
            "гимн рок н рола КриК",
            "гимн рок н рола",
            "гимн рок н",
            "гимн рок",
        ]

    def test_variants_handle_empty_parts(self):
        assert m.providers.search.query_variants("", "Song") == ["Song"]
        assert m.providers.search.query_variants("Artist", "") == ["Artist"]
        assert m.providers.search.query_variants("", "") == []

    def test_short_title_is_not_truncated_below_two_words(self):
        assert m.providers.search.query_variants("A", "One More") == [
            "A One More",
            "One More A",
            "One More",
        ]

    def test_strict_match_stops_before_relaxed_queries(self):
        calls = []
        candidate = {
            "title": "One More Time",
            "artist": "Daft Punk",
            "source": "deezer",
            "source_id": 1,
        }

        def fetch(query):
            calls.append(query)
            return [candidate]

        result = m.providers.search.search_variants(
            fetch,
            "Daft Punk",
            "One More Time",
            make_config(["deezer"]),
            strict_query="strict",
        )

        assert result == [candidate]
        assert calls == ["strict"]

    def test_relaxed_query_runs_after_strict_miss(self):
        calls = []
        wrong = {
            "title": "Nope",
            "artist": "Nobody",
            "source": "deezer",
            "source_id": 1,
        }
        right = {
            "title": "One More Time",
            "artist": "Daft Punk",
            "source": "deezer",
            "source_id": 2,
        }

        def fetch(query):
            calls.append(query)
            return [wrong] if query == "strict" else [right]

        result = m.providers.search.search_variants(
            fetch,
            "Daft Punk",
            "One More Time",
            make_config(["deezer"]),
            strict_query="strict",
        )

        assert result == [right]
        assert calls == ["strict", "Daft Punk One More Time"]

    def test_all_candidates_are_collected_when_nothing_matches(self):
        calls = []
        first = {
            "title": "Nope",
            "artist": "Nobody",
            "source": "deezer",
            "source_id": 1,
        }
        second = {
            "title": "Other",
            "artist": "Someone",
            "source": "deezer",
            "source_id": 2,
        }

        def fetch(query):
            calls.append(query)

            if query == "strict":
                return [first]

            if query == "Daft Punk One More Time":
                return [first, second, "not a dict"]

            return []

        result = m.providers.search.search_variants(
            fetch,
            "Daft Punk",
            "One More Time",
            make_config(["deezer"]),
            strict_query="strict",
        )

        assert result == [first, second]
        assert calls[0] == "strict"
        assert calls[1] == "Daft Punk One More Time"
        assert len(calls) == 5

    def test_none_and_non_dict_candidates_are_ignored(self):
        assert m.providers.search.search_variants(
            lambda query: None,
            "A",
            "B",
            make_config(["deezer"]),
        ) == []
        assert m.providers.search.search_variants(
            lambda query: ["not a dict"],
            "A",
            "B",
            make_config(["deezer"]),
        ) == []

    def test_itunes_uses_truncated_title_when_typo_breaks_search(self):
        session = FakeSession(
            FakeResponse({"results": []}),
            FakeResponse({"results": []}),
            FakeResponse({"results": []}),
            FakeResponse(
                {
                    "results": [
                        {
                            "trackName": "Гимн рок-н-ролла",
                            "artistName": "КриК",
                            "trackId": 1,
                        }
                    ]
                }
            ),
        )

        candidates = m.itunes_provider(
            make_runtime(session),
            "КриК",
            "гимн рок н рола",
            make_config(["itunes"]),
        )

        assert candidates[0]["title"] == "Гимн рок-н-ролла"
        assert session.calls[3]["params"]["term"] == "гимн рок н"

    def test_deezer_runs_free_text_after_strict_miss(self):
        session = FakeSession(
            FakeResponse({"data": []}),
            FakeResponse(
                {
                    "data": [
                        {
                            "id": 7,
                            "title": "One More Time",
                            "artist": {"name": "Daft Punk"},
                            "album": {"title": "Discovery"},
                        }
                    ]
                }
            ),
        )

        candidates = m.deezer_provider(
            make_runtime(session),
            "Daft Punk",
            "One More Time",
            make_config(["deezer"]),
        )

        assert candidates[0]["title"] == "One More Time"
        assert session.calls[0]["params"]["q"] == (
            'artist:"Daft Punk" track:"One More Time"'
        )
        assert session.calls[1]["params"]["q"] == "Daft Punk One More Time"


class TestFallbackSources:
    def _install(self, monkeypatch, results, calls):
        for name in m.METADATA_PROVIDERS:
            def provider(runtime, artist, title, config, name=name):
                calls.append(name)
                return results.get(name, [])

            monkeypatch.setitem(m.PROVIDER_FUNCTIONS, name, provider)

    def test_unconfigured_free_sources_are_tried_after_configured_miss(
        self, monkeypatch
    ):
        calls = []
        self._install(
            monkeypatch,
            {
                "musicbrainz": [
                    {
                        "title": "One More Time",
                        "artist": "Daft Punk",
                        "source": "musicbrainz",
                    }
                ]
            },
            calls,
        )

        result = m.resolve_metadata(
            "Daft Punk",
            "One More Time",
            make_config(["itunes"]),
            make_runtime(),
        )

        assert result["source"] == "musicbrainz"
        assert calls == ["itunes", "deezer", "musicbrainz"]

    def test_disabled_fallback_is_not_queried(self, monkeypatch):
        calls = []
        self._install(
            monkeypatch,
            {
                "musicbrainz": [
                    {
                        "title": "One More Time",
                        "artist": "Daft Punk",
                        "source": "musicbrainz",
                    }
                ]
            },
            calls,
        )

        result = m.resolve_metadata(
            "Daft Punk",
            "One More Time",
            make_config(["itunes"], disabled=("deezer",)),
            make_runtime(),
        )

        assert result["source"] == "musicbrainz"
        assert calls == ["itunes", "musicbrainz"]

    def test_no_metadata_selection_does_not_use_fallbacks(self, monkeypatch):
        calls = []
        self._install(monkeypatch, {}, calls)

        result = m.resolve_metadata(
            "A",
            "B",
            make_config([], none_selected=True),
            make_runtime(),
        )

        assert result["source"] == "input"
        assert calls == []

    def test_configured_provider_is_not_queried_twice(self, monkeypatch):
        calls = []
        self._install(
            monkeypatch,
            {
                "musicbrainz": [
                    {
                        "title": "One More Time",
                        "artist": "Daft Punk",
                        "source": "musicbrainz",
                    }
                ]
            },
            calls,
        )

        result = m.resolve_metadata(
            "Daft Punk",
            "One More Time",
            make_config(["deezer"]),
            make_runtime(),
        )

        assert result["source"] == "musicbrainz"
        assert calls == ["deezer", "musicbrainz"]

    def test_cli_disable_sources_blocks_fallbacks(self, monkeypatch):
        calls = []
        self._install(monkeypatch, {}, calls)
        config = m.build_source_config(
            make_args(
                metadata_sources="itunes",
                disable_sources="deezer,musicbrainz",
            ),
            {},
        )

        result = m.resolve_metadata("A", "B", config, make_runtime())

        assert result["source"] == "input"
        assert calls == ["itunes"]

    def test_config_disabled_fallback_is_not_queried(self, monkeypatch):
        calls = []
        self._install(monkeypatch, {}, calls)
        config = m.build_source_config(
            make_args(),
            {"deezer_enabled": "false"},
        )

        result = m.resolve_metadata("A", "B", config, make_runtime())

        assert result["source"] == "input"
        assert calls == ["itunes", "musicbrainz"]


class TestRateLimiting:
    def test_independent_provider_intervals(self, monkeypatch):
        now = [0.0]
        sleeps = []

        def fake_sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds

        monkeypatch.setattr(time, "sleep", fake_sleep)
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

        monkeypatch.setattr(time, "sleep", fake_sleep)
        limiter = m.RateLimiter({"deezer": 2.0}, clock=lambda: now[0])

        limiter.wait("deezer")
        limiter.wait("deezer")

        assert sleeps == [pytest.approx(2.0)]

    def test_zero_interval_never_blocks(self, monkeypatch):
        sleeps = []
        monkeypatch.setattr(time, "sleep", sleeps.append)
        limiter = m.RateLimiter({"vocadb": 0.0})

        limiter.wait("vocadb")
        limiter.wait("vocadb")

        assert sleeps == []


class TestRateLimitPolicy:
    def test_itunes_default_interval_keeps_below_twenty_per_minute(self):
        interval = m.PROVIDER_DEFAULTS["itunes"]["min_interval"]

        assert interval == 3.5
        # The Search API allows about 20 calls per minute; 20 * interval
        # must cover a full minute.
        assert interval * 20 >= 60

    def test_itunes_default_interval_is_enforced(self, monkeypatch):
        now = [0.0]
        sleeps = []

        def fake_sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds

        monkeypatch.setattr(time, "sleep", fake_sleep)
        limiter = m.RateLimiter(
            {"itunes": m.PROVIDER_DEFAULTS["itunes"]["min_interval"]},
            clock=lambda: now[0],
        )

        limiter.wait("itunes")
        limiter.wait("itunes")

        assert sleeps == [pytest.approx(3.5)]

    def test_metadata_request_goes_through_provider_limiter(self, monkeypatch):
        runtime = make_runtime()
        waits = []
        monkeypatch.setattr(runtime.limiter, "wait", waits.append)
        runtime.session = FakeSession(
            FakeResponse({"results": []}),
            FakeResponse({"results": []}),
            FakeResponse({"results": []}),
        )

        m.itunes_provider(runtime, "a", "b", make_config(["itunes"]))

        assert waits == ["itunes", "itunes", "itunes"]

    def test_youtube_search_is_not_rate_limited(self, monkeypatch):
        sleeps = []
        monkeypatch.setattr(time, "sleep", sleeps.append)

        class Result:
            stdout = ""

        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: Result())

        assert m.youtube_search("query") == []
        assert sleeps == []

    def test_youtube_download_is_not_rate_limited(self, monkeypatch, tmp_path):
        sleeps = []
        monkeypatch.setattr(time, "sleep", sleeps.append)

        class Result:
            returncode = 1

        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: Result())

        assert m.download_audio("url", tmp_path) is None
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
        runtime = make_runtime(
            FakeSession(
                FakeResponse({"results": []}),
                FakeResponse({"results": []}),
                FakeResponse({"results": []}),
            )
        )
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

        first = m.resolve_metadata("Daft Punk", "One More Time", config, runtime)
        second = m.resolve_metadata(
            "Daft Punk", "One More Time", config, runtime
        )
        assert first["source"] == "itunes"
        assert second["source"] == "itunes"
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

    def test_duration_is_cached(self, tmp_path):
        path = tmp_path / m.CACHE_FILENAME
        cache = m.MetadataCache(path)
        cache.set(
            "A",
            "B",
            "itunes",
            {"title": "B", "artist": "A", "source": "itunes", "duration": 321},
        )

        assert m.MetadataCache(path).get("A", "B", "itunes")["duration"] == 321

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
        ) == "https://img/640x640bb.jpg"

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
            requests,
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
            requests,
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
            requests,
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

        monkeypatch.setattr(requests, "get", fake_get)
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
            m.pipeline,
            "find_youtube_video",
            lambda artist, title, duration=None: calls.append((artist, title)),
        )
        config = make_config([], youtube=False, soundcloud=False, none_selected=True)

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

        assert (ok, reason) == (False, "no music sources enabled")
        assert calls == []

    def test_cli_youtube_disable_leaves_soundcloud_only(self):
        config = m.build_source_config(
            make_args(disable_sources="youtube"),
            {},
        )

        assert config.music_sources == ["soundcloud"]
        assert config.youtube_enabled is False
        assert config.soundcloud_enabled is True

    def test_both_music_sources_disabled_is_rejected(self):
        with pytest.raises(ValueError, match="At least one music source"):
            m.build_source_config(
                make_args(disable_sources="youtube,soundcloud"),
                {},
            )

        with pytest.raises(ValueError, match="At least one music source"):
            m.build_source_config(
                make_args(),
                {
                    "youtube_enabled": "false",
                    "soundcloud_enabled": "false",
                },
            )

    def test_none_metadata_still_uses_youtube(self, monkeypatch, tmp_path):
        import shutil

        from conftest import FIXTURES

        video = {"title": "A - B", "id": "abc"}
        monkeypatch.setattr(m.pipeline, "find_youtube_video", lambda a, t, d=None: video)
        monkeypatch.setattr(
            m.pipeline,
            "download_audio",
            lambda url, temp_dir, fmt, quality=None: shutil.copy(
                FIXTURES / f"silence.{fmt}",
                temp_dir / f"audio.{fmt}",
            ),
        )
        monkeypatch.setattr(
            m.images,
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


class TestMatchBranches:
    def test_artist_similarity_without_candidate(self):
        assert m.artist_similarity("Daft Punk", "") == 0.0

    def test_candidate_without_title_is_rejected(self):
        assert m.select_best_metadata(
            [{"artist": "Daft Punk"}], "Daft Punk", "One More Time", 0.6, 0.8
        ) is None

    def test_candidate_below_overall_threshold_is_rejected(self):
        candidate = {"title": "One More Time", "artist": "Someone Else"}

        assert m.select_best_metadata(
            [candidate], "Daft Punk", "One More Time", 0.99, 0.5
        ) is None

    def test_non_dict_candidate_is_skipped(self):
        scored = m.select_best_metadata(
            ["not a dict", {"title": "One More Time", "artist": "Daft Punk"}],
            "Daft Punk",
            "One More Time",
            0.6,
            0.8,
        )

        assert scored["artist"] == "Daft Punk"


class TestSourceValidation:
    def test_unknown_disable_source_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown source"):
            m.build_source_config(make_args(disable_sources="napster"), {})

    def test_invalid_boolean_is_rejected(self):
        with pytest.raises(ValueError, match="Invalid boolean"):
            m.parse_bool("maybe", "x")

    def test_provider_opt_without_key_is_rejected(self):
        with pytest.raises(ValueError, match="Invalid --provider-opt"):
            m.build_source_config(make_args(provider_opt=["itunes=1"]), {})

    def test_invalid_itunes_country_in_config_is_rejected(self):
        with pytest.raises(ValueError, match="two-letter"):
            m.build_source_config(make_args(), {"itunes_country": "ukraine"})

    def test_provider_opt_disable_removes_provider(self):
        config = m.build_source_config(
            make_args(
                metadata_sources="deezer,itunes",
                provider_opt=["deezer.enabled=false"],
            ),
            {},
        )

        assert config.metadata_sources == ["itunes"]
        assert not config.is_enabled("deezer")


class TestProviderErrorBranches:
    def test_itunes_skips_malformed_items(self):
        session = FakeSession(
            FakeResponse({"results": ["nope", {"trackId": 1}]}),
            FakeResponse({"results": ["nope", {"trackId": 1}]}),
            FakeResponse({"results": ["nope", {"trackId": 1}]}),
        )

        candidates = m.itunes_provider(
            make_runtime(session), "a", "b", make_config(["itunes"])
        )

        assert candidates == []

    def test_deezer_non_dict_response(self):
        runtime = make_runtime(FakeSession(FakeResponse(["nope"])))

        with pytest.raises(m.ProviderError, match="invalid response"):
            m.deezer_provider(runtime, "a", "b", make_config(["deezer"]))

    def test_deezer_data_not_a_list(self):
        runtime = make_runtime(FakeSession(FakeResponse({"data": {}})))

        with pytest.raises(m.ProviderError, match="invalid response"):
            m.deezer_provider(runtime, "a", "b", make_config(["deezer"]))

    def test_deezer_skips_malformed_items(self):
        session = FakeSession(
            FakeResponse({"data": ["nope", {"noTitle": 1}]}),
            FakeResponse({"data": ["nope", {"noTitle": 1}]}),
            FakeResponse({"data": ["nope", {"noTitle": 1}]}),
            FakeResponse({"data": ["nope", {"noTitle": 1}]}),
        )

        candidates = m.deezer_provider(
            make_runtime(session), "a", "b", make_config(["deezer"])
        )

        assert candidates == []

    def test_musicbrainz_invalid_response(self):
        runtime = make_runtime(FakeSession(FakeResponse({"unexpected": 1})))

        with pytest.raises(m.ProviderError, match="invalid response"):
            m.musicbrainz_provider(
                runtime, "a", "b", make_config(["musicbrainz"])
            )

    def test_musicbrainz_skips_malformed_items(self):
        session = FakeSession(
            FakeResponse({"recordings": ["nope", {"id": "x"}]}),
            FakeResponse({"recordings": ["nope", {"id": "x"}]}),
            FakeResponse({"recordings": ["nope", {"id": "x"}]}),
            FakeResponse({"recordings": ["nope", {"id": "x"}]}),
        )

        candidates = m.musicbrainz_provider(
            make_runtime(session), "a", "b", make_config(["musicbrainz"])
        )

        assert candidates == []

    def test_musicbrainz_release_date_from_media(self):
        session = FakeSession(
            FakeResponse(
                {
                    "recordings": [
                        {
                            "id": "rec-1",
                            "title": "One More Time",
                            "artist-credit": [{"name": "Daft Punk"}],
                            "releases": [
                                {
                                    "id": "rel-1",
                                    "title": "Discovery",
                                    "media": [
                                        {
                                            "tracks": [
                                                {
                                                    "first-release-date": "2001"
                                                }
                                            ]
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                }
            ),
            FakeResponse(status_code=404),
        )

        candidates = m.musicbrainz_provider(
            make_runtime(session), "Daft Punk", "One More Time",
            make_config(["musicbrainz"]),
        )

        assert candidates[0]["release_date"] == "2001"

    def test_vocadb_invalid_response(self):
        runtime = make_runtime(FakeSession(FakeResponse({"unexpected": 1})))

        with pytest.raises(m.ProviderError, match="invalid response"):
            m.vocadb_provider(runtime, "a", "b", make_config(["vocadb"]))

    def test_vocadb_skips_malformed_items(self):
        session = FakeSession(
            FakeResponse({"items": ["nope", {"id": 1}]}),
            FakeResponse({"items": ["nope", {"id": 1}]}),
            FakeResponse({"items": ["nope", {"id": 1}]}),
        )

        candidates = m.vocadb_provider(
            make_runtime(session), "a", "b", make_config(["vocadb"])
        )

        assert candidates == []

    def test_vocadb_artist_from_artist_credits(self):
        session = FakeSession(
            FakeResponse(
                {
                    "items": [
                        {
                            "id": 1,
                            "name": "Song",
                            "artists": [{"name": "A"}, {"name": "B"}],
                        }
                    ]
                }
            )
        )

        candidates = m.vocadb_provider(
            make_runtime(session), "A, B", "Song", make_config(["vocadb"])
        )

        assert candidates[0]["artist"] == "A, B"


class TestCoverArtArchiveBranches:
    def test_missing_release_id_returns_none(self):
        assert m.cover_art_archive_url(
            make_runtime(), None, make_config(["musicbrainz"])
        ) is None

    def test_auth_error_is_cached_as_none(self):
        runtime = make_runtime(FakeSession(FakeResponse(status_code=401)))

        assert m.cover_art_archive_url(
            runtime, "rel-1", make_config(["musicbrainz"])
        ) is None
        assert runtime.cover_art_cache["rel-1"] is None

    def test_missing_cover_is_cached_as_none(self):
        runtime = make_runtime(FakeSession(FakeResponse(status_code=404)))

        assert m.cover_art_archive_url(
            runtime, "rel-2", make_config(["musicbrainz"])
        ) is None
        assert runtime.cover_art_cache["rel-2"] is None

    def test_images_not_a_list_returns_none(self):
        runtime = make_runtime(FakeSession(FakeResponse({"images": "x"})))

        assert m.cover_art_archive_url(
            runtime, "rel-3", make_config(["musicbrainz"])
        ) is None

    def test_skips_images_without_url_and_picks_largest(self):
        session = FakeSession(
            FakeResponse(
                {
                    "images": [
                        {"front": True},
                        {"front": True, "image": "small", "width": 10, "height": 10},
                        {"front": True, "image": "big", "width": 100, "height": 100},
                    ]
                }
            )
        )
        runtime = make_runtime(session)

        assert m.cover_art_archive_url(
            runtime, "rel-4", make_config(["musicbrainz"])
        ) == "big"


class TestVocadbUrlHelpers:
    def test_absolute_vocadb_url_variants(self):
        assert m.absolute_vocadb_url(None) is None
        assert m.absolute_vocadb_url("//x/y") == "https://x/y"
        assert (
            m.absolute_vocadb_url("/img/a.jpg")
            == "https://vocadb.net/img/a.jpg"
        )
        assert m.absolute_vocadb_url("https://x/y") == "https://x/y"

    def test_picture_url_from_cover_key(self):
        assert (
            m.vocadb_picture_url({"coverUrl": "/img/c.jpg"})
            == "https://vocadb.net/img/c.jpg"
        )

    def test_picture_url_none_when_absent(self):
        assert m.vocadb_picture_url("x", "y") is None


class TestSpotifyBranches:
    def test_auth_error_detected_from_message(self):
        assert m.is_spotify_auth_error(Exception("HTTP 403 Forbidden"))
        assert not m.is_spotify_auth_error(Exception("boom"))

    def test_init_auth_error(self, monkeypatch):
        def boom(args):
            raise RuntimeError("401 unauthorized")

        monkeypatch.setattr(m.providers.spotify, "get_spotify", boom)

        with pytest.raises(m.ProviderAuthError):
            m.spotify_provider(
                make_runtime(), "a", "b", make_config(["spotify"])
            )

    def test_init_error(self, monkeypatch):
        def boom(args):
            raise RuntimeError("boom")

        monkeypatch.setattr(m.providers.spotify, "get_spotify", boom)

        with pytest.raises(m.ProviderError, match="authentication error"):
            m.spotify_provider(
                make_runtime(), "a", "b", make_config(["spotify"])
            )

    def test_search_auth_error(self, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("403")

        monkeypatch.setattr(m.providers.spotify, "find_spotify_track", boom)
        runtime = make_runtime()
        runtime.spotify_client = object()
        runtime.spotify_initialized = True

        with pytest.raises(m.ProviderAuthError):
            m.spotify_provider(runtime, "a", "b", make_config(["spotify"]))

    def test_search_error(self, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(m.providers.spotify, "find_spotify_track", boom)
        runtime = make_runtime()
        runtime.spotify_client = object()
        runtime.spotify_initialized = True

        with pytest.raises(m.ProviderError, match="search error"):
            m.spotify_provider(runtime, "a", "b", make_config(["spotify"]))

    def test_no_track_returns_empty(self, monkeypatch):
        monkeypatch.setattr(m.providers.spotify, "find_spotify_track", lambda *a, **k: None)
        runtime = make_runtime()
        runtime.spotify_client = object()
        runtime.spotify_initialized = True

        assert m.spotify_provider(
            runtime, "a", "b", make_config(["spotify"])
        ) == []

    def test_candidate_includes_duration(self, monkeypatch):
        track = {
            "id": "t1",
            "name": "Song",
            "duration_ms": 214000,
            "artists": [{"name": "Artist"}],
            "album": {"name": "Album", "artists": [], "images": []},
        }
        monkeypatch.setattr(
            m.providers.spotify, "find_spotify_track", lambda *a, **k: track
        )
        runtime = make_runtime()
        runtime.spotify_client = object()
        runtime.spotify_initialized = True

        candidates = m.spotify_provider(
            runtime, "Artist", "Song", make_config(["spotify"])
        )

        assert candidates[0]["duration"] == 214


class TestCacheBranches:
    def test_non_dict_json_is_handled(self, tmp_path):
        path = tmp_path / m.CACHE_FILENAME
        path.write_text("[]", encoding="utf-8")

        assert m.MetadataCache(path).entries == {}

    def test_save_oserror_is_ignored(self, monkeypatch, tmp_path):
        cache = m.MetadataCache(tmp_path / m.CACHE_FILENAME)

        def boom(self, *args, **kwargs):
            raise OSError("nope")

        monkeypatch.setattr(Path, "write_text", boom)

        assert cache.set("A", "B", "itunes", {"title": "B"}) is True

    def test_unparsable_score_does_not_block_update(self, tmp_path):
        cache = m.MetadataCache(tmp_path / m.CACHE_FILENAME)
        cache.set("A", "B", "itunes", {"title": "B", "score": "n/a"})

        assert cache.set(
            "A", "B", "itunes", {"title": "B", "score": 0.5}
        ) is True
        assert cache.get("A", "B", "itunes")["score"] == 0.5


class TestProcessSongDefaults:
    def test_builds_default_config_when_only_runtime_is_given(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(
            m.pipeline,
            "resolve_metadata",
            lambda artist, title, config, runtime: m.fallback_metadata(
                artist, title
            ),
        )
        monkeypatch.setattr(m.pipeline, "find_youtube_video", lambda a, t, d=None: None)

        ok, reason = m.process_song(
            None,
            "A",
            "B",
            tmp_path,
            False,
            "m4a",
            source_config=None,
            runtime=make_runtime(),
        )

        assert (ok, reason) == (False, "no YouTube result")


class TestConfigPathErrors:
    def test_config_path_that_is_a_directory_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="not a file"):
            m.load_config(tmp_path)


class TestSoundcloudModes:
    def test_defaults(self):
        config = m.build_source_config(make_args(), {})

        assert config.soundcloud_trigger == "age"
        assert config.soundcloud_ambiguous == "skip"

    def test_trigger_and_ambiguity_from_cli(self):
        config = m.build_source_config(
            make_args(
                soundcloud_trigger="any",
                soundcloud_ambiguous="best",
            ),
            {},
        )

        assert config.soundcloud_trigger == "any"
        assert config.soundcloud_ambiguous == "best"

    def test_trigger_and_ambiguity_from_config(self):
        config = m.build_source_config(
            make_args(),
            {
                "soundcloud_trigger": "age-or-missing",
                "soundcloud_ambiguous": "best",
            },
        )

        assert config.soundcloud_trigger == "age-or-missing"
        assert config.soundcloud_ambiguous == "best"

    def test_invalid_trigger_is_rejected(self):
        with pytest.raises(ValueError):
            m.build_source_config(
                make_args(),
                {"soundcloud_trigger": "always"},
            )

    def test_invalid_ambiguity_is_rejected(self):
        with pytest.raises(ValueError):
            m.build_source_config(
                make_args(),
                {"soundcloud_ambiguous": "random"},
            )
