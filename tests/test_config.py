import argparse
import configparser
import shutil
import sys
from pathlib import Path

import pytest
from conftest import FIXTURES, make_track

import trackfetch as m


@pytest.fixture
def pipeline(monkeypatch):
    state = {
        "track": make_track("One More Time", ["Daft Punk"], album="Discovery", track_number=1),
        "video": {"title": "Daft Punk - One More Time (Official Audio)", "id": "abc"},
        "formats": [],
    }

    def fake_download_audio(url, temp_dir, audio_format="mp3"):
        state["formats"].append(audio_format)
        path = temp_dir / f"audio.{audio_format}"
        if audio_format == "mp3":
            path.write_bytes(b"\x00" * 64)
        else:
            shutil.copy(FIXTURES / f"silence.{audio_format}", path)
        return path

    def fake_download_cover(url, dest):
        dest.write_bytes(b"\xff\xd8\xff\xe0jpeg")

    monkeypatch.setattr(m, "find_spotify_track", lambda sp, a, t: state["track"])
    monkeypatch.setattr(m, "find_youtube_video", lambda a, t: state["video"])
    monkeypatch.setattr(m, "download_audio", fake_download_audio)
    monkeypatch.setattr(m, "download_cover", fake_download_cover)
    monkeypatch.setattr(m, "get_spotify", lambda *a, **k: object())
    monkeypatch.setattr(m.time, "sleep", lambda s: None)
    return state


def run_cli(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["trackfetch", *map(str, args)])
    m.main()


def write_config(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


class TestConfigLookup:
    def test_no_config_file_returns_empty_settings(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty"))
        monkeypatch.delenv("TRACKFETCH_CONFIG", raising=False)
        monkeypatch.setattr(m.Path, "home", classmethod(lambda cls: tmp_path / "home"))

        settings, path = m.load_config()

        assert settings == {}
        assert path is None

    def test_explicit_config_file_is_used(self, tmp_path):
        config = write_config(tmp_path / "custom.ini", "[trackfetch]\noutput = /tmp/x\n")

        settings, path = m.load_config(config)

        assert settings["output"] == "/tmp/x"
        assert path == config

    def test_missing_explicit_config_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            m.load_config(tmp_path / "nope.ini")

    def test_config_in_current_directory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.delenv("TRACKFETCH_CONFIG", raising=False)
        monkeypatch.setattr(m.Path, "home", classmethod(lambda cls: tmp_path / "home"))
        write_config(tmp_path / m.CONFIG_FILENAME, "[trackfetch]\noutput = /tmp/from-cwd\n")

        settings, path = m.load_config()

        assert settings["output"] == "/tmp/from-cwd"
        assert path == tmp_path / m.CONFIG_FILENAME

    def test_config_in_xdg_directory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("TRACKFETCH_CONFIG", raising=False)
        monkeypatch.setattr(m.Path, "home", classmethod(lambda cls: tmp_path / "home"))
        xdg = tmp_path / "xdg"
        write_config(xdg / "trackfetch" / m.CONFIG_FILENAME, "[trackfetch]\noutput = /tmp/xdg\n")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

        settings, path = m.load_config()

        assert settings["output"] == "/tmp/xdg"

    def test_env_var_points_to_config(self, tmp_path, monkeypatch):
        config = write_config(tmp_path / "env.ini", "[trackfetch]\noutput = /tmp/env\n")
        monkeypatch.setenv("TRACKFETCH_CONFIG", str(config))

        settings, path = m.load_config()

        assert settings["output"] == "/tmp/env"

    def test_invalid_config_file_raises(self, tmp_path):
        config = write_config(tmp_path / "bad.ini", "not an ini file at all\n")

        with pytest.raises(configparser.Error):
            m.load_config(config)


class TestResolveOutput:
    def test_flag_wins_over_config(self, tmp_path):
        settings = {"output": str(tmp_path / "from-config")}

        result = m.resolve_output(tmp_path / "from-flag", settings)

        assert result == tmp_path / "from-flag"

    def test_config_used_when_no_flag(self, tmp_path):
        settings = {"output": str(tmp_path / "from-config")}

        result = m.resolve_output(None, settings)

        assert result == tmp_path / "from-config"

    def test_current_directory_is_the_last_resort(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        assert m.resolve_output(None, {}) == tmp_path
        assert m.resolve_output(None, {"output": "  "}) == tmp_path

    def test_tilde_is_expanded(self):
        result = m.resolve_output(None, {"output": "~/Music/x"})

        assert result == Path.home() / "Music" / "x"


class TestSpotifyCredentials:
    def test_env_is_used_when_config_is_silent(self, monkeypatch):
        monkeypatch.setenv("SPOTIFY_CLIENT_ID", "env-id")
        monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "env-secret")

        client_id, client_secret = m.spotify_credentials()

        assert (client_id, client_secret) == ("env-id", "env-secret")

    def test_config_wins_over_env(self, monkeypatch):
        monkeypatch.setenv("SPOTIFY_CLIENT_ID", "env-id")
        monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "env-secret")
        settings = {
            "spotify_client_id": "config-id",
            "spotify_client_secret": "config-secret",
        }

        parser = argparse.ArgumentParser()
        parser.add_argument("--spotify-client-id", default=None)
        parser.add_argument("--spotify-client-secret", default=None)
        args = parser.parse_args([])
        m.apply_config(args, parser, settings)
        client_id, client_secret = m.spotify_credentials(args)

        assert (client_id, client_secret) == ("config-id", "config-secret")

    def test_flag_wins_over_config_and_env(self, monkeypatch):
        monkeypatch.setenv("SPOTIFY_CLIENT_ID", "env-id")
        monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "env-secret")
        parser = argparse.ArgumentParser()
        parser.add_argument("--spotify-client-id", default=None)
        parser.add_argument("--spotify-client-secret", default=None)
        args = parser.parse_args(
            ["--spotify-client-id", "flag-id", "--spotify-client-secret", "flag-secret"]
        )
        settings = {
            "spotify_client_id": "config-id",
            "spotify_client_secret": "config-secret",
        }

        m.apply_config(args, parser, settings)

        client_id, client_secret = m.spotify_credentials(args)

        assert (client_id, client_secret) == ("flag-id", "flag-secret")

    def test_missing_credentials_exit(self, monkeypatch, capsys):
        monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
        monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)

        with pytest.raises(SystemExit) as exc:
            m.get_spotify()

        assert exc.value.code == 1
        assert "Spotify credentials not found" in capsys.readouterr().out


