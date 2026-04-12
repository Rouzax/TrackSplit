"""Tests for the probe module."""
from pathlib import Path
from unittest.mock import patch, MagicMock
import json
import subprocess

import pytest

from tracksplit.probe import (
    run_ffprobe,
    parse_chapters,
    parse_tags,
    detect_tier,
    has_audio,
    is_video_file,
    get_audio_codec,
    is_lossless_codec,
    LOSSLESS_CODECS,
    VIDEO_EXTENSIONS,
)
from tracksplit.models import Chapter


# ---------------------------------------------------------------------------
# Fixtures: representative ffprobe JSON structures
# ---------------------------------------------------------------------------

def _make_ffprobe_data(chapters=None, streams=None, tags=None):
    """Build a minimal ffprobe-style dict."""
    data = {}
    if chapters is not None:
        data["chapters"] = chapters
    if streams is not None:
        data["streams"] = streams
    if tags is not None:
        data["format"] = {"tags": tags}
    return data


def _chapter_entry(start, end, title=None):
    """Build one ffprobe chapter entry (times in seconds)."""
    entry = {
        "start_time": str(start),
        "end_time": str(end),
    }
    if title is not None:
        entry["tags"] = {"title": title}
    return entry


# ---------------------------------------------------------------------------
# parse_chapters
# ---------------------------------------------------------------------------

class TestParseChapters:
    def test_basic_parsing(self):
        data = _make_ffprobe_data(chapters=[
            _chapter_entry(0, 60, "Intro"),
            _chapter_entry(60, 180, "Main Set"),
            _chapter_entry(180, 240, "Encore"),
        ])
        chapters = parse_chapters(data)
        assert len(chapters) == 3
        assert chapters[0] == Chapter(index=1, title="Intro", start=0.0, end=60.0)
        assert chapters[1] == Chapter(index=2, title="Main Set", start=60.0, end=180.0)
        assert chapters[2] == Chapter(index=3, title="Encore", start=180.0, end=240.0)

    def test_no_title_gets_default(self):
        data = _make_ffprobe_data(chapters=[
            _chapter_entry(0, 60),
            _chapter_entry(60, 120),
        ])
        chapters = parse_chapters(data)
        assert chapters[0].title == "Track 01"
        assert chapters[1].title == "Track 02"

    def test_empty_title_gets_default(self):
        data = _make_ffprobe_data(chapters=[
            _chapter_entry(0, 60, ""),
        ])
        chapters = parse_chapters(data)
        assert chapters[0].title == "Track 01"

    def test_empty_chapters_list(self):
        data = _make_ffprobe_data(chapters=[])
        chapters = parse_chapters(data)
        assert chapters == []

    def test_missing_chapters_key(self):
        data = _make_ffprobe_data()
        chapters = parse_chapters(data)
        assert chapters == []

    def test_zero_duration_filtered(self):
        data = _make_ffprobe_data(chapters=[
            _chapter_entry(0, 60, "Good"),
            _chapter_entry(60, 60, "Zero Duration"),
            _chapter_entry(60, 180, "Also Good"),
        ])
        chapters = parse_chapters(data)
        assert len(chapters) == 2
        assert chapters[0].title == "Good"
        assert chapters[0].index == 1
        assert chapters[1].title == "Also Good"
        assert chapters[1].index == 2  # re-indexed after filtering

    def test_zero_duration_warning_logged(self, caplog):
        data = _make_ffprobe_data(chapters=[
            _chapter_entry(10, 10, "Marker"),
        ])
        import logging
        with caplog.at_level(logging.WARNING):
            chapters = parse_chapters(data)
        assert len(chapters) == 0
        assert "zero" in caplog.text.lower() or "duration" in caplog.text.lower()

    def test_chapter_times_as_floats(self):
        data = _make_ffprobe_data(chapters=[
            _chapter_entry(0.5, 30.123, "Precise"),
        ])
        chapters = parse_chapters(data)
        assert chapters[0].start == pytest.approx(0.5)
        assert chapters[0].end == pytest.approx(30.123)


# ---------------------------------------------------------------------------
# parse_tags
# ---------------------------------------------------------------------------

