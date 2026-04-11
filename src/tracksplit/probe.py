"""Probe video files for chapters and metadata using ffprobe."""
import json
import logging
import subprocess
from pathlib import Path

from tracksplit.models import Chapter

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".webm", ".avi", ".mov", ".m2ts", ".ts", ".flv"}


def run_ffprobe(path: Path) -> dict:
    """Run ffprobe with JSON output on *path* and return parsed data."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_chapters",
        "-show_streams",
        "-show_format",
        str(path),
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, check=True, encoding="utf-8",
    )
    return json.loads(result.stdout)


def parse_chapters(ffprobe_data: dict) -> list[Chapter]:
    """Parse chapter entries from ffprobe JSON into Chapter objects.

    Zero-duration chapters are skipped (with a warning). Chapters without a
    title receive a default "Track NN" name. Indices are assigned sequentially
    after filtering.
    """
    raw_chapters = ffprobe_data.get("chapters", [])
    chapters: list[Chapter] = []

    for raw in raw_chapters:
        start = float(raw["start_time"])
        end = float(raw["end_time"])

        if end - start <= 0:
            title = raw.get("tags", {}).get("title", "(untitled)")
            logger.warning(
                "Skipping zero-duration chapter %r at %.3f s", title, start
            )
            continue

        title = (raw.get("tags") or {}).get("title", "").strip()
        if not title:
            title = f"Track {len(chapters) + 1:02d}"

        chapters.append(
            Chapter(
                index=len(chapters) + 1,
                title=title,
                start=start,
                end=end,
            )
        )

    return chapters


def parse_tags(ffprobe_data: dict) -> dict:
    """Extract metadata tags from ffprobe JSON.

    Performs case-insensitive key lookup. Returns a normalized dict with
    standard keys regardless of what the source file contains.
    """
    raw_tags = ffprobe_data.get("format", {}).get("tags", {})

    # Build a case-insensitive lookup map
    ci: dict[str, str] = {k.upper(): v for k, v in raw_tags.items()}

    genres_raw = ci.get("CRATEDIGGER_1001TL_GENRES", "").strip()
    genres = [g.strip() for g in genres_raw.split("|") if g.strip()] if genres_raw else []

    cratedigger = any(k.startswith("CRATEDIGGER_") for k in ci)

    return {
        "artist": ci.get("ARTIST", ""),
        "festival": ci.get("CRATEDIGGER_1001TL_FESTIVAL", ""),
        "date": ci.get("CRATEDIGGER_1001TL_DATE", ""),
        "genres": genres,
        "stage": ci.get("CRATEDIGGER_1001TL_STAGE", ""),
        "venue": ci.get("CRATEDIGGER_1001TL_VENUE", ""),
        "comment": ci.get("CRATEDIGGER_1001TL_URL", ""),
        "musicbrainz_artistid": ci.get("CRATEDIGGER_MBID", ""),
        "dj_artwork": ci.get("CRATEDIGGER_1001TL_DJ_ARTWORK", ""),
        "cratedigger": cratedigger,
    }


def detect_tier(tags: dict) -> int:
    """Return enrichment tier: 2 if CrateDigger metadata present, else 1."""
    return 2 if tags.get("cratedigger") else 1


def has_audio(ffprobe_data: dict) -> bool:
    """Check whether at least one audio stream exists."""
    return any(
        s.get("codec_type") == "audio"
        for s in ffprobe_data.get("streams", [])
    )


def is_video_file(path: Path) -> bool:
    """Check whether *path* has a recognized video extension."""
    return path.suffix.lower() in VIDEO_EXTENSIONS


def get_audio_codec(ffprobe_data: dict) -> str:
    """Return the codec name of the first audio stream (e.g. 'opus', 'flac', 'aac')."""
    for s in ffprobe_data.get("streams", []):
        if s.get("codec_type") == "audio":
            return s.get("codec_name", "")
    return ""


LOSSLESS_CODECS = {"flac", "alac", "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "wavpack"}


def is_lossless_codec(codec: str) -> bool:
    """Check if a codec is lossless."""
    return codec in LOSSLESS_CODECS or codec.startswith("pcm_")
