import sys
from pathlib import Path

import pytest

import trackfetch as m
from trackfetch import colors, themes


def write(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


class TestParsing:
    def test_minimal_theme_inherits_cassette(self, tmp_path):
        path = write(
            tmp_path / "themes.ini",
            "[mine]\naccent = #ff0000\n",
        )

        parsed = themes.parse_theme_file(path)

        assert parsed["mine"]["accent"] == {
            "16": 91,
            "256": 9,
            "truecolor": (255, 0, 0),
        }
        assert parsed["mine"]["success"] == colors.THEMES["cassette"]["success"]

    def test_short_hex(self, tmp_path):
        path = write(tmp_path / "themes.ini", "[mine]\nframe = #f80\n")

        parsed = themes.parse_theme_file(path)

        assert parsed["mine"]["frame"]["truecolor"] == (255, 136, 0)

    def test_named_color(self, tmp_path):
        path = write(tmp_path / "themes.ini", "[mine]\nwarning = bright-red\n")

        parsed = themes.parse_theme_file(path)

        assert parsed["mine"]["warning"]["16"] == 91
        assert parsed["mine"]["warning"]["truecolor"] == (255, 0, 0)

    def test_256_index(self, tmp_path):
        path = write(tmp_path / "themes.ini", "[mine]\nprogress = 196\n")

        parsed = themes.parse_theme_file(path)

        assert parsed["mine"]["progress"]["256"] == 196
        assert parsed["mine"]["progress"]["truecolor"] == (255, 0, 0)

    @pytest.mark.parametrize("value", ["default", "none", "terminal", ""])
    def test_terminal_default(self, tmp_path, value):
        path = write(tmp_path / "themes.ini", f"[mine]\ntext = {value}\n")

        parsed = themes.parse_theme_file(path)

        assert parsed["mine"]["text"] == {
            "16": None,
            "256": None,
            "truecolor": None,
        }

    def test_custom_base_defined_earlier(self, tmp_path):
        path = write(
            tmp_path / "themes.ini",
            "[first]\naccent = #112233\n"
            "\n[second]\nbase = first\nsuccess = #445566\n",
        )

        parsed = themes.parse_theme_file(path)

        assert parsed["second"]["accent"] == parsed["first"]["accent"]
        assert parsed["second"]["success"]["truecolor"] == (68, 85, 102)

    def test_builtin_name_is_reserved(self, tmp_path):
        path = write(tmp_path / "themes.ini", "[cassette]\naccent = #000000\n")

        with pytest.raises(ValueError, match="built in"):
            themes.parse_theme_file(path)

    def test_unknown_base(self, tmp_path):
        path = write(tmp_path / "themes.ini", "[mine]\nbase = missing\n")

        with pytest.raises(ValueError, match="unknown base"):
            themes.parse_theme_file(path)

    def test_unknown_option(self, tmp_path):
        path = write(tmp_path / "themes.ini", "[mine]\nsparkle = #ffffff\n")

        with pytest.raises(ValueError, match="unknown option"):
            themes.parse_theme_file(path)

    @pytest.mark.parametrize("value", ["#12", "#gg0000", "300", "ultraviolet"])
    def test_invalid_color(self, tmp_path, value):
        path = write(tmp_path / "themes.ini", f"[mine]\naccent = {value}\n")

        with pytest.raises(ValueError, match="Invalid color"):
            themes.parse_theme_file(path)

    def test_invalid_ini(self, tmp_path):
        path = write(tmp_path / "themes.ini", "not an ini file\n")

        with pytest.raises(ValueError, match="Invalid theme file"):
            themes.parse_theme_file(path)


class TestLoading:
    def test_missing_optional_file_is_ignored(self):
        assert themes.load_theme_file(None) == []
        assert themes.load_theme_file(Path("/does/not/exist")) == []

    def test_missing_required_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Theme file not found"):
            themes.load_theme_file(tmp_path / "missing.ini", required=True)

    def test_load_registers_themes(self, tmp_path):
        path = write(tmp_path / "themes.ini", "[mine]\naccent = #ff0000\n")

        names = themes.load_theme_file(path)

        assert names == ["mine"]
        assert "mine" in colors.theme_names()
        colors.set_theme("mine")
        assert colors.get_theme() == "mine"

    def test_find_theme_file_explicit(self, tmp_path):
        path = tmp_path / "custom.ini"

        assert themes.find_theme_file(path) == path

    def test_find_theme_file_next_to_config(self, tmp_path):
        config = tmp_path / "trackfetch.ini"

        assert themes.find_theme_file(None, config) == tmp_path / "themes.ini"

    def test_find_theme_file_in_config_locations(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("TRACKFETCH_CONFIG", raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
        path = write(tmp_path / "themes.ini", "[mine]\naccent = #ff0000\n")

        assert themes.find_theme_file() == path

    def test_find_theme_file_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("TRACKFETCH_CONFIG", raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))

        assert themes.find_theme_file() is None


class TestCli:
    def run(self, monkeypatch, *args):
        monkeypatch.setattr(sys, "argv", ["trackfetch", *map(str, args)])
        m.main()

    def test_custom_theme_through_config(self, tmp_path, monkeypatch, capsys):
        config = write(
            tmp_path / "trackfetch.ini",
            "[trackfetch]\ncolor = always\ncolor_theme = mine\n",
        )
        write(
            tmp_path / "themes.ini",
            "[mine]\naccent = #ff0000\n",
        )

        self.run(monkeypatch, "--config", config, "--list-sources")

        output = capsys.readouterr().out
        assert "\x1b[38;2;255;0;0m" in output

    def test_explicit_themes_file(self, tmp_path, monkeypatch, capsys):
        config = write(tmp_path / "trackfetch.ini", "[trackfetch]\n")
        theme_file = write(
            tmp_path / "custom.ini",
            "[mine]\naccent = #00ff00\n",
        )

        self.run(
            monkeypatch,
            "--config",
            config,
            "--themes-file",
            theme_file,
            "--color-theme",
            "mine",
            "--color",
            "always",
            "--list-sources",
        )

        assert "\x1b[38;2;0;255;0m" in capsys.readouterr().out

    def test_themes_file_from_config(self, tmp_path, monkeypatch, capsys):
        theme_file = write(
            tmp_path / "custom.ini",
            "[mine]\naccent = #0000ff\n",
        )
        config = write(
            tmp_path / "trackfetch.ini",
            "[trackfetch]\n"
            f"themes_file = {theme_file}\n"
            "color = always\n"
            "color_theme = mine\n",
        )

        self.run(monkeypatch, "--config", config, "--list-sources")

        assert "\x1b[38;2;0;0;255m" in capsys.readouterr().out

    def test_missing_explicit_themes_file_exits(self, tmp_path, monkeypatch, capsys):
        config = write(tmp_path / "trackfetch.ini", "[trackfetch]\n")

        with pytest.raises(SystemExit) as exc:
            self.run(
                monkeypatch,
                "--config",
                config,
                "--themes-file",
                tmp_path / "missing.ini",
                "--list-sources",
            )

        assert exc.value.code == 1
        assert "Theme file not found" in capsys.readouterr().out

    def test_unknown_theme_exits(self, tmp_path, monkeypatch, capsys):
        config = write(
            tmp_path / "trackfetch.ini",
            "[trackfetch]\ncolor_theme = missing\n",
        )

        with pytest.raises(SystemExit) as exc:
            self.run(monkeypatch, "--config", config, "--list-sources")

        assert exc.value.code == 1
        assert "Unknown color theme" in capsys.readouterr().out

    def test_no_color_flag_keeps_plain_output(self, tmp_path, monkeypatch, capsys):
        config = write(tmp_path / "trackfetch.ini", "[trackfetch]\n")

        self.run(
            monkeypatch,
            "--config",
            config,
            "--color",
            "never",
            "--list-sources",
        )

        assert "\x1b[" not in capsys.readouterr().out