class TestParseTags:
    def test_cratedigger_tags(self):
        data = _make_ffprobe_data(tags={
            "ARTIST": "Tiesto",
            "CRATEDIGGER_1001TL_GENRES": "Trance|Progressive House",
            "CRATEDIGGER_1001TL_URL": "https://www.1001tracklists.com/tracklist/abc",
            "CRATEDIGGER_1001TL_FESTIVAL": "Tomorrowland",
            "CRATEDIGGER_1001TL_STAGE": "Main Stage",
            "CRATEDIGGER_1001TL_VENUE": "Boom, Belgium",
            "CRATEDIGGER_1001TL_DATE": "2024-07-21",
            "CRATEDIGGER_MBID": "some-uuid",
            "CRATEDIGGER_1001TL_DJ_ARTWORK": "/path/to/art.jpg",
        })
        tags = parse_tags(data)
        assert tags["artist"] == "Tiesto"
        assert tags["festival"] == "Tomorrowland"
        assert tags["date"] == "2024-07-21"
        assert tags["genres"] == ["Trance", "Progressive House"]
        assert tags["stage"] == "Main Stage"
        assert tags["venue"] == "Boom, Belgium"
        assert tags["comment"] == "https://www.1001tracklists.com/tracklist/abc"
        assert tags["musicbrainz_artistid"] == "some-uuid"
        assert tags["dj_artwork"] == "/path/to/art.jpg"
        assert tags["cratedigger"] is True

    def test_no_cratedigger_tags(self):
        data = _make_ffprobe_data(tags={
            "ARTIST": "Someone",
        })
        tags = parse_tags(data)
        assert tags["artist"] == "Someone"
        assert tags["date"] == ""
        assert tags["genres"] == []
        assert tags["festival"] == ""
        assert tags["stage"] == ""
        assert tags["venue"] == ""
        assert tags["comment"] == ""
        assert tags["musicbrainz_artistid"] == ""
        assert tags["dj_artwork"] == ""
        assert tags["cratedigger"] is False

    def test_case_insensitive_lookup(self):
        data = _make_ffprobe_data(tags={
            "artist": "lowercase",
            "cratedigger_1001tl_date": "2024",
        })
        tags = parse_tags(data)
        assert tags["artist"] == "lowercase"
        assert tags["date"] == "2024"

    def test_empty_genres(self):
        data = _make_ffprobe_data(tags={
            "CRATEDIGGER_1001TL_GENRES": "",
        })
        tags = parse_tags(data)
        assert tags["genres"] == []

    def test_single_genre(self):
        data = _make_ffprobe_data(tags={
            "CRATEDIGGER_1001TL_GENRES": "Techno",
        })
        tags = parse_tags(data)
        assert tags["genres"] == ["Techno"]

    def test_no_format_key(self):
        tags = parse_tags({})
        assert tags["artist"] == ""
        assert tags["cratedigger"] is False

    def test_no_tags_key_in_format(self):
        tags = parse_tags({"format": {}})
        assert tags["artist"] == ""
        assert tags["cratedigger"] is False


# ---------------------------------------------------------------------------
# detect_tier
# ---------------------------------------------------------------------------

class TestDetectTier:
    def test_tier_2_when_cratedigger(self):
        assert detect_tier({"cratedigger": True}) == 2

    def test_tier_1_when_not_cratedigger(self):
        assert detect_tier({"cratedigger": False}) == 1

    def test_tier_1_when_key_missing(self):
        assert detect_tier({}) == 1


# ---------------------------------------------------------------------------
# has_audio
# ---------------------------------------------------------------------------

class TestHasAudio:
    def test_audio_stream_present(self):
        data = _make_ffprobe_data(streams=[
            {"codec_type": "video"},
            {"codec_type": "audio"},
        ])
        assert has_audio(data) is True

    def test_no_audio_stream(self):
        data = _make_ffprobe_data(streams=[
            {"codec_type": "video"},
            {"codec_type": "subtitle"},
        ])
        assert has_audio(data) is False

    def test_no_streams_key(self):
        assert has_audio({}) is False

    def test_empty_streams(self):
        data = _make_ffprobe_data(streams=[])
        assert has_audio(data) is False


# ---------------------------------------------------------------------------
# is_video_file
# ---------------------------------------------------------------------------

class TestIsVideoFile:
    @pytest.mark.parametrize("ext", [".mkv", ".mp4", ".webm", ".avi", ".mov", ".m2ts", ".ts", ".flv"])
    def test_valid_extensions(self, ext):
        assert is_video_file(Path(f"/some/file{ext}")) is True

    def test_case_insensitive(self):
        assert is_video_file(Path("/some/file.MKV")) is True
        assert is_video_file(Path("/some/file.Mp4")) is True

    def test_non_video_extension(self):
        assert is_video_file(Path("/some/file.flac")) is False
        assert is_video_file(Path("/some/file.txt")) is False

    def test_no_extension(self):
        assert is_video_file(Path("/some/file")) is False


# ---------------------------------------------------------------------------
# run_ffprobe
# ---------------------------------------------------------------------------

