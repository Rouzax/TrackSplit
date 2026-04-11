import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from tracksplit.extract import build_extract_command, extract_audio


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
    with patch("tracksplit.extract.subprocess.run") as mock_run:
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
        capture_output=True,
        check=True,
    )


def test_extract_audio_raises_on_failure(tmp_path):
    input_path = Path("/tmp/video.mkv")
    with patch("tracksplit.extract.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1, cmd="ffmpeg"
        )
        with pytest.raises(subprocess.CalledProcessError):
            extract_audio(input_path, temp_dir=tmp_path)
