import shutil
import sys

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

    def fake_download_audio(url, temp_dir, audio_format="mp3"):
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

    monkeypatch.setattr(m, "find_spotify_track", fake_find_spotify)
    monkeypatch.setattr(m, "find_youtube_video", lambda artist, title: state["video"])
    monkeypatch.setattr(m, "download_audio", fake_download_audio)
    monkeypatch.setattr(m, "download_cover", fake_download_cover)
    monkeypatch.setattr(m, "get_spotify", lambda *a, **k: object())
    monkeypatch.setattr(m.time, "sleep", lambda s: None)
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

    def test_opus(self, pipeline, tmp_path):
        assert m.process_song(None, "a", "b", tmp_path, False, "opus") == (True, "downloaded")
        tags = OggOpus(tmp_path / "Daft Punk - One More Time.opus")
        assert tags["TITLE"] == ["One More Time"]
        assert tags["METADATA_BLOCK_PICTURE"]
        assert pipeline["formats"] == ["opus"]

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

    def test_metadata_error(self, pipeline, tmp_path, monkeypatch):
        def boom(*args):
            raise ValueError("bad tag")

        monkeypatch.setattr(m, "add_metadata", boom)
        assert m.process_song(None, "a", "b", tmp_path, False) == (False, "metadata error: bad tag")

    def test_move_error(self, pipeline, tmp_path, monkeypatch):
        def boom(src, dst):
            raise OSError("disk full")

        monkeypatch.setattr(m.shutil, "move", boom)
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

        def video_for(artist, title):
            return None if pipeline["searched"][-1] == ("Bad", "Song") else pipeline["video"]

        monkeypatch.setattr(m, "find_youtube_video", video_for)
        real_find = m.find_spotify_track

        def spotify_for(sp, artist, title):
            track = real_find(sp, artist, title)
            return track if artist != "Bad" else None

        monkeypatch.setattr(m, "find_spotify_track", spotify_for)

        run_cli(monkeypatch, songs, "-o", out, "--delay", "0")
        log = capsys.readouterr().out

        assert "Found 2 songs" in log
        assert "SUCCESS: 1" in log
        assert "FAILED: 1" in log
        assert (out / "Daft Punk - One More Time.m4a").exists()
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

    def test_delay_between_songs_only(self, pipeline, monkeypatch, tmp_path):
        songs = tmp_path / "songs.txt"
        songs.write_text("A - 1\nA - 2\nA - 3\n", encoding="utf-8")
        sleeps = []
        monkeypatch.setattr(m.time, "sleep", sleeps.append)
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
        (out / "Daft Punk - One More Time.m4a").write_bytes(b"")

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

    def test_default_format_is_m4a(self, pipeline, monkeypatch, tmp_path):
        songs = tmp_path / "songs.txt"
        songs.write_text("Daft Punk - One More Time\n", encoding="utf-8")

        run_cli(monkeypatch, songs, "-o", tmp_path / "o")
        assert pipeline["formats"] == ["m4a"]

    def test_rejects_unknown_format(self, monkeypatch, tmp_path, capsys):
        songs = tmp_path / "songs.txt"
        songs.write_text("A - B\n", encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            run_cli(monkeypatch, songs, "--format", "flac")
        assert exc.value.code == 2
        assert "invalid choice" in capsys.readouterr().err