class TestRunFfprobe:
    def test_returns_parsed_json(self):
        fake_output = json.dumps({"chapters": [], "streams": []})
        mock_result = MagicMock()
        mock_result.stdout = fake_output
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = run_ffprobe(Path("/fake/video.mkv"))
        assert result == {"chapters": [], "streams": []}
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "ffprobe" in cmd
        assert "/fake/video.mkv" in cmd

    def test_raises_on_ffprobe_failure(self):
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "ffprobe")):
            with pytest.raises(subprocess.CalledProcessError):
                run_ffprobe(Path("/fake/video.mkv"))


# ---------------------------------------------------------------------------
# get_audio_codec
# ---------------------------------------------------------------------------

class TestGetAudioCodec:
    def test_opus_codec(self):
        data = _make_ffprobe_data(streams=[
            {"codec_type": "video", "codec_name": "h264"},
            {"codec_type": "audio", "codec_name": "opus"},
        ])
        assert get_audio_codec(data) == "opus"

    def test_flac_codec(self):
        data = _make_ffprobe_data(streams=[
            {"codec_type": "audio", "codec_name": "flac"},
        ])
        assert get_audio_codec(data) == "flac"

    def test_no_audio_stream(self):
        data = _make_ffprobe_data(streams=[
            {"codec_type": "video", "codec_name": "h264"},
        ])
        assert get_audio_codec(data) == ""

    def test_no_streams(self):
        assert get_audio_codec({}) == ""

    def test_missing_codec_name(self):
        data = _make_ffprobe_data(streams=[
            {"codec_type": "audio"},
        ])
        assert get_audio_codec(data) == ""

    def test_first_audio_stream_returned(self):
        data = _make_ffprobe_data(streams=[
            {"codec_type": "audio", "codec_name": "opus"},
            {"codec_type": "audio", "codec_name": "aac"},
        ])
        assert get_audio_codec(data) == "opus"


# ---------------------------------------------------------------------------
# is_lossless_codec
# ---------------------------------------------------------------------------

class TestIsLosslessCodec:
    @pytest.mark.parametrize("codec", ["flac", "alac", "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "wavpack"])
    def test_known_lossless(self, codec):
        assert is_lossless_codec(codec) is True

    def test_unknown_pcm_variant(self):
        assert is_lossless_codec("pcm_s64le") is True

    @pytest.mark.parametrize("codec", ["opus", "aac", "mp3", "vorbis"])
    def test_lossy_codecs(self, codec):
        assert is_lossless_codec(codec) is False

    def test_empty_string(self):
        assert is_lossless_codec("") is False


class TestMojibakeFix:
    """Verify ffprobe output with mojibake is repaired via ftfy."""

    def test_parse_tags_fixes_artist_mojibake(self):
        """Classic UTF-8-as-Latin-1 mojibake should be repaired."""
        from tracksplit.probe import parse_tags
        data = {
            "format": {
                "tags": {
                    "ARTIST": "KÃ¶lsch",
                },
            },
        }
        tags = parse_tags(data)
        assert tags["artist"] == "Kölsch"

    def test_parse_tags_leaves_correct_artist_unchanged(self):
        """Already-correct UTF-8 strings should pass through unchanged."""
        from tracksplit.probe import parse_tags
        data = {
            "format": {
                "tags": {
                    "ARTIST": "Kölsch",
                },
            },
        }
        tags = parse_tags(data)
        assert tags["artist"] == "Kölsch"

    def test_parse_tags_plain_ascii(self):
        """Plain ASCII unchanged."""
        from tracksplit.probe import parse_tags
        data = {"format": {"tags": {"ARTIST": "Tiesto"}}}
        tags = parse_tags(data)
        assert tags["artist"] == "Tiesto"

    def test_parse_chapters_fixes_title_mojibake(self):
        """Chapter titles with mojibake should be repaired."""
        from tracksplit.probe import parse_chapters
        data = {
            "chapters": [
                {
                    "start_time": "0.0",
                    "end_time": "60.0",
                    "tags": {"title": "KÃ¶lsch - Loreley"},
                },
            ],
        }
        chapters = parse_chapters(data)
        assert chapters[0].title == "Kölsch - Loreley"


def test_parse_tags_returns_enriched_at():
    ffprobe_data = {
        "format": {
            "tags": {
                "ARTIST": "X",
                "CRATEDIGGER_ENRICHED_AT": "2026-04-10T12:34:56Z",
            }
        }
    }
    from tracksplit.probe import parse_tags
    tags = parse_tags(ffprobe_data)
    assert tags["enriched_at"] == "2026-04-10T12:34:56Z"


def test_parse_tags_enriched_at_missing_is_empty():
    from tracksplit.probe import parse_tags
    tags = parse_tags({"format": {"tags": {"ARTIST": "X"}}})
    assert tags["enriched_at"] == ""
