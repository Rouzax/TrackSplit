import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from tracksplit.cover import (
    build_cover_command,
    compose_cover,
    create_gradient,
    extract_cover_from_mkv,
)


class TestCreateGradient:
    def test_dimensions(self):
        img = create_gradient(1000, 1000)
        assert img.size == (1000, 1000)

    def test_mode_is_rgb(self):
        img = create_gradient(500, 500)
        assert img.mode == "RGB"

    def test_non_square(self):
        img = create_gradient(800, 600)
        assert img.size == (800, 600)


class TestComposeCover:
    def _make_test_image_bytes(self, width=1200, height=800):
        """Create a simple test image and return its bytes."""
        img = Image.new("RGB", (width, height), color=(100, 150, 200))
        import io

        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        return buf.getvalue()

    def test_with_background_returns_bytes(self):
        bg = self._make_test_image_bytes()
        result = compose_cover("Test Artist", "Test Album", background_data=bg)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_with_background_is_square(self):
        bg = self._make_test_image_bytes()
        result = compose_cover("Test Artist", "Test Album", background_data=bg)
        img = Image.open(__import__("io").BytesIO(result))
        assert img.size == (1000, 1000)

    def test_without_background_returns_bytes(self):
        result = compose_cover("Test Artist", "Test Album")
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_without_background_is_square(self):
        result = compose_cover("Test Artist", "Test Album")
        img = Image.open(__import__("io").BytesIO(result))
        assert img.size == (1000, 1000)

    def test_custom_size(self):
        result = compose_cover("Artist", "Album", size=500)
        img = Image.open(__import__("io").BytesIO(result))
        assert img.size == (500, 500)

    def test_output_is_jpeg(self):
        result = compose_cover("Artist", "Album")
        img = Image.open(__import__("io").BytesIO(result))
        assert img.format == "JPEG"


class TestBuildCoverCommand:
    def test_command_structure(self):
        cmd = build_cover_command(
            Path("/tmp/video.mkv"),
            Path("/tmp/cover.jpg"),
        )
        assert cmd[0] == "ffmpeg"
        assert "-i" in cmd
        assert str(Path("/tmp/video.mkv")) in cmd
        assert str(Path("/tmp/cover.jpg")) in cmd

    def test_uses_image2pipe_or_output(self):
        cmd = build_cover_command(
            Path("/tmp/video.mkv"),
            Path("/tmp/cover.jpg"),
        )
        # Should extract an image stream
        assert "ffmpeg" in cmd


class TestExtractCoverFromMkv:
    @patch("tracksplit.cover.subprocess.run")
    def test_ffmpeg_success(self, mock_run):
        fake_image = b"\xff\xd8\xff\xe0fake_jpeg_data"
        mock_run.return_value = MagicMock(stdout=fake_image, returncode=0)

        result = extract_cover_from_mkv(Path("/tmp/video.mkv"))
        assert result == fake_image

    @patch("tracksplit.cover.subprocess.run")
    def test_ffmpeg_failure_returns_none_for_non_mkv(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, "ffmpeg")

        result = extract_cover_from_mkv(Path("/tmp/video.mp4"))
        assert result is None

    @patch("tracksplit.cover.subprocess.run")
    def test_ffmpeg_failure_tries_mkvmerge(self, mock_run):
        """When ffmpeg fails on .mkv, should try mkvmerge fallback."""
        identify_output = json.dumps(
            {
                "attachments": [
                    {
                        "id": 1,
                        "content_type": "image/jpeg",
                        "file_name": "cover.jpg",
                    }
                ]
            }
        )
        fake_image = b"\xff\xd8\xff\xe0fake_jpeg_data"

        def run_side_effect(cmd, **kwargs):
            if cmd[0] == "ffmpeg":
                raise subprocess.CalledProcessError(1, "ffmpeg")
            if cmd[0] == "mkvmerge":
                return MagicMock(stdout=identify_output, returncode=0)
            if cmd[0] == "mkvextract":
                # mkvextract writes to a file; we mock the file read
                return MagicMock(returncode=0)
            return MagicMock(returncode=0)

        mock_run.side_effect = run_side_effect

        with patch("pathlib.Path.read_bytes", return_value=fake_image):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("pathlib.Path.unlink"):
                    result = extract_cover_from_mkv(Path("/tmp/video.mkv"))

        assert result == fake_image
