"""Tests for the pipeline module."""
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from tracksplit.models import AlbumMeta, Chapter, TrackMeta
from tracksplit.pipeline import build_intro_track, should_regenerate, _safe_log_name


# ---------------------------------------------------------------------------
# build_intro_track
# ---------------------------------------------------------------------------

class TestBuildIntroTrack:
    def test_intro_track_created(self):
        """First chapter starts after 0.0, so an intro track is created."""
        chapters = [
            Chapter(index=1, title="Track 1", start=30.0, end=120.0),
            Chapter(index=2, title="Track 2", start=120.0, end=240.0),
        ]
        result = build_intro_track(chapters)
        assert result is not None
        assert result.number == 0
        assert result.title == "Intro"
        assert result.start == 0.0
        assert result.end == 30.0

    def test_no_intro_when_starts_at_zero(self):
        """First chapter starts at 0.0, no intro needed."""
        chapters = [
            Chapter(index=1, title="Track 1", start=0.0, end=120.0),
        ]
        result = build_intro_track(chapters)
        assert result is None

    def test_empty_chapters(self):
        """Empty chapter list returns None."""
        result = build_intro_track([])
        assert result is None


# ---------------------------------------------------------------------------
# should_regenerate
# ---------------------------------------------------------------------------

class TestShouldRegenerate:
    def _write_manifest(self, album_dir, **overrides):
        from tracksplit.manifest import (
            ALBUM_MANIFEST_FILENAME, MANIFEST_SCHEMA,
        )
        data = {
            "schema": MANIFEST_SCHEMA,
            "source": {"path": overrides.get("source_path", "/x.mkv"),
                       "mtime_ns": overrides.get("mtime_ns", 1),
                       "size": overrides.get("size", 10),
                       "enriched_at": overrides.get("enriched_at", "")},
            "resolved_artist_folder": overrides.get("artist_folder", "A"),
            "resolved_album_folder": overrides.get("album_folder", "B"),
            "output_format": overrides.get("output_format", "flac"),
            "codec_mode": overrides.get("codec_mode", "copy"),
            "chapters": overrides.get("chapters",
                [{"index": 1, "title": "T", "start": 0.0, "end": 60.0}]),
            "tags": overrides.get("tags",
                {"artist": "A", "album": "", "festival": "", "date": "",
                 "stage": "", "venue": "", "mbid": "",
                 "musicbrainz_artistid": "", "enriched_at": ""}),
            "track_filenames": overrides.get("track_filenames", ["01 - T.flac"]),
            "cover_sha256": overrides.get("cover_sha256", "a" * 64),
        }
        (album_dir / ALBUM_MANIFEST_FILENAME).write_text(json.dumps(data))

    def _mk_source(self, tmp_path, size=10):
        p = tmp_path / "src.mkv"
        p.write_bytes(b"x" * size)
        return p

    def _fingerprint(self, src):
        return {"source_path": str(src), "mtime_ns": src.stat().st_mtime_ns,
                "size": src.stat().st_size}

    def test_no_existing_dir(self, tmp_path):
        from tracksplit.pipeline import should_regenerate
        src = self._mk_source(tmp_path)
        assert should_regenerate(
            tmp_path / "nope", src, {}, [], "A", "B", "flac", "copy",
            force=False,
        ) is True

    def test_force_always_true(self, tmp_path):
        from tracksplit.pipeline import should_regenerate
        src = self._mk_source(tmp_path)
        album = tmp_path / "album"
        album.mkdir()
        self._write_manifest(album, **self._fingerprint(src))
        assert should_regenerate(
            album, src, {}, [], "A", "B", "flac", "copy", force=True,
        ) is True

    def test_unchanged_everything(self, tmp_path):
        from tracksplit.pipeline import should_regenerate
        src = self._mk_source(tmp_path)
        album = tmp_path / "album"
        album.mkdir()
        fp = self._fingerprint(src)
        self._write_manifest(album, **fp)
        tags = {"artist": "A", "album": "", "festival": "", "date": "",
                "stage": "", "venue": "", "mbid": "",
                "musicbrainz_artistid": "", "enriched_at": ""}
        assert should_regenerate(
            album, src, tags,
            [{"index": 1, "title": "T", "start": 0.0, "end": 60.0}],
            "A", "B", "flac", "copy", force=False,
        ) is False

    def test_chapter_change_regenerates(self, tmp_path):
        from tracksplit.pipeline import should_regenerate
        src = self._mk_source(tmp_path)
        album = tmp_path / "album"
        album.mkdir()
        self._write_manifest(album, **self._fingerprint(src))
        new_chapters = [{"index": 1, "title": "T2", "start": 0.0, "end": 90.0}]
        assert should_regenerate(
            album, src, {}, new_chapters, "A", "B", "flac", "copy",
            force=False,
        ) is True

    def test_metadata_only_change_regenerates(self, tmp_path):
        from tracksplit.pipeline import should_regenerate
        src = self._mk_source(tmp_path)
        album = tmp_path / "album"
        album.mkdir()
        fp = self._fingerprint(src)
        self._write_manifest(album, **fp)
        tags = {"artist": "A", "album": "", "festival": "NEW-FESTIVAL",
                "date": "", "stage": "", "venue": "", "mbid": "",
                "musicbrainz_artistid": "", "enriched_at": ""}
        assert should_regenerate(
            album, src, tags,
            [{"index": 1, "title": "T", "start": 0.0, "end": 60.0}],
            "A", "B", "flac", "copy", force=False,
        ) is True

    def test_source_mtime_change_regenerates(self, tmp_path):
        from tracksplit.pipeline import should_regenerate
        src = self._mk_source(tmp_path)
        album = tmp_path / "album"
        album.mkdir()
        self._write_manifest(
            album, source_path=str(src), mtime_ns=1, size=src.stat().st_size,
        )
        assert should_regenerate(
            album, src, {}, [], "A", "B", "flac", "copy", force=False,
        ) is True

    def test_format_change_regenerates(self, tmp_path):
        from tracksplit.pipeline import should_regenerate
        src = self._mk_source(tmp_path)
        album = tmp_path / "album"
        album.mkdir()
        self._write_manifest(
            album, **self._fingerprint(src), output_format="flac",
        )
        assert should_regenerate(
            album, src, {}, [], "A", "B", "opus", "libopus", force=False,
        ) is True

    def test_missing_manifest_triggers_regenerate_even_with_legacy_cache(self, tmp_path):
        from tracksplit.pipeline import should_regenerate
        src = self._mk_source(tmp_path)
        album = tmp_path / "album"
        album.mkdir()
        (album / ".tracksplit_chapters.json").write_text(json.dumps([
            {"index": 1, "title": "T", "start": 0.0, "end": 60.0}
        ]))
        assert should_regenerate(
            album, src, {}, [], "A", "B", "flac", "copy", force=False,
        ) is True

    def test_corrupt_manifest_regenerates(self, tmp_path):
        from tracksplit.pipeline import should_regenerate
        from tracksplit.manifest import ALBUM_MANIFEST_FILENAME
        src = self._mk_source(tmp_path)
        album = tmp_path / "album"
        album.mkdir()
        (album / ALBUM_MANIFEST_FILENAME).write_text("{not json")
        assert should_regenerate(
            album, src, {}, [], "A", "B", "flac", "copy", force=False,
        ) is True