class TestMainWithConfig:
    def test_config_output_is_used(self, pipeline, monkeypatch, tmp_path):
        songs = tmp_path / "songs.txt"
        songs.write_text("Daft Punk - One More Time\n", encoding="utf-8")
        out = tmp_path / "from-config"
        config = write_config(tmp_path / "cfg.ini", f"[trackfetch]\noutput = {out}\n")

        run_cli(monkeypatch, songs, "--config", config)

        assert (out / "Daft Punk - One More Time.m4a").exists()

    def test_flag_overrides_config(self, pipeline, monkeypatch, tmp_path):
        songs = tmp_path / "songs.txt"
        songs.write_text("Daft Punk - One More Time\n", encoding="utf-8")
        config_out = tmp_path / "from-config"
        flag_out = tmp_path / "from-flag"
        config = write_config(tmp_path / "cfg.ini", f"[trackfetch]\noutput = {config_out}\n")

        run_cli(monkeypatch, songs, "--config", config, "-o", flag_out)

        assert (flag_out / "Daft Punk - One More Time.m4a").exists()
        assert not config_out.exists()

    def test_current_directory_is_used_without_config(self, pipeline, monkeypatch, tmp_path):
        songs = tmp_path / "songs.txt"
        songs.write_text("Daft Punk - One More Time\n", encoding="utf-8")
        workdir = tmp_path / "work"
        workdir.mkdir()
        monkeypatch.chdir(workdir)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.delenv("TRACKFETCH_CONFIG", raising=False)
        monkeypatch.setattr(m.Path, "home", classmethod(lambda cls: tmp_path / "home"))

        run_cli(monkeypatch, songs)

        assert (workdir / "Daft Punk - One More Time.m4a").exists()

    def test_invalid_config_file_exits(self, monkeypatch, tmp_path, capsys):
        songs = tmp_path / "songs.txt"
        songs.write_text("A - B\n", encoding="utf-8")
        config = write_config(tmp_path / "bad.ini", "not an ini file at all\n")

        with pytest.raises(SystemExit) as exc:
            run_cli(monkeypatch, songs, "--config", config)

        assert exc.value.code == 1
        assert "Invalid config file" in capsys.readouterr().out

    def test_invalid_value_in_config_exits(self, monkeypatch, tmp_path, capsys):
        songs = tmp_path / "songs.txt"
        songs.write_text("A - B\n", encoding="utf-8")
        config = write_config(tmp_path / "cfg.ini", "[trackfetch]\ndelay = abc\n")

        with pytest.raises(SystemExit) as exc:
            run_cli(monkeypatch, songs, "--config", config)

        assert exc.value.code == 1
        assert "Invalid value for 'delay' in config file" in capsys.readouterr().out

    def test_missing_input_file_exits(self, monkeypatch, tmp_path, capsys):
        with pytest.raises(SystemExit) as exc:
            run_cli(monkeypatch)

        assert exc.value.code == 1
        assert "No input" in capsys.readouterr().out

    def test_input_can_come_from_the_config(self, pipeline, monkeypatch, tmp_path):
        songs = tmp_path / "songs.txt"
        songs.write_text("Daft Punk - One More Time\n", encoding="utf-8")
        out = tmp_path / "o"
        config = write_config(
            tmp_path / "cfg.ini", f"[trackfetch]\ninput = {songs}\noutput = {out}\n"
        )

        run_cli(monkeypatch, "--config", config)

        assert (out / "Daft Punk - One More Time.m4a").exists()

    def test_missing_explicit_config_exits(self, monkeypatch, tmp_path, capsys):
        songs = tmp_path / "songs.txt"
        songs.write_text("A - B\n", encoding="utf-8")

        with pytest.raises(SystemExit) as exc:
            run_cli(monkeypatch, songs, "--config", tmp_path / "nope.ini")

        assert exc.value.code == 1
        assert "Config file not found" in capsys.readouterr().out

    def test_format_from_config(self, pipeline, monkeypatch, tmp_path):
        songs = tmp_path / "songs.txt"
        songs.write_text("Daft Punk - One More Time\n", encoding="utf-8")
        out = tmp_path / "o"
        config = write_config(
            tmp_path / "cfg.ini", f"[trackfetch]\noutput = {out}\nformat = opus\n"
        )

        run_cli(monkeypatch, songs, "--config", config)

        assert (out / "Daft Punk - One More Time.opus").exists()
        assert pipeline["formats"] == ["opus"]

    def test_unknown_format_in_config_exits(self, monkeypatch, tmp_path, capsys):
        songs = tmp_path / "songs.txt"
        songs.write_text("A - B\n", encoding="utf-8")
        config = write_config(tmp_path / "cfg.ini", "[trackfetch]\nformat = flac\n")

        with pytest.raises(SystemExit) as exc:
            run_cli(monkeypatch, songs, "--config", config)

        assert exc.value.code == 1
        assert "Unknown value for 'format' in config file" in capsys.readouterr().out

    def test_title_only_from_config(self, pipeline, monkeypatch, tmp_path):
        songs = tmp_path / "songs.txt"
        songs.write_text("Daft Punk - One More Time\n", encoding="utf-8")
        out = tmp_path / "o"
        config = write_config(
            tmp_path / "cfg.ini", f"[trackfetch]\noutput = {out}\ntitle_only = true\n"
        )

        run_cli(monkeypatch, songs, "--config", config)

        assert (out / "One More Time.m4a").exists()

    def test_delay_from_config(self, pipeline, monkeypatch, tmp_path):
        songs = tmp_path / "songs.txt"
        songs.write_text("A - 1\nA - 2\n", encoding="utf-8")
        out = tmp_path / "o"
        config = write_config(tmp_path / "cfg.ini", f"[trackfetch]\noutput = {out}\ndelay = 2.5\n")
        sleeps = []
        monkeypatch.setattr(m.time, "sleep", sleeps.append)

        run_cli(monkeypatch, songs, "--config", config)

        assert sleeps == [2.5]

    def test_config_path_is_reported(self, pipeline, monkeypatch, tmp_path, capsys):
        songs = tmp_path / "songs.txt"
        songs.write_text("Daft Punk - One More Time\n", encoding="utf-8")
        out = tmp_path / "o"
        config = write_config(tmp_path / "cfg.ini", f"[trackfetch]\noutput = {out}\n")

        run_cli(monkeypatch, songs, "--config", config)
        log = capsys.readouterr().out

        assert f"Config: {config}" in log
        assert f"Output: {out}" in log
