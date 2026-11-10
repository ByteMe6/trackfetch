import shutil
import sys

import pytest
from conftest import FIXTURES, make_track

import trackfetch as m


@pytest.fixture
def pipeline(monkeypatch):
    state = {
        "track": make_track("One More Time", ["Daft Punk"], album="Discovery", track_number=1),
        "video": {"title": "Daft Punk - One More Time (Official Audio)", "id": "abc"},
        "searched": [],
    }

    def fake_find_spotify(sp, artist, title):
        state["searched"].append((artist, title))
        return state["track"]

    def fake_download_audio(url, temp_dir, audio_format="mp3"):
        path = temp_dir / f"audio.{audio_format}"
        if audio_format == "mp3":
            path.write_bytes(b"\x00" * 64)
        else:
            shutil.copy(FIXTURES / f"silence.{audio_format}", path)
        return path

    monkeypatch.setattr(m, "find_spotify_track", fake_find_spotify)
    monkeypatch.setattr(m, "find_youtube_video", lambda a, t: state["video"])
    monkeypatch.setattr(m, "download_audio", fake_download_audio)
    monkeypatch.setattr(m, "download_cover", lambda url, dest: dest.write_bytes(b"x"))
    monkeypatch.setattr(m, "get_spotify", lambda *a, **k: object())
    monkeypatch.setattr(m.time, "sleep", lambda s: None)
    return state


def run_cli(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["trackfetch", *map(str, args)])
    m.main()


