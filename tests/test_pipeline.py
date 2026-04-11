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
    def test_no_existing_dir(self, tmp_path):
        """Nonexistent directory means regeneration is needed."""
        nonexistent = tmp_path / "does_not_exist"
        chapters = [Chapter(index=1, title="T", start=0.0, end=60.0)]
        assert should_regenerate(nonexistent, chapters, force=False) is True

    def test_force_always_true(self, tmp_path):
        """Force flag always triggers regeneration."""
        album_dir = tmp_path / "album"
        album_dir.mkdir()
        # Even with a matching cache, force should return True
        chapters = [Chapter(index=1, title="T", start=0.0, end=60.0)]
        cache_data = [{"index": 1, "title": "T", "start": 0.0, "end": 60.0}]
        cache_file = album_dir / ".tracksplit_chapters.json"
        cache_file.write_text(json.dumps(cache_data))
        assert should_regenerate(album_dir, chapters, force=True) is True

    def test_unchanged_chapters(self, tmp_path):
        """Same chapters as cached means no regeneration needed."""
        album_dir = tmp_path / "album"
        album_dir.mkdir()
        chapters = [
            Chapter(index=1, title="Track A", start=0.0, end=60.0),
            Chapter(index=2, title="Track B", start=60.0, end=120.0),
        ]
        cache_data = [
            {"index": 1, "title": "Track A", "start": 0.0, "end": 60.0},
            {"index": 2, "title": "Track B", "start": 60.0, "end": 120.0},
        ]
        cache_file = album_dir / ".tracksplit_chapters.json"
        cache_file.write_text(json.dumps(cache_data))
        assert should_regenerate(album_dir, chapters, force=False) is False

    def test_changed_chapters(self, tmp_path):
        """Different chapters from cached means regeneration needed."""
        album_dir = tmp_path / "album"
        album_dir.mkdir()
        chapters = [
            Chapter(index=1, title="New Track", start=0.0, end=90.0),
        ]
        cache_data = [
            {"index": 1, "title": "Old Track", "start": 0.0, "end": 60.0},
        ]
        cache_file = album_dir / ".tracksplit_chapters.json"
        cache_file.write_text(json.dumps(cache_data))
        assert should_regenerate(album_dir, chapters, force=False) is True


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
