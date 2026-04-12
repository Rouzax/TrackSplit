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
