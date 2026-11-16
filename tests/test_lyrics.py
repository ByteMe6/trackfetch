import argparse
import sys

import pytest
from mutagen.id3 import COMM, ID3, TCOM, TIT2, USLT

import trackfetch as m

CYRILLIC_LYRICS = "Привет, мир!\nВторая строка — с тире и «кавычками»."
UNICODE_LYRICS = "Hello — “world”!\n第二行 🎵 & <special>"
SYNCED_LRC = """[ar:Artist]
[00:01.50]First line
[00:03.000]Вторая строка
[00:04.25]Third line
"""


def make_args(**overrides):
    values = {
        "metadata_sources": None,
        "disable_sources": None,
        "provider_opt": None,
        "match_threshold": None,
        "title_threshold": None,
        "lyrics_enabled": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def make_mp3(path, payload=b"\x00" * 64):
    path.write_bytes(payload)
    return path


def audio_payload(path):
    """Return the bytes after the leading ID3v2 tag."""
    data = path.read_bytes()
    assert data[:3] == b"ID3"
    size = (
        (data[6] << 21)
        | (data[7] << 14)
        | (data[8] << 7)
        | data[9]
    )
    return data[10 + size:]


class FakeResponse:
    def __init__(self, payload=None, status_code=200, json_error=None):
        self.payload = payload
        self.status_code = status_code
        self.json_error = json_error

    def json(self):
        if self.json_error is not None:
            raise self.json_error
        return self.payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self.response


def make_runtime(response):
    session = FakeSession(response)
    runtime = m.MetadataRuntime(
        session=session,
        limiter=m.RateLimiter({"lrclib": 0.0}),
    )
    return runtime, session


class TestParseSyncedLyrics:
    def test_parses_fractions_and_metadata(self):
        assert m.parse_synced_lyrics(SYNCED_LRC) == [
            ("First line", 1500),
            ("Вторая строка", 3000),
            ("Third line", 4250),
        ]

    def test_one_digit_fraction_means_tenths(self):
        assert m.parse_synced_lyrics("[00:01.5]Line") == [("Line", 1500)]

    def test_multiple_timestamps_for_one_line(self):
        assert m.parse_synced_lyrics("[00:01.00][00:02.00]Chorus") == [
            ("Chorus", 1000),
            ("Chorus", 2000),
        ]

    def test_sorts_out_of_order_timestamps(self):
        assert m.parse_synced_lyrics(
            "[00:05.00]Later\n[00:01.00]Earlier\n"
        ) == [("Earlier", 1000), ("Later", 5000)]

    def test_skips_blank_lines(self):
        assert m.parse_synced_lyrics("[00:01.00]   ") == []


class TestSelectLyrics:
    def test_selects_best_matching_result(self):
        results = [
            {
                "trackName": "Another Song",
                "artistName": "Artist",
                "plainLyrics": "wrong",
            },
            {
                "trackName": "Song",
                "artistName": "Artist",
                "plainLyrics": "right",
                "syncedLyrics": "[00:01.00]right",
            },
        ]

        lyrics = m.select_lyrics(results, "Artist", "Song")

        assert lyrics["plain"] == "right"
        assert lyrics["synced"] == "[00:01.00]right"

    def test_instrumental_is_ignored(self):
        results = [
            {
                "trackName": "Song",
                "artistName": "Artist",
                "instrumental": True,
                "plainLyrics": "should not be used",
            }
        ]

        assert m.select_lyrics(results, "Artist", "Song") is None

    def test_plain_only_has_no_synced_text(self):
        results = [
            {
                "trackName": "Song",
                "artistName": "Artist",
                "plainLyrics": "Words",
            }
        ]

        lyrics = m.select_lyrics(results, "Artist", "Song")

        assert lyrics["plain"] == "Words"
        assert lyrics["synced"] is None

    def test_timed_only_derives_plain_text(self):
        results = [
            {
                "trackName": "Song",
                "artistName": "Artist",
                "syncedLyrics": "[00:01.00]One\n[00:02.00]Two",
            }
        ]

        lyrics = m.select_lyrics(results, "Artist", "Song")

        assert lyrics["plain"] == "One\nTwo"
        assert lyrics["synced"].startswith("[00:01.00]")

    def test_no_matching_result(self):
        results = [
            {
                "trackName": "Unrelated",
                "artistName": "Someone",
                "plainLyrics": "Words",
            }
        ]

        assert m.select_lyrics(results, "Artist", "Song") is None


class TestFetchLyrics:
    def test_returns_matching_lyrics(self):
        response = FakeResponse(
            [
                {
                    "trackName": "Song",
                    "artistName": "Artist",
                    "plainLyrics": "Words",
                    "syncedLyrics": "[00:01.00]Words",
                }
            ]
        )
        runtime, session = make_runtime(response)

        lyrics = m.fetch_lyrics("Artist", "Song", runtime)

        assert lyrics["plain"] == "Words"
        assert session.calls[0]["params"] == {
            "artist_name": "Artist",
            "track_name": "Song",
        }
        assert session.calls[0]["url"] == m.LRCLIB_SEARCH_URL

    def test_404_means_no_lyrics(self):
        runtime, _ = make_runtime(FakeResponse(status_code=404))

        assert m.fetch_lyrics("Artist", "Song", runtime=runtime) is None

    def test_http_error_raises_provider_error(self):
        runtime, _ = make_runtime(FakeResponse(status_code=500))

        with pytest.raises(m.ProviderError, match="HTTP 500"):
            m.fetch_lyrics("Artist", "Song", runtime=runtime)

    def test_invalid_json_raises_provider_error(self):
        runtime, _ = make_runtime(
            FakeResponse(json_error=ValueError("bad json"))
        )

        with pytest.raises(m.ProviderError, match="invalid JSON"):
            m.fetch_lyrics("Artist", "Song", runtime=runtime)


class TestMp3Lyrics:
    def test_writes_and_reads_uslt(self, tmp_path):
        mp3 = make_mp3(tmp_path / "song.mp3")

        m.add_mp3_metadata(
            mp3,
            tmp_path / "missing.jpg",
            m.fallback_metadata("Artist", "Song"),
            {"plain": CYRILLIC_LYRICS},
        )

        tags = ID3(mp3)
        assert tags.getall("USLT")[0].text == CYRILLIC_LYRICS
        assert not tags.getall("SYLT")

    def test_writes_and_reads_sylt(self, tmp_path):
        mp3 = make_mp3(tmp_path / "song.mp3")

        m.add_mp3_metadata(
            mp3,
            tmp_path / "missing.jpg",
            m.fallback_metadata("Artist", "Song"),
            {"plain": CYRILLIC_LYRICS, "synced": SYNCED_LRC},
        )

        sylt = ID3(mp3).getall("SYLT")[0]
        assert sylt.format == 2
        assert sylt.type == 1
        assert sylt.text == [
            ("First line", 1500),
            ("Вторая строка", 3000),
            ("Third line", 4250),
        ]

    def test_writes_both_frames_when_timed_lyrics_exist(self, tmp_path):
        mp3 = make_mp3(tmp_path / "song.mp3")

        m.add_mp3_metadata(
            mp3,
            tmp_path / "missing.jpg",
            m.fallback_metadata("Artist", "Song"),
            {"plain": CYRILLIC_LYRICS, "synced": SYNCED_LRC},
        )

        tags = ID3(mp3)
        assert tags.getall("USLT")[0].text == CYRILLIC_LYRICS
        assert tags.getall("SYLT")[0].text

    def test_unicode_and_special_characters_roundtrip(self, tmp_path):
        mp3 = make_mp3(tmp_path / "song.mp3")
        first, second = UNICODE_LYRICS.splitlines()

        m.add_mp3_metadata(
            mp3,
            tmp_path / "missing.jpg",
            m.fallback_metadata("Artist", "Song"),
            {
                "plain": UNICODE_LYRICS,
                "synced": f"[00:01.00]{first}\n[00:02.00]{second}",
            },
        )

        tags = ID3(mp3)
        assert tags.getall("USLT")[0].text == UNICODE_LYRICS
        assert tags.getall("SYLT")[0].text == [
            (first, 1000),
            (second, 2000),
        ]

    def test_no_lyrics_adds_no_empty_frames(self, tmp_path):
        mp3 = make_mp3(tmp_path / "song.mp3")

        m.add_mp3_metadata(
            mp3,
            tmp_path / "missing.jpg",
            m.fallback_metadata("Artist", "Song"),
            None,
        )

        tags = ID3(mp3)
        assert not tags.getall("USLT")
        assert not tags.getall("SYLT")

    def test_empty_lyrics_adds_no_frames(self, tmp_path):
        mp3 = make_mp3(tmp_path / "song.mp3")

        m.add_mp3_metadata(
            mp3,
            tmp_path / "missing.jpg",
            m.fallback_metadata("Artist", "Song"),
            {"plain": "   ", "synced": "[00:01.00]   "},
        )

        tags = ID3(mp3)
        assert not tags.getall("USLT")
        assert not tags.getall("SYLT")

    def test_existing_lyrics_are_kept_when_none_found(self, tmp_path):
        mp3 = make_mp3(tmp_path / "song.mp3")
        old = ID3()
        old.add(USLT(encoding=3, lang="eng", desc="", text="Old words"))
        old.save(mp3)

        m.add_mp3_metadata(
            mp3,
            tmp_path / "missing.jpg",
            m.fallback_metadata("Artist", "Song"),
            None,
        )

        tags = ID3(mp3)
        assert tags.getall("USLT")[0].text == "Old words"
        assert not tags.getall("SYLT")

    def test_rewrites_without_duplicates(self, tmp_path):
        mp3 = make_mp3(tmp_path / "song.mp3")
        metadata = m.fallback_metadata("Artist", "Song")

        m.add_mp3_metadata(
            mp3,
            tmp_path / "missing.jpg",
            metadata,
            {"plain": "Old words", "synced": "[00:01.00]Old words"},
        )
        m.add_mp3_metadata(
            mp3,
            tmp_path / "missing.jpg",
            metadata,
            {"plain": "New words", "synced": "[00:02.00]New words"},
        )

        tags = ID3(mp3)
        assert len(tags.getall("USLT")) == 1
        assert len(tags.getall("SYLT")) == 1
        assert tags.getall("USLT")[0].text == "New words"
        assert tags.getall("SYLT")[0].text == [("New words", 2000)]

    def test_preserves_existing_tags_and_cover(self, tmp_path):
        mp3 = make_mp3(tmp_path / "song.mp3")
        cover = tmp_path / "cover.jpg"
        cover.write_bytes(b"\xff\xd8\xff\xe0jpeg")

        old = ID3()
        old.add(TCOM(encoding=3, text="Composer"))
        old.add(COMM(encoding=3, lang="eng", desc="", text="A comment"))
        old.add(TIT2(encoding=3, text="Old title"))
        old.save(mp3)

        m.add_mp3_metadata(
            mp3,
            cover,
            m.fallback_metadata("Artist", "Song"),
            {"plain": "Words"},
        )

        tags = ID3(mp3)
        assert tags.getall("TCOM")[0].text == ["Composer"]
        assert tags.getall("COMM")[0].text == ["A comment"]
        assert tags.getall("TIT2")[0].text == ["Song"]
        assert tags.getall("APIC")[0].data == cover.read_bytes()
        assert tags.getall("USLT")[0].text == "Words"

    def test_does_not_change_audio_payload(self, tmp_path):
        payload = bytes(range(256)) * 4
        mp3 = make_mp3(tmp_path / "song.mp3", payload)

        m.add_mp3_metadata(
            mp3,
            tmp_path / "missing.jpg",
            m.fallback_metadata("Artist", "Song"),
            {"plain": "Words", "synced": "[00:01.00]Words"},
        )

        assert audio_payload(mp3) == payload


class TestLyricsSettings:
    def test_enabled_by_default(self):
        assert m.build_source_config(make_args(), {}).lyrics_enabled is True

    def test_config_can_disable(self):
        config = m.build_source_config(
            make_args(),
            {"lyrics_enabled": "false"},
        )

        assert config.lyrics_enabled is False

    def test_config_can_enable(self):
        config = m.build_source_config(
            make_args(),
            {"lyrics_enabled": "true"},
        )

        assert config.lyrics_enabled is True

    def test_cli_enable_wins_over_config_disable(self):
        config = m.build_source_config(
            make_args(lyrics_enabled=True),
            {"lyrics_enabled": "false"},
        )

        assert config.lyrics_enabled is True

    def test_cli_disable_wins_over_config_enable(self):
        config = m.build_source_config(
            make_args(lyrics_enabled=False),
            {"lyrics_enabled": "true"},
        )

        assert config.lyrics_enabled is False

    def test_invalid_config_value_is_rejected(self):
        with pytest.raises(ValueError, match="lyrics_enabled"):
            m.build_source_config(
                make_args(),
                {"lyrics_enabled": "maybe"},
            )


class TestLyricsCli:
    def run_cli(self, monkeypatch, *args):
        monkeypatch.setattr(sys, "argv", ["trackfetch", *map(str, args)])
        m.main()

    def test_no_lyrics_is_shown_by_list_sources(
        self, monkeypatch, tmp_path, capsys
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.delenv("TRACKFETCH_CONFIG", raising=False)
        monkeypatch.setattr(
            m.Path, "home", classmethod(lambda cls: tmp_path / "home")
        )

        self.run_cli(monkeypatch, "--list-sources", "--no-lyrics")

        assert "Lyrics embedding: disabled" in capsys.readouterr().out

    def test_default_is_enabled_in_list_sources(
        self, monkeypatch, tmp_path, capsys
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.delenv("TRACKFETCH_CONFIG", raising=False)
        monkeypatch.setattr(
            m.Path, "home", classmethod(lambda cls: tmp_path / "home")
        )

        self.run_cli(monkeypatch, "--list-sources")

        output = capsys.readouterr().out
        assert "Lyrics embedding: enabled" in output

    def test_config_disables_lyrics(self, monkeypatch, tmp_path, capsys):
        config = tmp_path / "cfg.ini"
        config.write_text(
            "[trackfetch]\nlyrics_enabled = false\n",
            encoding="utf-8",
        )

        self.run_cli(
            monkeypatch,
            "--list-sources",
            "--config",
            config,
        )

        assert "Lyrics embedding: disabled" in capsys.readouterr().out

    def test_cli_enables_lyrics_over_disabled_config(
        self, monkeypatch, tmp_path, capsys
    ):
        config = tmp_path / "cfg.ini"
        config.write_text(
            "[trackfetch]\nlyrics_enabled = false\n",
            encoding="utf-8",
        )

        self.run_cli(
            monkeypatch,
            "--list-sources",
            "--config",
            config,
            "--lyrics",
        )

        assert "Lyrics embedding: enabled" in capsys.readouterr().out

    def test_invalid_config_value_exits(self, monkeypatch, tmp_path, capsys):
        config = tmp_path / "cfg.ini"
        config.write_text(
            "[trackfetch]\nlyrics_enabled = maybe\n",
            encoding="utf-8",
        )

        with pytest.raises(SystemExit) as exc:
            self.run_cli(
                monkeypatch,
                "--list-sources",
                "--config",
                config,
            )

        assert exc.value.code == 1
        assert "Invalid value for 'lyrics_enabled'" in capsys.readouterr().out
