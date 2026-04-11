"""Tests for tracksplit.cover module."""

import io
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image

from tracksplit.cover import (
    _artwork_cache_filename,
    _wcag_contrast,
    _wcag_luminance,
    build_cover_command,
    compose_artist_cover,
    compose_cover,
    create_gradient,
    extract_cover_from_mkv,
    find_dj_artwork,
    format_date_display,
    get_accent_color,
)


def _make_solid_image(color, width=200, height=200):
    """Create a solid-color PIL image."""
    return Image.new("RGB", (width, height), color)


def _make_image_bytes(color=(100, 150, 200), width=200, height=200):
    """Create a JPEG image as bytes."""
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


class TestGetAccentColor:
    def test_returns_rgb_tuple(self):
        img = _make_solid_image((100, 50, 50))
        result = get_accent_color(img)
        assert isinstance(result, tuple)
        assert len(result) == 3
        assert all(0 <= c <= 255 for c in result)

    def test_red_image_gives_reddish(self):
        img = _make_solid_image((220, 30, 30))
        r, g, b = get_accent_color(img)
        assert r > g and r > b

    def test_blue_image_gives_bluish(self):
        img = _make_solid_image((30, 30, 220))
        r, g, b = get_accent_color(img)
        assert b > r and b > g

    def test_gray_image_works(self):
        img = _make_solid_image((128, 128, 128))
        result = get_accent_color(img)
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_wcag_contrast_met(self):
        img = _make_solid_image((80, 40, 40))
        accent = get_accent_color(img)
        contrast = _wcag_contrast(accent, (10, 10, 10))
        assert contrast >= 4.5


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


class TestFormatDateDisplay:
    def test_full_iso_date(self):
        assert format_date_display("2026-03-01") == "1 March 2026"

    def test_year_only(self):
        assert format_date_display("2026") == "2026"

    def test_empty_string(self):
        assert format_date_display("") == ""

    def test_partial_date(self):
        # Partial date that does not match ISO format
        result = format_date_display("2026-03")
        assert isinstance(result, str)
        assert len(result) > 0


class TestComposeCover:
    def test_returns_jpeg_bytes(self):
        result = compose_cover("Test Artist", "Test Festival")
        assert isinstance(result, bytes)
        assert len(result) > 0
        img = Image.open(io.BytesIO(result))
        assert img.format == "JPEG"

    def test_square_output(self):
        result = compose_cover("Artist", "Festival")
        img = Image.open(io.BytesIO(result))
        assert img.size == (1000, 1000)

    def test_with_background(self):
        bg = _make_image_bytes((100, 50, 50), 1200, 800)
        result = compose_cover("Artist", "Festival", background_data=bg)
        assert isinstance(result, bytes)
        img = Image.open(io.BytesIO(result))
        assert img.size == (1000, 1000)

    def test_with_all_fields(self):
        result = compose_cover(
            artist="DJ Test",
            festival="Ultra Music Festival",
            date="2026-03-01",
            stage="Main Stage",
            venue="Bayfront Park, Miami",
        )
        assert isinstance(result, bytes)
        img = Image.open(io.BytesIO(result))
        assert img.size == (1000, 1000)

    def test_custom_size(self):
        result = compose_cover("Artist", "Festival", size=500)
        img = Image.open(io.BytesIO(result))
        assert img.size == (500, 500)

    def test_no_festival_still_works(self):
        result = compose_cover("Artist", "")
        assert isinstance(result, bytes)
        img = Image.open(io.BytesIO(result))
        assert img.size == (1000, 1000)


class TestArtworkCacheFilename:
    def test_returns_hash_dot_ext(self):
        name = _artwork_cache_filename("https://example.com/photo.jpg")
        assert "." in name
        base, ext = name.rsplit(".", 1)
        assert len(base) == 12
        assert ext == "jpg"

    def test_consistent_hash(self):
        url = "https://example.com/photo.jpg"
        assert _artwork_cache_filename(url) == _artwork_cache_filename(url)

    def test_webp_extension(self):
        name = _artwork_cache_filename("https://example.com/photo.webp")
        assert name.endswith(".webp")

    def test_no_extension_defaults_jpg(self):
        name = _artwork_cache_filename("https://example.com/photo")
        assert name.endswith(".jpg")

    def test_empty_url(self):
        assert _artwork_cache_filename("") == ""


class TestFindDjArtwork:
    def test_finds_in_global_cache(self, tmp_path):
        url = "https://example.com/dj.jpg"
        filename = _artwork_cache_filename(url)
        cache_dir = tmp_path / ".cratedigger" / "dj-artwork"
        cache_dir.mkdir(parents=True)
        (cache_dir / filename).write_bytes(b"fake-image-data")

        result = find_dj_artwork(url, tmp_path / "music" / "file.flac", home_dir=tmp_path)
        assert result == b"fake-image-data"

    def test_finds_in_library_cache(self, tmp_path):
        url = "https://example.com/dj2.jpg"
        filename = _artwork_cache_filename(url)
        # Create library-level cache one directory above input
        lib_dir = tmp_path / "music"
        lib_dir.mkdir()
        cache_dir = lib_dir / ".cratedigger" / "dj-artwork"
        cache_dir.mkdir(parents=True)
        (cache_dir / filename).write_bytes(b"library-image")

        input_file = lib_dir / "artist" / "file.flac"
        input_file.parent.mkdir(parents=True)

        # Use a home_dir that does NOT have the cache
        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()

        result = find_dj_artwork(url, input_file, home_dir=fake_home)
        assert result == b"library-image"

    def test_returns_none_when_not_found(self, tmp_path):
        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        result = find_dj_artwork(
            "https://example.com/missing.jpg",
            tmp_path / "file.flac",
            home_dir=fake_home,
        )
        assert result is None

    def test_empty_url_returns_none(self, tmp_path):
        result = find_dj_artwork("", tmp_path / "file.flac")
        assert result is None


class TestComposeArtistCover:
    def test_returns_jpeg_bytes(self):
        result = compose_artist_cover("Test Artist")
        assert isinstance(result, bytes)
        img = Image.open(io.BytesIO(result))
        assert img.format == "JPEG"

    def test_square_output(self):
        result = compose_artist_cover("Artist")
        img = Image.open(io.BytesIO(result))
        assert img.size == (1000, 1000)

    def test_with_dj_photo(self):
        photo = _make_image_bytes((200, 100, 50), 400, 400)
        result = compose_artist_cover("Artist", dj_artwork_data=photo)
        assert isinstance(result, bytes)
        img = Image.open(io.BytesIO(result))
        assert img.size == (1000, 1000)

    def test_with_background_and_photo(self):
        bg = _make_image_bytes((50, 50, 100), 1200, 800)
        photo = _make_image_bytes((200, 100, 50), 400, 400)
        result = compose_artist_cover(
            "Artist", background_data=bg, dj_artwork_data=photo
        )
        assert isinstance(result, bytes)

    def test_no_photo_no_background(self):
        result = compose_artist_cover("Solo Artist")
        assert isinstance(result, bytes)
        img = Image.open(io.BytesIO(result))
        assert img.size == (1000, 1000)

    def test_custom_size(self):
        result = compose_artist_cover("Artist", size=500)
        img = Image.open(io.BytesIO(result))
        assert img.size == (500, 500)


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
