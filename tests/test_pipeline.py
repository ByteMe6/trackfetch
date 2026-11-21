import argparse
import shutil
import sys
import time

import pytest
from conftest import FIXTURES, make_track
from mutagen.id3 import ID3
from mutagen.mp4 import MP4
from mutagen.oggopus import OggOpus

import trackfetch as m


@pytest.fixture
def pipeline(monkeypatch):
    """Stub every network and subprocess boundary; tests tweak `state` to steer it."""
    state = {
        "track": make_track("One More Time", ["Daft Punk"], album="Discovery", track_number=1),
        "video": {"title": "Daft Punk - One More Time (Official Audio)", "id": "abc"},
        "download_ok": True,
        "cover_ok": True,
        "downloaded_urls": [],
        "formats": [],
        "searched": [],
    }

    def fake_find_spotify(sp, artist, title):
        state["searched"].append((artist, title))
        return state["track"]

    def fake_download_audio(url, temp_dir, audio_format="mp3", audio_quality=None):
        state["downloaded_urls"].append(url)
        state["formats"].append(audio_format)
        if not state["download_ok"]:
            return None
        path = temp_dir / f"audio.{audio_format}"
        if audio_format == "mp3":
            path.write_bytes(b"\x00" * 64)
        else:
            shutil.copy(FIXTURES / f"silence.{audio_format}", path)
        return path

    def fake_download_cover(url, dest):
        if not state["cover_ok"]:
            raise OSError("cover unavailable")
        dest.write_bytes(b"\xff\xd8\xff\xe0jpeg")

    def fake_resolve_metadata(artist, title, source_config, runtime):
        track = m.pipeline.find_spotify_track(None, artist, title)

        if track is None:
            return m.fallback_metadata(artist, title)

        metadata = m.get_track_metadata(track, artist, title)
        metadata.update(source="spotify", source_id=track.get("id"), score=1.0)
        return metadata

    monkeypatch.setattr(m.pipeline, "resolve_metadata", fake_resolve_metadata)
    monkeypatch.setattr(m.pipeline, "find_spotify_track", fake_find_spotify)
    monkeypatch.setattr(
        m.pipeline,
        "find_youtube_video",
        lambda artist, title, duration=None: state["video"],
    )
    monkeypatch.setattr(m.pipeline, "download_audio", fake_download_audio)
    monkeypatch.setattr(m.images, "download_cover", fake_download_cover)
    monkeypatch.setattr(m.providers.spotify, "get_spotify", lambda *a, **k: object())
    monkeypatch.setattr(m.pipeline, "fetch_lyrics", lambda *a, **k: None)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    return state


