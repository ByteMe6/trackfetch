import json
import subprocess

import pytest

import trackfetch as m


def completed(stdout="", returncode=0, stderr=None):
    return subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def video(title, channel, video_id):
    return {"title": title, "channel": channel, "id": video_id}


OTEB_FIXTURE = [
    video("Отъебитесь от детей!", "Порнофильмы - Topic", "T-TbyB0mohE"),
    video("Отъебитесь от детей!", "Порнофильмы - Topic", "lwZPk1L3Wwc"),
    video(
        "Пор*нофильмы - Отъ*ебитесь от детей",
        "грусть",
        "pcwbFPg2sK0",
    ),
    video(
        "Порнофильмы – Отъебитесь от детей (live @ Yerevan, 19.07.2025)",
        "cherezovsky",
        "ExmGAc_tml0",
    ),
]

CHUZHOE_GORE_FIXTURE = [
    video("Порнофильмы - Чужое горе", "ПОРНОФИЛЬМЫ", "lCLRjh6N0k0"),
    video("Чужое горе", "Порнофильмы - Topic", "YRM8Eg967pc"),
    video(
        "Ирина Орлова «Чужое Горе» Крещенские Вечера 2013...",
        "Крещенские Вечера",
        "3jzEnSwNwHw",
    ),
    video(
        "Порнофильмы - Чужое горе (cover by A.Kopeiko)",
        "Anastasia Kopeiko",
        "Rx_ZGgNWr7k",
    ),
]

PRAVITELSTVO_FIXTURE = [
    video(
        "Порнофильмы - Не доверяйте правительству",
        None,
        "hL1oP9w2LZ8",
    ),
    video(
        "Порнофильмы - Не доверяйте правительству",
        "NA",
        "Zq6yYf3bJ1A",
    ),
]


