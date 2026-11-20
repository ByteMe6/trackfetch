import json
import subprocess

import pytest

import trackfetch as m
from trackfetch import soundcloud
from trackfetch.errors import SoundcloudError

# Captured before the autouse fixture replaces the module attribute.
real_details = soundcloud.soundcloud_track_details


def completed(stdout="", returncode=0, stderr=None):
    return subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def entry(
    track_id="1",
    title="Artist - Song",
    duration=200,
    uploader="Artist",
    artist=None,
    **extra,
):
    data = {
        "id": track_id,
        "title": title,
        "track": title,
        "duration": duration,
        "uploader": uploader,
        "webpage_url": f"https://soundcloud.com/{uploader}/{track_id}",
    }

    if artist is not None:
        data["artist"] = artist
        data["artists"] = [artist]

    data.update(extra)
    return data


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Keep every test independent from live SoundCloud and yt-dlp."""
    soundcloud.reset_attempts()
    monkeypatch.setattr(
        soundcloud,
        "soundcloud_track_details",
        lambda url: {},
    )

    yield

    soundcloud.reset_attempts()


class TestAgeRestrictionDetection:
    @pytest.mark.parametrize(
        "text",
        [
            (
                "ERROR: [youtube] NyHj69Be_fY: Sign in to confirm your age. "
                "This video may be inappropriate for some users."
            ),
            "ERROR: This video is age-restricted",
            "age_verification_required",
            "AGE_CHECK_REQUIRED",
            "This video is inappropriate for some users",
            "YouTube requires age verification",
        ],
    )
    def test_detects_age_restriction(self, text):
        assert m.is_age_restriction_error(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "",
            None,
            "ERROR: [youtube] x: Video unavailable",
            "ERROR: [youtube] x: Private video. Sign in if you've been granted access",
            "ERROR: [youtube] x: Sign in to confirm you're not a bot",
            "ERROR: Unable to download webpage: <urlopen error timed out>",
            "ERROR: [youtube] x: 403 Forbidden",
            "ERROR: [soundcloud] x: HTTP Error 404: Not Found",
            "ERROR: Invalid URL: nope",
        ],
    )
    def test_ignores_other_errors(self, text):
        assert m.is_age_restriction_error(text) is False

    def test_probe_detects_age_restriction_from_stderr(self, monkeypatch):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: completed(
                returncode=1,
                stderr="ERROR: Sign in to confirm your age",
            ),
        )

        assert m.probe_age_restriction("https://youtu.be/x") is True

    def test_probe_ignores_success_and_other_failures(self, monkeypatch):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: completed(json.dumps({"id": "x"})),
        )
        assert m.probe_age_restriction("https://youtu.be/x") is False

        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: completed(
                returncode=1,
                stderr="ERROR: Video unavailable",
            ),
        )
        assert m.probe_age_restriction("https://youtu.be/x") is False

    def test_probe_timeout_is_not_an_age_restriction(self, monkeypatch):
        def fake_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="yt-dlp", timeout=1)

        monkeypatch.setattr(subprocess, "run", fake_run)

        assert m.probe_age_restriction("https://youtu.be/x") is False

    def test_probe_without_url_does_nothing(self, monkeypatch):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: pytest.fail("must not run"),
        )

        assert m.probe_age_restriction("") is False

    def test_probe_command_does_not_use_cookies_or_auth(self, monkeypatch):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return completed(returncode=1, stderr="Sign in to confirm your age")

        monkeypatch.setattr(subprocess, "run", fake_run)
        m.probe_age_restriction("https://youtu.be/x")

        assert "--cookies" not in calls[0]
        assert "--cookies-from-browser" not in calls[0]
        assert "--username" not in calls[0]
        assert "--skip-download" in calls[0]


class TestSearchParsing:
    def test_parses_flat_playlist_lines_and_skips_garbage(self, monkeypatch):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            lines = [
                json.dumps(entry("1", "Artist - Song")),
                "WARNING: not json",
                json.dumps(entry("2", "Artist - Other")),
            ]
            return completed("\n".join(lines))

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = m.soundcloud_search("Artist Song", limit=5)

        assert [item["id"] for item in result] == ["1", "2"]
        assert calls[0][0] == "yt-dlp"
        assert calls[0][-1] == "scsearch5:Artist Song"
        assert "--flat-playlist" in calls[0]
        assert "--dump-json" in calls[0]

    def test_default_limit(self, monkeypatch):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return completed("")

        monkeypatch.setattr(subprocess, "run", fake_run)

        assert m.soundcloud_search("q") == []
        assert calls[0][-1] == f"scsearch{m.SOUNDCLOUD_SEARCH_LIMIT}:q"

    def test_empty_query_never_calls_ytdlp(self, monkeypatch):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: pytest.fail("must not run"),
        )

        assert m.soundcloud_search("   ") == []

    def test_nonzero_exit_raises_with_stderr(self, monkeypatch):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: completed(returncode=1, stderr="boom"),
        )

        with pytest.raises(SoundcloudError) as exc:
            m.soundcloud_search("q")

        assert "boom" in str(exc.value)

    def test_timeout_raises_soundcloud_error(self, monkeypatch):
        def fake_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="yt-dlp", timeout=1)

        monkeypatch.setattr(subprocess, "run", fake_run)

        with pytest.raises(SoundcloudError):
            m.soundcloud_search("q")

    def test_parse_search_result_uses_track_title_and_artists(self):
        parsed = m.parse_search_result(
            entry(
                "850231564",
                "Михаил Елизаров - Горбачев",
                duration=161.9,
                artist="Михаил Елизаров",
            )
        )

        assert parsed["id"] == "850231564"
        assert parsed["title"] == "Михаил Елизаров - Горбачев"
        assert parsed["artist"] == "Михаил Елизаров"
        assert parsed["artists"] == ["Михаил Елизаров"]
        assert parsed["duration"] == pytest.approx(161.9)

    def test_parse_search_result_rejects_missing_identity(self):
        assert m.parse_search_result({"title": "No id"}) is None
        assert m.parse_search_result({"id": "1"}) is None
        assert m.parse_search_result("garbage") is None
        assert m.parse_search_result({"id": "1", "title": "x"}) is not None

    def test_parse_search_result_sanitizes_bad_values(self):
        parsed = m.parse_search_result(
            {
                "id": 42,
                "track": "Song",
                "duration": "nope",
                "artists": ["A", "", 3, None],
                "webpage_url": "https://soundcloud.com/a/b",
            }
        )

        assert parsed["id"] == "42"
        assert parsed["duration"] is None
        assert parsed["artists"] == ["A"]

    def test_negative_and_boolean_durations_are_unusable(self):
        assert m.parse_search_result(entry(duration=-5))["duration"] is None
        assert m.parse_search_result(entry(duration=True))["duration"] is None
        assert m.parse_search_result(entry(duration=0))["duration"] is None

    def test_merge_details_overlays_metadata(self):
        candidate = m.parse_search_result(entry("1", "Artist - Song", duration=100))
        merged = m.merge_details(
            candidate,
            {
                "duration": 201.4,
                "artist": "Artist",
                "artists": ["Artist"],
                "license": "all-rights-reserved",
            },
        )

        assert merged["duration"] == pytest.approx(201.4)
        assert merged["artist"] == "Artist"
        assert merged["title"] == "Artist - Song"

class TestNormalizationAndScoring:
    def test_artist_prefix_is_accepted(self):
        scored = m.score_candidate(
            m.parse_search_result(entry(title="Artist - Song")),
            "Artist",
            "Song",
            200,
        )

        assert scored["title_score"] == pytest.approx(1.0)
        assert scored["reject_reason"] is None

    def test_official_audio_suffix_is_accepted(self):
        scored = m.score_candidate(
            m.parse_search_result(entry(title="Song (Official Audio)")),
            "Artist",
            "Song",
            200,
        )

        assert scored["title_score"] >= 0.8
        assert scored["reject_reason"] is None

    def test_case_punctuation_and_whitespace_are_ignored(self):
        scored = m.score_candidate(
            m.parse_search_result(entry(title="ARTIST  -  Song!!!")),
            "artist",
            "song",
            200,
        )

        assert scored["title_score"] == pytest.approx(1.0)
        assert scored["artist_score"] >= 0.9

    def test_featuring_suffix_does_not_break_the_match(self):
        assert m.score_candidate(
            m.parse_search_result(entry(title="Song (feat. Guest)")),
            "Artist",
            "Song",
        )["title_score"] >= 0.8

    def test_cyrillic_and_latin_forms_match(self):
        scored = m.score_candidate(
            m.parse_search_result(
                entry(title="Порнофильмы - Песня", artist="Порнофильмы")
            ),
            "Pornofilmy",
            "Песня",
        )

        assert scored["artist_score"] >= 0.9

    def test_missing_duration_is_not_a_rejection(self):
        candidate = m.parse_search_result(entry(duration=None))
        scored = m.score_candidate(candidate, "Artist", "Song", 200)

        assert scored["duration_score"] is None
        assert scored["reject_reason"] is None

    def test_missing_expected_duration_is_not_a_rejection(self):
        scored = m.score_candidate(
            m.parse_search_result(entry(duration=200)),
            "Artist",
            "Song",
            None,
        )

        assert scored["duration_score"] is None
        assert scored["reject_reason"] is None

    def test_duration_scores_fall_off_with_distance(self):
        exact = m.duration_score({"duration": 200}, 200)
        near = m.duration_score({"duration": 208}, 200)
        loose = m.duration_score({"duration": 220}, 200)
        far = m.duration_score({"duration": 320}, 200)

        assert exact == 1.0
        assert exact > near > loose > far
        assert far == 0.0

    def test_non_positive_candidate_duration_is_invalid(self):
        assert m.duration_score({"duration": -1}, 200) is None
        assert m.duration_score({"duration": 0}, 200) is None

    def test_title_similarity_dominates_the_weighting(self):
        good_title = m.score_candidate(
            m.parse_search_result(entry(title="Wrong Artist - Song", uploader="X")),
            "Artist",
            "Song",
            200,
        )
        wrong_title = m.score_candidate(
            m.parse_search_result(entry(title="Artist - Different", uploader="X")),
            "Artist",
            "Song",
            200,
        )

        assert good_title["score"] > wrong_title["score"]

    def test_unrelated_track_is_rejected_for_its_title(self):
        scored = m.score_candidate(
            m.parse_search_result(entry(title="Artist - Another Song")),
            "Artist",
            "Song",
            200,
        )

        assert scored["reject_reason"] == "title does not match"

    def test_candidate_without_a_title_is_rejected(self):
        scored = m.score_candidate(
            {"title": "", "duration": 200},
            "Artist",
            "Song",
            200,
        )

        assert scored["reject_reason"] == "no title metadata"


class TestPreviewRejection:
    def test_30_second_preview_of_a_long_track_is_rejected(self):
        candidate = m.parse_search_result(
            entry(title="Горбачёв", duration=30, artist="Михаил Елизаров")
        )
        reason = m.preview_reason(candidate, 161)

        assert reason == "shorter than the expected track"

    def test_preview_flag_is_honoured_without_durations(self):
        assert m.preview_reason({"is_preview": True}, None)

    def test_short_upload_without_expected_duration_is_rejected(self):
        assert m.preview_reason({"duration": 20}, None)

    def test_short_expected_track_is_not_a_preview(self):
        assert m.preview_reason({"duration": 30}, 30) is None

    def test_slightly_shorter_result_is_kept(self):
        assert m.preview_reason({"duration": 195}, 200) is None

    def test_far_too_long_result_is_rejected(self):
        assert m.preview_reason({"duration": 900}, 200)

    def test_unknown_durations_are_never_rejected(self):
        assert m.preview_reason({"duration": None}, None) is None
        assert m.preview_reason({"duration": None}, 200) is None
        assert m.preview_reason({"duration": 200}, None) is None

    def test_preview_is_ranked_below_the_full_track(self):
        preview = m.score_candidate(
            m.parse_search_result(
                entry("1", "Artist - Song", duration=30, artist="Artist")
            ),
            "Artist",
            "Song",
            200,
        )
        full = m.score_candidate(
            m.parse_search_result(entry("2", "Artist - Song", duration=200)),
            "Artist",
            "Song",
            200,
        )

        assert preview["reject_reason"]
        assert full["reject_reason"] is None
        # Duration is part of the score, so the full track wins as well.
        assert full["score"] > preview["score"]


class TestVersionRejection:
    @pytest.mark.parametrize(
        "suffix",
        [
            "(Remix)",
            "[Bootleg]",
            "(Cover)",
            "(Live at Brixton)",
            "(Instrumental)",
            "(Karaoke Version)",
            "(Nightcore)",
            "(Slowed + Reverb)",
            "(Acoustic)",
        ],
    )
    def test_alternate_versions_are_rejected(self, suffix):
        scored = m.score_candidate(
            m.parse_search_result(entry(title=f"Artist - Song {suffix}")),
            "Artist",
            "Song",
            200,
        )

        assert scored["reject_reason"]
        assert m.is_version_mismatch({"title": f"Song {suffix}"}, "Song")

    def test_requested_remix_is_not_rejected(self):
        scored = m.score_candidate(
            m.parse_search_result(entry(title="Artist - Song (Remix)")),
            "Artist",
            "Song (Remix)",
            200,
        )

        assert scored["reject_reason"] is None

    def test_plain_upload_is_not_a_version_mismatch(self):
        assert not m.is_version_mismatch({"title": "Artist - Song"}, "Song")

    def test_live_word_is_whole_word_only(self):
        assert not m.is_version_mismatch({"title": "Artist - Song Delivery"}, "Song")


class TestSelection:
    def test_high_confidence_match_is_selected_automatically(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            soundcloud,
            "soundcloud_search",
            lambda query, limit=5: [
                entry("850231564", "Artist - Song", duration=200),
                entry("2", "Artist - Other", duration=200),
            ],
        )

        result = soundcloud.find_soundcloud_fallback(
            "Artist",
            "Song",
            200,
            chooser=lambda items: pytest.fail("must not ask"),
        )

        assert result.selected
        assert result.candidate["id"] == "850231564"

    def test_ambiguous_results_require_a_choice(self):
        asked = []

        def fake_search(query, limit=5):
            return [
                entry("1", "Artist - Song", duration=200, uploader="Artist"),
                entry("2", "Artist - Song", duration=200, uploader="Artist"),
            ]

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(soundcloud, "soundcloud_search", fake_search)

        try:
            def chooser(items):
                asked.append([item["id"] for item in items])
                return None

            result = soundcloud.find_soundcloud_fallback(
                "Artist",
                "Song",
                200,
                chooser=chooser,
            )

        finally:
            monkeypatch.undo()

        assert not result.selected
        assert result.status == soundcloud.STATUS_AMBIGUOUS
        assert asked == [["1", "2"]]

    def test_user_choice_is_returned_as_selected(self):
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(
            soundcloud,
            "soundcloud_search",
            lambda query, limit=5: [
                entry("1", "Artist - Song", duration=200),
                entry("2", "Artist - Song", duration=200),
            ],
        )

        try:
            result = soundcloud.find_soundcloud_fallback(
                "Artist",
                "Song",
                200,
                chooser=lambda items: items[1],
            )

        finally:
            monkeypatch.undo()

        assert result.selected
        assert result.candidate["id"] == "2"

    def test_low_confidence_result_is_not_downloaded(self):
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(
            soundcloud,
            "soundcloud_search",
            lambda query, limit=5: [entry("1", "Artist - Song-ish", duration=200)],
        )

        try:
            result = soundcloud.find_soundcloud_fallback(
                "Artist",
                "A Completely Different Song",
                200,
                chooser=lambda items: pytest.fail("must not ask"),
            )

        finally:
            monkeypatch.undo()

        assert not result.selected
        assert result.status in {
            soundcloud.STATUS_LOW_CONFIDENCE,
            soundcloud.STATUS_NO_MATCH,
        }

    def test_no_results(self):
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(
            soundcloud,
            "soundcloud_search",
            lambda query, limit=5: [],
        )

        try:
            result = soundcloud.find_soundcloud_fallback("Artist", "Song", 200)

        finally:
            monkeypatch.undo()

        assert result.status == soundcloud.STATUS_NO_MATCH
        assert result.candidate is None

    def test_all_results_rejected_reports_no_match(self):
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(
            soundcloud,
            "soundcloud_search",
            lambda query, limit=5: [
                entry("1", "Artist - Song (Cover)", duration=200),
                entry("2", "Artist - Song", duration=40),
            ],
        )

        try:
            result = soundcloud.find_soundcloud_fallback(
                "Artist", "Song", 200, chooser=lambda items: None
            )

        finally:
            monkeypatch.undo()

        assert result.status == soundcloud.STATUS_NO_MATCH

    def test_search_failure_returns_error_status(self):
        monkeypatch = pytest.MonkeyPatch()

        def boom(query, limit=5):
            raise SoundcloudError("boom")

        monkeypatch.setattr(soundcloud, "soundcloud_search", boom)

        try:
            result = soundcloud.find_soundcloud_fallback("Artist", "Song", 200)

        finally:
            monkeypatch.undo()

        assert result.status == soundcloud.STATUS_ERROR
        assert result.error == "boom"
        assert m.describe_failure(result) == "SoundCloud search failed"

    def test_disabled_fallback_never_searches(self):
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(
            soundcloud,
            "soundcloud_search",
            lambda *a, **k: pytest.fail("must not search"),
        )

        try:
            result = soundcloud.find_soundcloud_fallback(
                "Artist", "Song", 200, enabled=False
            )

        finally:
            monkeypatch.undo()

        assert result.status == soundcloud.STATUS_DISABLED

    def test_duplicate_attempt_is_prevented(self):
        calls = []
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(
            soundcloud,
            "soundcloud_search",
            lambda query, limit=5: calls.append(query) or [],
        )

        try:
            first = soundcloud.find_soundcloud_fallback("Artist", "Song", 200)
            second = soundcloud.find_soundcloud_fallback("Artist", "Song", 200)

        finally:
            monkeypatch.undo()

        assert first.status == soundcloud.STATUS_NO_MATCH
        assert second.status == soundcloud.STATUS_DISABLED
        assert len(calls) == 1

    def test_configurable_thresholds_are_respected(self, monkeypatch):
        monkeypatch.setattr(
            soundcloud,
            "soundcloud_search",
            lambda query, limit=5: [entry("1", "Artist - Song", duration=200)],
        )

        strict = soundcloud.find_soundcloud_fallback(
            "Artist", "Song", 200, min_score=1.01
        )
        relaxed = soundcloud.find_soundcloud_fallback(
            "Artist", "Song", 200, min_score=0.1, attempt_key="relaxed"
        )

        assert strict.status == soundcloud.STATUS_LOW_CONFIDENCE
        assert relaxed.selected


class TestBlockedDownloads:
    def test_unstreamable_track_is_rejected(self):
        assert m.blocked_reason({"streamable": False}) == "not streamable"

    def test_uploader_disabled_download_is_honoured(self):
        assert (
            m.blocked_reason({"downloadable": False})
            == "downloads disabled by the uploader"
        )

    def test_blocked_policy_is_rejected(self):
        assert m.blocked_reason({"policy": "BLOCK"})

    def test_normal_track_is_not_blocked(self):
        assert m.blocked_reason({"policy": "ALLOW"}) is None
        assert m.blocked_reason({}) is None

    def test_formats_preview_is_detected(self):
        details = {
            "formats": [
                {"format_id": "preview-hls"},
                {"format_id": "http_mp3"},
            ]
        }
        assert m.is_formats_preview(details) is True

    def test_missing_formats_are_not_a_preview(self):
        assert m.is_formats_preview({}) is False
        assert m.is_formats_preview({"formats": None}) is False


class TestTrackDetails:
    def test_returns_parsed_details(self, monkeypatch):
        calls = []
        payload = {
            "id": "850231564",
            "title": "Михаил Елизаров - Горбачев",
            "duration": 161.901,
        }

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return completed(json.dumps(payload))

        monkeypatch.setattr(subprocess, "run", fake_run)

        assert real_details("https://soundcloud.com/a/b") == payload
        assert calls[0][-1] == "https://soundcloud.com/a/b"
        assert "--skip-download" in calls[0]
        assert "--dump-single-json" in calls[0]
        assert "--no-playlist" in calls[0]

    def test_nonzero_exit_raises(self, monkeypatch):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: completed(returncode=1, stderr="404"),
        )

        with pytest.raises(SoundcloudError):
            real_details("u")

    def test_invalid_json_raises(self, monkeypatch):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: completed("not json"),
        )

        with pytest.raises(SoundcloudError):
            real_details("u")

    def test_non_object_json_raises(self, monkeypatch):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: completed("[1, 2, 3]"),
        )

        with pytest.raises(SoundcloudError):
            real_details("u")

    def test_missing_url_raises_without_running(self, monkeypatch):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: pytest.fail("must not run"),
        )

        with pytest.raises(SoundcloudError):
            real_details("")

    def test_missing_ytdlp_binary_raises(self, monkeypatch):
        def fake_run(*args, **kwargs):
            raise FileNotFoundError("yt-dlp")

        monkeypatch.setattr(subprocess, "run", fake_run)

        with pytest.raises(SoundcloudError):
            real_details("u")


class TestPrompt:
    def test_non_interactive_stream_never_asks(self, capsys):
        class NotATty:
            def isatty(self):
                return False

        asked = []

        result = m.prompt_for_candidate(
            [{"title": "Song", "duration": 200}],
            input_func=lambda prompt: asked.append(prompt) or "1",
            stream=NotATty(),
        )

        assert result is None
        assert asked == []
        assert "1. Song" in capsys.readouterr().out

    def test_valid_choice_returns_candidate(self):
        class Tty:
            def isatty(self):
                return True

        candidates = [{"title": "First"}, {"title": "Second"}]

        assert m.prompt_for_candidate(
            candidates,
            input_func=lambda prompt: "2",
            stream=Tty(),
        ) is candidates[1]

    def test_empty_or_invalid_choice_skips(self):
        class Tty:
            def isatty(self):
                return True

        candidates = [{"title": "First"}]

        for answer in ("", "x", "0", "9"):
            assert (
                m.prompt_for_candidate(
                    candidates,
                    input_func=lambda prompt, a=answer: a,
                    stream=Tty(),
                )
                is None
            )

    def test_interrupt_skips(self):
        class Tty:
            def isatty(self):
                return True

        def interrupt(prompt):
            raise KeyboardInterrupt

        assert (
            m.prompt_for_candidate(
                [{"title": "First"}],
                input_func=interrupt,
                stream=Tty(),
            )
            is None
        )

    def test_no_candidates_returns_none(self):
        assert m.prompt_for_candidate([]) is None

    def test_duration_formatting(self):
        assert m.format_duration(161.4) == "2:41"
        assert m.format_duration(161.9) == "2:42"
        assert m.format_duration(5) == "0:05"
        assert m.format_duration(None) == "?:??"
        assert m.format_duration(-1) == "?:??"


class TestEdgeCases:
    def test_blank_search_line_is_skipped(self, monkeypatch):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: completed(
                "\n" + json.dumps(entry("1", "Artist - Song")) + "\n\n"
            ),
        )

        assert [item["id"] for item in m.soundcloud_search("q")] == ["1"]

    def test_merge_details_with_non_dict_returns_copy(self):
        candidate = {"title": "Song"}
        merged = m.merge_details(candidate, None)

        assert merged == candidate
        assert merged is not candidate

    def test_merge_details_marks_preview_flag(self):
        merged = m.merge_details({"title": "Song"}, {"preview": True})

        assert merged["is_preview"] is True

    def test_en_dash_artist_title_split(self):
        scored = m.score_candidate(
            m.parse_search_result(entry(title="Artist – Song")),
            "Artist",
            "Song",
            200,
        )

        assert scored["title_score"] == pytest.approx(1.0)
        assert scored["artist_score"] >= 0.9

    def test_empty_artist_name_does_not_strip_tokens(self):
        scored = m.score_candidate(
            m.parse_search_result(entry(title="Song")),
            "",
            "Song",
        )

        assert scored["title_score"] == pytest.approx(1.0)

    def test_empty_title_has_zero_title_score(self):
        assert m.score_candidate(
            {"title": "Song", "duration": 200},
            "Artist",
            "",
        )["title_score"] == 0.0

    def test_very_short_upload_is_rejected(self):
        assert m.preview_reason({"duration": 10}, 200)

    def test_longer_upload_within_ratio_is_kept(self):
        # 2:41 vs a 2:45 YouTube video is just metadata noise.
        assert m.preview_reason({"duration": 165}, 161) is None

    def test_live_stream_is_rejected(self):
        scored = m.score_candidate(
            {"title": "Artist - Song", "is_live": True, "duration": 200},
            "Artist",
            "Song",
            200,
        )

        assert scored["reject_reason"] == "live stream"

    def test_exact_margin_boundary_is_ambiguous(self):
        ranked = [
            {"score": 0.9, "reject_reason": None},
            {"score": 0.83, "reject_reason": None},
        ]

        assert m.select_candidate(ranked, min_margin=0.08)[1] == (
            soundcloud.STATUS_AMBIGUOUS
        )
        assert m.select_candidate(ranked, min_margin=0.05)[1] == (
            soundcloud.STATUS_SELECTED
        )

    def test_rejected_candidates_do_not_count_as_runner_up(self):
        ranked = [
            {"score": 0.9, "reject_reason": None},
            {"score": 0.89, "reject_reason": "remix, cover or another version"},
        ]

        assert m.select_candidate(ranked)[1] == soundcloud.STATUS_SELECTED

    def test_stream_without_isatty_is_not_interactive(self):
        class NoIsatty:
            pass

        assert (
            m.prompt_for_candidate([{"title": "Song"}], stream=NoIsatty())
            is None
        )

    def test_chooser_interrupt_is_handled(self, monkeypatch):
        monkeypatch.setattr(
            soundcloud,
            "soundcloud_search",
            lambda query, limit=5: [
                entry("1", "Artist - Song", duration=200),
                entry("2", "Artist - Song", duration=200),
            ],
        )

        def interrupt(items):
            raise KeyboardInterrupt

        result = soundcloud.find_soundcloud_fallback(
            "Artist", "Song", 200, chooser=interrupt
        )

        assert result.status == soundcloud.STATUS_AMBIGUOUS

    def test_describe_failure_for_none(self):
        assert m.describe_failure(None) == "SoundCloud fallback failed"

    def test_describe_failure_statuses(self):
        for status in (
            soundcloud.STATUS_NO_MATCH,
            soundcloud.STATUS_LOW_CONFIDENCE,
            soundcloud.STATUS_AMBIGUOUS,
            soundcloud.STATUS_ERROR,
            soundcloud.STATUS_DISABLED,
        ):
            assert m.describe_failure(
                soundcloud.FallbackResult(status)
            )

    def test_result_repr(self):
        result = soundcloud.FallbackResult(soundcloud.STATUS_NO_MATCH)

        assert "no-match" in repr(result)


class TestMetadataEnrichment:
    def test_details_are_fetched_for_each_candidate(self):
        calls = []

        def details(url):
            calls.append(url)
            return {"duration": 200, "license": "all-rights-reserved"}

        candidates = [entry("1", "Artist - Song"), entry("2", "Artist - Song")]

        enriched = m.fetch_candidate_details(candidates, details_func=details)

        assert len(calls) == 2
        assert all(item["license"] == "all-rights-reserved" for item in enriched)

    def test_enrichment_is_capped(self):
        calls = []

        def details(url):
            calls.append(url)
            return {}

        candidates = [entry(str(i), "Artist - Song") for i in range(5)]

        m.fetch_candidate_details(candidates, limit=2, details_func=details)

        assert len(calls) == 2

    def test_failed_details_keep_the_search_payload(self):
        def details(url):
            raise SoundcloudError("404")

        candidates = [entry("1", "Artist - Song", duration=200)]
        enriched = m.fetch_candidate_details(candidates, details_func=details)

        assert enriched[0]["title"] == "Artist - Song"
        assert enriched[0]["duration"] == 200

    def test_candidate_without_url_is_not_fetched(self):
        def details(url):
            pytest.fail("must not fetch")

        assert m.fetch_candidate_details(
            [{"title": "Song"}], details_func=details
        ) == [{"title": "Song"}]

    def test_preview_revealed_by_details_is_rejected_before_selection(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            soundcloud,
            "soundcloud_search",
            lambda query, limit=5: [
                entry("1", "Artist - Song", duration=200),
            ],
        )

        result = soundcloud.find_soundcloud_fallback(
            "Artist",
            "Song",
            200,
            details_func=lambda url: {"duration": 30},
            chooser=lambda items: pytest.fail("must not ask"),
            attempt_key="enrich-preview",
        )

        assert not result.selected
        assert result.status == soundcloud.STATUS_NO_MATCH

    def test_details_flag_disables_downloads(self, monkeypatch):
        monkeypatch.setattr(
            soundcloud,
            "soundcloud_search",
            lambda query, limit=5: [entry("1", "Artist - Song", duration=200)],
        )

        result = soundcloud.find_soundcloud_fallback(
            "Artist",
            "Song",
            200,
            details_func=lambda url: {"downloadable": False},
            chooser=lambda items: pytest.fail("must not ask"),
            attempt_key="enrich-blocked",
        )

        assert not result.selected


class TestLiveAndRemaster:
    @pytest.mark.parametrize(
        "suffix",
        ["(Live)", "(Live at Brixton)", "(Instrumental)", "(Cover)"],
    )
    def test_noise_bracket_versions_are_still_detected(self, suffix):
        # matching.normalize removes "(live)" and similar, so detection must
        # not rely on it.
        assert m.is_version_mismatch({"title": f"Song {suffix}"}, "Song")

    def test_remastered_is_not_a_version_mismatch(self):
        assert not m.is_version_mismatch({"title": "Song (Remastered)"}, "Song")

    def test_official_audio_is_not_a_version_mismatch(self):
        assert not m.is_version_mismatch(
            {"title": "Song (Official Audio)"}, "Song"
        )

    def test_remastered_candidate_is_still_accepted(self):
        scored = m.score_candidate(
            m.parse_search_result(entry(title="Artist - Song (Remastered)")),
            "Artist",
            "Song",
            200,
        )

        assert scored["reject_reason"] is None


class TestTransliteration:
    def test_latin_upload_of_a_cyrillic_title_matches(self):
        scored = m.score_candidate(
            m.parse_search_result(
                entry(
                    "850231564",
                    "Mikhail Elizarov - Gorbachev",
                    uploader="nuclear_gandhi",
                    duration=161,
                )
            ),
            "Михаил Елизаров",
            "Горбачёв",
            161,
        )

        assert scored["title_score"] >= 0.8
        assert scored["reject_reason"] is None

    def test_transliteration_variance_is_tolerated(self):
        # Unidecode renders ё as "iov"; an uploader typed "ev".
        scored = m.score_candidate(
            m.parse_search_result(
                entry("1", "Mikhail Elizarov - Gorbachev", uploader="x")
            ),
            "Михаил Елизаров",
            "Горбачёв",
            161,
        )

        assert scored["title_score"] >= 0.8

    def test_upload_suffix_after_a_latin_title_is_ignored(self):
        scored = m.score_candidate(
            m.parse_search_result(
                entry(
                    "1",
                    "Mikhail Elizarov - Gorbachev - Kissvk.com",
                    uploader="nuclear_gandhi",
                )
            ),
            "Михаил Елизаров",
            "Горбачёв",
            161,
        )

        assert scored["title_score"] >= 0.8
        assert scored["reject_reason"] is None

    def test_a_different_latin_title_is_still_rejected(self):
        scored = m.score_candidate(
            m.parse_search_result(
                entry(
                    "1",
                    "Mikhail Elizarov - Nekronomikon - Kissvk.com",
                    uploader="x",
                )
            ),
            "Михаил Елизаров",
            "Горбачёв",
            161,
        )

        assert scored["reject_reason"] == "title does not match"


class TestArtistSuffixes:
    def test_artist_with_an_upload_label_suffix(self):
        scored = m.score_candidate(
            m.parse_search_result(
                entry("1", "Some Uploader - Song", uploader="Some Uploader")
            ),
            "Artist",
            "Song",
        )

        # The artist does not match, but the title alone cannot carry it.
        assert scored["artist_score"] < 0.6
        assert scored["score"] < m.SOUNDCLOUD_MIN_SCORE


class TestTitleScoringInternals:
    def test_latin_tokens_that_match_exactly_are_used(self):
        # Both sides transliterate to the same tokens, so the contiguous
        # Latin path is what produces the score.
        scored = m.score_candidate(
            m.parse_search_result(entry("1", "Pornofilmy - Pesnia", uploader="x")),
            "Порнофильмы",
            "Песня",
        )

        assert scored["title_score"] >= 0.95

    def test_unrelated_same_script_title_scores_zero(self):
        scored = m.score_candidate(
            m.parse_search_result(entry("1", "Completely Different Words")),
            "Artist",
            "Song",
        )

        assert scored["title_score"] == 0.0

    def test_many_trailing_words_are_penalized(self):
        many = m.score_candidate(
            m.parse_search_result(
                entry("1", "Artist - Song one two three four")
            ),
            "Artist",
            "Song",
        )
        short_suffix = m.score_candidate(
            m.parse_search_result(entry("2", "Artist - Song bonus")),
            "Artist",
            "Song",
        )
        clean = m.score_candidate(
            m.parse_search_result(entry("3", "Artist - Song")),
            "Artist",
            "Song",
        )

        assert clean["title_score"] == pytest.approx(1.0)
        assert many["title_score"] < short_suffix["title_score"]
        assert many["title_score"] > 0.0


class TestFormatsPreviewMerge:
    def test_preview_format_is_flagged_during_merge(self):
        merged = m.merge_details(
            {"title": "Song", "duration": 200},
            {"formats": [{"format_id": "preview-hls"}]},
        )

        assert merged["is_preview"] is True
        assert m.preview_reason(merged, 200) == "marked as a preview"

    def test_normal_formats_are_not_flagged(self):
        merged = m.merge_details(
            {"title": "Song", "duration": 200},
            {"formats": [{"format_id": "http_mp3"}]},
        )

        assert not merged.get("is_preview")
