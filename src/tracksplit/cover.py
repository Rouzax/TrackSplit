"""Cover art: accent color extraction, line-anchored album/artist covers."""

import colorsys
import io
import json
import logging
import math
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Font paths
# ---------------------------------------------------------------------------
_DEJAVU_BOLD_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
]

_DEJAVU_REGULAR_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
]


# ---------------------------------------------------------------------------
# Font helpers
# ---------------------------------------------------------------------------
def _load_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load DejaVu Sans at the given size, with fallback to default."""
    paths = _DEJAVU_BOLD_PATHS if bold else _DEJAVU_REGULAR_PATHS
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    name = "DejaVuSans-Bold" if bold else "DejaVuSans"
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        logger.debug("DejaVu font not found, using default font")
        return ImageFont.load_default()


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
        bg = Image.open(io.BytesIO(background_data)).convert("RGB")

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
def compose_cover(
    artist: str,
    festival: str,
    date: str = "",
    stage: str = "",
    venue: str = "",
    background_data: bytes | None = None,
    size: int = 1000,
) -> bytes:
    """Compose a line-anchored square album cover.

    Layout: sharp set artwork (1:1, rounded corners) centered above artist
    name, with blurred version as background. Festival/date/stage/venue
    below accent line.
    """
    s = size / 1000.0

    ART_SIZE = int(550 * s)  # same proportion as artist cover photo
    LINE_Y = int(750 * s)   # same as artist cover
    LINE_H = max(1, int(4 * s))
    LINE_W = int(400 * s)
    PAD_ART_TO_ARTIST = int(24 * s)  # same as artist cover
    PAD_LINE_TO_ARTIST = int(28 * s)
    PAD_LINE_TO_FEST = int(26 * s)
    PAD_FEST_TO_DATE = int(18 * s)
    PAD_DATE_TO_DETAIL = int(18 * s)
    PAD_DETAIL_LINES = int(8 * s)

    bg, accent = _prepare_background(background_data, size, darkness=0.18)

    max_text_w = int(size * 0.85)

    # Artist text
    artist_text = artist.upper()
    artist_font = _auto_fit(artist_text, True, max_text_w, start=int(72 * s), minimum=int(36 * s))
    artist_h = _font_height(artist_font)

    # Positions: same as artist cover layout
    artist_y = LINE_Y - PAD_LINE_TO_ARTIST - artist_h
    art_y = artist_y - PAD_ART_TO_ARTIST - ART_SIZE
    art_y = max(int(20 * s), art_y)

    # Draw on RGBA canvas
    canvas = bg.convert("RGBA")
    draw = ImageDraw.Draw(canvas)

    # Sharp set artwork with rounded corners
    if background_data is not None:
        try:
            art = Image.open(io.BytesIO(background_data)).convert("RGBA")
            # Center-crop to square
            w, h = art.size
            crop_size = min(w, h)
            left = (w - crop_size) // 2
            top = (h - crop_size) // 2
            art = art.crop((left, top, left + crop_size, top + crop_size))
            art = art.resize((ART_SIZE, ART_SIZE), Image.Resampling.LANCZOS)

            # Rounded corners
            corner_radius = int(ART_SIZE * 0.06)
            mask = Image.new("L", (ART_SIZE, ART_SIZE), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.rounded_rectangle(
                [0, 0, ART_SIZE - 1, ART_SIZE - 1],
                radius=corner_radius, fill=255,
            )
            art.putalpha(mask)

            art_x = (size - ART_SIZE) // 2
            canvas.paste(art, (art_x, art_y), art)
        except Exception:
            logger.debug("Failed to process set artwork for album cover")

    # Artist with drop shadow
    _draw_centered(draw, size, artist_y, artist_text, artist_font, (255, 255, 255, 255))

    # Glow line
    result = canvas.convert("RGB")
    result = _draw_glow_line(result, LINE_Y, LINE_W, LINE_H, accent)

    # Below-line text
    draw = ImageDraw.Draw(result)
    cursor_y = LINE_Y + LINE_H + PAD_LINE_TO_FEST

    # Festival name: accent color, bold, uppercase
    if festival:
        fest_text = festival.upper()
        fest_font = _auto_fit(fest_text, True, max_text_w, start=int(44 * s), minimum=int(26 * s))
        _draw_centered_no_shadow(draw, size, cursor_y, fest_text, fest_font, accent)
        cursor_y += _font_height(fest_font) + PAD_FEST_TO_DATE

    # Date
    date_display = format_date_display(date)
    if date_display:
        date_font = _auto_fit(date_display, False, max_text_w, start=int(36 * s), minimum=int(24 * s))
        _draw_centered_no_shadow(draw, size, cursor_y, date_display, date_font, (255, 255, 255))
        cursor_y += _font_height(date_font) + PAD_DATE_TO_DETAIL

    # Stage (split on comma: "Set Name, Stage Name")
    if stage:
        for part in [p.strip() for p in stage.split(",") if p.strip()]:
            stage_font = _auto_fit(part, False, max_text_w, start=int(30 * s), minimum=int(20 * s))
            _draw_centered_no_shadow(draw, size, cursor_y, part, stage_font, (255, 255, 255))
            cursor_y += _font_height(stage_font) + PAD_DETAIL_LINES

    # Venue (auto-fit, deduplicate against stage)
    if venue and venue.lower() != (stage or "").lower():
        venue_font = _auto_fit(venue, False, max_text_w, start=int(28 * s), minimum=int(18 * s))
        _draw_centered_no_shadow(draw, size, cursor_y, venue, venue_font, (200, 200, 200))
        cursor_y += _font_height(venue_font) + PAD_DETAIL_LINES

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
    if home_dir is None:
        home_dir = Path.home()

    # Collect .cratedigger directories to search: global first, then walk up
    cratedigger_dirs: list[Path] = []
    global_cd = home_dir / ".cratedigger"
    if global_cd.is_dir():
        cratedigger_dirs.append(global_cd)

    current = input_path.parent
    for _ in range(10):
        candidate = current / ".cratedigger"
        if candidate.is_dir() and candidate != global_cd:
            cratedigger_dirs.append(candidate)
        parent = current.parent
        if parent == current:
            break
        current = parent

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

    LINE_Y = int(750 * s)  # text at 75%, photo builds up from there
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
    artist_font = _auto_fit(artist_text, True, max_text_w, start=int(90 * s), minimum=int(40 * s))
    artist_h = _font_height(artist_font)
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
            logger.debug("Failed to process DJ artwork, skipping photo")

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
        "ffmpeg",
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


def extract_cover_from_mkv(input_path: Path) -> bytes | None:
    """Extract embedded cover art from a video file.

    Tries ffmpeg first (image2pipe). If that fails and the file is .mkv,
    falls back to mkvmerge --identify + mkvextract.
    """
    # Attempt 1: ffmpeg
    try:
        cmd = [
            "ffmpeg",
            "-i",
            str(input_path),
            "-an",
            "-vcodec",
            "copy",
            "-f",
            "image2pipe",
            "-",
        ]
        logger.debug("Trying ffmpeg cover extraction: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, check=True)
        if result.stdout:
            logger.info("Extracted cover art via ffmpeg from %s", input_path.name)
            return result.stdout
    except subprocess.CalledProcessError:
        logger.debug("ffmpeg cover extraction failed for %s", input_path.name)

    # Attempt 2: mkvmerge/mkvextract (only for .mkv files)
    if input_path.suffix.lower() != ".mkv":
        return None

    try:
        identify_cmd = [
            "mkvmerge",
            "--identify",
            "--identification-format",
            "json",
            str(input_path),
        ]
        logger.debug("Trying mkvmerge identify: %s", " ".join(identify_cmd))
        identify_result = subprocess.run(
            identify_cmd, capture_output=True, check=True, text=True
        )
        info = json.loads(identify_result.stdout)

        attachments = info.get("attachments", [])
        image_attachment = None
        for att in attachments:
            content_type = att.get("content_type", "")
            if content_type.startswith("image/"):
                image_attachment = att
                break

        if image_attachment is None:
            logger.debug("No image attachments found in %s", input_path.name)
            return None

        att_id = image_attachment["id"]
        tmp_dir = Path(tempfile.gettempdir())
        tmp_file = tmp_dir / f"tracksplit_cover_{att_id}.jpg"

        extract_cmd = [
            "mkvextract",
            str(input_path),
            "attachments",
            f"{att_id}:{tmp_file}",
        ]
        logger.debug("Extracting attachment: %s", " ".join(extract_cmd))
        subprocess.run(extract_cmd, capture_output=True, check=True)

        if tmp_file.exists():
            try:
                data = tmp_file.read_bytes()
                logger.info(
                    "Extracted cover art via mkvextract from %s", input_path.name
                )
                return data
            finally:
                tmp_file.unlink(missing_ok=True)

    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as exc:
        logger.debug("mkvmerge/mkvextract fallback failed: %s", exc)

    return None