class TestYoutubeThumbnailUrls:
    def test_thumbnail_field_is_used(self):
        assert m.youtube_thumbnail_urls({"thumbnail": "thumb"})[0] == "thumb"


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

    def test_close_duration_gets_a_bonus(self):
        exact = m.score_youtube_result(
            {"title": "Artist - Song", "duration": 320}, "Artist", "Song", 320
        )
        near = m.score_youtube_result(
            {"title": "Artist - Song", "duration": 320}, "Artist", "Song", 328
        )
        far = m.score_youtube_result(
            {"title": "Artist - Song", "duration": 320}, "Artist", "Song", 340
        )

        assert exact > near > far

    def test_artist_part_is_compared_with_artist(self):
        # "Artist - Song" should not be penalised for the trailing title.
        assert m.score_youtube_result(
            {"title": "Artist - Song"}, "Artist", "Song"
        ) == pytest.approx(1.0)

    def test_channel_name_prefix_does_not_inflate_a_cover(self):
        official = {"title": "Artist Song (Official Video)", "duration": 157}
        cover = {"title": "Some Channel “Artist - Song»", "duration": 144}

        assert m.score_youtube_result(
            official, "Artist", "Song", 157
        ) > m.score_youtube_result(cover, "Artist", "Song", 157)

    def test_title_suffix_still_matches_official_variants(self):
        exact = m.score_youtube_result(
            {"title": "Artist Song"}, "Artist", "Song"
        )
        noisy = m.score_youtube_result(
            {"title": "Artist Song (Official Audio)"}, "Artist", "Song"
        )

        assert noisy > exact

    def test_duration_without_video_duration_has_no_bonus(self):
        assert m.score_youtube_result(
            {"title": "Artist - Song"}, "Artist", "Song", 320
        ) == self.score("Artist - Song")

    def test_invalid_durations_are_ignored(self):
        assert m.score_youtube_result(
            {"title": "Artist - Song", "duration": "nope"},
            "Artist",
            "Song",
            320,
        ) == self.score("Artist - Song")

    def test_transliterated_artist_matches_cyrillic_title(self):
        latin = m.score_youtube_result(
            {"title": "Pornofilmy - Song"},
            "Pornofilmy",
            "Song",
        )
        cyrillic = m.score_youtube_result(
            {"title": "Порнофильмы - Песня"},
            "Pornofilmy",
            "Песня",
        )

        assert cyrillic == pytest.approx(latin)

    def test_transliterated_channel_matches_cyrillic_artist(self):
        topic = {
            "title": "Песня",
            "channel": "Порнофильмы - Topic",
        }
        no_channel = {"title": "Песня"}

        assert m.score_youtube_result(
            topic, "Pornofilmy", "Песня"
        ) > m.score_youtube_result(no_channel, "Pornofilmy", "Песня")

    def test_channel_matching_bonus(self):
        matching = {
            "title": "Song",
            "channel": "Artist",
        }
        other = {
            "title": "Song",
            "channel": "Someone Else",
        }

        assert m.score_youtube_result(
            matching, "Artist", "Song"
        ) > m.score_youtube_result(other, "Artist", "Song")

    def test_bad_words_are_whole_words_only(self):
        base = self.score("Artist - Song")
        discovery = self.score("Artist - Song Discovery")
        cover = self.score("Artist - Song cover")

        # "Discovery" contains "cover" but is not the word "cover".
        assert discovery > cover + 0.1
        assert cover < base - 0.1


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

    def test_nonzero_exit_raises_with_stderr(self, monkeypatch):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: completed("", returncode=1, stderr="boom"),
        )

        with pytest.raises(m.youtube.YoutubeSearchError) as exc:
            m.youtube_search("q")

        assert "boom" in str(exc.value)
        assert exc.value.stderr == "boom"


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
        calls = []

        def fake_search(query, limit):
            calls.append((query, limit))
            return []

        monkeypatch.setattr(m.youtube, "youtube_search", fake_search)
        monkeypatch.setattr(
            m.youtube,
            "youtube_music_search",
            lambda query, limit=8: [],
        )
        assert m.find_youtube_video("Artist", "Song") is None
        assert calls == [
            ("Artist Song", 5),
            ("Song", 5),
            ("Song Topic", 5),
        ]

    def test_single_search_when_first_rung_matches(self, monkeypatch):
        calls = []

        def fake_search(query, limit):
            calls.append(query)
            return [video("Artist - Song", "Artist - Topic", "abc")]

        monkeypatch.setattr(m.youtube, "youtube_search", fake_search)

        assert m.find_youtube_video("Artist", "Song")["id"] == "abc"
        assert calls == ["Artist Song"]

    def test_falls_back_to_title_query(self, monkeypatch):
        calls = []

        def fake_search(query, limit):
            calls.append(query)
            return [] if query == "Pornofilmy Отъебитесь от детей" else OTEB_FIXTURE

        monkeypatch.setattr(m.youtube, "youtube_search", fake_search)

        video_result = m.find_youtube_video(
            "Pornofilmy",
            "Отъебитесь от детей",
        )

        assert video_result["id"] in {"T-TbyB0mohE", "lwZPk1L3Wwc"}
        assert calls == [
            "Pornofilmy Отъебитесь от детей",
            "Отъебитесь от детей",
        ]

    def test_latin_artist_prefers_topic_upload(self, monkeypatch):
        monkeypatch.setattr(
            m.youtube,
            "youtube_search",
            lambda query, limit: OTEB_FIXTURE,
        )

        video_result = m.find_youtube_video(
            "Pornofilmy",
            "Отъебитесь от детей",
        )

        assert video_result["id"] in {"T-TbyB0mohE", "lwZPk1L3Wwc"}
        assert video_result["channel"] == "Порнофильмы - Topic"

    def test_never_selects_cover_or_other_artist(self, monkeypatch):
        monkeypatch.setattr(
            m.youtube,
            "youtube_search",
            lambda query, limit: CHUZHOE_GORE_FIXTURE,
        )

        video_result = m.find_youtube_video("Pornofilmy", "Чужое горе")

        assert video_result["id"] in {"YRM8Eg967pc", "lCLRjh6N0k0"}

    def test_missing_channel_uses_artist_in_title(self, monkeypatch):
        monkeypatch.setattr(
            m.youtube,
            "youtube_search",
            lambda query, limit: PRAVITELSTVO_FIXTURE,
        )

        video_result = m.find_youtube_video(
            "Pornofilmy",
            "Не доверяйте правительству",
        )

        assert video_result["id"] in {"hL1oP9w2LZ8", "Zq6yYf3bJ1A"}

    def test_title_only_results_without_artist_evidence_are_rejected(
        self, monkeypatch
    ):
        unrelated = [
            video("Чужое горе", "Someone Else", "nope1"),
            video("Чужое горе (Remastered)", "Another Band", "nope2"),
        ]

        def fake_search(query, limit):
            if query == "Pornofilmy Чужое горе":
                return []

            return unrelated

        monkeypatch.setattr(m.youtube, "youtube_search", fake_search)
        monkeypatch.setattr(
            m.youtube,
            "youtube_music_search",
            lambda query, limit=8: [],
        )

        assert m.find_youtube_video("Pornofilmy", "Чужое горе") is None
        assert m.youtube.LAST_SEARCH_HAD_CANDIDATES is True

    def test_title_only_result_with_close_duration_is_accepted(
        self, monkeypatch
    ):
        candidate = {
            "title": "Чужое горе",
            "channel": "Someone Else",
            "id": "duration",
            "duration": 201,
        }

        def fake_search(query, limit):
            if query == "Pornofilmy Чужое горе":
                return []

            return [candidate]

        monkeypatch.setattr(m.youtube, "youtube_search", fake_search)

        assert m.find_youtube_video(
            "Pornofilmy",
            "Чужое горе",
            200,
        ) is candidate

    def test_empty_artist_or_text_has_no_evidence(self):
        assert m.youtube._contains_artist("", "Song") is False
        assert m.youtube._contains_artist("Artist", "") is False

    def test_no_candidates_across_all_rungs(self, monkeypatch):
        monkeypatch.setattr(
            m.youtube,
            "youtube_search",
            lambda query, limit: [],
        )
        monkeypatch.setattr(
            m.youtube,
            "youtube_music_search",
            lambda query, limit=8: [],
        )

        assert m.find_youtube_video("Artist", "Song") is None
        assert m.youtube.LAST_SEARCH_HAD_CANDIDATES is False