# ---------------------------------------------------------------------------
# _safe_log_name
# ---------------------------------------------------------------------------


class TestSafeLogName:
    def test_normal_path(self):
        assert _safe_log_name(Path("/tmp/test.mkv")) == "test.mkv"

    def test_surrogate_path(self):
        """Should not raise even with surrogate bytes."""
        result = _safe_log_name(Path("/tmp/test\udceb.mkv"))
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# process_file: no chapters, no duration
# ---------------------------------------------------------------------------

class TestProcessFileNoChapters:
    @patch("tracksplit.pipeline.run_ffprobe")
    def test_no_chapters_no_duration_skips(self, mock_probe, tmp_path):
        """File with no chapters and no duration should be skipped."""
        mock_probe.return_value = {
            "streams": [{"codec_type": "audio", "codec_name": "aac"}],
            "format": {"tags": {}},
            "chapters": [],
        }
        input_file = tmp_path / "empty.mkv"
        input_file.touch()

        from tracksplit.pipeline import process_file
        result = process_file(input_file, tmp_path / "out")
        assert result is False


class TestProcessFileManifest:
    def _probe(self):
        return {
            "streams": [{"codec_type": "audio", "codec_name": "flac"}],
            "format": {"tags": {"ARTIST": "DJ X",
                                 "CRATEDIGGER_1001TL_FESTIVAL": "Show",
                                 "CRATEDIGGER_1001TL_DATE": "2025"},
                       "duration": "600.0"},
            "chapters": [
                {"start_time": "0.0", "end_time": "300.0",
                 "tags": {"title": "Track 1"}},
                {"start_time": "300.0", "end_time": "600.0",
                 "tags": {"title": "Track 2"}},
            ],
        }

    @patch("tracksplit.pipeline.tag_all")
    @patch("tracksplit.pipeline.split_tracks")
    @patch("tracksplit.pipeline.prepare_audio")
    @patch("tracksplit.pipeline.compose_cover")
    @patch("tracksplit.pipeline.compose_artist_cover")
    @patch("tracksplit.pipeline.find_dj_artwork")
    @patch("tracksplit.pipeline.extract_cover_from_mkv")
    @patch("tracksplit.pipeline.run_ffprobe")
    def test_process_file_writes_manifest(
        self, mock_probe, mock_cover_mkv, mock_dj, mock_artist_cover,
        mock_compose, mock_prepare, mock_split, mock_tag, tmp_path,
    ):
        from tracksplit.manifest import load_album_manifest
        from tracksplit.pipeline import process_file

        mock_probe.return_value = self._probe()
        mock_cover_mkv.return_value = None
        mock_dj.return_value = None
        mock_compose.return_value = b"JPEG"
        mock_artist_cover.return_value = b"JPEG2"

        src = tmp_path / "src.mkv"
        src.write_bytes(b"data" * 64)
        out = tmp_path / "out"
        album_dir = out / "DJ X" / "Show 2025"

        mock_prepare.return_value = (src, ".flac", "copy")
        mock_split.return_value = [
            album_dir / "01 - DJ X - Track 1.flac",
            album_dir / "02 - DJ X - Track 2.flac",
        ]

        assert process_file(src, out) is True
        m = load_album_manifest(album_dir)
        assert m is not None
        assert m.source.size == src.stat().st_size
        assert m.output_format == "flac"
        assert m.codec_mode == "copy"
        assert len(m.chapters) == 2
        assert m.cover_sha256  # non-empty
        assert m.track_filenames == [
            "01 - DJ X - Track 1.flac", "02 - DJ X - Track 2.flac",
        ]

    @patch("tracksplit.pipeline.run_ffprobe")
    def test_process_file_skips_when_manifest_matches(
        self, mock_probe, tmp_path,
    ):
        from tracksplit.manifest import (
            build_album_manifest, save_album_manifest,
        )
        from tracksplit.pipeline import process_file

        src = tmp_path / "src.mkv"
        src.write_bytes(b"data" * 64)
        mock_probe.return_value = {
            "streams": [{"codec_type": "audio", "codec_name": "flac"}],
            "format": {"tags": {"ARTIST": "DJ X",
                                 "CRATEDIGGER_1001TL_FESTIVAL": "Show",
                                 "CRATEDIGGER_1001TL_DATE": "2025"},
                       "duration": "600.0"},
            "chapters": [
                {"start_time": "0.0", "end_time": "600.0",
                 "tags": {"title": "Track 1"}},
            ],
        }
        album_dir = tmp_path / "out" / "DJ X" / "Show 2025"
        album_dir.mkdir(parents=True)
        from tracksplit.manifest import TAG_KEYS
        tags = {k: "" for k in TAG_KEYS}
        tags["artist"] = "DJ X"
        tags["festival"] = "Show"
        tags["date"] = "2025"
        manifest = build_album_manifest(
            source_path=src,
            chapters=[{"index": 1, "title": "Track 1", "start": 0.0, "end": 600.0}],
            tags=tags,
            artist_folder="DJ X",
            album_folder="Show 2025",
            output_format="flac", codec_mode="copy",
            track_filenames=["01 - DJ X - Track 1.flac"],
            cover_bytes=b"",
        )
        save_album_manifest(album_dir, manifest)
        assert process_file(src, tmp_path / "out") is False

    @patch("tracksplit.pipeline.tag_all")
    @patch("tracksplit.pipeline.split_tracks")
    @patch("tracksplit.pipeline.prepare_audio")
    @patch("tracksplit.pipeline.compose_cover")
    @patch("tracksplit.pipeline.compose_artist_cover")
    @patch("tracksplit.pipeline.find_dj_artwork")
    @patch("tracksplit.pipeline.extract_cover_from_mkv")
    @patch("tracksplit.pipeline.run_ffprobe")
    def test_process_file_removes_legacy_chapter_cache(
        self, mock_probe, mock_cover_mkv, mock_dj, mock_artist_cover,
        mock_compose, mock_prepare, mock_split, mock_tag, tmp_path,
    ):
        from tracksplit.manifest import LEGACY_CHAPTER_CACHE_FILENAME
        from tracksplit.pipeline import process_file

        mock_probe.return_value = self._probe()
        mock_cover_mkv.return_value = None
        mock_dj.return_value = None
        mock_compose.return_value = b"JPEG"
        mock_artist_cover.return_value = b"JPEG2"

        src = tmp_path / "src.mkv"
        src.write_bytes(b"data" * 64)
        out = tmp_path / "out"
        album_dir = out / "DJ X" / "Show 2025"
        album_dir.mkdir(parents=True)
        (album_dir / LEGACY_CHAPTER_CACHE_FILENAME).write_text("[]")
        mock_prepare.return_value = (src, ".flac", "copy")
        mock_split.return_value = [album_dir / "01 - t.flac"]

        assert process_file(src, out) is True
        assert not (album_dir / LEGACY_CHAPTER_CACHE_FILENAME).exists()
