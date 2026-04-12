"""Pipeline orchestration for TrackSplit.

Coordinates probing, extraction, splitting, tagging, and cover art
composition for individual video files and directories of video files.
"""
from __future__ import annotations

import logging
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

from tracksplit.cover import (
    compose_artist_cover,
    compose_cover,
    extract_cover_from_mkv,
    find_dj_artwork,
)
from tracksplit.cratedigger import apply_cratedigger_canon
from tracksplit.extract import prepare_audio
from tracksplit.manifest import (
    TAG_KEYS,
    SourceFingerprint,
    load_album_manifest,
)
from tracksplit.metadata import build_album_meta, safe_filename
from tracksplit.models import Chapter, TrackMeta
from tracksplit.probe import (
    detect_tier,
    has_audio,
    is_video_file,
    parse_chapters,
    parse_tags,
    run_ffprobe,
)
from tracksplit.split import split_tracks
from tracksplit.tagger import tag_all

logger = logging.getLogger(__name__)


def _safe_log_name(path: Path) -> str:
    """Return a logging-safe filename, replacing surrogate bytes."""
    try:
        name = path.name
        name.encode("utf-8")
        return name
    except (UnicodeEncodeError, UnicodeDecodeError):
        return path.name.encode("utf-8", errors="replace").decode("utf-8")


def _chapters_to_dicts(chapters: list[Chapter]) -> list[dict]:
    """Serialize chapters to a list of plain dicts for JSON caching."""
    return [
        {
            "index": ch.index,
            "title": ch.title,
            "start": ch.start,
            "end": ch.end,
        }
        for ch in chapters
    ]


def build_intro_track(chapters: list[Chapter]) -> TrackMeta | None:
    """Build an intro track if the first chapter starts after 0.0.

    Returns a TrackMeta with number=0 and title="Intro" spanning from
    0.0 to the first chapter's start time. Returns None if chapters is
    empty or the first chapter already starts at 0.0.
    """
    if not chapters:
        return None
    if chapters[0].start == 0.0:
        return None
    return TrackMeta(
        number=0,
        title="Intro",
        start=0.0,
        end=chapters[0].start,
    )


def should_regenerate(
    album_dir: Path,
    source_path: Path,
    tags: dict,
    chapter_dicts: list[dict],
    artist_folder: str,
    album_folder: str,
    output_format: str,
    codec_mode: str,
    *,
    force: bool,
) -> bool:
    """Return True when the album must be (re)generated."""
    if force:
        return True
    if not album_dir.exists():
        return True

    manifest = load_album_manifest(album_dir)
    if manifest is None:
        return True

    try:
        current_source = SourceFingerprint.from_path(
            source_path, enriched_at=tags.get("enriched_at", ""),
        )
    except OSError:
        return True

    if manifest.source != current_source:
        return True
    if manifest.resolved_artist_folder != artist_folder:
        return True
    if manifest.resolved_album_folder != album_folder:
        return True
    if manifest.output_format != output_format:
        return True
    if manifest.codec_mode != codec_mode:
        return True
    if manifest.chapters != chapter_dicts:
        return True

    for k in TAG_KEYS:
        if manifest.tags.get(k, "") != tags.get(k, ""):
            return True
    return False