class TestProcessSong:
    def test_downloads_and_tags(self, pipeline, tmp_path):
        ok, reason = m.process_song(None, "daft punk", "one more time", tmp_path, False)

        assert (ok, reason) == (True, "downloaded")
        out = tmp_path / "Daft Punk - One More Time.mp3"
        tags = ID3(out)
        assert tags["TIT2"].text == ["One More Time"]
        assert tags["TALB"].text == ["Discovery"]
        assert tags.getall("APIC")
        assert pipeline["downloaded_urls"] == ["https://www.youtube.com/watch?v=abc"]

    def test_embeds_plain_and_timed_lyrics(self, pipeline, tmp_path, monkeypatch):
        monkeypatch.setattr(
            m.pipeline,
            "fetch_lyrics",
            lambda *args, **kwargs: {
                "plain": "Привет, мир!\nВторая строка",
                "synced": "[00:01.00]Привет, мир!\n[00:02.00]Вторая строка",
            },
        )

        assert m.process_song(
            None, "a", "b", tmp_path, False
        ) == (True, "downloaded")

        tags = ID3(tmp_path / "Daft Punk - One More Time.mp3")
        assert tags.getall("USLT")[0].text == "[00:01.00]Привет, мир!\n[00:02.00]Вторая строка"
        assert tags.getall("SYLT")[0].text == [
            ("Привет, мир!", 1000),
            ("Вторая строка", 2000),
        ]

    def test_sidecar_lyrics_type_writes_lrc_next_to_audio(
        self, pipeline, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(
            m.pipeline,
            "fetch_lyrics",
            lambda *args, **kwargs: {
                "plain": "Привет, мир!\nВторая строка",
                "synced": "[00:01.00]Привет, мир!\n[00:02.00]Вторая строка",
            },
        )

        assert m.process_song(
            None, "a", "b", tmp_path, False, lyrics_type="sidecar"
        ) == (True, "downloaded")

        audio = tmp_path / "Daft Punk - One More Time.mp3"
        lrc = tmp_path / "Daft Punk - One More Time.lrc"

        assert ID3(audio).getall("USLT")[0].text == "Привет, мир!\nВторая строка"
        assert lrc.read_text(encoding="utf-8") == (
            "[00:01.00]Привет, мир!\n[00:02.00]Вторая строка\n"
        )

    def test_plain_lyrics_type_writes_no_lrc(
        self, pipeline, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(
            m.pipeline,
            "fetch_lyrics",
            lambda *args, **kwargs: {
                "plain": "Привет, мир!",
                "synced": "[00:01.00]Привет, мир!",
            },
        )

        assert m.process_song(
            None, "a", "b", tmp_path, False, lyrics_type="plain"
        ) == (True, "downloaded")

        assert not (tmp_path / "Daft Punk - One More Time.lrc").exists()

    def test_duration_is_forwarded_to_youtube_and_lyrics(
        self, pipeline, tmp_path, monkeypatch
    ):
        calls = []

        def resolve(artist, title, source_config, runtime):
            metadata = m.fallback_metadata(artist, title)
            metadata["duration"] = 321
            return metadata

        def find_video(artist, title, duration=None):
            calls.append(("video", duration))
            return pipeline["video"]

        def find_lyrics(artist, title, runtime=None, duration=None):
            calls.append(("lyrics", duration))
            return None

        monkeypatch.setattr(m.pipeline, "resolve_metadata", resolve)
        monkeypatch.setattr(m.pipeline, "find_youtube_video", find_video)
        monkeypatch.setattr(m.pipeline, "fetch_lyrics", find_lyrics)

        assert m.process_song(
            None,
            "a",
            "b",
            tmp_path,
            False,
            source_config=m.build_source_config(None, {}),
            runtime=m.MetadataRuntime(),
        ) == (True, "downloaded")
        assert calls == [("video", 321), ("lyrics", 321)]

    def test_synced_lyrics_status_message(self, pipeline, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(
            m.pipeline,
            "fetch_lyrics",
            lambda *args, **kwargs: {
                "plain": "Words",
                "synced": "[00:01.00]Words",
            },
        )

        assert m.process_song(
            None, "a", "b", tmp_path, False
        ) == (True, "downloaded")
        assert "Lyrics: synced (embedded)" in capsys.readouterr().out

    def test_plain_only_lyrics_status_message(self, pipeline, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(
            m.pipeline,
            "fetch_lyrics",
            lambda *args, **kwargs: {"plain": "Words", "synced": None},
        )

        assert m.process_song(
            None, "a", "b", tmp_path, False
        ) == (True, "downloaded")
        assert (
            "Lyrics: plain only (no synced version)"
            in capsys.readouterr().out
        )

    def test_missing_lyrics_does_not_fail_download(
        self, pipeline, tmp_path, capsys
    ):
        assert m.process_song(
            None, "a", "b", tmp_path, False
        ) == (True, "downloaded")

        tags = ID3(tmp_path / "Daft Punk - One More Time.mp3")
        assert not tags.getall("USLT")
        assert not tags.getall("SYLT")
        assert "Lyrics: not found" in capsys.readouterr().out

    def test_disabled_lyrics_are_not_fetched(self, pipeline, tmp_path, monkeypatch):
        def boom(*args, **kwargs):
            raise AssertionError("lyrics must not be fetched")

        monkeypatch.setattr(m.pipeline, "fetch_lyrics", boom)
        config = m.build_source_config(
            argparse.Namespace(
                metadata_sources=None,
                disable_sources=None,
                provider_opt=None,
                match_threshold=None,
                title_threshold=None,
                lyrics_enabled=False,
            ),
            {},
        )

        assert m.process_song(
            None,
            "a",
            "b",
            tmp_path,
            False,
            "mp3",
            source_config=config,
        ) == (True, "downloaded")
        assert not ID3(tmp_path / "Daft Punk - One More Time.mp3").getall("USLT")


    def test_opus(self, pipeline, tmp_path):
        assert m.process_song(None, "a", "b", tmp_path, False, "opus") == (True, "downloaded")
        tags = OggOpus(tmp_path / "Daft Punk - One More Time.opus")
        assert tags["TITLE"] == ["One More Time"]
        assert tags["METADATA_BLOCK_PICTURE"]
        assert pipeline["formats"] == ["opus"]

    def test_opus_embeds_lyrics(self, pipeline, tmp_path, monkeypatch):
        monkeypatch.setattr(
            m.pipeline,
            "fetch_lyrics",
            lambda *args, **kwargs: {
                "plain": "Words",
                "synced": "[00:01.00]Words",
            },
        )

        assert m.process_song(None, "a", "b", tmp_path, False, "opus") == (True, "downloaded")

        tags = OggOpus(tmp_path / "Daft Punk - One More Time.opus")
        assert tags["LYRICS"] == ["[00:01.00]Words"]
        assert tags["SYNCEDLYRICS"] == ["[00:01.00]Words"]

    def test_m4a_embeds_lyrics(self, pipeline, tmp_path, monkeypatch):
        monkeypatch.setattr(
            m.pipeline,
            "fetch_lyrics",
            lambda *args, **kwargs: {
                "plain": "Words",
                "synced": "[00:01.00]Words",
            },
        )

        assert m.process_song(None, "a", "b", tmp_path, False, "m4a") == (True, "downloaded")

        tags = MP4(tmp_path / "Daft Punk - One More Time.m4a")
        assert tags["\xa9lyr"] == ["[00:01.00]Words"]
        assert bytes(tags[m.M4A_SYNCED_LYRICS_KEY][0]).decode("utf-8") == "[00:01.00]Words"

    def test_m4a(self, pipeline, tmp_path):
        assert m.process_song(None, "a", "b", tmp_path, False, "m4a") == (True, "downloaded")
        tags = MP4(tmp_path / "Daft Punk - One More Time.m4a")
        assert tags["\xa9alb"] == ["Discovery"]
        assert tags["covr"]

    def test_existing_file_check_uses_format_extension(self, pipeline, tmp_path):
        (tmp_path / "Daft Punk - One More Time.mp3").write_bytes(b"")
        assert m.process_song(None, "a", "b", tmp_path, False, "opus") == (True, "downloaded")

    def test_title_only(self, pipeline, tmp_path):
        m.process_song(None, "a", "b", tmp_path, True)
        assert (tmp_path / "One More Time.mp3").exists()

    def test_skips_existing_file(self, pipeline, tmp_path):
        (tmp_path / "Daft Punk - One More Time.mp3").write_bytes(b"")
        assert m.process_song(None, "a", "b", tmp_path, False) == (True, "exists")
        assert pipeline["downloaded_urls"] == []

    def test_uses_input_when_spotify_has_no_match(self, pipeline, tmp_path):
        pipeline["track"] = None
        assert m.process_song(None, "Unknown", "Demo", tmp_path, False)[0]
        assert ID3(tmp_path / "Unknown - Demo.mp3")["TPE1"].text == ["Unknown"]

    def test_prefers_webpage_url(self, pipeline, tmp_path):
        pipeline["video"] = {"webpage_url": "https://w", "url": "https://u", "id": "i"}
        m.process_song(None, "a", "b", tmp_path, False)
        assert pipeline["downloaded_urls"] == ["https://w"]

    def test_no_youtube_result(self, pipeline, tmp_path):
        pipeline["video"] = None
        assert m.process_song(None, "a", "b", tmp_path, False) == (False, "no YouTube result")

    def test_no_confident_youtube_match(self, pipeline, tmp_path, monkeypatch):
        def no_match(artist, title, duration=None):
            m.youtube.LAST_SEARCH_HAD_CANDIDATES = True
            return None

        monkeypatch.setattr(m.pipeline, "find_youtube_video", no_match)

        assert m.process_song(
            None, "a", "b", tmp_path, False
        ) == (False, "no confident YouTube match")

    def test_ytdlp_search_failure(self, pipeline, tmp_path, monkeypatch):
        def search_failed(artist, title, duration=None):
            raise m.youtube.YoutubeSearchError("boom")

        monkeypatch.setattr(m.pipeline, "find_youtube_video", search_failed)

        assert m.process_song(
            None, "a", "b", tmp_path, False
        ) == (False, "yt-dlp search failed")

    def test_music_fallback_with_no_match_is_not_a_result(
        self, pipeline, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(m.pipeline, "find_youtube_video", m.youtube.find_youtube_video)
        monkeypatch.setattr(
            m.youtube,
            "youtube_search",
            lambda query, limit: [],
        )
        monkeypatch.setattr(
            m.youtube,
            "youtube_music_search",
            lambda query, limit=8: [
                {"id": "W831-GLcBKc", "title": "Life"},
            ],
        )
        monkeypatch.setattr(
            m.youtube,
            "youtube_video_details",
            lambda video_id: {
                "id": video_id,
                "title": "Life",
                "artist": "Someone Else",
            },
        )

        assert m.process_song(
            None, "a", "b", tmp_path, False
        ) == (False, "no confident YouTube match")

    def test_invalid_youtube_result(self, pipeline, tmp_path):
        pipeline["video"] = {"title": "no id"}
        assert m.process_song(None, "a", "b", tmp_path, False) == (False, "invalid YouTube result")

    def test_download_failure(self, pipeline, tmp_path):
        pipeline["download_ok"] = False
        assert m.process_song(None, "a", "b", tmp_path, False) == (False, "yt-dlp download failed")
        assert not list(tmp_path.glob("*.mp3"))

    def test_cover_failure_is_not_fatal(self, pipeline, tmp_path, capsys):
        pipeline["cover_ok"] = False
        assert m.process_song(None, "a", "b", tmp_path, False) == (True, "downloaded")
        assert not ID3(tmp_path / "Daft Punk - One More Time.mp3").getall("APIC")
        assert "cover download failed" in capsys.readouterr().out

    def test_lrc_sidecar_error_is_not_fatal(
        self, pipeline, tmp_path, monkeypatch, capsys
    ):
        def boom(*args):
            raise OSError("read-only")

        monkeypatch.setattr(m.pipeline, "write_lrc_sidecar", boom)

        assert m.process_song(
            None, "a", "b", tmp_path, False
        ) == (True, "downloaded")
        assert "could not write LRC file" in capsys.readouterr().out

    def test_metadata_error(self, pipeline, tmp_path, monkeypatch):
        def boom(*args):
            raise ValueError("bad tag")

        monkeypatch.setattr(m.pipeline, "add_metadata", boom)
        assert m.process_song(None, "a", "b", tmp_path, False) == (False, "metadata error: bad tag")

    def test_move_error(self, pipeline, tmp_path, monkeypatch):
        def boom(src, dst):
            raise OSError("disk full")

        monkeypatch.setattr(shutil, "move", boom)
        assert m.process_song(None, "a", "b", tmp_path, False) == (False, "move error: disk full")


def run_cli(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["trackfetch", *map(str, args)])
    m.main()


class TestMain:
    def test_missing_input_file(self, monkeypatch, tmp_path, capsys):
        with pytest.raises(SystemExit) as exc:
            run_cli(monkeypatch, tmp_path / "nope.txt")
        assert exc.value.code == 1
        assert "Input file not found" in capsys.readouterr().out

    def test_end_to_end_with_resume(self, pipeline, monkeypatch, tmp_path, capsys):
        songs = tmp_path / "songs.txt"
        songs.write_text(
            "# comment\n\nDaft Punk - One More Time\nnot a song line\nBad - Song\n",
            encoding="utf-8",
        )
        out = tmp_path / "out" / "nested"

        def video_for(artist, title, duration=None):
            return None if pipeline["searched"][-1] == ("Bad", "Song") else pipeline["video"]

        monkeypatch.setattr(m.pipeline, "find_youtube_video", video_for)
        real_find = m.pipeline.find_spotify_track

        def spotify_for(sp, artist, title):
            track = real_find(sp, artist, title)
            return track if artist != "Bad" else None

        monkeypatch.setattr(m.pipeline, "find_spotify_track", spotify_for)

        run_cli(monkeypatch, songs, "-o", out, "--delay", "0")
        log = capsys.readouterr().out

        assert "Found 2 songs" in log
        assert "SUCCESS: 1" in log
        assert "FAILED: 1" in log
        assert (out / "Daft Punk - One More Time.mp3").exists()
        assert (out / "done.txt").read_text(encoding="utf-8") == "Daft Punk - One More Time\n"
        assert (out / "failed.txt").read_text(
            encoding="utf-8"
        ) == "Bad - Song | no YouTube result\n"

        # Second run: the completed song is skipped without touching Spotify or YouTube.
        pipeline["searched"].clear()
        run_cli(monkeypatch, songs, "-o", out, "--delay", "0")
        log = capsys.readouterr().out
        assert "Already completed: 1" in log
        assert "SKIP: already completed" in log
        assert pipeline["searched"] == [("Bad", "Song")]

    def test_logs_are_written_without_no_logs(self, pipeline, monkeypatch, tmp_path):
        songs = tmp_path / "songs.txt"
        songs.write_text("Daft Punk - One More Time\nBad - Song\n", encoding="utf-8")
        out = tmp_path / "o"

        def video_for(artist, title, duration=None):
            return None if artist == "Bad" else pipeline["video"]

        def spotify_for(sp, artist, title):
            return None if artist == "Bad" else pipeline["track"]

        monkeypatch.setattr(m.pipeline, "find_youtube_video", video_for)
        monkeypatch.setattr(m.pipeline, "find_spotify_track", spotify_for)

        run_cli(monkeypatch, songs, "-o", out, "--delay", "0")

        assert m.read_done(out / "done.txt") == {"Daft Punk - One More Time"}
        assert (out / "failed.txt").read_text(
            encoding="utf-8"
        ) == "Bad - Song | no YouTube result\n"

    def test_no_logs_does_not_read_logs(self, pipeline, monkeypatch, tmp_path):
        songs = tmp_path / "songs.txt"
        songs.write_text("Daft Punk - One More Time\n", encoding="utf-8")
        out = tmp_path / "o"
        out.mkdir()
        done = out / "done.txt"
        done.write_text("Daft Punk - One More Time\n", encoding="utf-8")

        run_cli(monkeypatch, songs, "-o", out, "--no-logs", "--delay", "0")

        assert (out / "Daft Punk - One More Time.mp3").exists()
        assert pipeline["downloaded_urls"] == ["https://www.youtube.com/watch?v=abc"]
        assert done.read_text(encoding="utf-8") == "Daft Punk - One More Time\n"

    def test_no_logs_does_not_write_logs(self, pipeline, monkeypatch, tmp_path, capsys):
        songs = tmp_path / "songs.txt"
        songs.write_text("Daft Punk - One More Time\nBad - Song\n", encoding="utf-8")
        out = tmp_path / "o"
        out.mkdir()
        done = out / "done.txt"
        failed = out / "failed.txt"
        done.write_text("Old - Song\n", encoding="utf-8")
        failed.write_text("Bad - Song | old reason\n", encoding="utf-8")

        def video_for(artist, title, duration=None):
            return None if artist == "Bad" else pipeline["video"]

        def spotify_for(sp, artist, title):
            return None if artist == "Bad" else pipeline["track"]

        monkeypatch.setattr(m.pipeline, "find_youtube_video", video_for)
        monkeypatch.setattr(m.pipeline, "find_spotify_track", spotify_for)

        run_cli(monkeypatch, songs, "-o", out, "--no-logs", "--delay", "0")
        log = capsys.readouterr().out

        assert (out / "Daft Punk - One More Time.mp3").exists()
        assert done.read_text(encoding="utf-8") == "Old - Song\n"
        assert failed.read_text(encoding="utf-8") == "Bad - Song | old reason\n"
        assert "DONE FILE" not in log
        assert "FAILED FILE" not in log

    def test_no_logs_still_removes_duplicates(self, pipeline, monkeypatch, tmp_path, capsys):
        songs = tmp_path / "songs.txt"
        songs.write_text(
            "Daft Punk - One More Time\nDaft Punk - One More Time\n",
            encoding="utf-8",
        )
        out = tmp_path / "o"

        run_cli(monkeypatch, songs, "-o", out, "--no-logs", "--delay", "0")
        log = capsys.readouterr().out

        assert "Removed 1 duplicate(s)" in log
        assert "SUCCESS: 1" in log
        assert pipeline["downloaded_urls"] == ["https://www.youtube.com/watch?v=abc"]
        assert not (out / "done.txt").exists()
        assert not (out / "failed.txt").exists()

    def test_delay_between_songs_only(self, pipeline, monkeypatch, tmp_path):
        songs = tmp_path / "songs.txt"
        songs.write_text("A - 1\nA - 2\nA - 3\n", encoding="utf-8")
        sleeps = []
        monkeypatch.setattr(time, "sleep", sleeps.append)
        pipeline["track"] = None

        run_cli(monkeypatch, songs, "-o", tmp_path / "o", "--delay", "2.5")
        assert sleeps == [2.5, 2.5]

    def test_existing_file_counts_as_skipped_and_done(
        self, pipeline, monkeypatch, tmp_path, capsys
    ):
        songs = tmp_path / "songs.txt"
        songs.write_text("Daft Punk - One More Time\n", encoding="utf-8")
        out = tmp_path / "o"
        out.mkdir()
        (out / "Daft Punk - One More Time.mp3").write_bytes(b"")

        run_cli(monkeypatch, songs, "-o", out)
        log = capsys.readouterr().out
        assert "SKIPPED: 1" in log
        assert m.read_done(out / "done.txt") == {"Daft Punk - One More Time"}

    def test_format_option(self, pipeline, monkeypatch, tmp_path):
        songs = tmp_path / "songs.txt"
        songs.write_text("Daft Punk - One More Time\n", encoding="utf-8")
        out = tmp_path / "o"

        run_cli(monkeypatch, songs, "-o", out, "--format", "opus")
        assert (out / "Daft Punk - One More Time.opus").exists()
        assert pipeline["formats"] == ["opus"]

    def test_default_format_is_mp3(self, pipeline, monkeypatch, tmp_path):
        songs = tmp_path / "songs.txt"
        songs.write_text("Daft Punk - One More Time\n", encoding="utf-8")

        run_cli(monkeypatch, songs, "-o", tmp_path / "o")
        assert pipeline["formats"] == ["mp3"]

    def test_no_cache_passes_no_cache_to_runtime(self, pipeline, monkeypatch, tmp_path):
        songs = tmp_path / "songs.txt"
        songs.write_text("Daft Punk - One More Time\n", encoding="utf-8")
        seen = {}

        real_process = m.pipeline.process_song

        def spy(*args, **kwargs):
            seen["cache"] = kwargs["runtime"].cache
            return real_process(*args, **kwargs)

        monkeypatch.setattr(m.pipeline, "process_song", spy)
        monkeypatch.setattr(m.cli, "process_song", spy, raising=False)

        run_cli(monkeypatch, songs, "-o", tmp_path / "o", "--no-cache", "--delay", "0")

        assert seen["cache"] is None
        assert not (tmp_path / "o" / "metadata-cache.json").exists()

    def test_cache_is_enabled_by_default(self, pipeline, monkeypatch, tmp_path):
        songs = tmp_path / "songs.txt"
        songs.write_text("Daft Punk - One More Time\n", encoding="utf-8")
        seen = {}

        real_process = m.pipeline.process_song

        def spy(*args, **kwargs):
            seen["cache"] = kwargs["runtime"].cache
            return real_process(*args, **kwargs)

        monkeypatch.setattr(m.pipeline, "process_song", spy)
        monkeypatch.setattr(m.cli, "process_song", spy, raising=False)

        run_cli(monkeypatch, songs, "-o", tmp_path / "o", "--delay", "0")

        assert isinstance(seen["cache"], m.MetadataCache)
        assert seen["cache"].path.name == "metadata-cache.json"

    def test_rejects_unknown_format(self, monkeypatch, tmp_path, capsys):
        songs = tmp_path / "songs.txt"
        songs.write_text("A - B\n", encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            run_cli(monkeypatch, songs, "--format", "flac")
        assert exc.value.code == 2
        assert "invalid choice" in capsys.readouterr().err


class TestSoundcloudFallbackIntegration:
    """The fallback must run only for an age restriction, and only once."""

    @pytest.fixture(autouse=True)
    def offline(self, monkeypatch):
        """Never touch live SoundCloud; individual tests override as needed."""
        from trackfetch import soundcloud

        soundcloud.reset_attempts()
        monkeypatch.setattr(
            soundcloud,
            "soundcloud_track_details",
            lambda url: {},
        )

    AGE_ERROR = (
        "ERROR: [youtube] x: Sign in to confirm your age. "
        "This video may be inappropriate for some users."
    )

    def prepare(self, pipeline, monkeypatch, age_restricted):
        from trackfetch import soundcloud

        soundcloud.reset_attempts()
        state = {"downloads": 0, "urls": []}

        def fake_download_audio(url, temp_dir, audio_format="mp3", audio_quality=None):
            state["urls"].append(url)
            state["downloads"] += 1

            if state["downloads"] == 1:
                return None

            path = temp_dir / f"audio.{audio_format}"
            path.write_bytes(b"\x00" * 64)
            return path

        monkeypatch.setattr(m.pipeline, "download_audio", fake_download_audio)
        monkeypatch.setattr(
            m.pipeline,
            "probe_age_restriction",
            lambda url, *a, **k: age_restricted,
        )
        return state

    def candidate(self, **overrides):
        data = {
            "id": "850231564",
            "title": "Daft Punk - One More Time",
            "track": "Daft Punk - One More Time",
            "duration": 200,
            "uploader": "Daft Punk",
            "webpage_url": "https://soundcloud.com/daftpunk/one-more-time",
        }
        data.update(overrides)
        return data

    def config(self, **kwargs):
        return m.build_source_config(
            argparse.Namespace(
                metadata_sources=None,
                disable_sources=None,
                provider_opt=None,
                match_threshold=None,
                title_threshold=None,
                **kwargs,
            ),
            {},
        )

    def test_age_restriction_downloads_the_soundcloud_copy(
        self, pipeline, monkeypatch, tmp_path
    ):
        state = self.prepare(pipeline, monkeypatch, True)
        monkeypatch.setattr(
            m.pipeline.soundcloud,
            "soundcloud_search",
            lambda query, limit=5: [self.candidate()],
        )
        monkeypatch.setattr(
            m.pipeline.soundcloud,
            "soundcloud_track_details",
            lambda url: {
                "id": "850231564",
                "title": "Daft Punk - One More Time",
                "duration": 200,
                "license": "all-rights-reserved",
            },
        )

        ok, reason = m.process_song(
            None,
            "Daft Punk",
            "One More Time",
            tmp_path,
            False,
            source_config=self.config(),
        )

        assert (ok, reason) == (True, "downloaded")
        assert state["urls"] == [
            "https://www.youtube.com/watch?v=abc",
            "https://soundcloud.com/daftpunk/one-more-time",
        ]
        assert (tmp_path / "Daft Punk - One More Time.mp3").exists()

    def test_non_age_error_never_searches_soundcloud(
        self, pipeline, monkeypatch, tmp_path
    ):
        self.prepare(pipeline, monkeypatch, False)

        def boom(*args, **kwargs):
            pytest.fail("SoundCloud must not be searched")

        monkeypatch.setattr(m.pipeline.soundcloud, "soundcloud_search", boom)

        assert m.process_song(
            None,
            "Daft Punk",
            "One More Time",
            tmp_path,
            False,
            source_config=self.config(),
        ) == (False, "yt-dlp download failed")

    def test_network_error_never_searches_soundcloud(
        self, pipeline, monkeypatch, tmp_path
    ):
        self.prepare(pipeline, monkeypatch, False)
        monkeypatch.setattr(
            m.pipeline.soundcloud,
            "soundcloud_search",
            lambda *a, **k: pytest.fail("must not search"),
        )

        assert m.process_song(
            None,
            "Daft Punk",
            "One More Time",
            tmp_path,
            False,
            source_config=self.config(),
        ) == (False, "yt-dlp download failed")

    def test_private_video_never_searches_soundcloud(
        self, pipeline, monkeypatch, tmp_path
    ):
        self.prepare(pipeline, monkeypatch, False)
        monkeypatch.setattr(
            m.pipeline.soundcloud,
            "soundcloud_search",
            lambda *a, **k: pytest.fail("must not search"),
        )

        assert m.process_song(
            None,
            "Daft Punk",
            "One More Time",
            tmp_path,
            False,
            source_config=self.config(),
        )[0] is False

    def test_disabled_fallback_keeps_the_original_reason(
        self, pipeline, monkeypatch, tmp_path
    ):
        self.prepare(pipeline, monkeypatch, True)
        monkeypatch.setattr(
            m.pipeline.soundcloud,
            "soundcloud_search",
            lambda *a, **k: pytest.fail("must not search"),
        )

        assert m.process_song(
            None,
            "Daft Punk",
            "One More Time",
            tmp_path,
            False,
            source_config=self.config(soundcloud_enabled=False),
        ) == (False, "yt-dlp download failed")

    def test_preview_candidate_is_not_downloaded(
        self, pipeline, monkeypatch, tmp_path
    ):
        state = self.prepare(pipeline, monkeypatch, True)
        monkeypatch.setattr(
            m.pipeline.soundcloud,
            "soundcloud_search",
            lambda query, limit=5: [self.candidate(duration=30)],
        )

        ok, reason = m.process_song(
            None,
            "Daft Punk",
            "One More Time",
            tmp_path,
            False,
            source_config=self.config(),
        )

        assert ok is False
        assert "SoundCloud" in reason
        assert len(state["urls"]) == 1

    def test_no_match_does_not_download(
        self, pipeline, monkeypatch, tmp_path
    ):
        state = self.prepare(pipeline, monkeypatch, True)
        monkeypatch.setattr(
            m.pipeline.soundcloud,
            "soundcloud_search",
            lambda query, limit=5: [],
        )

        ok, reason = m.process_song(
            None,
            "Daft Punk",
            "One More Time",
            tmp_path,
            False,
            source_config=self.config(),
        )

        assert ok is False
        assert reason == "no SoundCloud match"
        assert len(state["urls"]) == 1

    def test_soundcloud_download_failure_is_reported(
        self, pipeline, monkeypatch, tmp_path
    ):
        self.prepare(pipeline, monkeypatch, True)
        # Both the YouTube and the SoundCloud download fail.
        monkeypatch.setattr(
            m.pipeline,
            "download_audio",
            lambda *a, **k: None,
        )
        monkeypatch.setattr(
            m.pipeline.soundcloud,
            "soundcloud_search",
            lambda query, limit=5: [self.candidate()],
        )
        monkeypatch.setattr(
            m.pipeline.soundcloud,
            "soundcloud_track_details",
            lambda url: {},
        )

        ok, reason = m.process_song(
            None,
            "Daft Punk",
            "One More Time",
            tmp_path,
            False,
            source_config=self.config(),
        )

        assert (ok, reason) == (False, "yt-dlp download failed")

    def test_fallback_runs_only_once_per_song(
        self, pipeline, monkeypatch, tmp_path
    ):
        m.soundcloud.reset_attempts()
        calls = []

        def failing_download(url, temp_dir, audio_format="mp3", audio_quality=None):
            return None

        monkeypatch.setattr(m.pipeline, "download_audio", failing_download)
        monkeypatch.setattr(
            m.pipeline,
            "probe_age_restriction",
            lambda url, *a, **k: True,
        )
        monkeypatch.setattr(
            m.pipeline.soundcloud,
            "soundcloud_search",
            lambda query, limit=5: calls.append(query) or [self.candidate()],
        )
        monkeypatch.setattr(
            m.pipeline.soundcloud,
            "soundcloud_track_details",
            lambda url: {},
        )

        config = self.config()
        m.process_song(
            None, "Daft Punk", "One More Time", tmp_path, False, source_config=config
        )
        m.process_song(
            None, "Daft Punk", "One More Time", tmp_path, False, source_config=config
        )

        assert len(calls) == 1

    def test_soundcloud_artwork_fills_missing_cover(
        self, pipeline, monkeypatch, tmp_path
    ):
        from mutagen.id3 import ID3

        self.prepare(pipeline, monkeypatch, True)

        def no_artwork(artist, title, source_config, runtime):
            metadata = m.fallback_metadata(artist, title)
            metadata["duration"] = 200
            return metadata

        monkeypatch.setattr(m.pipeline, "resolve_metadata", no_artwork)
        cover_urls = []

        def fake_cover(metadata_arg, video, dest, youtube_enabled):
            cover_urls.append(metadata_arg.get("cover_url"))
            dest.write_bytes(b"\xff\xd8\xff\xe0jpeg")
            return dest

        monkeypatch.setattr(m.pipeline, "download_best_cover", fake_cover)
        monkeypatch.setattr(
            m.pipeline.soundcloud,
            "soundcloud_search",
            lambda query, limit=5: [
                self.candidate(
                    thumbnails=[
                        {"url": "https://i1.sndcdn.com/small.jpg", "width": 100},
                        {"url": "https://i1.sndcdn.com/large.jpg", "width": 500},
                    ]
                )
            ],
        )
        monkeypatch.setattr(
            m.pipeline.soundcloud,
            "soundcloud_track_details",
            lambda url: {},
        )

        assert m.process_song(
            None,
            "Daft Punk",
            "One More Time",
            tmp_path,
            False,
            source_config=self.config(),
        ) == (True, "downloaded")

        # The provider had no artwork in this pipeline fixture, so the largest
        # SoundCloud thumbnail is used.
        assert "https://i1.sndcdn.com/large.jpg" in cover_urls
        assert (tmp_path / "Daft Punk - One More Time.mp3").exists()
        assert ID3(tmp_path / "Daft Punk - One More Time.mp3").getall("APIC")

    def test_candidate_blocked_after_verification_is_not_downloaded(
        self, pipeline, monkeypatch, tmp_path
    ):
        state = self.prepare(pipeline, monkeypatch, True)
        monkeypatch.setattr(
            m.pipeline.soundcloud,
            "soundcloud_search",
            lambda query, limit=5: [self.candidate()],
        )
        monkeypatch.setattr(
            m.pipeline.soundcloud,
            "soundcloud_track_details",
            lambda url: {"downloadable": False},
        )

        ok, reason = m.process_song(
            None,
            "Daft Punk",
            "One More Time",
            tmp_path,
            False,
            source_config=self.config(),
        )

        assert ok is False
        assert "install" not in reason
        assert len(state["urls"]) == 1

    def test_soundcloud_thumbnail_is_used_without_a_thumbnail_list(
        self, pipeline, monkeypatch, tmp_path
    ):
        from mutagen.id3 import ID3

        self.prepare(pipeline, monkeypatch, True)

        def no_artwork(artist, title, source_config, runtime):
            metadata = m.fallback_metadata(artist, title)
            metadata["duration"] = 200
            return metadata

        monkeypatch.setattr(m.pipeline, "resolve_metadata", no_artwork)
        seen = []

        def fake_cover(metadata_arg, video, dest, youtube_enabled):
            seen.append(metadata_arg.get("cover_url"))
            dest.write_bytes(b"\xff\xd8\xff\xe0jpeg")
            return dest

        monkeypatch.setattr(m.pipeline, "download_best_cover", fake_cover)
        monkeypatch.setattr(
            m.pipeline.soundcloud,
            "soundcloud_search",
            lambda query, limit=5: [
                self.candidate(thumbnail="https://i1.sndcdn.com/only.jpg")
            ],
        )
        monkeypatch.setattr(
            m.pipeline.soundcloud,
            "soundcloud_track_details",
            lambda url: {},
        )

        assert m.process_song(
            None,
            "Daft Punk",
            "One More Time",
            tmp_path,
            False,
            source_config=self.config(),
        ) == (True, "downloaded")
        assert seen == ["https://i1.sndcdn.com/only.jpg"]
        assert ID3(tmp_path / "Daft Punk - One More Time.mp3").getall("APIC")

    def test_invalid_soundcloud_result_is_reported(
        self, pipeline, monkeypatch, tmp_path
    ):
        self.prepare(pipeline, monkeypatch, True)

        # The search payload has no URL; the details call cannot add one.
        monkeypatch.setattr(
            m.pipeline.soundcloud,
            "soundcloud_search",
            lambda query, limit=5: [
                {
                    "id": "850231564",
                    "title": "Daft Punk - One More Time",
                    "track": "Daft Punk - One More Time",
                    "duration": 200,
                    "uploader": "Daft Punk",
                }
            ],
        )
        monkeypatch.setattr(
            m.pipeline.soundcloud,
            "soundcloud_track_details",
            lambda url: {},
        )

        ok, reason = m.process_song(
            None,
            "Daft Punk",
            "One More Time",
            tmp_path,
            False,
            source_config=self.config(),
        )

        assert ok is False

    def test_preview_found_only_in_details_is_rejected(
        self, pipeline, monkeypatch, tmp_path
    ):
        state = self.prepare(pipeline, monkeypatch, True)
        monkeypatch.setattr(
            m.pipeline.soundcloud,
            "soundcloud_search",
            lambda query, limit=5: [self.candidate(duration=200)],
        )
        # The details call reveals the 30-second preview duration.
        monkeypatch.setattr(
            m.pipeline.soundcloud,
            "soundcloud_track_details",
            lambda url: {"duration": 30},
        )

        ok, reason = m.process_song(
            None,
            "Daft Punk",
            "One More Time",
            tmp_path,
            False,
            source_config=self.config(),
        )

        assert ok is False
        assert "SoundCloud" in reason
        assert len(state["urls"]) == 1

    def test_artwork_helper_handles_missing_thumbnails(self):
        assert m.pipeline._soundcloud_artwork({}) is None
        assert m.pipeline._soundcloud_artwork({"thumbnails": "x"}) is None
        assert (
            m.pipeline._soundcloud_artwork({"thumbnail": "https://t"})
            == "https://t"
        )


class TestSoundcloudTrigger:
    """Which YouTube failures may open the SoundCloud fallback."""

    def config(self, **overrides):
        values = {
            "metadata_sources": None,
            "disable_sources": None,
            "provider_opt": None,
            "match_threshold": None,
            "title_threshold": None,
        }
        values.update(overrides)
        return m.build_source_config(argparse.Namespace(**values), {})

    def setup_soundcloud(self, monkeypatch, approved=True):
        from trackfetch import soundcloud

        soundcloud.reset_attempts()
        monkeypatch.setattr(
            m.pipeline.soundcloud,
            "soundcloud_search",
            lambda query, limit=5: [
                {
                    "id": "sc1",
                    "title": "Daft Punk - One More Time",
                    "track": "Daft Punk - One More Time",
                    "duration": 320,
                    "uploader": "Daft Punk",
                    "webpage_url": "https://soundcloud.com/daftpunk/one",
                }
            ] if approved else [],
        )
        monkeypatch.setattr(
            m.pipeline.soundcloud,
            "soundcloud_track_details",
            lambda url: {},
        )

    def default_trigger_does_not_run_on_missing_match(
        self, pipeline, monkeypatch, tmp_path
    ):
        self.setup_soundcloud(monkeypatch)
        monkeypatch.setattr(
            m.pipeline,
            "find_youtube_video",
            lambda artist, title, duration=None: None,
        )

        assert m.process_song(
            None,
            "Daft Punk",
            "One More Time",
            tmp_path,
            False,
            source_config=self.config(),
        ) == (False, "no YouTube result")

    def test_age_or_missing_runs_on_no_youtube_result(
        self, pipeline, monkeypatch, tmp_path
    ):
        self.setup_soundcloud(monkeypatch)
        monkeypatch.setattr(
            m.pipeline,
            "find_youtube_video",
            lambda artist, title, duration=None: None,
        )
        m.youtube.LAST_SEARCH_HAD_CANDIDATES = False
        def fake_download(url, temp_dir, fmt="mp3", quality=None):
            path = temp_dir / f"audio.{fmt}"
            path.write_bytes(b"\x00" * 64)
            return path

        monkeypatch.setattr(m.pipeline, "download_audio", fake_download)
        monkeypatch.setattr(
            m.pipeline,
            "probe_age_restriction",
            lambda *a, **k: False,
        )

        ok, reason = m.process_song(
            None,
            "Daft Punk",
            "One More Time",
            tmp_path,
            False,
            source_config=self.config(soundcloud_trigger="age-or-missing"),
        )

        assert (ok, reason) == (True, "downloaded")
        assert (tmp_path / "Daft Punk - One More Time.mp3").exists()

    def test_age_or_missing_does_not_run_on_network_error(
        self, pipeline, monkeypatch, tmp_path
    ):
        self.setup_soundcloud(monkeypatch)
        monkeypatch.setattr(
            m.pipeline.soundcloud,
            "soundcloud_search",
            lambda *a, **k: pytest.fail("must not search"),
        )

        def failing_search(artist, title, duration=None):
            raise m.youtube.YoutubeSearchError("timed out")

        monkeypatch.setattr(m.pipeline, "find_youtube_video", failing_search)

        assert m.process_song(
            None,
            "Daft Punk",
            "One More Time",
            tmp_path,
            False,
            source_config=self.config(soundcloud_trigger="age-or-missing"),
        ) == (False, "yt-dlp search failed")

    def test_any_trigger_runs_on_download_failure(
        self, pipeline, monkeypatch, tmp_path
    ):
        self.setup_soundcloud(monkeypatch)
        calls = {"n": 0}

        def fake_download(url, temp_dir, audio_format="mp3", audio_quality=None):
            calls["n"] += 1

            if calls["n"] == 1:
                return None

            path = temp_dir / f"audio.{audio_format}"
            path.write_bytes(b"\x00" * 64)
            return path

        monkeypatch.setattr(m.pipeline, "download_audio", fake_download)
        monkeypatch.setattr(
            m.pipeline,
            "probe_age_restriction",
            lambda *a, **k: False,
        )

        ok, _reason = m.process_song(
            None,
            "Daft Punk",
            "One More Time",
            tmp_path,
            False,
            source_config=self.config(soundcloud_trigger="any"),
        )

        assert ok is True
        assert calls["n"] == 2

    def test_alone_any_trigger_keeps_the_default_off(
        self, pipeline, monkeypatch, tmp_path
    ):
        self.setup_soundcloud(monkeypatch)
        monkeypatch.setattr(
            m.pipeline.soundcloud,
            "soundcloud_search",
            lambda *a, **k: pytest.fail("must not search"),
        )
        monkeypatch.setattr(
            m.pipeline,
            "download_audio",
            lambda *a, **k: None,
        )
        monkeypatch.setattr(
            m.pipeline,
            "probe_age_restriction",
            lambda *a, **k: False,
        )

        assert m.process_song(
            None,
            "Daft Punk",
            "One More Time",
            tmp_path,
            False,
            source_config=self.config(),
        ) == (False, "yt-dlp download failed")

    def test_soundcloud_disabled_overrides_any_trigger(
        self, pipeline, monkeypatch, tmp_path
    ):
        self.setup_soundcloud(monkeypatch)
        monkeypatch.setattr(
            m.pipeline.soundcloud,
            "soundcloud_search",
            lambda *a, **k: pytest.fail("must not search"),
        )
        monkeypatch.setattr(
            m.pipeline,
            "find_youtube_video",
            lambda artist, title, duration=None: None,
        )

        assert m.process_song(
            None,
            "Daft Punk",
            "One More Time",
            tmp_path,
            False,
            source_config=self.config(
                soundcloud_enabled=False,
                soundcloud_trigger="any",
            ),
        ) == (False, "no YouTube result")
