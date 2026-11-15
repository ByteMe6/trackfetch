import pytest
from conftest import FakeSpotify, make_track

import trackfetch as m


class TestGetSpotify:
    def test_returns_none_without_credentials(self, monkeypatch, capsys):
        monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
        monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)

        assert m.get_spotify() is None
        assert capsys.readouterr().out == ""

    def test_returns_none_with_only_one_credential(self, monkeypatch):
        monkeypatch.setenv("SPOTIFY_CLIENT_ID", "id")
        monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)

        assert m.get_spotify() is None

    def test_builds_client(self, monkeypatch):
        monkeypatch.setenv("SPOTIFY_CLIENT_ID", "id")
        monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "secret")
        assert isinstance(m.get_spotify(), m.spotipy.Spotify)


class TestFindSpotifyTrack:
    def test_strict_query_format(self):
        sp = FakeSpotify([make_track()])
        m.find_spotify_track(sp, "Daft Punk", "One More Time")
        assert sp.queries == ['artist:"Daft Punk" track:"One More Time"']

    def test_picks_best_match_not_first(self):
        wrong = make_track("One More Time (Live)", ["Someone Else"])
        right = make_track("One More Time", ["Daft Punk"])
        sp = FakeSpotify([wrong, right])
        assert m.find_spotify_track(sp, "Daft Punk", "One More Time") is right

    def test_falls_back_to_loose_search(self):
        track = make_track("One More Time", ["Daft Punk"])
        sp = FakeSpotify([], [track])
        assert m.find_spotify_track(sp, "Daft Punk", "One More Time") is track
        assert sp.queries[1] == "Daft Punk One More Time"

    def test_none_when_nothing_found(self):
        assert m.find_spotify_track(FakeSpotify([], []), "x", "y") is None

    def test_none_when_strict_search_errors(self, capsys):
        sp = FakeSpotify(RuntimeError("boom"))
        assert m.find_spotify_track(sp, "x", "y") is None
        assert "Spotify search error" in capsys.readouterr().out

    def test_none_when_fallback_errors(self):
        assert m.find_spotify_track(FakeSpotify([], RuntimeError("boom")), "x", "y") is None


class TestGetTrackMetadata:
    def test_fallback_without_track(self):
        assert m.get_track_metadata(None, "Artist", "Title") == {
            "artist": "Artist",
            "title": "Title",
            "album": "",
            "album_artist": "Artist",
            "track_number": None,
            "release_date": None,
            "cover_url": None,
        }

    def test_full_track(self):
        track = make_track(
            "Song",
            ["A", "B"],
            album="LP",
            album_artists=["A"],
            track_number=7,
            release_date="1999",
            images=[{"url": "big"}, {"url": "small"}],
        )
        assert m.get_track_metadata(track, "x", "y") == {
            "artist": "A, B",
            "title": "Song",
            "album": "LP",
            "album_artist": "A",
            "track_number": 7,
            "release_date": "1999",
            "cover_url": "big",
        }

    def test_album_artist_defaults_to_artist(self):
        track = make_track(artists=["A", "B"], album_artists=[])
        assert m.get_track_metadata(track, "x", "y")["album_artist"] == "A, B"

    def test_no_images(self):
        assert m.get_track_metadata(make_track(images=[]), "x", "y")["cover_url"] is None