def process_file(
    input_path: Path,
    output_dir: Path,
    force: bool = False,
    dry_run: bool = False,
    output_format: str = "auto",
    on_progress: Callable[[str, int, int], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> bool:
    """Process a single video file through the full pipeline.

    Steps: probe, build metadata, extract audio, split tracks, compose
    cover art, tag files, save cover and chapter cache.

    Returns True on success, False if skipped or failed.
    """
    def _progress(step: str, current: int = 0, total: int = 0) -> None:
        if on_progress:
            on_progress(step, current, total)

    input_path = Path(input_path)
    output_dir = Path(output_dir)

    # Probe
    _progress("Probing")
    ffprobe_data = run_ffprobe(input_path)

    if not has_audio(ffprobe_data):
        logger.warning("No audio stream found in %s, skipping", _safe_log_name(input_path))
        return False

    chapters = parse_chapters(ffprobe_data)
    tags = parse_tags(ffprobe_data)
    apply_cratedigger_canon(tags, input_path)
    tier = detect_tier(tags)

    # Build album metadata
    album = build_album_meta(tags, chapters, input_path.stem, tier)

    # Handle intro track
    intro = build_intro_track(chapters)
    if intro is not None:
        album.tracks.insert(0, intro)

    # Handle no chapters: single track spanning full duration
    if not chapters:
        duration = float(
            ffprobe_data.get("format", {}).get("duration", 0)
        )
        if duration <= 0:
            logger.warning(
                "No chapters and no duration in %s, skipping",
                _safe_log_name(input_path),
            )
            return False
        single_track = TrackMeta(
            number=1,
            title=album.album,
            start=0.0,
            end=duration,
        )
        album.tracks = [single_track]

    # Build output path
    artist_folder = safe_filename(album.artist_folder)
    album_folder = safe_filename(album.album_folder)
    album_dir = output_dir / artist_folder / album_folder

    # Check if regeneration is needed
    if not should_regenerate(album_dir, chapters, force):
        logger.info(
            "Skipping %s, output unchanged since last run",
            _safe_log_name(input_path),
        )
        return False

    # Dry run: log and return
    if dry_run:
        logger.info(
            "Dry run: would process %s -> %s (%d tracks)",
            _safe_log_name(input_path),
            album_dir,
            len(album.tracks),
        )
        return True

    # Extract, split, tag
    album_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp_dir = Path(tmp_str)

        # Prepare audio (detect codec, extract if needed)
        _progress("Extracting audio")
        audio_path, ext, codec_mode = prepare_audio(
            input_path, ffprobe_data, output_format, tmp_dir,
            cancel_event=cancel_event,
        )
        from_video = (audio_path == input_path)

        # Split into tracks
        _progress("Splitting tracks")
        track_paths = split_tracks(
            audio_path, album.tracks, album_dir,
            ext=ext, codec_mode=codec_mode, from_video=from_video,
            on_progress=on_progress, cancel_event=cancel_event,
        )

        # Cover art
        _progress("Extracting cover art")
        cover_data = extract_cover_from_mkv(input_path, ffprobe_data=ffprobe_data)
        dj_artwork_data = find_dj_artwork(
            input_path, artist=album.artist,
        )

        _progress("Composing covers")
        cover_bytes = compose_cover(
            artist=album.artist,
            festival=album.festival,
            date=album.date,
            stage=album.stage,
            venue=album.venue,
            background_data=cover_data,
        )

        # Tag all tracks
        _progress("Tagging tracks")
        tag_all(track_paths, album, cover_data=cover_bytes, on_progress=on_progress)

        # Save cover.jpg
        _progress("Saving")
        cover_path = album_dir / "cover.jpg"
        cover_path.write_bytes(cover_bytes)

    # Save chapter cache
    _save_chapter_cache(album_dir, chapters)

    # Artist cover (only if not already present, tolerates parallel races)
    artist_dir = output_dir / safe_filename(album.artist_folder)
    artist_cover_path = artist_dir / "folder.jpg"
    if not artist_cover_path.exists():
        try:
            artist_bytes = compose_artist_cover(
                artist=album.artist,
                dj_artwork_data=dj_artwork_data,
            )
            artist_cover_path.write_bytes(artist_bytes)
            # Also save as artist.jpg for Lyrion
            (artist_dir / "artist.jpg").write_bytes(artist_bytes)
            logger.info("Created artist cover: %s", artist_dir.name)
        except OSError:
            pass  # another worker may have written it concurrently

    logger.info("Processed %s -> %s", _safe_log_name(input_path), album_dir)
    return True


def find_video_files(input_dir: Path) -> list[Path]:
    """Find all video files in a directory, sorted by name."""
    return sorted(
        f for f in input_dir.rglob("*") if f.is_file() and is_video_file(f)
    )


