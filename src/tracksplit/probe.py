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


def _split_pipe_preserving_empty(value: str) -> list[str]:
    """Split ``value`` on '|' without dropping empty slots.

    Positional alignment matters for MBID lists, so "a||b" -> ["a", "", "b"].
    Empty input returns [].
    """
    if not value:
        return []
    return value.split("|")


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

    albumartists_raw = ci.get("CRATEDIGGER_1001TL_ARTISTS", "")
    albumartists = [n for n in albumartists_raw.split("|") if n] if albumartists_raw else []

    albumartist_mbids_raw = ci.get("CRATEDIGGER_ALBUMARTIST_MBIDS", "")
    albumartist_mbids = _split_pipe_preserving_empty(albumartist_mbids_raw)

    return {
        "artist": ci.get("ARTIST", ""),
        "festival": ci.get("CRATEDIGGER_1001TL_FESTIVAL", ""),
        "date": ci.get("CRATEDIGGER_1001TL_DATE", ""),
        "genres": genres,
        "stage": ci.get("CRATEDIGGER_1001TL_STAGE", ""),
        "venue": ci.get("CRATEDIGGER_1001TL_VENUE", ""),
        "comment": ci.get("CRATEDIGGER_1001TL_URL", ""),
        "dj_artwork": ci.get("CRATEDIGGER_1001TL_DJ_ARTWORK", ""),
        "enriched_at": ci.get("CRATEDIGGER_ENRICHED_AT", ""),
        "albumartist_display": ci.get("CRATEDIGGER_ALBUMARTIST_DISPLAY", ""),
        "albumartists": albumartists,
        "albumartist_mbids": albumartist_mbids,
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


def get_opus_packet_duration_ms(path: Path) -> int | None:
    """Return packet duration in ms if the first 20 audio packets agree.

    Returns None if packets disagree, the duration_time field is missing,
    or ffprobe produces no output. Callers use this to decide whether the
    Opus stream-copy path can safely apply the 20 ms prefix-frame fix.
    """
    cmd = [
        get_tool("ffprobe"),
        "-v", "error",
        "-show_packets",
        "-select_streams", "a:0",
        "-read_intervals", "%+#20",
        "-show_entries", "packet=duration_time",
        "-of", "default=noprint_wrappers=1",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    durations_ms: set[int] = set()
    for line in result.stdout.splitlines():
        if not line.startswith("duration_time="):
            continue
        try:
            seconds = float(line.split("=", 1)[1])
        except ValueError:
            return None
        durations_ms.add(int(round(seconds * 1000)))
    if len(durations_ms) != 1:
        return None
    return next(iter(durations_ms))
