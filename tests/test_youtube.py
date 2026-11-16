import json
import subprocess

import pytest

import trackfetch as m


def completed(stdout="", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout)


class TestScoreYoutubeResult:
    def score(self, title, artist="Artist", song="Song"):
        return m.score_youtube_result({"title": title}, artist, song)

    def test_official_audio_bonus(self):
        # Same-length titles, so only the bonus differs.
        bonus = self.score("Artist - Song (Official Audio)") - self.score(
            "Artist - Song (Official Video)"
        )
        assert bonus == pytest.approx(0.08 + 0.03)

    def test_audio_bonus(self):
        assert self.score("Song audio") > self.score("Song video")

    @pytest.mark.parametrize(
        "word",
        ["cover", "karaoke", "караоке", "nightcore", "sped up", "slowed", "remix", "reaction"],
    )
    def test_penalised_words(self, word):
        assert self.score(f"Artist - Song {word}") < self.score("Artist - Song") - 0.1

    def test_penalties_stack(self):
        assert self.score("Song cover remix") < self.score("Song cover")

    def test_missing_title(self):
        assert isinstance(m.score_youtube_result({}, "Artist", "Song"), float)


class TestYoutubeSearch:
    def test_parses_json_lines_and_skips_garbage(self, monkeypatch):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            lines = [json.dumps({"id": "a"}), "WARNING: noise", json.dumps({"id": "b"})]
            return completed("\n".join(lines))

        monkeypatch.setattr(subprocess, "run", fake_run)
        assert m.youtube_search("q", limit=3) == [{"id": "a"}, {"id": "b"}]
        assert calls[0][0] == "yt-dlp"
        assert calls[0][-1] == "ytsearch3:q"
        assert "--flat-playlist" in calls[0]

    def test_empty_output(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: completed(""))
        assert m.youtube_search("q") == []


class TestFindYoutubeVideo:
    def test_selects_highest_score(self, monkeypatch):
        videos = [
            {"title": "Artist - Song (Karaoke)"},
            {"title": "Artist - Song (Official Audio)"},
            {"title": "Totally different"},
        ]
        monkeypatch.setattr(m.youtube, "youtube_search", lambda q, limit: videos)
        assert m.find_youtube_video("Artist", "Song") is videos[1]

    def test_query_and_limit(self, monkeypatch):
        seen = {}

        def fake_search(query, limit):
            seen.update(query=query, limit=limit)
            return []

        monkeypatch.setattr(m.youtube, "youtube_search", fake_search)
        assert m.find_youtube_video("Artist", "Song") is None
        assert seen == {"query": "Artist Song", "limit": 5}


class TestDownloadAudio:
    def test_success(self, monkeypatch, tmp_path):
        def fake_run(cmd):
            assert cmd[0] == "yt-dlp"
            assert cmd[-1] == "https://youtu.be/x"
            assert ["--audio-format", "mp3"] == cmd[cmd.index("--audio-format") :][:2]
            assert "--no-playlist" in cmd
            (tmp_path / "audio.mp3").write_bytes(b"mp3")
            return completed()

        monkeypatch.setattr(subprocess, "run", fake_run)
        assert m.download_audio("https://youtu.be/x", tmp_path) == tmp_path / "audio.mp3"

    def test_nonzero_exit(self, monkeypatch, tmp_path):
        monkeypatch.setattr(subprocess, "run", lambda cmd: completed(returncode=1))
        assert m.download_audio("u", tmp_path) is None

    def test_no_output_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(subprocess, "run", lambda cmd: completed())
        assert m.download_audio("u", tmp_path) is None

    @pytest.mark.parametrize(
        ("audio_format", "selector"),
        [
            ("mp3", None),
            ("m4a", "bestaudio[ext=m4a]/bestaudio"),
            ("opus", "bestaudio[acodec=opus]/bestaudio"),
        ],
    )
    def test_format_arguments(self, monkeypatch, tmp_path, audio_format, selector):
        def fake_run(cmd):
            assert cmd[cmd.index("--audio-format") + 1] == audio_format
            if selector:
                assert cmd[cmd.index("-f") + 1] == selector
            else:
                assert "-f" not in cmd
            (tmp_path / f"audio.{audio_format}").write_bytes(b"x")
            return completed()

        monkeypatch.setattr(subprocess, "run", fake_run)
        expected = tmp_path / f"audio.{audio_format}"
        assert m.download_audio("u", tmp_path, audio_format) == expected

    def test_ignores_files_in_other_formats(self, monkeypatch, tmp_path):
        def fake_run(cmd):
            (tmp_path / "audio.webm").write_bytes(b"x")
            return completed()

        monkeypatch.setattr(subprocess, "run", fake_run)
        assert m.download_audio("u", tmp_path, "opus") is None
