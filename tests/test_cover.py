"""Tests for tracksplit.cover module."""

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from tracksplit.cover import (
    _is_image_attachment,
    _layout_album_cover,
    _load_font,
    _pick_image_attachment,
    _wcag_contrast,
    build_cover_command,
    compose_artist_cover,
    compose_cover,
    create_gradient,
    extract_cover_from_mkv,
    find_dj_artwork,
    format_date_display,
    get_accent_color,
    split_artist,
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


class TestSplitArtist:
    def test_single_name(self):
        assert split_artist("Hardwell") == ["Hardwell"]

    def test_single_ampersand(self):
        assert split_artist("Martin Garrix & Alesso") == ["Martin Garrix", "& Alesso"]

    def test_multiple_ampersands(self):
        result = split_artist("Axwell & Sebastian Ingrosso & Steve Angello")
        assert result == ["Axwell", "& Sebastian Ingrosso", "& Steve Angello"]

    def test_b2b(self):
        assert split_artist("Adam Beyer B2B Cirez D") == ["Adam Beyer", "B2B Cirez D"]

    def test_vs(self):
        assert split_artist("Armin VS Vini Vici") == ["Armin", "VS Vini Vici"]

    def test_x(self):
        assert split_artist("Sub Focus X Dimension") == ["Sub Focus", "X Dimension"]

    def test_parenthetical(self):
        result = split_artist("Everything Always (Dom Dolla & John Summit)")
        assert result == ["Everything Always", "Dom Dolla & John Summit"]

    def test_case_insensitive_connectors(self):
        assert split_artist("Artist1 b2b Artist2") == ["Artist1", "b2b Artist2"]

    def test_embedded_ampersand_no_spaces_not_split(self):
        assert split_artist("AC&DC") == ["AC&DC"]

    def test_empty_string(self):
        assert split_artist("") == [""]


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

    def test_multi_artist_produces_multi_line_block(self):
        from tracksplit.cover import _layout_album_cover

        L = _layout_album_cover(
            artist="Martin Garrix & Alesso",
            festival="Ultra",
            date="",
            stage="",
            venue="",
            size=1000,
        )
        assert L["artist_lines"] == ["MARTIN GARRIX", "& ALESSO"]
        # All lines share one font.
        assert L["artist_font"] is not None
        # Block sits above the accent rail.
        assert L["artist_block_top"] + L["artist_block_h"] <= L["line_y"]

    def test_single_artist_single_line_block(self):
        from tracksplit.cover import _layout_album_cover

        L = _layout_album_cover(
            artist="Hardwell",
            festival="Ultra",
            date="",
            stage="",
            venue="",
            size=1000,
        )
        assert L["artist_lines"] == ["HARDWELL"]

    def test_layout_no_overlap_no_overflow(self):
        """Worst-case text must sit below the photo and stay within canvas."""
        from tracksplit.cover import _layout_album_cover

        L = _layout_album_cover(
            artist="Agents Of Time",
            festival="Tomorrowland Belgium",
            date="2025-07-25",
            stage="Live At The Main Stage, Mainstage",
            venue="De Schorre, Boom, Belgium",
            size=1000,
        )
        # Artist text must land within the fade/gradient zone, i.e. below
        # the photo's opaque region.
        photo_fade_start = int(L["photo_h"] * 0.60)
        assert L["artist_block_top"] >= photo_fade_start, (
            f"artist text overlaps opaque photo: artist_block_top={L['artist_block_top']} "
            f"< fade_start={photo_fade_start}"
        )
        assert L["final_cursor_y"] <= L["size"] - L["bottom_margin"], (
            f"below-line text overflows: {L['final_cursor_y']} > "
            f"{L['size'] - L['bottom_margin']}"
        )
        # Line is pinned at y=720 regardless of content.
        assert L["line_y"] == int(720 * (L["size"] / 1000.0))
        # Stage collapses to at most a single line; venue is dropped.
        assert len(L["stage_parts"]) <= 1
        assert L["venue_font"] is None

    def test_compose_cover_multi_artist_does_not_crash(self):
        result = compose_cover(
            artist="Axwell & Sebastian Ingrosso & Steve Angello",
            festival="Tomorrowland",
            date="2025-07-25",
            stage="Main Stage",
        )
        assert isinstance(result, bytes)
        img = Image.open(io.BytesIO(result))
        assert img.size == (1000, 1000)


class TestFindDjArtwork:
    @pytest.fixture(autouse=True)
    def _empty_cache(self, tmp_path, monkeypatch):
        """Isolate tests from the real CrateDigger cache directory."""
        empty = tmp_path / "_empty_cd_cache"
        empty.mkdir()
        monkeypatch.setattr("tracksplit.cover.cratedigger_cache_dir", lambda: empty)

    def test_slug_resolves_cache_folder(self, tmp_path, monkeypatch):
        """The embedded slug keys the cache folder directly."""
        cache_dir = tmp_path / "cd_cache"
        artist_dir = cache_dir / "artists" / "aboveandbeyond"
        artist_dir.mkdir(parents=True)
        (artist_dir / "dj-artwork.jpg").write_bytes(b"slug-artwork")
        monkeypatch.setattr("tracksplit.cover.cratedigger_cache_dir", lambda: cache_dir)
        monkeypatch.setattr("tracksplit.paths.walkup_cratedigger_dir", lambda _p: None)
        monkeypatch.setattr(
            "tracksplit.paths.cratedigger_data_dir",
            lambda: tmp_path / "empty",
        )

        result = find_dj_artwork(
            tmp_path / "file.mkv",
            slug="aboveandbeyond",
            artist="Above & Beyond",
        )
        assert result == b"slug-artwork"

    def test_folder_slug_strips_trailing_dots(self, tmp_path, monkeypatch):
        """A real slug with trailing dots resolves the Windows-safe folder."""
        cache_dir = tmp_path / "cd_cache"
        artist_dir = cache_dir / "artists" / "fredagain"
        artist_dir.mkdir(parents=True)
        (artist_dir / "dj-artwork.jpg").write_bytes(b"fred-artwork")
        monkeypatch.setattr("tracksplit.cover.cratedigger_cache_dir", lambda: cache_dir)
        monkeypatch.setattr("tracksplit.paths.walkup_cratedigger_dir", lambda _p: None)
        monkeypatch.setattr(
            "tracksplit.paths.cratedigger_data_dir",
            lambda: tmp_path / "empty",
        )

        result = find_dj_artwork(tmp_path / "file.mkv", slug="fredagain..")
        assert result == b"fred-artwork"

    def test_prefers_dj_artwork_over_fanart(self, tmp_path, monkeypatch):
        cache_dir = tmp_path / "cd_cache"
        artist_dir = cache_dir / "artists" / "tiesto"
        artist_dir.mkdir(parents=True)
        (artist_dir / "dj-artwork.jpg").write_bytes(b"dj-data")
        (artist_dir / "fanart.jpg").write_bytes(b"fan-data")
        monkeypatch.setattr("tracksplit.cover.cratedigger_cache_dir", lambda: cache_dir)
        monkeypatch.setattr("tracksplit.paths.walkup_cratedigger_dir", lambda _p: None)
        monkeypatch.setattr(
            "tracksplit.paths.cratedigger_data_dir",
            lambda: tmp_path / "empty",
        )

        result = find_dj_artwork(tmp_path / "file.mkv", slug="tiesto")
        assert result == b"dj-data"

    def test_falls_back_to_fanart(self, tmp_path, monkeypatch):
        cache_dir = tmp_path / "cd_cache"
        artist_dir = cache_dir / "artists" / "tiesto"
        artist_dir.mkdir(parents=True)
        (artist_dir / "fanart.jpg").write_bytes(b"fan-data")
        monkeypatch.setattr("tracksplit.cover.cratedigger_cache_dir", lambda: cache_dir)
        monkeypatch.setattr("tracksplit.paths.walkup_cratedigger_dir", lambda _p: None)
        monkeypatch.setattr(
            "tracksplit.paths.cratedigger_data_dir",
            lambda: tmp_path / "empty",
        )

        result = find_dj_artwork(tmp_path / "file.mkv", slug="tiesto")
        assert result == b"fan-data"

    def test_slugify_fallback_when_no_slug(self, tmp_path, monkeypatch):
        """Files without the slug tag fall back to slugify(artist)."""
        cache_dir = tmp_path / "cd_cache"
        artist_dir = cache_dir / "artists" / "cosmicgate"
        artist_dir.mkdir(parents=True)
        (artist_dir / "dj-artwork.jpg").write_bytes(b"cg-artwork")
        monkeypatch.setattr("tracksplit.cover.cratedigger_cache_dir", lambda: cache_dir)
        monkeypatch.setattr("tracksplit.paths.walkup_cratedigger_dir", lambda _p: None)
        monkeypatch.setattr(
            "tracksplit.paths.cratedigger_data_dir",
            lambda: tmp_path / "empty",
        )

        result = find_dj_artwork(tmp_path / "file.mkv", artist="Cosmic Gate")
        assert result == b"cg-artwork"

    def test_slug_wins_over_artist_slugify(self, tmp_path, monkeypatch):
        """When both are given, the explicit slug is used (not slugify(artist))."""
        cache_dir = tmp_path / "cd_cache"
        (cache_dir / "artists" / "aboveandbeyond").mkdir(parents=True)
        (cache_dir / "artists" / "aboveandbeyond" / "dj-artwork.jpg").write_bytes(
            b"by-slug"
        )
        # slugify("Above & Beyond") would also be "aboveandbeyond", so use a slug
        # that differs from slugify(artist) to prove the slug path is taken.
        (cache_dir / "artists" / "ab").mkdir(parents=True)
        (cache_dir / "artists" / "ab" / "dj-artwork.jpg").write_bytes(b"by-real-slug")
        monkeypatch.setattr("tracksplit.cover.cratedigger_cache_dir", lambda: cache_dir)
        monkeypatch.setattr("tracksplit.paths.walkup_cratedigger_dir", lambda _p: None)
        monkeypatch.setattr(
            "tracksplit.paths.cratedigger_data_dir",
            lambda: tmp_path / "empty",
        )

        result = find_dj_artwork(
            tmp_path / "file.mkv", slug="ab", artist="Above & Beyond"
        )
        assert result == b"by-real-slug"

    def test_finds_in_data_dir_by_slug(self, tmp_path, monkeypatch):
        """Walk-up .cratedigger/artists/<slug>/ is searched too."""
        cd_dir = tmp_path / ".cratedigger"
        artist_dir = cd_dir / "artists" / "tiesto"
        artist_dir.mkdir(parents=True)
        (artist_dir / "dj-artwork.jpg").write_bytes(b"data-artwork")
        monkeypatch.setattr(
            "tracksplit.paths.walkup_cratedigger_dir", lambda _p: cd_dir
        )
        monkeypatch.setattr(
            "tracksplit.paths.cratedigger_data_dir",
            lambda: tmp_path / "empty",
        )

        result = find_dj_artwork(tmp_path / "music" / "file.mkv", slug="tiesto")
        assert result == b"data-artwork"

    def test_cache_takes_priority_over_data(self, tmp_path, monkeypatch):
        cache_dir = tmp_path / "cd_cache"
        (cache_dir / "artists" / "tiesto").mkdir(parents=True)
        (cache_dir / "artists" / "tiesto" / "dj-artwork.jpg").write_bytes(b"from-cache")
        data_dir = tmp_path / ".cratedigger"
        (data_dir / "artists" / "tiesto").mkdir(parents=True)
        (data_dir / "artists" / "tiesto" / "dj-artwork.jpg").write_bytes(b"from-data")
        monkeypatch.setattr("tracksplit.cover.cratedigger_cache_dir", lambda: cache_dir)
        monkeypatch.setattr(
            "tracksplit.paths.walkup_cratedigger_dir", lambda _p: data_dir
        )
        monkeypatch.setattr(
            "tracksplit.paths.cratedigger_data_dir",
            lambda: tmp_path / "empty",
        )

        result = find_dj_artwork(tmp_path / "file.mkv", slug="tiesto")
        assert result == b"from-cache"

    def test_no_slug_no_artist_returns_none(self, tmp_path):
        assert find_dj_artwork(tmp_path / "file.flac") is None

    def test_returns_none_when_not_found(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tracksplit.paths.walkup_cratedigger_dir", lambda _p: None)
        monkeypatch.setattr(
            "tracksplit.paths.cratedigger_data_dir",
            lambda: tmp_path / "empty_visible",
        )
        result = find_dj_artwork(tmp_path / "file.flac", slug="nobody")
        assert result is None

    def test_logs_not_found(self, tmp_path, monkeypatch, caplog):
        import logging

        monkeypatch.setattr("tracksplit.paths.walkup_cratedigger_dir", lambda _p: None)
        monkeypatch.setattr(
            "tracksplit.paths.cratedigger_data_dir",
            lambda: tmp_path / "empty",
        )

        with caplog.at_level(logging.DEBUG, logger="tracksplit.cover"):
            result = find_dj_artwork(tmp_path / "file.mkv", slug="nobody")
        assert result is None
        assert any("found=false" in r.message for r in caplog.records)


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

    def test_photo_used_as_background(self):
        """DJ photo serves as both the sharp image and the blurred background."""
        photo = _make_image_bytes((200, 100, 50), 400, 400)
        result = compose_artist_cover("Artist", dj_artwork_data=photo)
        assert isinstance(result, bytes)
        img = Image.open(io.BytesIO(result))
        assert img.size == (1000, 1000)

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
    def test_mkvtools_success(self, mock_run):
        """MKV files try mkvmerge/mkvextract first."""
        identify_json = '{"attachments": [{"id": 1, "content_type": "image/jpeg"}]}'
        fake_image = b"\xff\xd8\xff\xe0fake_jpeg_data"

        def side_effect(cmd, **kwargs):
            if any("mkvmerge" in str(c) for c in cmd):
                return MagicMock(stdout=identify_json, returncode=0)
            elif any("mkvextract" in str(c) for c in cmd):
                import re

                for part in cmd:
                    m = re.match(r"\d+:(.*)", str(part))
                    if m:
                        Path(m.group(1)).write_bytes(fake_image)
                return MagicMock(returncode=0)
            return MagicMock(returncode=0)

        mock_run.side_effect = side_effect
        result = extract_cover_from_mkv(Path("/tmp/video.mkv"))
        assert result == fake_image

    @patch("tracksplit.cover.subprocess.run")
    def test_ffmpeg_stream_extraction(self, mock_run):
        """Non-MKV and mkvtools-unavailable paths use ffmpeg stream mapping."""
        fake_image = b"\xff\xd8\xff\xe0fake_jpeg_data"
        ffprobe_data = {
            "streams": [
                {"index": 0, "codec_type": "video", "codec_name": "av1"},
                {"index": 1, "codec_type": "audio", "codec_name": "opus"},
                {
                    "index": 2,
                    "codec_type": "video",
                    "codec_name": "png",
                    "tags": {"filename": "cover.png", "mimetype": "image/png"},
                },
            ],
        }

        def side_effect(cmd, **kwargs):
            if any("ffmpeg" in str(c) for c in cmd):
                # Find the output path (last arg) and write fake image
                for i, part in enumerate(cmd):
                    if str(part).endswith((".png", ".jpg", ".webp")):
                        try:
                            Path(str(part)).write_bytes(fake_image)
                        except OSError:
                            pass
                return MagicMock(returncode=0)
            return MagicMock(returncode=0)

        mock_run.side_effect = side_effect
        result = extract_cover_from_mkv(
            Path("/tmp/video.mp4"),
            ffprobe_data=ffprobe_data,
        )
        assert result == fake_image

    def test_no_cover_stream_returns_none(self):
        """Files without an image stream return None."""
        ffprobe_data = {
            "streams": [
                {"index": 0, "codec_type": "video", "codec_name": "h264"},
                {"index": 1, "codec_type": "audio", "codec_name": "aac"},
            ],
        }
        result = extract_cover_from_mkv(
            Path("/tmp/video.mp4"),
            ffprobe_data=ffprobe_data,
        )
        assert result is None


class TestLoadFont:
    def test_returns_freetype_font(self):
        """Bundled Inter font should load as a FreeTypeFont, not bitmap."""
        from PIL import ImageFont

        font = _load_font(90, bold=True)
        assert isinstance(font, ImageFont.FreeTypeFont)

    def test_size_scales_width(self):
        """Rendered text width must scale with size (not fixed bitmap width)."""
        from tracksplit.cover import _measure_w

        small = _load_font(40, bold=True)
        large = _load_font(90, bold=True)
        w_small = _measure_w(small, "TIESTO")
        w_large = _measure_w(large, "TIESTO")
        assert w_large > w_small * 1.5

    def test_unicode_glyph_rendered(self):
        """Inter includes 'ë' so measured width should be reasonable."""
        from tracksplit.cover import _measure_w

        font = _load_font(90, bold=True)
        plain = _measure_w(font, "TIESTO")
        accented = _measure_w(font, "TIëSTO")
        # The accented version should be similar width to the plain version
        # (not tiny because the glyph is missing)
        assert accented >= plain * 0.8


class TestIsImageAttachment:
    def test_by_content_type(self):
        assert _is_image_attachment({"content_type": "image/jpeg"}) is True
        assert _is_image_attachment({"content_type": "image/png"}) is True

    def test_by_file_name(self):
        assert (
            _is_image_attachment({"content_type": "", "file_name": "cover.jpg"}) is True
        )
        assert _is_image_attachment({"file_name": "COVER.PNG"}) is True

    def test_non_image(self):
        assert _is_image_attachment({"content_type": "text/plain"}) is False
        assert _is_image_attachment({"file_name": "notes.txt"}) is False
        assert _is_image_attachment({}) is False


class TestPickImageAttachment:
    def test_prefers_cover_named(self):
        atts = [
            {"id": 1, "content_type": "image/jpeg", "file_name": "other.jpg"},
            {"id": 2, "content_type": "image/jpeg", "file_name": "cover.jpg"},
        ]
        result = _pick_image_attachment(atts)
        assert result is not None
        assert result["id"] == 2

    def test_picks_only_image(self):
        atts = [
            {"id": 1, "content_type": "text/plain"},
            {"id": 2, "content_type": "image/png", "file_name": "pic.png"},
        ]
        result = _pick_image_attachment(atts)
        assert result is not None
        assert result["id"] == 2

    def test_prefers_cover_land_over_cover(self):
        atts = [
            {"id": 1, "content_type": "image/jpeg", "file_name": "cover.jpg"},
            {"id": 2, "content_type": "image/jpeg", "file_name": "cover_land.jpg"},
        ]
        result = _pick_image_attachment(atts)
        assert result is not None
        assert result["id"] == 2

    def test_empty(self):
        assert _pick_image_attachment([]) is None


class TestFitSquare:
    """Item 5: the artist photo is center-cropped to square, not stretched."""

    def test_returns_square(self):
        from tracksplit.cover import _fit_square

        img = Image.new("RGB", (1920, 1080), (10, 20, 30))
        out = _fit_square(img, 550)
        assert out.size == (550, 550)

    def test_center_crops_not_stretches(self):
        from tracksplit.cover import _fit_square

        # Red center band with green far-left/far-right vertical strips.
        # A center-crop to square keeps only the red center (the green edges
        # fall outside the 1:1 crop); a naive resize would squeeze the green
        # edges into the result's left/right edges instead.
        img = Image.new("RGB", (1920, 1080), (220, 30, 30))
        green = Image.new("RGB", (420, 1080), (30, 220, 30))
        img.paste(green, (0, 0))
        img.paste(green, (1500, 0))
        out = _fit_square(img, 550).convert("RGB")
        px = out.getpixel((5, 275))
        assert isinstance(px, tuple)
        assert px[0] > px[1], (
            "left edge should be the cropped-in red center, not stretched green"
        )


class TestPrepareBackgroundRatioGuard:
    """Item 4: a non-landscape source is rejected as a full-bleed album background."""

    def test_landscape_used(self):
        from tracksplit.cover import _ensure_contrast, _prepare_background

        data = _make_image_bytes((40, 80, 200), 1000, 400)
        _bg, accent = _prepare_background(data, 1000, reject_non_landscape=True)
        assert accent != _ensure_contrast(180, 100, 220)

    def test_portrait_rejected_to_gradient(self, caplog):
        import logging

        from tracksplit.cover import _ensure_contrast, _prepare_background

        data = _make_image_bytes((40, 80, 200), 400, 500)
        with caplog.at_level(logging.WARNING):
            _bg, accent = _prepare_background(data, 1000, reject_non_landscape=True)
        assert accent == _ensure_contrast(180, 100, 220)
        assert any("bg_reject" in r.getMessage() for r in caplog.records)

    def test_square_not_rejected_when_guard_off(self):
        """Artist covers (default reject_non_landscape=False) keep square sources."""
        from tracksplit.cover import _ensure_contrast, _prepare_background

        data = _make_image_bytes((40, 80, 200), 600, 600)
        _bg, accent = _prepare_background(data, 1000)
        assert accent != _ensure_contrast(180, 100, 220)


class TestMkvtoolsTempFileUnique:
    """Verify unique temp file names to prevent parallel worker races."""

    @patch("tracksplit.cover.subprocess.run")
    def test_different_calls_use_different_temp_files(self, mock_run, tmp_path):
        """Two parallel extractions must not share a temp file path."""
        identify_json = '{"attachments": [{"id": 1, "content_type": "image/jpeg", "file_name": "cover.jpg"}]}'
        seen_paths = []

        def side_effect(cmd, **kwargs):
            if "mkvmerge" in cmd[0] if cmd else "":
                return MagicMock(stdout=identify_json, returncode=0)
            elif "mkvextract" in (cmd[0] if cmd else ""):
                import re

                for part in cmd:
                    m = re.match(r"\d+:(.*)", part)
                    if m:
                        seen_paths.append(m.group(1))
                        Path(m.group(1)).write_bytes(b"data")
                return MagicMock(returncode=0)
            return MagicMock(returncode=0)

        mock_run.side_effect = side_effect

        extract_cover_from_mkv(Path("/tmp/video1.mkv"))
        extract_cover_from_mkv(Path("/tmp/video2.mkv"))

        assert len(seen_paths) == 2
        assert seen_paths[0] != seen_paths[1]


class TestFestivalFallback:
    def test_festival_used_when_present(self):
        from tracksplit.cover import _layout_album_cover

        L = _layout_album_cover(
            artist="A",
            festival="Ultra",
            date="",
            stage="",
            venue="",
            size=1000,
        )
        assert L["fest_text"] == "ULTRA"

    def test_venue_fills_slot_when_festival_empty(self):
        from tracksplit.cover import _layout_album_cover

        L = _layout_album_cover(
            artist="A",
            festival="",
            date="",
            stage="",
            venue="Red Rocks",
            size=1000,
        )
        assert L["fest_text"] == "RED ROCKS"

    def test_stage_fills_slot_when_festival_and_venue_empty(self):
        from tracksplit.cover import _layout_album_cover

        L = _layout_album_cover(
            artist="A",
            festival="",
            date="",
            stage="Mainstage",
            venue="",
            size=1000,
        )
        assert L["fest_text"] == "MAINSTAGE"

    def test_stage_subline_suppressed_when_stage_fills_slot(self):
        from tracksplit.cover import _layout_album_cover

        L = _layout_album_cover(
            artist="A",
            festival="",
            date="",
            stage="Mainstage",
            venue="",
            size=1000,
        )
        assert L["stage_parts"] == [], (
            "stage must not render twice when it filled the festival slot"
        )

    def test_stage_subline_kept_when_festival_fills_slot(self):
        from tracksplit.cover import _layout_album_cover

        L = _layout_album_cover(
            artist="A",
            festival="Ultra",
            date="",
            stage="Mainstage",
            venue="",
            size=1000,
        )
        assert L["fest_text"] == "ULTRA"
        assert L["stage_parts"] == ["Mainstage"]

    def test_stage_subline_kept_when_venue_fills_slot(self):
        from tracksplit.cover import _layout_album_cover

        L = _layout_album_cover(
            artist="A",
            festival="",
            date="",
            stage="Mainstage",
            venue="Red Rocks",
            size=1000,
        )
        assert L["fest_text"] == "RED ROCKS"
        assert L["stage_parts"] == ["Mainstage"]

    def test_all_empty_leaves_slot_blank(self):
        from tracksplit.cover import _layout_album_cover

        L = _layout_album_cover(
            artist="A",
            festival="",
            date="",
            stage="",
            venue="",
            size=1000,
        )
        assert L["fest_text"] == ""
        assert L["fest_font"] is None

    def test_stage_with_commas_collapses_in_accent_slot(self):
        from tracksplit.cover import _layout_album_cover

        L = _layout_album_cover(
            artist="A",
            festival="",
            date="",
            stage="Main, Balcony",
            venue="",
            size=1000,
        )
        # Accent slot renders the collapsed first segment, matching the
        # subline collapse rule so the same stage input looks the same
        # wherever it renders.
        assert L["fest_text"] == "MAIN"
        assert L["stage_parts"] == []

    def test_whitespace_only_festival_falls_through_to_venue(self):
        from tracksplit.cover import _layout_album_cover

        L = _layout_album_cover(
            artist="A",
            festival="   ",
            date="",
            stage="",
            venue="Red Rocks",
            size=1000,
        )
        assert L["fest_text"] == "RED ROCKS"


class TestLayoutAlbumArtistLines:
    def _lines(self, albumartists, artist="X"):
        L = _layout_album_cover(
            artist, "Festival", "", "", "", 1000, albumartists=albumartists
        )
        return L["artist_lines"]

    def test_single_act_with_ampersand_stays_one_line(self):
        assert self._lines(["Above & Beyond"]) == ["ABOVE & BEYOND"]

    def test_b2b_keeps_ampersand_prefix(self):
        assert self._lines(["Martin Garrix", "Alesso"]) == ["MARTIN GARRIX", "& ALESSO"]

    def test_three_way_b2b(self):
        assert self._lines(["A", "B", "C"]) == ["A", "& B", "& C"]

    def test_none_falls_back_to_split_artist(self):
        L = _layout_album_cover(
            "Above & Beyond", "Festival", "", "", "", 1000, albumartists=None
        )
        assert L["artist_lines"] == ["ABOVE", "& BEYOND"]

    def test_empty_list_falls_back_to_split_artist(self):
        L = _layout_album_cover(
            "Above & Beyond", "Festival", "", "", "", 1000, albumartists=[]
        )
        assert L["artist_lines"] == ["ABOVE", "& BEYOND"]
