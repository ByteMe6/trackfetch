import base64
import shutil

import pytest
import requests
from conftest import FIXTURES
from mutagen.flac import Picture
from mutagen.id3 import ID3, TIT2
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggopus import OggOpus

import trackfetch as m

JPEG = b"\xff\xd8\xff\xe0fake-jpeg"
PNG = b"\x89PNG\r\n\x1a\nfake-png"
GIF = b"GIF89afake-gif"
WEBP = b"RIFF\x00\x00\x00\x00WEBPfake-webp"
INVALID_IMAGE = b"<html>not an image</html>"


@pytest.fixture
def mp3(tmp_path):
    path = tmp_path / "song.mp3"
    path.write_bytes(b"\x00" * 64)
    return path


class TestAddMetadata:
    def test_writes_all_frames(self, mp3, tmp_path, metadata):
        cover = tmp_path / "cover.jpg"
        cover.write_bytes(JPEG)
        m.add_metadata(mp3, cover, metadata)

        tags = ID3(mp3)
        assert tags.version[:2] == (2, 3)
        assert tags["TIT2"].text == ["One More Time"]
        assert tags["TPE1"].text == ["Daft Punk"]
        assert tags["TALB"].text == ["Discovery"]
        assert tags["TPE2"].text == ["Daft Punk"]
        assert tags["TRCK"].text == ["1"]
        assert str(tags["TDRC"].text[0]) == "2001-03-12"
        apic = tags.getall("APIC")[0]
        assert apic.data == JPEG
        assert apic.type == 3
        assert apic.mime == "image/jpeg"

    def test_skips_empty_optional_fields(self, mp3, tmp_path):
        meta = m.get_track_metadata(None, "Artist", "Title")
        meta["album_artist"] = ""
        m.add_metadata(mp3, tmp_path / "missing.jpg", meta)

        tags = ID3(mp3)
        assert tags["TIT2"].text == ["Title"]
        for frame in ("TALB", "TPE2", "TRCK", "TDRC", "APIC"):
            assert not tags.getall(frame), frame

    def test_replaces_existing_tags(self, mp3, tmp_path, metadata):
        old = ID3()
        old.add(TIT2(encoding=3, text="Old title"))
        old.save(mp3)

        m.add_metadata(mp3, tmp_path / "missing.jpg", metadata)
        assert ID3(mp3).getall("TIT2")[0].text == ["One More Time"]

    def test_unicode(self, mp3, tmp_path, metadata):
        metadata.update(artist="Korol i Shut", title="Мёртвый Анархист")
        m.add_metadata(mp3, tmp_path / "missing.jpg", metadata)
        assert ID3(mp3)["TIT2"].text == ["Мёртвый Анархист"]


@pytest.fixture
def cover(tmp_path):
    path = tmp_path / "cover.jpg"
    path.write_bytes(JPEG)
    return path


@pytest.fixture
def opus(tmp_path):
    path = tmp_path / "song.opus"
    shutil.copy(FIXTURES / "silence.opus", path)
    return path


@pytest.fixture
def m4a(tmp_path):
    path = tmp_path / "song.m4a"
    shutil.copy(FIXTURES / "silence.m4a", path)
    return path


def opus_picture(tags):
    return Picture(base64.b64decode(tags["METADATA_BLOCK_PICTURE"][0]))


class TestAddOpusMetadata:
    def test_writes_all_fields(self, opus, cover, metadata):
        m.add_metadata(opus, cover, metadata)

        tags = OggOpus(opus)
        assert tags["TITLE"] == ["One More Time"]
        assert tags["ARTIST"] == ["Daft Punk"]
        assert tags["ALBUM"] == ["Discovery"]
        assert tags["ALBUMARTIST"] == ["Daft Punk"]
        assert tags["TRACKNUMBER"] == ["1"]
        assert tags["DATE"] == ["2001-03-12"]
        picture = opus_picture(tags)
        assert picture.data == JPEG
        assert picture.type == 3
        assert picture.mime == "image/jpeg"

    def test_skips_empty_optional_fields(self, opus, tmp_path):
        meta = m.get_track_metadata(None, "Artist", "Title")
        meta["album_artist"] = ""
        m.add_metadata(opus, tmp_path / "missing.jpg", meta)

        tags = OggOpus(opus)
        assert tags["TITLE"] == ["Title"]
        for key in ("ALBUM", "ALBUMARTIST", "TRACKNUMBER", "DATE", "METADATA_BLOCK_PICTURE"):
            assert key not in tags, key

    def test_replaces_existing_tags(self, opus, cover, metadata):
        m.add_metadata(opus, cover, {**metadata, "title": "Old title"})
        m.add_metadata(opus, cover, metadata)

        tags = OggOpus(opus)
        assert tags["TITLE"] == ["One More Time"]
        assert len(tags["METADATA_BLOCK_PICTURE"]) == 1

    def test_audio_stays_readable(self, opus, cover, metadata):
        m.add_metadata(opus, cover, metadata)
        assert OggOpus(opus).info.length > 0


