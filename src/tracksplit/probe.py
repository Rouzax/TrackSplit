"""Probe video files for chapters and metadata using ffprobe."""
import json
import logging
import subprocess
from pathlib import Path

import ftfy

from tracksplit.models import Chapter
from tracksplit.tools import get_tool


def _fix_text(s: str) -> str:
    """Normalize text using ftfy to repair mojibake and other issues."""
    if not s:
        return s
    return ftfy.fix_text(s)

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".webm", ".avi", ".mov", ".m2ts", ".ts", ".flv"}


def run_ffprobe(path: Path) -> dict:
    """Run ffprobe with JSON output on *path* and return parsed data."""
    cmd = [
        get_tool("ffprobe"),
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
        raw_tags = raw.get("tags") or {}

        if end - start <= 0:
            title = raw_tags.get("title", "(untitled)")
            logger.warning(
                "Skipping zero-duration chapter %r at %.3f s", title, start
            )
            continue

        title = _fix_text(raw_tags.get("title", "").strip())
        if not title:
            title = f"Track {len(chapters) + 1:02d}"

        tags: dict[str, str] = {}
        for k, v in raw_tags.items():
            if k == "title":
                # Already extracted into Chapter.title above.
                continue
            if isinstance(v, str):
                tags[k.upper()] = _fix_text(v)

        chapters.append(
            Chapter(
                index=len(chapters) + 1,
                title=title,
                start=start,
                end=end,
                tags=tags,
            )
        )

    return chapters


def parse_tags(ffprobe_data: dict) -> dict:
    """Extract metadata tags from ffprobe JSON.

    Performs case-insensitive key lookup. Returns a normalized dict with
    standard keys regardless of what the source file contains.
    """
    raw_tags = ffprobe_data.get("format", {}).get("tags", {})

    # Build a case-insensitive lookup map with mojibake repair
    ci: dict[str, str] = {k.upper(): _fix_text(v) for k, v in raw_tags.items()}

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
        "enriched_at": ci.get("CRATEDIGGER_ENRICHED_AT", ""),
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
