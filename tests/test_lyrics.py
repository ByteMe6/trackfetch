import argparse
import shutil
import sys
from pathlib import Path

import pytest
from conftest import FIXTURES
from mutagen.id3 import COMM, ID3, TCOM, TIT2, USLT
from mutagen.mp4 import MP4
from mutagen.oggopus import OggOpus

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
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})

        if len(self.responses) == 1:
            return self.responses[0]

        return self.responses.pop(0)


def make_runtime(*responses):
    session = FakeSession(*responses)
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

    def test_empty_fraction_is_zero(self):
        assert m.lrc_fraction_to_ms("") == 0

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

    def test_near_duration_is_preferred(self):
        results = [
            {
                "trackName": "Song",
                "artistName": "Artist",
                "duration": 328,
                "plainLyrics": "near",
            },
            {
                "trackName": "Song",
                "artistName": "Artist",
                "duration": 400,
                "plainLyrics": "far",
            },
        ]

        lyrics = m.select_lyrics(results, "Artist", "Song", duration=320)

        assert lyrics["plain"] == "near"

    def test_invalid_durations_are_ignored(self):
        results = [
            {
                "trackName": "Song",
                "artistName": "Artist",
                "duration": "nope",
                "plainLyrics": "bad item",
            },
            {
                "trackName": "Song",
                "artistName": "Artist",
                "duration": 320,
                "plainLyrics": "good item",
            },
        ]

        lyrics = m.select_lyrics(results, "Artist", "Song", duration=320)

        assert lyrics["plain"] == "good item"

    def test_invalid_target_duration_is_ignored(self):
        results = [
            {
                "trackName": "Song",
                "artistName": "Artist",
                "duration": 320,
                "plainLyrics": "Words",
            }
        ]

        lyrics = m.select_lyrics(results, "Artist", "Song", duration="bad")

        assert lyrics["plain"] == "Words"

    def test_synced_version_wins_a_tie(self):
        results = [
            {
                "trackName": "Song",
                "artistName": "Artist",
                "plainLyrics": "plain",
            },
            {
                "trackName": "Song",
                "artistName": "Artist",
                "plainLyrics": "timed",
                "syncedLyrics": "[00:01.00]timed",
            },
        ]

        lyrics = m.select_lyrics(results, "Artist", "Song")

        assert lyrics["plain"] == "timed"
        assert lyrics["synced"]

    def test_empty_result_is_ignored(self):
        results = [
            {
                "trackName": "Song",
                "artistName": "Artist",
                "plainLyrics": "   ",
                "syncedLyrics": "",
            }
        ]

        assert m.select_lyrics(results, "Artist", "Song") is None


