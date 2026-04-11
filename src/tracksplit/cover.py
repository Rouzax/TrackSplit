"""Cover art extraction and 1:1 album cover composition."""

import io
import json
import logging
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

logger = logging.getLogger(__name__)

# Font paths to try, in order of preference
_DEJAVU_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load DejaVu Sans Bold at the given size, with fallback to default."""
    for path in _DEJAVU_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    try:
        return ImageFont.truetype("DejaVuSans-Bold", size)
    except OSError:
        logger.debug("DejaVu font not found, using default font")
        return ImageFont.load_default()


def create_gradient(width: int, height: int) -> Image.Image:
    """Create a dark gradient background with purple/blue tones.

    Args:
        width: Image width in pixels.
        height: Image height in pixels.

    Returns:
        RGB image with a vertical dark gradient.
    """
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)

    # Dark purple at top, dark blue at bottom
    for y in range(height):
        ratio = y / max(height - 1, 1)
        r = int(25 + 5 * ratio)
        g = int(10 + 15 * ratio)
        b = int(40 + 30 * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    return img


def compose_cover(
    artist: str,
    album: str,
    background_data: bytes | None = None,
    size: int = 1000,
) -> bytes:
    """Compose a 1:1 square album cover image.

    If background_data is provided, the image is resized to fill the square,
    center-cropped, blurred, and darkened. Otherwise a gradient is used.

    Args:
        artist: Artist name shown in large white text.
        album: Album name shown in smaller light gray text.
        background_data: Raw image bytes for the background, or None.
        size: Output image dimension (square).

    Returns:
        JPEG image as bytes (quality 90).
    """
    if background_data is not None:
        bg = Image.open(io.BytesIO(background_data)).convert("RGB")

        # Resize to fill the square (cover-fit), then center-crop
        src_w, src_h = bg.size
        scale = max(size / src_w, size / src_h)
        new_w = int(src_w * scale)
        new_h = int(src_h * scale)
        bg = bg.resize((new_w, new_h), Image.LANCZOS)

        left = (new_w - size) // 2
        top = (new_h - size) // 2
        bg = bg.crop((left, top, left + size, top + size))

        # Blur
        bg = bg.filter(ImageFilter.GaussianBlur(radius=15))

        # Darken: blend with black at 0.4 opacity
        black = Image.new("RGB", (size, size), (0, 0, 0))
        bg = Image.blend(bg, black, 0.4)
    else:
        bg = create_gradient(size, size)

    # Draw text overlay
    draw = ImageDraw.Draw(bg)

    artist_font = _load_font(size // 14)
    album_font = _load_font(size // 20)

    # Artist name, centered, white
    artist_bbox = draw.textbbox((0, 0), artist, font=artist_font)
    artist_w = artist_bbox[2] - artist_bbox[0]
    artist_h = artist_bbox[3] - artist_bbox[1]
    artist_x = (size - artist_w) // 2
    artist_y = size // 2 - artist_h - 10

    draw.text((artist_x, artist_y), artist, fill=(255, 255, 255), font=artist_font)

    # Album name, centered below, light gray
    album_bbox = draw.textbbox((0, 0), album, font=album_font)
    album_w = album_bbox[2] - album_bbox[0]
    album_x = (size - album_w) // 2
    album_y = artist_y + artist_h + 20

    draw.text((album_x, album_y), album, fill=(200, 200, 200), font=album_font)

    # Return as JPEG bytes
    buf = io.BytesIO()
    bg.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def build_cover_command(input_path: Path, output_path: Path) -> list[str]:
    """Build ffmpeg command for extracting cover art via image2pipe.

    Args:
        input_path: Path to the source video file.
        output_path: Path for the extracted image.

    Returns:
        Command as a list of strings.
    """
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

    Args:
        input_path: Path to the source video file.

    Returns:
        Image bytes or None if no artwork found.
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
            data = tmp_file.read_bytes()
            tmp_file.unlink()
            logger.info(
                "Extracted cover art via mkvextract from %s", input_path.name
            )
            return data

    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as exc:
        logger.debug("mkvmerge/mkvextract fallback failed: %s", exc)

    return None