class TestYoutubeMusicSearch:
    def test_builds_music_url_and_filters_non_video_ids(self, monkeypatch):
        calls = []
        rows = [
            {"id": "hkMC_uh7HQc", "title": "Власть"},
            {"id": "UCabc123456789012345678", "title": "Channel"},
            {"id": "MPREb_abcdefghijklmnopqrstuv", "title": "Album"},
            {"id": "VLPLabcdefghijklmnopqrstuvwx", "title": "Playlist"},
            {"id": "MPSPPLabcdefghijklmnopqrstuvwx", "title": "Mix"},
            {"id": "", "title": "No id"},
            "garbage",
        ]

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return completed("\n".join(json.dumps(row) for row in rows))

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = m.youtube_music_search("CG Bros Власть", limit=8)

        assert result == [{"id": "hkMC_uh7HQc", "title": "Власть"}]
        assert calls[0][-1] == (
            "https://music.youtube.com/search?q=CG+Bros+%D0%92%D0%BB%D0%B0%D1%81%D1%82%D1%8C#songs"
        )
        assert calls[0][calls[0].index("-I") + 1] == "1:8"
        assert "--flat-playlist" in calls[0]

    def test_default_limit(self, monkeypatch):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return completed("")

        monkeypatch.setattr(subprocess, "run", fake_run)
        assert m.youtube_music_search("q") == []
        assert calls[0][calls[0].index("-I") + 1] == f"1:{m.YOUTUBE_MUSIC_SEARCH_LIMIT}"

    def test_nonzero_exit_raises_with_stderr(self, monkeypatch):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: completed("", returncode=1, stderr="boom"),
        )

        with pytest.raises(m.youtube.YoutubeSearchError) as exc:
            m.youtube_music_search("q")

        assert "boom" in str(exc.value)
        assert exc.value.stderr == "boom"


class TestYoutubeVideoDetails:
    def test_returns_parsed_details(self, monkeypatch):
        calls = []
        payload = {"id": "hkMC_uh7HQc", "artist": "CG Bros"}

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return completed(json.dumps(payload))

        monkeypatch.setattr(subprocess, "run", fake_run)

        assert m.youtube_video_details("hkMC_uh7HQc") == payload
        assert calls[0][-1] == "https://www.youtube.com/watch?v=hkMC_uh7HQc"
        assert "--skip-download" in calls[0]
        assert "--no-playlist" in calls[0]
        assert "--dump-single-json" in calls[0]

    def test_nonzero_exit_raises(self, monkeypatch):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: completed("", returncode=1, stderr="nope"),
        )

        with pytest.raises(m.youtube.YoutubeSearchError):
            m.youtube_video_details("id")

    def test_invalid_json_raises(self, monkeypatch):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: completed("not json"),
        )

        with pytest.raises(m.youtube.YoutubeSearchError):
            m.youtube_video_details("id")