class TestAddM4aMetadata:
    def test_writes_all_fields(self, m4a, cover, metadata):
        m.add_metadata(m4a, cover, metadata)

        tags = MP4(m4a)
        assert tags["\xa9nam"] == ["One More Time"]
        assert tags["\xa9ART"] == ["Daft Punk"]
        assert tags["\xa9alb"] == ["Discovery"]
        assert tags["aART"] == ["Daft Punk"]
        assert tags["trkn"] == [(1, 0)]
        assert tags["\xa9day"] == ["2001-03-12"]
        assert bytes(tags["covr"][0]) == JPEG
        assert tags["covr"][0].imageformat == MP4Cover.FORMAT_JPEG

    def test_skips_empty_optional_fields(self, m4a, tmp_path):
        meta = m.get_track_metadata(None, "Artist", "Title")
        meta["album_artist"] = ""
        m.add_metadata(m4a, tmp_path / "missing.jpg", meta)

        tags = MP4(m4a)
        assert tags["\xa9nam"] == ["Title"]
        for key in ("\xa9alb", "aART", "trkn", "\xa9day", "covr"):
            assert key not in tags, key

    def test_replaces_existing_tags(self, m4a, cover, metadata):
        m.add_metadata(m4a, cover, {**metadata, "title": "Old title", "track_number": 9})
        m.add_metadata(m4a, cover, metadata)

        tags = MP4(m4a)
        assert tags["\xa9nam"] == ["One More Time"]
        assert tags["trkn"] == [(1, 0)]
        assert len(tags["covr"]) == 1


class TestDownloadCover:
    def test_writes_bytes(self, monkeypatch, tmp_path):
        class Response:
            content = JPEG

            def raise_for_status(self):
                pass

        seen = {}

        def fake_get(url, timeout, headers):
            seen.update(url=url, timeout=timeout)
            return Response()

        monkeypatch.setattr(requests, "get", fake_get)
        dest = tmp_path / "cover.jpg"
        m.download_cover("https://img/x.jpg", dest)
        assert dest.read_bytes() == JPEG
        assert seen == {"url": "https://img/x.jpg", "timeout": 30}

    def test_raises_on_http_error(self, monkeypatch, tmp_path):
        class Response:
            def raise_for_status(self):
                raise requests.HTTPError("404")

        monkeypatch.setattr(requests, "get", lambda *a, **k: Response())
        with pytest.raises(requests.HTTPError):
            m.download_cover("u", tmp_path / "c.jpg")


class TestDoneFile:
    def test_missing_file(self, tmp_path):
        assert m.read_done(tmp_path / "done.txt") == set()

    def test_append_and_read_roundtrip(self, tmp_path):
        done = tmp_path / "done.txt"
        m.append_line(done, "A - B")
        m.append_line(done, "Кино - Группа крови")
        assert done.read_text(encoding="utf-8") == "A - B\nКино - Группа крови\n"
        assert m.read_done(done) == {"A - B", "Кино - Группа крови"}

    def test_ignores_blank_lines_and_whitespace(self, tmp_path):
        done = tmp_path / "done.txt"
        done.write_text("  A - B  \n\n\nC - D\n", encoding="utf-8")
        assert m.read_done(done) == {"A - B", "C - D"}


class TestCoverFormatMimeTypes:
    @pytest.mark.parametrize(
        ("data", "mime"),
        [
            (JPEG, "image/jpeg"),
            (PNG, "image/png"),
            (GIF, "image/gif"),
            (WEBP, "image/webp"),
        ],
    )
    def test_mp3_embeds_matching_mime(self, mp3, tmp_path, metadata, data, mime):
        cover = tmp_path / "cover.img"
        cover.write_bytes(data)

        m.add_metadata(mp3, cover, metadata)

        apic = ID3(mp3).getall("APIC")[0]
        assert apic.data == data
        assert apic.mime == mime

    def test_mp3_skips_invalid_cover(self, mp3, tmp_path, metadata):
        cover = tmp_path / "cover.img"
        cover.write_bytes(INVALID_IMAGE)

        m.add_metadata(mp3, cover, metadata)

        assert not ID3(mp3).getall("APIC")

    @pytest.mark.parametrize(
        ("data", "mime"),
        [
            (JPEG, "image/jpeg"),
            (PNG, "image/png"),
            (GIF, "image/gif"),
            (WEBP, "image/webp"),
        ],
    )
    def test_opus_embeds_matching_mime(self, opus, tmp_path, metadata, data, mime):
        cover = tmp_path / "cover.img"
        cover.write_bytes(data)

        m.add_metadata(opus, cover, metadata)

        picture = opus_picture(OggOpus(opus))
        assert picture.data == data
        assert picture.mime == mime

    def test_opus_skips_invalid_cover(self, opus, tmp_path, metadata):
        cover = tmp_path / "cover.img"
        cover.write_bytes(INVALID_IMAGE)

        m.add_metadata(opus, cover, metadata)

        assert "METADATA_BLOCK_PICTURE" not in OggOpus(opus)

    @pytest.mark.parametrize(
        ("data", "image_format"),
        [
            (JPEG, MP4Cover.FORMAT_JPEG),
            (PNG, MP4Cover.FORMAT_PNG),
        ],
    )
    def test_m4a_embeds_supported_formats(
        self, m4a, tmp_path, metadata, data, image_format
    ):
        cover = tmp_path / "cover.img"
        cover.write_bytes(data)

        m.add_metadata(m4a, cover, metadata)

        covr = MP4(m4a)["covr"][0]
        assert bytes(covr) == data
        assert covr.imageformat == image_format

    @pytest.mark.parametrize("data", [GIF, WEBP, INVALID_IMAGE])
    def test_m4a_does_not_mislabel_unsupported_formats(
        self, m4a, tmp_path, metadata, data
    ):
        cover = tmp_path / "cover.img"
        cover.write_bytes(data)

        m.add_metadata(m4a, cover, metadata)

        assert "covr" not in MP4(m4a)
