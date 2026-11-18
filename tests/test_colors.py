import sys
import types

import pytest

from trackfetch import colors


class FakeStream:
    def __init__(self, tty):
        self.tty = tty

    def isatty(self):
        return self.tty


def plain_environment(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("COLORTERM", raising=False)
    monkeypatch.setenv("TERM", "xterm")


class TestDefaults:
    def test_default_theme_and_mode(self):
        assert colors.DEFAULT_THEME == "cassette"
        assert colors.DEFAULT_COLOR_MODE == "auto"
        assert colors.get_theme() == "cassette"
        assert colors.get_color_mode() == "auto"

    def test_built_in_themes(self):
        assert colors.theme_names() == (
            "cassette",
            "neon-tape",
            "mono",
            "vinyl",
        )
        assert colors.is_builtin_theme("cassette")
        assert not colors.is_builtin_theme("mine")


class TestMode:
    def test_never_is_plain_even_on_a_tty(self):
        colors.set_color_mode("never")

        assert colors.paint("x", "accent", stream=FakeStream(True)) == "x"

    def test_always_colors_redirected_output(self, monkeypatch):
        plain_environment(monkeypatch)
        colors.set_color_mode("always")

        assert "\x1b[" in colors.paint("x", "accent", stream=FakeStream(False))

    def test_auto_needs_a_tty(self, monkeypatch):
        plain_environment(monkeypatch)
        colors.set_color_mode("auto")

        assert colors.paint("x", "accent", stream=FakeStream(False)) == "x"
        assert "\x1b[" in colors.paint("x", "accent", stream=FakeStream(True))

    def test_auto_respects_no_color(self, monkeypatch):
        plain_environment(monkeypatch)
        monkeypatch.setenv("NO_COLOR", "1")

        assert colors.paint("x", "accent", stream=FakeStream(True)) == "x"

    def test_auto_respects_dumb_terminal(self, monkeypatch):
        plain_environment(monkeypatch)
        monkeypatch.setenv("TERM", "dumb")

        assert colors.paint("x", "accent", stream=FakeStream(True)) == "x"

    def test_always_ignores_no_color(self, monkeypatch):
        plain_environment(monkeypatch)
        monkeypatch.setenv("NO_COLOR", "1")
        colors.set_color_mode("always")

        assert "\x1b[" in colors.paint("x", "accent", stream=FakeStream(False))

    def test_stream_without_isatty_is_plain(self, monkeypatch):
        plain_environment(monkeypatch)

        assert colors.paint("x", "accent", stream=object()) == "x"

    def test_stream_with_broken_isatty_is_plain(self, monkeypatch):
        plain_environment(monkeypatch)

        class Broken:
            def isatty(self):
                raise ValueError("closed")

        assert colors.paint("x", "accent", stream=Broken()) == "x"

    def test_invalid_mode(self):
        with pytest.raises(ValueError, match="Invalid color mode"):
            colors.set_color_mode("sometimes")


class TestDepth:
    def test_ansi_16(self, monkeypatch):
        plain_environment(monkeypatch)
        colors.set_color_mode("always")

        assert "\x1b[36m" in colors.paint("x", "accent")

    def test_ansi_256(self, monkeypatch):
        monkeypatch.setenv("TERM", "xterm-256color")
        monkeypatch.delenv("COLORTERM", raising=False)
        colors.set_color_mode("always")

        assert "\x1b[38;5;73m" in colors.paint("x", "accent")

    def test_truecolor(self, monkeypatch):
        monkeypatch.setenv("TERM", "xterm-256color")
        monkeypatch.setenv("COLORTERM", "truecolor")
        colors.set_color_mode("always")

        assert "\x1b[38;2;77;182;172m" in colors.paint("x", "accent")


class TestPaint:
    def test_no_styles_returns_text(self):
        assert colors.paint("x") == "x"

    def test_text_role_has_no_color(self, monkeypatch):
        plain_environment(monkeypatch)
        colors.set_color_mode("always")

        assert colors.paint("x", "text") == "x"

    def test_attributes_combine(self, monkeypatch):
        plain_environment(monkeypatch)
        colors.set_color_mode("always")

        assert colors.paint("x", "bold", "underline").startswith("\x1b[1;4m")

    def test_invalid_style(self, monkeypatch):
        plain_environment(monkeypatch)
        colors.set_color_mode("always")

        with pytest.raises(ValueError, match="Unknown color style"):
            colors.paint("x", "sparkles")

    def test_all_helpers(self, monkeypatch):
        plain_environment(monkeypatch)
        colors.set_color_mode("always")

        helpers = (
            colors.accent,
            colors.accent_bright,
            colors.progress,
            colors.success,
            colors.warning,
            colors.error,
            colors.skip,
            colors.muted,
            colors.frame,
            colors.heading,
            colors.label,
            colors.bold,
        )

        for helper in helpers:
            assert "\x1b[" in helper("x")


class TestThemes:
    def test_set_theme(self):
        colors.set_theme("vinyl")

        assert colors.get_theme() == "vinyl"

    def test_theme_name_is_case_insensitive(self):
        colors.set_theme("Neon-Tape")

        assert colors.get_theme() == "neon-tape"

    def test_invalid_theme(self):
        with pytest.raises(ValueError, match="Unknown color theme"):
            colors.set_theme("missing")

    def test_register_theme(self, monkeypatch):
        plain_environment(monkeypatch)
        colors.set_color_mode("always")
        palette = {
            role: dict(colors.THEMES["cassette"][role])
            for role in colors.ROLES
        }
        palette["accent"] = {"16": 31, "256": 196, "truecolor": (255, 0, 0)}

        colors.register_theme("mine", palette)
        colors.set_theme("mine")
        monkeypatch.setenv("COLORTERM", "truecolor")

        assert "mine" in colors.theme_names()
        assert colors.get_theme() == "mine"
        assert "\x1b[38;2;255;0;0m" in colors.paint("x", "accent")

    def test_custom_theme_can_be_reloaded(self):
        palette = {
            role: dict(colors.THEMES["cassette"][role])
            for role in colors.ROLES
        }

        colors.register_theme("mine", palette)
        colors.register_theme("mine", palette)

        assert "mine" in colors.theme_names()

    def test_builtin_name_cannot_be_overridden(self):
        palette = {
            role: dict(colors.THEMES["cassette"][role])
            for role in colors.ROLES
        }

        with pytest.raises(ValueError, match="is built in"):
            colors.register_theme("cassette", palette)

    def test_register_requires_all_roles(self):
        with pytest.raises(ValueError, match="missing"):
            colors.register_theme("mine", {})

    def test_register_rejects_bad_entry(self):
        palette = {
            role: dict(colors.THEMES["cassette"][role])
            for role in colors.ROLES
        }
        palette["accent"] = 31

        with pytest.raises(ValueError, match="invalid value"):
            colors.register_theme("mine", palette)


class TestWindows:
    def test_windows_ansi_is_enabled(self, monkeypatch):
        class Mode:
            value = 0

        class Kernel32:
            mode = None

            def GetStdHandle(self, handle):
                return 7

            def GetConsoleMode(self, handle, mode):
                mode.value = 0
                return 1

            def SetConsoleMode(self, handle, mode):
                self.mode = mode
                return 1

        kernel32 = Kernel32()
        fake_ctypes = types.SimpleNamespace(
            windll=types.SimpleNamespace(kernel32=kernel32),
            c_uint32=Mode,
            byref=lambda value: value,
        )
        monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)
        monkeypatch.setattr(colors.os, "name", "nt")
        colors._windows_ansi_ready = False

        colors._enable_windows_ansi()

        assert kernel32.mode == 0x4

    def test_windows_setup_is_best_effort(self, monkeypatch):
        class BrokenKernel32:
            def GetStdHandle(self, handle):
                raise OSError("no console")

        fake_ctypes = types.SimpleNamespace(
            windll=types.SimpleNamespace(kernel32=BrokenKernel32()),
            c_uint32=object,
            byref=lambda value: value,
        )
        monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)
        monkeypatch.setattr(colors.os, "name", "nt")
        colors._windows_ansi_ready = False

        colors._enable_windows_ansi()

        assert colors._windows_ansi_ready