class TestYoutubeMusicFallback:
    def no_plain_results(self, monkeypatch):
        monkeypatch.setattr(
            m.youtube,
            "youtube_search",
            lambda query, limit: [],
        )

    def test_selects_verifiable_candidate_and_skips_bad_title(
        self, monkeypatch
    ):
        self.no_plain_results(monkeypatch)
        details_calls = []

        flat = [
            {"id": "hkMC_uh7HQc", "title": "Власть"},
            {"id": "6MWlIvHfplA", "title": "Смерть Или Свобода"},
        ]
        details = {
            "id": "hkMC_uh7HQc",
            "title": "Власть",
            "artist": "CG Bros",
            "duration": 195,
        }

        monkeypatch.setattr(
            m.youtube,
            "youtube_music_search",
            lambda query, limit=8: flat,
        )

        def fake_details(video_id):
            details_calls.append(video_id)
            return details

        monkeypatch.setattr(m.youtube, "youtube_video_details", fake_details)

        result = m.find_youtube_video("CG Bros", "Власть", 195)

        assert result is details
        assert details_calls == ["hkMC_uh7HQc"]

    def test_unrelated_tracks_are_all_rejected(self, monkeypatch):
        self.no_plain_results(monkeypatch)

        flat = [
            {"id": "W831-GLcBKc", "title": "Life"},
            {"id": "PsV4dNC9CDc", "title": "Жёсткий секс"},
            {"id": "aQyPzGyxRrQ", "title": "Gemidos"},
            {"id": "uBPRDJYdipM", "title": "xx"},
            {"id": "0HU0XgSG15U", "title": "period sex"},
            {
                "id": "kKwUSV4fv7A",
                "title": "Best Porno Models With Silicon Boobs Have Big Orgy With This Track",
            },
            {"id": "3tqiirVFXnQ", "title": "Pure Pleasure"},
            {
                "id": "ZQzvLYbLYIE",
                "title": "Sex Machine (feat. Lady Gala)",
            },
        ]

        monkeypatch.setattr(
            m.youtube,
            "youtube_music_search",
            lambda query, limit=8: flat,
        )
        monkeypatch.setattr(
            m.youtube,
            "youtube_video_details",
            lambda video_id: {
                "id": video_id,
                "title": "Unrelated",
                "artist": "Someone Else",
                "duration": 200,
            },
        )

        assert m.find_youtube_video("Порнофильмы", "Вагина") is None
        assert m.youtube.LAST_SEARCH_HAD_CANDIDATES is True

    def test_not_called_when_a_plain_rung_matches(self, monkeypatch):
        music_calls = []

        monkeypatch.setattr(
            m.youtube,
            "youtube_search",
            lambda query, limit: [video("Artist - Song", "Artist", "abc")],
        )
        monkeypatch.setattr(
            m.youtube,
            "youtube_music_search",
            lambda query, limit=8: music_calls.append(query) or [],
        )

        assert m.find_youtube_video("Artist", "Song")["id"] == "abc"
        assert music_calls == []

    def test_not_called_when_a_plain_rung_fails(self, monkeypatch):
        music_calls = []

        def failing_search(query, limit):
            raise m.youtube.YoutubeSearchError("boom")

        monkeypatch.setattr(m.youtube, "youtube_search", failing_search)
        monkeypatch.setattr(
            m.youtube,
            "youtube_music_search",
            lambda query, limit=8: music_calls.append(query) or [],
        )

        with pytest.raises(m.youtube.YoutubeSearchError):
            m.find_youtube_video("Artist", "Song")

        assert music_calls == []

    def test_empty_music_result_returns_none(self, monkeypatch):
        self.no_plain_results(monkeypatch)
        monkeypatch.setattr(
            m.youtube,
            "youtube_music_search",
            lambda query, limit=8: [],
        )

        assert m.find_youtube_video("Artist", "Song") is None
        assert m.youtube.LAST_SEARCH_HAD_CANDIDATES is False

    def test_failing_details_call_skips_to_the_next(self, monkeypatch):
        self.no_plain_results(monkeypatch)

        flat = [
            {"id": "aaaaaaaaaaa", "title": "Song"},
            {"id": "bbbbbbbbbbb", "title": "Song"},
        ]
        second = {
            "id": "bbbbbbbbbbb",
            "title": "Song",
            "artist": "Artist",
            "duration": 200,
        }

        monkeypatch.setattr(
            m.youtube,
            "youtube_music_search",
            lambda query, limit=8: flat,
        )

        def fake_details(video_id):
            if video_id == "aaaaaaaaaaa":
                raise m.youtube.YoutubeSearchError("boom")

            return second

        monkeypatch.setattr(m.youtube, "youtube_video_details", fake_details)

        assert m.find_youtube_video("Artist", "Song", 200) is second

    def test_duration_mismatch_rejects(self, monkeypatch):
        self.no_plain_results(monkeypatch)

        monkeypatch.setattr(
            m.youtube,
            "youtube_music_search",
            lambda query, limit=8: [{"id": "aaaaaaaaaaa", "title": "Song"}],
        )
        monkeypatch.setattr(
            m.youtube,
            "youtube_video_details",
            lambda video_id: {
                "id": video_id,
                "title": "Song",
                "artist": "Artist",
                "duration": 260,
            },
        )

        assert m.find_youtube_video("Artist", "Song", 200) is None
        assert m.youtube.LAST_SEARCH_HAD_CANDIDATES is True

    def test_unknown_duration_does_not_reject(self, monkeypatch):
        self.no_plain_results(monkeypatch)

        monkeypatch.setattr(
            m.youtube,
            "youtube_music_search",
            lambda query, limit=8: [{"id": "aaaaaaaaaaa", "title": "Song"}],
        )
        monkeypatch.setattr(
            m.youtube,
            "youtube_video_details",
            lambda video_id: {
                "id": video_id,
                "title": "Song",
                "artist": "Artist",
            },
        )

        result = m.find_youtube_video("Artist", "Song", 200)

        assert result is not None
        assert result["id"] == "aaaaaaaaaaa"

    def test_artist_only_from_artists_list_is_accepted(self, monkeypatch):
        self.no_plain_results(monkeypatch)

        monkeypatch.setattr(
            m.youtube,
            "youtube_music_search",
            lambda query, limit=8: [{"id": "aaaaaaaaaaa", "title": "Song"}],
        )
        monkeypatch.setattr(
            m.youtube,
            "youtube_video_details",
            lambda video_id: {
                "id": video_id,
                "title": "Song",
                "artists": ["Someone", "Artist"],
            },
        )

        assert m.find_youtube_video("Artist", "Song") is not None

    def test_unverifiable_artist_is_rejected(self, monkeypatch):
        self.no_plain_results(monkeypatch)

        monkeypatch.setattr(
            m.youtube,
            "youtube_music_search",
            lambda query, limit=8: [{"id": "aaaaaaaaaaa", "title": "Song"}],
        )
        monkeypatch.setattr(
            m.youtube,
            "youtube_video_details",
            lambda video_id: {
                "id": video_id,
                "title": "Song",
                "channel": "Completely Different",
            },
        )

        assert m.find_youtube_video("Artist", "Song") is None

    def test_latin_artist_matches_cyrillic_details_artist(
        self, monkeypatch
    ):
        self.no_plain_results(monkeypatch)

        monkeypatch.setattr(
            m.youtube,
            "youtube_music_search",
            lambda query, limit=8: [
                {"id": "aaaaaaaaaaa", "title": "Вагина"}
            ],
        )
        monkeypatch.setattr(
            m.youtube,
            "youtube_video_details",
            lambda video_id: {
                "id": video_id,
                "title": "Вагина",
                "artist": "Порнофильмы",
            },
        )

        assert (
            m.find_youtube_video("Pornofilmy", "Вагина") is not None
        )

    def test_best_scored_candidate_wins(self, monkeypatch):
        self.no_plain_results(monkeypatch)

        flat = [
            {"id": "aaaaaaaaaaa", "title": "Song"},
            {"id": "bbbbbbbbbbb", "title": "Song"},
        ]
        details = {
            "aaaaaaaaaaa": {
                "id": "aaaaaaaaaaa",
                "title": "Song",
                "channel": "Someone Else",
            },
            "bbbbbbbbbbb": {
                "id": "bbbbbbbbbbb",
                "title": "Song",
                "channel": "Artist - Topic",
            },
        }

        monkeypatch.setattr(
            m.youtube,
            "youtube_music_search",
            lambda query, limit=8: flat,
        )
        monkeypatch.setattr(
            m.youtube,
            "youtube_video_details",
            lambda video_id: details[video_id],
        )

        result = m.find_youtube_video("Artist", "Song")

        assert result["id"] == "bbbbbbbbbbb"


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

    def test_audio_quality_is_passed_to_ytdlp(self, monkeypatch, tmp_path):
        def fake_run(cmd):
            assert cmd[cmd.index("--audio-quality") + 1] == "7"
            (tmp_path / "audio.mp3").write_bytes(b"x")
            return completed()

        monkeypatch.setattr(subprocess, "run", fake_run)

        assert m.download_audio("u", tmp_path, "mp3", 7) == tmp_path / "audio.mp3"

    def test_ignores_files_in_other_formats(self, monkeypatch, tmp_path):
        def fake_run(cmd):
            (tmp_path / "audio.webm").write_bytes(b"x")
            return completed()

        monkeypatch.setattr(subprocess, "run", fake_run)
        assert m.download_audio("u", tmp_path, "opus") is None
