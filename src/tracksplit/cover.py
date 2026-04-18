"""Cover art: accent color extraction, line-anchored album/artist covers."""

import colorsys
import io
import json
import logging
import math
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, UnidentifiedImageError

from tracksplit.cratedigger import find_cratedigger_dirs
from tracksplit.fonts import get_font_path
from tracksplit.tools import get_tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Font helpers
# ---------------------------------------------------------------------------
def _load_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    """Load the bundled Inter font at the given size."""
    weight = "bold" if bold else "regular"
    path = get_font_path(weight)
    return ImageFont.truetype(path, size)


def _measure_w(font: ImageFont.FreeTypeFont | ImageFont.ImageFont, text: str) -> int:
    """Return text width in pixels."""
    bbox = font.getbbox(text)
    return int(bbox[2] - bbox[0])


def _font_height(font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> int:
    """Return ascent + descent for the font."""
    try:
        ascent, descent = font.getmetrics()  # type: ignore[union-attr]
        return ascent + descent
    except AttributeError:
        bbox = font.getbbox("Ay")
        return int(bbox[3] - bbox[1])


def split_artist(name: str) -> list[str]:
    """Split a multi-artist credit into one display line per artist.

    Rules (in priority order):
    1. "Act Name (Artist & Artist)" -> ["Act Name", "Artist & Artist"]
    2. One or more connectors (" & ", " B2B ", " VS ", " X ", case-insensitive):
       one line per artist segment, connectors kept on subsequent lines.
    3. No connector: single-element list with the original name.

    No group protection: users who want a duo kept on one line should
    alias it to a short canonical form via the artist_aliases config.
    """
    paren_match = re.match(r"^(.+?)\s*\((.+)\)\s*$", name)
    if paren_match:
        return [paren_match.group(1).strip(), paren_match.group(2).strip()]

    upper = name.upper()
    splits: list[tuple[int, str]] = []
    for sep in (" & ", " B2B ", " VS ", " X "):
        start = 0
        while True:
            idx = upper.find(sep, start)
            if idx == -1:
                break
            splits.append((idx, sep))
            start = idx + len(sep)

    if not splits:
        return [name]
    splits.sort()

    if len(splits) == 1:
        idx, _sep = splits[0]
        return [name[:idx].strip(), name[idx:].strip()]

    lines = [name[: splits[0][0]].strip()]
    for i, (idx, _sep) in enumerate(splits):
        end = splits[i + 1][0] if i + 1 < len(splits) else len(name)
        lines.append(name[idx:end].strip())
    return lines


def _auto_fit(
    text: str, bold: bool, max_width: int, start: int = 90, minimum: int = 40
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Return the largest font that fits text within max_width."""
    for size in range(start, minimum - 1, -1):
        font = _load_font(size, bold=bold)
        if _measure_w(font, text) <= max_width:
            return font
    return _load_font(minimum, bold=bold)


# ---------------------------------------------------------------------------
# WCAG contrast helpers
# ---------------------------------------------------------------------------
def _wcag_luminance(r: int, g: int, b: int) -> float:
    """Relative luminance per WCAG 2.0."""
    vals = []
    for c in (r, g, b):
        s = c / 255.0
        if s <= 0.04045:
            vals.append(s / 12.92)
        else:
            vals.append(((s + 0.055) / 1.055) ** 2.4)
    return 0.2126 * vals[0] + 0.7152 * vals[1] + 0.0722 * vals[2]


def _wcag_contrast(rgb1: tuple[int, int, int], rgb2: tuple[int, int, int]) -> float:
    """Contrast ratio between two RGB colors."""
    l1 = _wcag_luminance(*rgb1)
    l2 = _wcag_luminance(*rgb2)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _ensure_contrast(
    r: int, g: int, b: int, bg: tuple[int, int, int] = (10, 10, 10), target: float = 4.5
) -> tuple[int, int, int]:
    """Boost brightness until WCAG AA contrast ratio is met against bg."""
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    for _ in range(100):
        rr, gg, bb = (int(c * 255) for c in colorsys.hsv_to_rgb(h, s, v))
        if _wcag_contrast((rr, gg, bb), bg) >= target:
            return (rr, gg, bb)
        v = min(1.0, v + 0.02)
        s = max(0.0, s - 0.01)
    rr, gg, bb = (int(c * 255) for c in colorsys.hsv_to_rgb(h, s, v))
    return (rr, gg, bb)


# ---------------------------------------------------------------------------
# Accent color extraction
# ---------------------------------------------------------------------------
def _circular_hue_mean(h_array: np.ndarray, s_array: np.ndarray, min_sat: int = 40) -> float:
    """Circular mean of hue (0-360) weighted by saturation.

    Filters pixels below min_sat. Uses sin/cos decomposition to handle
    the wrapping at red (0/360 degrees).
    """
    mask = s_array >= min_sat
    h_filtered = h_array[mask]
    s_filtered = s_array[mask]

    if len(h_filtered) == 0:
        return 0.0

    radians = np.deg2rad(h_filtered.astype(np.float64))
    weights = s_filtered.astype(np.float64)

    sin_mean = np.average(np.sin(radians), weights=weights)
    cos_mean = np.average(np.cos(radians), weights=weights)

    mean_rad = math.atan2(sin_mean, cos_mean)
    mean_deg = math.degrees(mean_rad) % 360
    return mean_deg


def get_accent_color(img: Image.Image) -> tuple[int, int, int]:
    """Derive accent RGB from an image.

    Convert to HSV, compute circular hue mean, set V=0.95, then
    ensure WCAG AA contrast against a dark background.
    """
    small = img.copy()
    small.thumbnail((200, 200))
    hsv = small.convert("HSV")

    data = np.array(hsv)
    # PIL HSV: H is 0-255, S is 0-255, V is 0-255
    # Scale H to 0-360 and S to 0-255
    h_array = data[:, :, 0].flatten().astype(np.float64) * (360.0 / 255.0)
    s_array = data[:, :, 1].flatten().astype(np.float64) * (100.0 / 255.0)

    hue_deg = _circular_hue_mean(h_array, s_array, min_sat=40)

    # Convert to RGB with V=0.95
    h_norm = hue_deg / 360.0
    s_norm = 0.8
    v_norm = 0.95
    r, g, b = colorsys.hsv_to_rgb(h_norm, s_norm, v_norm)
    rgb = (int(r * 255), int(g * 255), int(b * 255))

    return _ensure_contrast(*rgb)


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------
def create_gradient(width: int, height: int) -> Image.Image:
    """Create a dark gradient background with purple/blue tones."""
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)

    for y in range(height):
        ratio = y / max(height - 1, 1)
        r = int(25 + 5 * ratio)
        g = int(10 + 15 * ratio)
        b = int(40 + 30 * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    return img


def _draw_centered(
    draw: ImageDraw.ImageDraw,
    canvas_w: int,
    y: int,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: tuple[int, ...],
) -> None:
    """Draw centered text WITH drop shadow."""
    tw = _measure_w(font, text)
    x = (canvas_w - tw) // 2
    # Drop shadow
    draw.text((x + 2, y + 3), text, font=font, fill=(0, 0, 0, 160))
    draw.text((x, y), text, font=font, fill=fill)


def _draw_centered_no_shadow(
    draw: ImageDraw.ImageDraw,
    canvas_w: int,
    y: int,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: tuple[int, ...],
) -> None:
    """Draw centered text without shadow."""
    tw = _measure_w(font, text)
    x = (canvas_w - tw) // 2
    draw.text((x, y), text, font=font, fill=fill)


def _draw_glow_line(
    base_img: Image.Image,
    y: int,
    width: int,
    height: int,
    color: tuple[int, int, int],
    glow_radius: int = 14,
) -> Image.Image:
    """Draw an accent line with glow effect. Returns new RGB image."""
    canvas_w = base_img.size[0]
    x_start = (canvas_w - width) // 2

    # Create glow overlay
    overlay = Image.new("RGBA", base_img.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(overlay)

    # Thick rectangle for glow source
    glow_draw.rectangle(
        [x_start, y, x_start + width, y + height],
        fill=(*color, 200),
    )

    # Blur twice for soft glow
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=glow_radius))
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=glow_radius // 2))

    # Composite glow onto base
    base_rgba = base_img.convert("RGBA")
    composited = Image.alpha_composite(base_rgba, overlay)

    # Draw sharp line on top
    sharp_draw = ImageDraw.Draw(composited)
    sharp_draw.rectangle(
        [x_start, y, x_start + width, y + height],
        fill=(*color, 255),
    )

    return composited.convert("RGB")


def _prepare_background(
    background_data: bytes | None, size: int, darkness: float = 0.4
) -> tuple[Image.Image, tuple[int, int, int]]:
    """Blur+darken background or create gradient. Returns (image, accent_color).

    darkness: 0.0 = black, 1.0 = no darkening. Album covers use 0.4,
    artist covers use 0.18 (CrateDigger style).
    """
    if background_data is not None:
        try:
            bg = Image.open(io.BytesIO(background_data)).convert("RGB")
        except (UnidentifiedImageError, OSError) as exc:
            logger.warning("Could not decode background image, using gradient: %s", exc)
            bg = create_gradient(size, size)
            accent = _ensure_contrast(180, 100, 220)
            return bg, accent

        # Cover-fit resize and center crop
        src_w, src_h = bg.size
        scale = max(size / src_w, size / src_h)
        new_w = int(src_w * scale)
        new_h = int(src_h * scale)
        bg = bg.resize((new_w, new_h), Image.Resampling.LANCZOS)

        left = (new_w - size) // 2
        top = (new_h - size) // 2
        bg = bg.crop((left, top, left + size, top + size))

        # Get accent before blurring
        accent = get_accent_color(bg)

        # Blur and darken
        bg = bg.filter(ImageFilter.GaussianBlur(radius=40))
        bg = ImageEnhance.Brightness(bg).enhance(darkness)

        return bg, accent
    else:
        bg = create_gradient(size, size)
        # Default accent: a warm purple/magenta
        accent = _ensure_contrast(180, 100, 220)
        return bg, accent


# ---------------------------------------------------------------------------
# Date formatting
# ---------------------------------------------------------------------------
def format_date_display(date: str) -> str:
    """Format date for display: '2026-03-01' -> '1 March 2026', '2026' -> '2026'."""
    if not date:
        return ""
    if len(date) == 4:
        return date
    parts = date.split("-")
    if len(parts) == 3:
        months = [
            "", "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ]
        year, month, day = parts
        month_idx = int(month)
        if 1 <= month_idx <= 12:
            return f"{int(day)} {months[month_idx]} {year}"
    return date


# ---------------------------------------------------------------------------
# Album cover composition
# ---------------------------------------------------------------------------
PHOTO_HEIGHT_FRAC = 0.60
PHOTO_FADE_START_FRAC = 0.60
GRADIENT_START_FRAC = 0.40
GRADIENT_MAX_ALPHA = 200
GRADIENT_GAMMA = 1.4


def _apply_fade_photo(
    canvas: Image.Image,
    photo_data: bytes,
    photo_h: int,
) -> None:
    """Paste photo at top of canvas, cover-fit to width, fading to transparent
    starting at PHOTO_FADE_START_FRAC of photo height.
    """
    w = canvas.size[0]
    try:
        src = Image.open(io.BytesIO(photo_data)).convert("RGBA")
    except Exception:
        logger.warning("Failed to open set artwork for fade photo; skipping")
        return

    src_w, src_h = src.size
    scale = max(w / src_w, photo_h / src_h)
    new_w = int(src_w * scale)
    new_h = int(src_h * scale)
    src = src.resize((new_w, new_h), Image.Resampling.LANCZOS)

    left = (new_w - w) // 2
    top = (new_h - photo_h) // 2
    photo = src.crop((left, top, left + w, top + photo_h))

    fade_mask = Image.new("L", (w, photo_h), 255)
    fade_start = int(photo_h * PHOTO_FADE_START_FRAC)
    if photo_h > fade_start:
        dm = ImageDraw.Draw(fade_mask)
        span = photo_h - fade_start
        for y in range(fade_start, photo_h):
            alpha = int(255 * (1.0 - (y - fade_start) / span))
            dm.line([(0, y), (w, y)], fill=alpha)

    photo.putalpha(fade_mask)
    canvas.alpha_composite(photo, dest=(0, 0))


def _apply_dark_gradient(canvas: Image.Image) -> None:
    """Composite a darkening gradient from GRADIENT_START_FRAC down to bottom
    using a gamma-shaped curve for natural falloff.
    """
    w, h = canvas.size
    start = int(h * GRADIENT_START_FRAC)
    if start >= h:
        return
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dg = ImageDraw.Draw(overlay)
    span = h - start
    for y in range(start, h):
        progress = (y - start) / span
        a = int(GRADIENT_MAX_ALPHA * (progress ** GRADIENT_GAMMA))
        dg.line([(0, y), (w, y)], fill=(0, 0, 0, a))
    canvas.alpha_composite(overlay)


def _layout_album_cover(
    artist: str,
    festival: str,
    date: str,
    stage: str,
    venue: str,
    size: int,
) -> dict:
    """Measure fonts and compute positions for compose_cover.

    Returns a dict with fitted fonts, their heights, and y-positions.
    Below-line content shrinks / drops venue to fit within canvas.
    Line position is pinned below the photo area.
    """
    s = size / 1000.0
    max_text_w = int(size * 0.85)
    bottom_margin = int(20 * s)
    top_margin = int(20 * s)
    line_h = max(1, int(4 * s))
    line_w = int(400 * s)
    photo_h = int(size * PHOTO_HEIGHT_FRAC)

    PAD_LINE_TO_ARTIST = int(28 * s)
    PAD_LINE_TO_FEST = int(20 * s)
    PAD_FEST_TO_DATE = int(14 * s)
    PAD_DATE_TO_DETAIL = int(14 * s)
    PAD_DETAIL_LINES = int(8 * s)

    PAD_ARTIST_LINES = int(6 * s)
    artist_lines = [line.upper() for line in split_artist(artist)]
    # Size the shared font to the widest line so all lines align visually.
    longest = max(artist_lines, key=len) if artist_lines else ""
    artist_font = _auto_fit(
        longest, True, max_text_w, start=int(100 * s), minimum=int(54 * s)
    )
    line_h_artist = _font_height(artist_font)
    artist_block_h = (
        len(artist_lines) * line_h_artist
        + max(0, len(artist_lines) - 1) * PAD_ARTIST_LINES
    )

    fest_text = festival.upper() if festival else ""
    fest_font = None
    fest_h = 0
    if fest_text:
        fest_font = _auto_fit(
            fest_text, True, max_text_w, start=int(80 * s), minimum=int(36 * s)
        )
        fest_h = _font_height(fest_font)

    date_display = format_date_display(date)
    date_font = None
    date_h = 0
    if date_display:
        date_font = _auto_fit(
            date_display, False, max_text_w, start=int(44 * s), minimum=int(26 * s)
        )
        date_h = _font_height(date_font)

    # Stage collapses to at most one line: first comma-separated part only.
    first_stage = (stage or "").split(",")[0].strip()
    stage_parts = [first_stage] if first_stage else []
    stage_fonts: list = []
    stage_heights: list[int] = []
    for part in stage_parts:
        sf = _auto_fit(part, False, max_text_w, start=int(36 * s), minimum=int(22 * s))
        stage_fonts.append(sf)
        stage_heights.append(_font_height(sf))

    # Line is pinned so the accent rail sits at the same Y on every cover.
    line_y = int(720 * s)

    artist_block_top = line_y - PAD_LINE_TO_ARTIST - artist_block_h

    # Final cursor check after placement.
    cursor_y = line_y + line_h + PAD_LINE_TO_FEST
    if fest_font is not None:
        cursor_y += fest_h + PAD_FEST_TO_DATE
    if date_font is not None:
        cursor_y += date_h + PAD_DATE_TO_DETAIL
    for h in stage_heights:
        cursor_y += h + PAD_DETAIL_LINES

    return {
        "size": size,
        "artist_lines": artist_lines,
        "artist_font": artist_font,
        "artist_line_h": line_h_artist,
        "artist_pad_lines": PAD_ARTIST_LINES,
        "artist_block_top": artist_block_top,
        "artist_block_h": artist_block_h,
        "photo_h": photo_h,
        "line_y": line_y,
        "line_h": line_h,
        "line_w": line_w,
        "pad_line_to_fest": PAD_LINE_TO_FEST,
        "pad_fest_to_date": PAD_FEST_TO_DATE,
        "pad_date_to_detail": PAD_DATE_TO_DETAIL,
        "pad_detail_lines": PAD_DETAIL_LINES,
        "fest_text": fest_text,
        "fest_font": fest_font,
        "fest_h": fest_h,
        "date_text": date_display,
        "date_font": date_font,
        "date_h": date_h,
        "stage_parts": stage_parts,
        "stage_fonts": stage_fonts,
        "stage_heights": stage_heights,
        "venue_text": "",
        "venue_font": None,
        "venue_h": 0,
        "final_cursor_y": cursor_y,
        "top_margin": top_margin,
        "bottom_margin": bottom_margin,
    }


def compose_cover(
    artist: str,
    festival: str,
    date: str = "",
    stage: str = "",
    venue: str = "",
    background_data: bytes | None = None,
    size: int = 1000,
) -> bytes:
    """Compose an album cover with the set thumb fading into the dark.

    Layout: set artwork cover-fit to the top portion of the canvas, alpha-
    fading into a darkening gradient below; accent line with artist above,
    festival / date / stage / venue below.
    """
    L = _layout_album_cover(artist, festival, date, stage, venue, size)

    bg, accent = _prepare_background(background_data, size, darkness=0.18)
    canvas = bg.convert("RGBA")

    if background_data is not None:
        _apply_fade_photo(canvas, background_data, L["photo_h"])
    _apply_dark_gradient(canvas)

    draw = ImageDraw.Draw(canvas)
    cursor = L["artist_block_top"]
    for line in L["artist_lines"]:
        _draw_centered(draw, size, cursor, line, L["artist_font"], (255, 255, 255, 255))
        cursor += L["artist_line_h"] + L["artist_pad_lines"]

    result = canvas.convert("RGB")
    result = _draw_glow_line(result, L["line_y"], L["line_w"], L["line_h"], accent)

    draw = ImageDraw.Draw(result)
    cursor_y = L["line_y"] + L["line_h"] + L["pad_line_to_fest"]

    if L["fest_font"] is not None:
        _draw_centered_no_shadow(draw, size, cursor_y, L["fest_text"], L["fest_font"], accent)
        cursor_y += L["fest_h"] + L["pad_fest_to_date"]

    if L["date_font"] is not None:
        _draw_centered_no_shadow(draw, size, cursor_y, L["date_text"], L["date_font"], (255, 255, 255))
        cursor_y += L["date_h"] + L["pad_date_to_detail"]

    for part, sf, sh in zip(L["stage_parts"], L["stage_fonts"], L["stage_heights"]):
        _draw_centered_no_shadow(draw, size, cursor_y, part, sf, (255, 255, 255))
        cursor_y += sh + L["pad_detail_lines"]

    buf = io.BytesIO()
    result.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# DJ artwork lookup
# ---------------------------------------------------------------------------

def find_dj_artwork(
    input_path: Path,
    artist: str = "",
    home_dir: Path | None = None,
) -> bytes | None:
    """Look up cached DJ artwork from CrateDigger's artist cache.

    Lookup chain:
    1. ~/.cratedigger/artists/{artist}/dj-artwork.jpg (global)
    2. Walk up from input_path for .cratedigger/artists/{artist}/dj-artwork.jpg
    3. Same for fanart.jpg as fallback
    4. Return None if not found.
    """
    cratedigger_dirs = find_cratedigger_dirs(input_path, home_dir=home_dir)

    # 1. Look for artists/{name}/dj-artwork.jpg then fanart.jpg
    if artist:
        for cd in cratedigger_dirs:
            artist_dir = cd / "artists" / artist
            for name in ("dj-artwork.jpg", "fanart.jpg"):
                candidate = artist_dir / name
                if candidate.is_file():
                    logger.debug("DJ artwork found: %s", candidate)
                    return candidate.read_bytes()

    return None


# ---------------------------------------------------------------------------
# Artist cover composition
# ---------------------------------------------------------------------------
def compose_artist_cover(
    artist: str,
    dj_artwork_data: bytes | None = None,
    size: int = 1000,
) -> bytes:
    """Compose a line-anchored square artist cover.

    Uses the DJ artwork as both the sharp photo and blurred background.
    Layout: DJ photo centered above artist name, artist name above
    accent line with glow. Nothing below the line.
    """
    s = size / 1000.0

    LINE_H = max(1, int(4 * s))
    LINE_W = int(400 * s)
    PAD_LINE_TO_ARTIST = int(28 * s)
    PHOTO_SIZE = int(550 * s)
    PAD_PHOTO_TO_ARTIST = int(24 * s)

    # Use DJ artwork as background (blurred version of same photo)
    bg, accent = _prepare_background(dj_artwork_data, size, darkness=0.18)

    max_text_w = int(size * 0.85)

    # Artist name
    artist_text = artist.upper()
    artist_font = _auto_fit(artist_text, True, max_text_w, start=int(100 * s), minimum=int(54 * s))
    artist_h = _font_height(artist_font)

    # Center the photo + artist + line block vertically on the canvas.
    block_h = PHOTO_SIZE + PAD_PHOTO_TO_ARTIST + artist_h + PAD_LINE_TO_ARTIST + LINE_H
    block_top = max(int(20 * s), (size - block_h) // 2)
    LINE_Y = block_top + block_h - LINE_H
    artist_y = LINE_Y - PAD_LINE_TO_ARTIST - artist_h

    canvas = bg.convert("RGBA")
    draw = ImageDraw.Draw(canvas)

    # DJ photo (if provided)
    if dj_artwork_data is not None:
        try:
            photo = Image.open(io.BytesIO(dj_artwork_data)).convert("RGBA")
            photo = photo.resize((PHOTO_SIZE, PHOTO_SIZE), Image.Resampling.LANCZOS)

            # Rounded corners mask
            corner_radius = int(PHOTO_SIZE * 0.1)
            mask = Image.new("L", (PHOTO_SIZE, PHOTO_SIZE), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.rounded_rectangle(
                [0, 0, PHOTO_SIZE - 1, PHOTO_SIZE - 1],
                radius=corner_radius,
                fill=255,
            )

            photo.putalpha(mask)

            photo_x = (size - PHOTO_SIZE) // 2
            photo_y = artist_y - PAD_PHOTO_TO_ARTIST - PHOTO_SIZE
            canvas.paste(photo, (photo_x, photo_y), photo)
        except Exception:
            logger.warning("Failed to process DJ artwork, skipping photo")

    # Artist name: NO shadow for artist cover
    _draw_centered_no_shadow(draw, size, artist_y, artist_text, artist_font, (255, 255, 255, 255))

    # Glow line
    result = canvas.convert("RGB")
    result = _draw_glow_line(result, LINE_Y, LINE_W, LINE_H, accent)

    buf = io.BytesIO()
    result.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Existing extraction functions (used by pipeline.py)
# ---------------------------------------------------------------------------
def build_cover_command(input_path: Path, output_path: Path) -> list[str]:
    """Build ffmpeg command for extracting cover art via image2pipe."""
    return [
        get_tool("ffmpeg"),
        "-i",
        str(input_path),
        "-an",
        "-vcodec",
        "copy",
        "-f",
        "image2pipe",
        "-y",
        str(output_path),
    ]


_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")
_IMAGE_CODECS = ("png", "mjpeg", "jpeg", "webp", "bmp")
_STREAM_EXT = {"png": ".png", "mjpeg": ".jpg", "jpeg": ".jpg", "webp": ".webp", "bmp": ".bmp"}


def extract_cover_from_mkv(
    input_path: Path, ffprobe_data: dict | None = None,
) -> bytes | None:
    """Extract embedded cover art from a video file.

    For MKV files, tries mkvmerge/mkvextract first (fastest, most reliable
    when available). Falls back to ffmpeg stream mapping for all formats
    when mkvtools are missing, using ffprobe to locate the image stream.
    """
    if input_path.suffix.lower() == ".mkv":
        result = _extract_cover_mkvtools(input_path)
        if result is not None:
            return result

    return _extract_cover_ffmpeg_stream(input_path, ffprobe_data)


def _find_cover_stream(ffprobe_data: dict) -> tuple[int, str] | None:
    """Find an attached picture stream index and output extension.

    MKV stores cover art as a video stream with an image codec plus
    filename/mimetype tags. MP4/MOV uses disposition.attached_pic.
    """
    for stream in ffprobe_data.get("streams", []):
        if stream.get("codec_type") != "video":
            continue
        codec_name = stream.get("codec_name", "")
        if codec_name not in _IMAGE_CODECS:
            continue
        tags = stream.get("tags") or {}
        mimetype = (tags.get("mimetype") or "").lower()
        filename = (tags.get("filename") or "").lower()
        disposition = stream.get("disposition") or {}
        is_attached = (
            mimetype.startswith("image/")
            or filename.endswith(_IMAGE_EXTS)
            or disposition.get("attached_pic") == 1
        )
        if is_attached:
            return (stream["index"], _STREAM_EXT.get(codec_name, ".jpg"))
    return None


def _extract_cover_ffmpeg_stream(
    input_path: Path, ffprobe_data: dict | None,
) -> bytes | None:
    """Extract cover art by mapping a specific image stream via ffmpeg."""
    if ffprobe_data is None:
        try:
            from tracksplit.probe import run_ffprobe
            ffprobe_data = run_ffprobe(input_path)
        except (subprocess.CalledProcessError, OSError) as exc:
            logger.debug("ffprobe failed for cover lookup on %s: %s", input_path.name, exc)
            return None

    found = _find_cover_stream(ffprobe_data)
    if found is None:
        logger.debug("No cover art stream found in %s", input_path.name)
        return None
    stream_index, ext = found

    tmp_file: Path | None = None
    try:
        fd, tmp_path_str = tempfile.mkstemp(prefix="tracksplit_cover_", suffix=ext)
        import os
        os.close(fd)
        tmp_file = Path(tmp_path_str)

        cmd = [
            get_tool("ffmpeg"),
            "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(input_path),
            "-map", f"0:{stream_index}",
            "-c", "copy",
            "-frames:v", "1",
            "-update", "1",
            str(tmp_file),
        ]
        logger.debug("Extracting cover via ffmpeg stream map: %s", " ".join(cmd))
        subprocess.run(cmd, capture_output=True, check=True, timeout=30)

        if tmp_file.exists() and tmp_file.stat().st_size > 0:
            data = tmp_file.read_bytes()
            logger.info(
                "Extracted cover art via ffmpeg stream from %s", input_path.name,
            )
            return data
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("ffmpeg cover stream extraction failed: %s", exc)
    finally:
        if tmp_file is not None:
            tmp_file.unlink(missing_ok=True)
    return None


def _is_image_attachment(att: dict) -> bool:
    """Return True if an mkvmerge attachment entry looks like an image."""
    content_type = att.get("content_type", "") or ""
    if content_type.startswith("image/"):
        return True
    name = (att.get("file_name") or "").lower()
    return name.endswith(_IMAGE_EXTS)


def _pick_image_attachment(attachments: list[dict]) -> dict | None:
    """Pick the best image attachment, preferring one named cover.*."""
    images = [a for a in attachments if _is_image_attachment(a)]
    if not images:
        return None
    images.sort(
        key=lambda a: not (a.get("file_name") or "").lower().startswith("cover"),
    )
    return images[0]


def _extract_cover_mkvtools(input_path: Path) -> bytes | None:
    """Extract cover art from MKV using mkvmerge identify + mkvextract."""
    tmp_file: Path | None = None
    try:
        identify_cmd = [
            get_tool("mkvmerge"),
            "--identify",
            "--identification-format",
            "json",
            str(input_path),
        ]
        logger.debug("Trying mkvmerge identify: %s", " ".join(identify_cmd))
        identify_result = subprocess.run(
            identify_cmd, capture_output=True, check=True, text=True,
            timeout=30, encoding="utf-8",
        )
        info = json.loads(identify_result.stdout)

        image_attachment = _pick_image_attachment(info.get("attachments", []))
        if image_attachment is None:
            logger.debug("No image attachments found in %s", input_path.name)
            return None

        att_id = image_attachment["id"]

        # Create a unique temp file to avoid collisions under parallel workers
        fd, tmp_path_str = tempfile.mkstemp(prefix="tracksplit_cover_", suffix=".jpg")
        import os
        os.close(fd)
        tmp_file = Path(tmp_path_str)

        extract_cmd = [
            get_tool("mkvextract"),
            str(input_path),
            "attachments",
            f"{att_id}:{tmp_file}",
        ]
        logger.debug("Extracting attachment: %s", " ".join(extract_cmd))
        subprocess.run(extract_cmd, capture_output=True, check=True, timeout=30)

        if tmp_file.exists() and tmp_file.stat().st_size > 0:
            data = tmp_file.read_bytes()
            logger.info(
                "Extracted cover art via mkvextract from %s", input_path.name
            )
            return data

    except (
        subprocess.CalledProcessError, subprocess.TimeoutExpired,
        json.JSONDecodeError, KeyError, OSError,
    ) as exc:
        logger.debug("mkvmerge/mkvextract failed: %s", exc)
    finally:
        if tmp_file is not None:
            tmp_file.unlink(missing_ok=True)

    return None
