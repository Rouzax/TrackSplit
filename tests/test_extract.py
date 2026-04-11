import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from tracksplit.extract import build_extract_command, extract_audio, prepare_audio


def test_build_extract_command():
    cmd = build_extract_command(
        Path("/tmp/video.mkv"),
        Path("/tmp/video_tracksplit_full.flac"),
    )
    assert cmd == [
        "ffmpeg",
        "-i",
        "/tmp/video.mkv",
        "-vn",
        "-c:a",
        "flac",
        "-y",
        "/tmp/video_tracksplit_full.flac",
    ]


def test_extract_audio_calls_ffmpeg(tmp_path):
    input_path = Path("/tmp/video.mkv")
    with patch("tracksplit.extract.tracked_run") as mock_run:
        result = extract_audio(input_path, temp_dir=tmp_path)

    expected_output = tmp_path / "video_tracksplit_full.flac"
    assert result == expected_output
    mock_run.assert_called_once_with(
        [
            "ffmpeg",
            "-i",
            "/tmp/video.mkv",
            "-vn",
            "-c:a",
            "flac",
            "-y",
            str(expected_output),
        ],
        cancel_event=None,
    )


def test_extract_audio_raises_on_failure(tmp_path):
    input_path = Path("/tmp/video.mkv")
    with patch("tracksplit.extract.tracked_run") as mock_run:
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1, cmd="ffmpeg"
        )
        with pytest.raises(subprocess.CalledProcessError):
            extract_audio(input_path, temp_dir=tmp_path)


# ---------------------------------------------------------------------------
# prepare_audio
# ---------------------------------------------------------------------------

def _ffprobe_with_codec(codec_name):
    """Build minimal ffprobe data with one audio stream."""
    return {
        "streams": [{"codec_type": "audio", "codec_name": codec_name}],
    }


class TestPrepareAudio:
    def test_auto_opus_stream_copy(self, tmp_path):
        """Auto format with Opus source: stream copy, no extraction."""
        input_path = Path("/tmp/video.mkv")
        data = _ffprobe_with_codec("opus")

        audio_path, ext, codec_mode = prepare_audio(input_path, data, "auto", tmp_path)

        assert audio_path == input_path
        assert ext == ".opus"
        assert codec_mode == "copy"

    def test_auto_flac_extracts(self, tmp_path):
        """Auto format with FLAC source: extract to temp FLAC."""
        input_path = Path("/tmp/video.mkv")
        data = _ffprobe_with_codec("flac")

        with patch("tracksplit.extract.tracked_run"):
            audio_path, ext, codec_mode = prepare_audio(input_path, data, "auto", tmp_path)

        assert audio_path == tmp_path / "video_tracksplit_full.flac"
        assert ext == ".flac"
        assert codec_mode == "copy"

    def test_auto_aac_reencodes(self, tmp_path):
        """Auto format with AAC source: re-encode to Opus."""
        input_path = Path("/tmp/video.mkv")
        data = _ffprobe_with_codec("aac")

        audio_path, ext, codec_mode = prepare_audio(input_path, data, "auto", tmp_path)

        assert audio_path == input_path
        assert ext == ".opus"
        assert codec_mode == "libopus"

    def test_flac_format_always_extracts(self, tmp_path):
        """Explicit flac format: always extract regardless of source codec."""
        input_path = Path("/tmp/video.mkv")
        data = _ffprobe_with_codec("opus")

        with patch("tracksplit.extract.tracked_run"):
            audio_path, ext, codec_mode = prepare_audio(input_path, data, "flac", tmp_path)

        assert audio_path == tmp_path / "video_tracksplit_full.flac"
        assert ext == ".flac"
        assert codec_mode == "copy"

    def test_opus_format_opus_source(self, tmp_path):
        """Explicit opus format with Opus source: stream copy."""
        input_path = Path("/tmp/video.mkv")
        data = _ffprobe_with_codec("opus")

        audio_path, ext, codec_mode = prepare_audio(input_path, data, "opus", tmp_path)

        assert audio_path == input_path
        assert ext == ".opus"
        assert codec_mode == "copy"

    def test_opus_format_non_opus_source(self, tmp_path):
        """Explicit opus format with non-Opus source: re-encode."""
        input_path = Path("/tmp/video.mkv")
        data = _ffprobe_with_codec("flac")

        audio_path, ext, codec_mode = prepare_audio(input_path, data, "opus", tmp_path)

        assert audio_path == input_path
        assert ext == ".opus"
        assert codec_mode == "libopus"

    def test_unknown_format_raises(self, tmp_path):
        """Unknown format raises ValueError."""
        input_path = Path("/tmp/video.mkv")
        data = _ffprobe_with_codec("opus")

        with pytest.raises(ValueError, match="Unknown output format"):
            prepare_audio(input_path, data, "wav", tmp_path)