class TestInlineTracks:
    def test_single_inline_track(self, pipeline, monkeypatch, tmp_path):
        out = tmp_path / "o"

        run_cli(monkeypatch, "Daft Punk - One More Time", "-o", out)

        assert pipeline["searched"] == [("Daft Punk", "One More Time")]
        assert (out / "Daft Punk - One More Time.m4a").exists()

    def test_several_inline_tracks(self, pipeline, monkeypatch, tmp_path):
        out = tmp_path / "o"

        run_cli(
            monkeypatch,
            "Daft Punk - One More Time",
            "Radiohead - Paranoid Android",
            "-o",
            out,
        )

        assert [artist for artist, _ in pipeline["searched"]] == [
            "Daft Punk",
            "Radiohead",
        ]

    def test_track_flag(self, pipeline, monkeypatch, tmp_path):
        out = tmp_path / "o"

        run_cli(
            monkeypatch,
            "--track",
            "Daft Punk - One More Time",
            "--track",
            "Radiohead - Paranoid Android",
            "-o",
            out,
        )

        assert len(pipeline["searched"]) == 2

    def test_track_flag_with_several_values(self, pipeline, monkeypatch, tmp_path):
        out = tmp_path / "o"

        run_cli(
            monkeypatch,
            "--track",
            "Daft Punk - One More Time",
            "Radiohead - Paranoid Android",
            "-o",
            out,
        )

        assert len(pipeline["searched"]) == 2

    def test_file_and_inline_track_together(self, pipeline, monkeypatch, tmp_path):
        songs = tmp_path / "songs.txt"
        songs.write_text("Daft Punk - One More Time\n", encoding="utf-8")
        out = tmp_path / "o"

        run_cli(monkeypatch, songs, "--track", "Radiohead - Paranoid Android", "-o", out)

        assert len(pipeline["searched"]) == 2

    def test_inline_track_and_file_in_one_call(self, pipeline, monkeypatch, tmp_path):
        songs = tmp_path / "songs.txt"
        songs.write_text("Daft Punk - One More Time\n", encoding="utf-8")
        out = tmp_path / "o"

        run_cli(monkeypatch, "Radiohead - Paranoid Android", songs, "-o", out)

        assert len(pipeline["searched"]) == 2

    def test_missing_file_exits(self, pipeline, monkeypatch, tmp_path, capsys):
        with pytest.raises(SystemExit) as exc:
            run_cli(monkeypatch, "songs.txt", "-o", tmp_path / "o")

        assert exc.value.code == 1
        assert "Input file not found" in capsys.readouterr().out

    def test_unparsable_track_flag_exits(self, pipeline, monkeypatch, tmp_path, capsys):
        with pytest.raises(SystemExit) as exc:
            run_cli(monkeypatch, "--track", "nonsense", "-o", tmp_path / "o")

        assert exc.value.code == 1
        assert "Could not parse track" in capsys.readouterr().out

    def test_inline_track_without_artist_exits(self, pipeline, monkeypatch, tmp_path, capsys):
        with pytest.raises(SystemExit) as exc:
            run_cli(monkeypatch, " - One More Time", "-o", tmp_path / "o")

        assert exc.value.code == 1
        assert "Could not parse track" in capsys.readouterr().out

    def test_inline_track_without_title_exits(self, pipeline, monkeypatch, tmp_path, capsys):
        with pytest.raises(SystemExit) as exc:
            run_cli(monkeypatch, "Daft Punk - ", "-o", tmp_path / "o")

        assert exc.value.code == 1
        assert "Could not parse track" in capsys.readouterr().out

    def test_wrong_separator_hints_at_the_track_format(
        self, pipeline, monkeypatch, tmp_path, capsys
    ):
        with pytest.raises(SystemExit) as exc:
            run_cli(monkeypatch, "Daft Punk -One More Time", "-o", tmp_path / "o")

        assert exc.value.code == 1
        assert "Artist - Title" in capsys.readouterr().out

    def test_output_path_that_is_a_file_exits(self, pipeline, monkeypatch, tmp_path, capsys):
        target = tmp_path / "afile"
        target.write_bytes(b"")

        with pytest.raises(SystemExit) as exc:
            run_cli(monkeypatch, "Daft Punk - One More Time", "-o", target)

        assert exc.value.code == 1
        assert "not a directory" in capsys.readouterr().out

    def test_empty_input_file_exits(self, pipeline, monkeypatch, tmp_path, capsys):
        songs = tmp_path / "songs.txt"
        songs.write_text("# only a comment\n\n", encoding="utf-8")

        with pytest.raises(SystemExit) as exc:
            run_cli(monkeypatch, songs, "-o", tmp_path / "o")

        assert exc.value.code == 0
        assert "No songs to download" in capsys.readouterr().out

    def test_unparsable_lines_in_a_file_are_reported(
        self, pipeline, monkeypatch, tmp_path, capsys
    ):
        songs = tmp_path / "songs.txt"
        songs.write_text(
            "Daft Punk -One More Time\nRadiohead - Paranoid Android\n",
            encoding="utf-8",
        )

        run_cli(monkeypatch, songs, "-o", tmp_path / "o")
        log = capsys.readouterr().out

        assert "WARNING: skipped 1 line(s)" in log
        assert "Daft Punk -One More Time" in log

    def test_inline_track_uses_the_output_rules(self, pipeline, monkeypatch, tmp_path):
        out = tmp_path / "o"
        config = tmp_path / "cfg.ini"
        config.write_text(f"[trackfetch]\noutput = {out}\n", encoding="utf-8")

        run_cli(monkeypatch, "Daft Punk - One More Time", "--config", config)

        assert (out / "Daft Punk - One More Time.m4a").exists()


class TestCollectSources:
    def test_config_input_is_a_file(self, tmp_path):
        songs = tmp_path / "songs.txt"
        songs.write_text("A - B\n", encoding="utf-8")

        class Args:
            inputs = []
            track = None

        sources = m.collect_sources(Args(), {"input": str(songs)})

        assert sources == [songs]

    def test_missing_config_input_raises(self, tmp_path):
        class Args:
            inputs = []
            track = None

        with pytest.raises(ValueError) as exc:
            m.collect_sources(Args(), {"input": str(tmp_path / "nope.txt")})

        assert "Input file not found" in str(exc.value)

    def test_read_song_file_skips_comments(self, tmp_path):
        songs = tmp_path / "songs.txt"
        songs.write_text("# comment\n\nA - B\nbroken line\nC - D\n", encoding="utf-8")

        parsed, skipped = m.read_song_file(songs)

        assert parsed == [("A", "B"), ("C", "D")]
        assert skipped == ["broken line"]