class TestSplitLyrics:
    def test_timed_only_lyrics_derive_plain_text(self):
        plain, synced_entries = m.split_lyrics(
            {"synced": "[00:01.00]One\n[00:02.00]Two"}
        )

        assert plain == "One\nTwo"
        assert synced_entries == [("One", 1000), ("Two", 2000)]

    def test_existing_plain_text_is_kept(self):
        plain, synced_entries = m.split_lyrics(
            {"plain": "Words", "synced": "[00:01.00]Words"}
        )

        assert plain == "Words"
        assert synced_entries == [("Words", 1000)]


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
        assert session.calls[0]["params"] == {"track_name": "Song"}
        assert session.calls[0]["url"] == m.LRCLIB_SEARCH_URL

    def test_queries_are_progressive_and_prefer_strict_title(self):
        assert m.lyrics_queries("КриК", "гимн рок н рола") == [
            {"track_name": "гимн рок н рола"},
            {"q": "КриК гимн рок н рола"},
            {"q": "гимн рок н рола КриК"},
            {"q": "гимн рок н рола"},
            {"q": "гимн рок н"},
            {"q": "гимн рок"},
        ]

    def test_empty_title_skips_empty_track_name_query(self):
        assert {"track_name": ""} not in m.lyrics_queries("Artist", "")
        assert m.lyrics_queries("Artist", "") == [{"q": "Artist"}]

    def test_stops_after_synced_result(self):
        synced = FakeResponse(
            [
                {
                    "trackName": "Song",
                    "artistName": "Artist",
                    "plainLyrics": "Words",
                    "syncedLyrics": "[00:01.00]Words",
                }
            ]
        )
        runtime, session = make_runtime(synced)

        lyrics = m.fetch_lyrics("Artist", "Song", runtime)

        assert lyrics["synced"]
        assert len(session.calls) == 1

    def test_relaxed_query_finds_typo_title(self):
        empty = FakeResponse([])
        found = FakeResponse(
            [
                {
                    "trackName": "Гимн рок-н-ролла",
                    "artistName": "КриК",
                    "plainLyrics": "Строки",
                    "syncedLyrics": "[00:01.00]Строки",
                }
            ]
        )
        runtime, session = make_runtime(empty, empty, empty, empty, found)

        lyrics = m.fetch_lyrics("КриК", "гимн рок н рола", runtime)

        assert lyrics["plain"] == "Строки"
        assert session.calls[-1]["params"] == {"q": "гимн рок н"}

    def test_plain_result_continues_looking_for_synced(self):
        plain = FakeResponse(
            [
                {
                    "trackName": "Song",
                    "artistName": "Artist",
                    "plainLyrics": "Words",
                }
            ]
        )
        synced = FakeResponse(
            [
                {
                    "trackName": "Song",
                    "artistName": "Artist",
                    "plainLyrics": "Words",
                    "syncedLyrics": "[00:01.00]Words",
                }
            ]
        )
        runtime, session = make_runtime(plain, synced)

        lyrics = m.fetch_lyrics("Artist", "Song", runtime)

        assert lyrics["synced"]
        assert len(session.calls) == 2

    def test_duration_prefers_closest_result(self):
        results = FakeResponse(
            [
                {
                    "trackName": "Song",
                    "artistName": "Artist",
                    "duration": 200,
                    "plainLyrics": "wrong length",
                },
                {
                    "trackName": "Song",
                    "artistName": "Artist",
                    "duration": 321,
                    "plainLyrics": "right length",
                },
            ]
        )
        runtime, _ = make_runtime(results)

        lyrics = m.fetch_lyrics("Artist", "Song", runtime, duration=320)

        assert lyrics["plain"] == "right length"

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

    def test_data_wrapper_is_unwrapped(self):
        runtime, _ = make_runtime(
            FakeResponse(
                {
                    "data": [
                        {
                            "trackName": "Song",
                            "artistName": "Artist",
                            "plainLyrics": "Words",
                        }
                    ]
                }
            )
        )

        assert m.fetch_lyrics("Artist", "Song", runtime)["plain"] == "Words"

    def test_without_runtime_uses_requests(self, monkeypatch):
        calls = []
        response = FakeResponse(
            [
                {
                    "trackName": "Song",
                    "artistName": "Artist",
                    "plainLyrics": "Words",
                }
            ]
        )

        def fake_get(url, **kwargs):
            calls.append(url)
            return response

        monkeypatch.setattr(m.lyrics.requests, "get", fake_get)

        assert m.fetch_lyrics("Artist", "Song")["plain"] == "Words"
        assert calls[0] == m.LRCLIB_SEARCH_URL

    def test_transport_error_without_runtime(self, monkeypatch):
        def fake_get(url, **kwargs):
            raise m.lyrics.requests.ConnectionError("offline")

        monkeypatch.setattr(m.lyrics.requests, "get", fake_get)

        with pytest.raises(m.ProviderError, match="lyrics request failed"):
            m.fetch_lyrics("Artist", "Song")


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
        assert tags.getall("USLT")[0].text == SYNCED_LRC.strip()
        assert tags.getall("SYLT")[0].text

    @pytest.mark.parametrize("lyrics_type", ["sidecar", "plain"])
    def test_timed_modes_keep_plain_uslt(self, tmp_path, lyrics_type):
        mp3 = make_mp3(tmp_path / "song.mp3")

        m.add_mp3_metadata(
            mp3,
            tmp_path / "missing.jpg",
            m.fallback_metadata("Artist", "Song"),
            {"plain": CYRILLIC_LYRICS, "synced": SYNCED_LRC},
            lyrics_type,
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
        assert tags.getall("USLT")[0].text == f"[00:01.00]{first}\n[00:02.00]{second}"
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
        assert tags.getall("USLT")[0].text == "[00:02.00]New words"
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


class TestContainerLyrics:
    """M4A and Opus use their own standard lyrics tags, not ID3 frames."""

    LYRICS = {
        "plain": CYRILLIC_LYRICS,
        "synced": SYNCED_LRC,
    }

    def test_m4a_writes_plain_and_synced(self, tmp_path):
        audio = tmp_path / "song.m4a"
        shutil.copy(FIXTURES / "silence.m4a", audio)

        m.add_m4a_metadata(
            audio,
            tmp_path / "missing.jpg",
            m.fallback_metadata("Artist", "Song"),
            self.LYRICS,
        )

        tags = MP4(audio)
        assert tags["\xa9lyr"] == [SYNCED_LRC.strip()]
        assert bytes(tags[m.M4A_SYNCED_LYRICS_KEY][0]).decode("utf-8") == SYNCED_LRC.strip()

    @pytest.mark.parametrize("lyrics_type", ["sidecar", "plain"])
    def test_m4a_timed_modes_keep_plain_text(self, tmp_path, lyrics_type):
        audio = tmp_path / "song.m4a"
        shutil.copy(FIXTURES / "silence.m4a", audio)

        m.add_m4a_metadata(
            audio,
            tmp_path / "missing.jpg",
            m.fallback_metadata("Artist", "Song"),
            self.LYRICS,
            lyrics_type,
        )

        tags = MP4(audio)
        assert tags["\xa9lyr"] == [CYRILLIC_LYRICS]
        assert bytes(tags[m.M4A_SYNCED_LYRICS_KEY][0]).decode("utf-8") == SYNCED_LRC.strip()

    def test_m4a_plain_only_has_no_synced_atom(self, tmp_path):
        audio = tmp_path / "song.m4a"
        shutil.copy(FIXTURES / "silence.m4a", audio)

        m.add_m4a_metadata(
            audio,
            tmp_path / "missing.jpg",
            m.fallback_metadata("Artist", "Song"),
            {"plain": CYRILLIC_LYRICS},
        )

        tags = MP4(audio)
        assert tags["\xa9lyr"] == [CYRILLIC_LYRICS]
        assert m.M4A_SYNCED_LYRICS_KEY not in tags

    def test_m4a_rewrites_without_duplicates(self, tmp_path):
        audio = tmp_path / "song.m4a"
        shutil.copy(FIXTURES / "silence.m4a", audio)
        metadata = m.fallback_metadata("Artist", "Song")

        m.add_m4a_metadata(audio, tmp_path / "missing.jpg", metadata, self.LYRICS)
        m.add_m4a_metadata(
            audio,
            tmp_path / "missing.jpg",
            metadata,
            {"plain": "New words", "synced": "[00:02.00]New words"},
        )

        tags = MP4(audio)
        assert tags["\xa9lyr"] == ["[00:02.00]New words"]
        assert bytes(tags[m.M4A_SYNCED_LYRICS_KEY][0]).decode("utf-8") == "[00:02.00]New words"

    def test_m4a_keeps_existing_lyrics_when_none_found(self, tmp_path):
        audio = tmp_path / "song.m4a"
        shutil.copy(FIXTURES / "silence.m4a", audio)
        tags = MP4(audio)
        tags["\xa9lyr"] = ["Old words"]
        tags.save()

        m.add_m4a_metadata(
            audio,
            tmp_path / "missing.jpg",
            m.fallback_metadata("Artist", "Song"),
            None,
        )

        assert MP4(audio)["\xa9lyr"] == ["Old words"]

    def test_opus_writes_plain_and_synced(self, tmp_path):
        audio = tmp_path / "song.opus"
        shutil.copy(FIXTURES / "silence.opus", audio)

        m.add_opus_metadata(
            audio,
            tmp_path / "missing.jpg",
            m.fallback_metadata("Artist", "Song"),
            self.LYRICS,
        )

        tags = OggOpus(audio)
        assert tags["LYRICS"] == [SYNCED_LRC.strip()]
        assert tags["SYNCEDLYRICS"] == [SYNCED_LRC.strip()]

    @pytest.mark.parametrize("lyrics_type", ["sidecar", "plain"])
    def test_opus_timed_modes_keep_plain_text(self, tmp_path, lyrics_type):
        audio = tmp_path / "song.opus"
        shutil.copy(FIXTURES / "silence.opus", audio)

        m.add_opus_metadata(
            audio,
            tmp_path / "missing.jpg",
            m.fallback_metadata("Artist", "Song"),
            self.LYRICS,
            lyrics_type,
        )

        tags = OggOpus(audio)
        assert tags["LYRICS"] == [CYRILLIC_LYRICS]
        assert tags["SYNCEDLYRICS"] == [SYNCED_LRC.strip()]

    def test_opus_plain_only_has_no_synced_comment(self, tmp_path):
        audio = tmp_path / "song.opus"
        shutil.copy(FIXTURES / "silence.opus", audio)

        m.add_opus_metadata(
            audio,
            tmp_path / "missing.jpg",
            m.fallback_metadata("Artist", "Song"),
            {"plain": CYRILLIC_LYRICS},
        )

        tags = OggOpus(audio)
        assert tags["LYRICS"] == [CYRILLIC_LYRICS]
        assert "SYNCEDLYRICS" not in tags

    def test_opus_rewrites_without_duplicates(self, tmp_path):
        audio = tmp_path / "song.opus"
        shutil.copy(FIXTURES / "silence.opus", audio)
        metadata = m.fallback_metadata("Artist", "Song")

        m.add_opus_metadata(audio, tmp_path / "missing.jpg", metadata, self.LYRICS)
        m.add_opus_metadata(
            audio,
            tmp_path / "missing.jpg",
            metadata,
            {"plain": "New words", "synced": "[00:02.00]New words"},
        )

        tags = OggOpus(audio)
        assert tags["LYRICS"] == ["[00:02.00]New words"]
        assert tags["SYNCEDLYRICS"] == ["[00:02.00]New words"]

    def test_opus_keeps_existing_lyrics_when_none_found(self, tmp_path):
        audio = tmp_path / "song.opus"
        shutil.copy(FIXTURES / "silence.opus", audio)
        tags = OggOpus(audio)
        tags["LYRICS"] = "Old words"
        tags.save()

        m.add_opus_metadata(
            audio,
            tmp_path / "missing.jpg",
            m.fallback_metadata("Artist", "Song"),
            None,
        )

        assert OggOpus(audio)["LYRICS"] == ["Old words"]

    def test_empty_lyrics_add_no_tags(self, tmp_path):
        for name, writer in (
            ("m4a", m.add_m4a_metadata),
            ("opus", m.add_opus_metadata),
        ):
            audio = tmp_path / f"song.{name}"
            shutil.copy(FIXTURES / f"silence.{name}", audio)

            writer(
                audio,
                tmp_path / "missing.jpg",
                m.fallback_metadata("Artist", "Song"),
                {"plain": "   ", "synced": "[00:01.00]   "},
            )

        assert "\xa9lyr" not in MP4(tmp_path / "song.m4a")
        assert "LYRICS" not in OggOpus(tmp_path / "song.opus")


class TestLrcSidecar:
    def test_sidecar_contains_lrc(self, tmp_path):
        audio = tmp_path / "Artist - Song.mp3"
        audio.write_bytes(b"audio")

        path = m.write_lrc_sidecar(
            audio,
            {"plain": CYRILLIC_LYRICS, "synced": SYNCED_LRC},
            "sidecar",
        )

        assert path == tmp_path / "Artist - Song.lrc"
        assert path.read_text(encoding="utf-8") == SYNCED_LRC.strip() + "\n"

    @pytest.mark.parametrize("lyrics_type", ["inline", "plain"])
    def test_other_modes_write_nothing(self, tmp_path, lyrics_type):
        audio = tmp_path / "song.mp3"
        audio.write_bytes(b"audio")

        assert m.write_lrc_sidecar(
            audio,
            {"synced": SYNCED_LRC},
            lyrics_type,
        ) is None
        assert not (tmp_path / "song.lrc").exists()

    def test_sidecar_without_timed_lyrics_removes_stale_file(self, tmp_path):
        audio = tmp_path / "song.mp3"
        audio.write_bytes(b"audio")
        stale = tmp_path / "song.lrc"
        stale.write_text("[00:01.00]Old", encoding="utf-8")

        assert m.write_lrc_sidecar(
            audio,
            {"plain": CYRILLIC_LYRICS},
            "sidecar",
        ) is None
        assert not stale.exists()


class TestLyricsSettings:
    def test_enabled_by_default(self):
        assert m.build_source_config(make_args(), {}).lyrics_enabled is True

    def test_type_defaults_to_inline(self):
        assert m.build_source_config(make_args(), {}).lyrics_type == "inline"

    def test_config_can_set_type(self):
        config = m.build_source_config(
            make_args(),
            {"lyrics_type": "sidecar"},
        )

        assert config.lyrics_type == "sidecar"

    def test_cli_type_wins_over_config(self):
        config = m.build_source_config(
            make_args(lyrics_type="plain"),
            {"lyrics_type": "sidecar"},
        )

        assert config.lyrics_type == "plain"

    def test_invalid_config_type_is_rejected(self):
        with pytest.raises(ValueError, match="lyrics_type"):
            m.build_source_config(
                make_args(),
                {"lyrics_type": "karaoke"},
            )

    def test_invalid_cli_type_is_rejected(self):
        with pytest.raises(ValueError, match="lyrics_type"):
            m.build_source_config(
                make_args(lyrics_type="karaoke"),
                {},
            )

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
            Path, "home", classmethod(lambda cls: tmp_path / "home")
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
            Path, "home", classmethod(lambda cls: tmp_path / "home")
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


class TestCacheSettings:
    def test_enabled_by_default(self):
        assert m.build_source_config(make_args(), {}).cache_enabled is True

    def test_config_can_disable(self):
        config = m.build_source_config(make_args(), {"cache_enabled": "false"})

        assert config.cache_enabled is False

    def test_cli_disable_wins_over_config_enable(self):
        config = m.build_source_config(
            make_args(cache_enabled=False),
            {"cache_enabled": "true"},
        )

        assert config.cache_enabled is False

    def test_cli_enable_wins_over_config_disable(self):
        config = m.build_source_config(
            make_args(cache_enabled=True),
            {"cache_enabled": "false"},
        )

        assert config.cache_enabled is True

    def test_invalid_config_value_is_rejected(self):
        with pytest.raises(ValueError, match="cache_enabled"):
            m.build_source_config(make_args(), {"cache_enabled": "maybe"})


class TestCacheCli:
    def run_cli(self, monkeypatch, *args):
        monkeypatch.setattr(sys, "argv", ["trackfetch", *map(str, args)])
        m.main()

    def isolate(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.delenv("TRACKFETCH_CONFIG", raising=False)
        monkeypatch.setattr(
            Path, "home", classmethod(lambda cls: tmp_path / "home")
        )

    def test_list_sources_shows_enabled_by_default(self, monkeypatch, tmp_path, capsys):
        self.isolate(monkeypatch, tmp_path)

        self.run_cli(monkeypatch, "--list-sources")

        assert "Metadata cache: enabled" in capsys.readouterr().out

    def test_no_cache_is_shown_by_list_sources(self, monkeypatch, tmp_path, capsys):
        self.isolate(monkeypatch, tmp_path)

        self.run_cli(monkeypatch, "--list-sources", "--no-cache")

        assert "Metadata cache: disabled" in capsys.readouterr().out
