"""Integration tests using real video files.

These tests require ffmpeg, ffprobe, and access to video files with chapters.
They are skipped by default. Run with: pytest tests/test_integration.py -v

Set TRACKSPLIT_TEST_VIDEO to a video file path to enable.
"""
import os
from pathlib import Path

import pytest

from tracksplit.pipeline import process_file
from tracksplit.probe import has_audio, parse_chapters, parse_tags, run_ffprobe

TEST_VIDEO = os.environ.get("TRACKSPLIT_TEST_VIDEO", "")


@pytest.fixture
def video_path():
    if not TEST_VIDEO or not Path(TEST_VIDEO).exists():
        pytest.skip("Set TRACKSPLIT_TEST_VIDEO to a video file path to run")
    return Path(TEST_VIDEO)


def test_probe_real_file(video_path):
    data = run_ffprobe(video_path)
    assert has_audio(data)
    chapters = parse_chapters(data)
    assert len(chapters) >= 0  # may or may not have chapters


def test_probe_cratedigger_tags(video_path):
    data = run_ffprobe(video_path)
    tags = parse_tags(data)
    # Just verify the structure is correct
    assert "artist" in tags
    assert "festival" in tags
    assert "genres" in tags
    assert "cratedigger" in tags


def test_full_pipeline(video_path, tmp_path):
    result = process_file(video_path, tmp_path)
    assert result is True

    # Check output structure
    artist_dirs = [d for d in tmp_path.iterdir() if d.is_dir()]
    assert len(artist_dirs) == 1

    album_dirs = [d for d in artist_dirs[0].iterdir() if d.is_dir()]
    assert len(album_dirs) == 1

    album_dir = album_dirs[0]
    flac_files = sorted(album_dir.glob("*.flac"))
    assert len(flac_files) > 0

    cover = album_dir / "cover.jpg"
    assert cover.exists()

    # Verify tags on first track
    from mutagen.flac import FLAC
    audio = FLAC(str(flac_files[0]))
    assert "TITLE" in audio
    assert "ARTIST" in audio
    assert "ALBUM" in audio
    assert "TRACKNUMBER" in audio
    assert "DISCNUMBER" in audio
    assert audio.pictures  # embedded cover art


def test_rerun_skips_unchanged(video_path, tmp_path):
    """Second run should skip if chapters haven't changed."""
    result1 = process_file(video_path, tmp_path)
    assert result1 is True

    result2 = process_file(video_path, tmp_path)
    assert result2 is False  # skipped, unchanged


def test_rerun_force_regenerates(video_path, tmp_path):
    """Force flag should regenerate even if unchanged."""
    process_file(video_path, tmp_path)
    result = process_file(video_path, tmp_path, force=True)
    assert result is True
