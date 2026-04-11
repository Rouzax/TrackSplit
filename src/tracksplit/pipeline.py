"""Pipeline orchestration for TrackSplit.

Coordinates probing, extraction, splitting, tagging, and cover art
composition for individual video files and directories of video files.
"""
import json
import logging
import tempfile
from pathlib import Path

from tracksplit.cover import (
    compose_artist_cover,
    compose_cover,
    extract_cover_from_mkv,
    find_dj_artwork,
)
from tracksplit.extract import extract_audio
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

_CACHE_FILENAME = ".tracksplit_chapters.json"


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
    chapters: list[Chapter],
    force: bool,
) -> bool:
    """Determine whether the album needs to be (re)generated.

    Returns True if force is set, the album directory does not exist,
    or the chapter data differs from the cached version.
    """
    if force:
        return True
    if not album_dir.exists():
        return True

    cache_file = album_dir / _CACHE_FILENAME
    if not cache_file.exists():
        return True

    try:
        cached = json.loads(cache_file.read_text())
    except (json.JSONDecodeError, OSError):
        return True

    return cached != _chapters_to_dicts(chapters)


def _save_chapter_cache(album_dir: Path, chapters: list[Chapter]) -> None:
    """Write chapter data to the cache file in album_dir."""
    cache_file = album_dir / _CACHE_FILENAME
    cache_file.write_text(json.dumps(_chapters_to_dicts(chapters)))


def process_file(
    input_path: Path,
    output_dir: Path,
    force: bool = False,
    dry_run: bool = False,
) -> bool:
    """Process a single video file through the full pipeline.

    Steps: probe, build metadata, extract audio, split tracks, compose
    cover art, tag files, save cover and chapter cache.

    Returns True on success, False if skipped or failed.
    """
    input_path = Path(input_path)
    output_dir = Path(output_dir)

    # Probe
    ffprobe_data = run_ffprobe(input_path)

    if not has_audio(ffprobe_data):
        logger.warning("No audio stream found in %s, skipping", _safe_log_name(input_path))
        return False

    chapters = parse_chapters(ffprobe_data)
    tags = parse_tags(ffprobe_data)
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

        # Extract full audio
        full_flac = extract_audio(input_path, temp_dir=tmp_dir)

        # Split into tracks
        track_paths = split_tracks(full_flac, album.tracks, album_dir)

        # Cover art
        cover_data = extract_cover_from_mkv(input_path)
        dj_artwork_data = find_dj_artwork(
            input_path, artist=album.artist,
        )

        cover_bytes = compose_cover(
            artist=album.artist,
            festival=album.festival,
            date=album.date,
            stage=album.stage,
            venue=album.venue,
            background_data=cover_data,
            dj_artwork_data=dj_artwork_data,
        )

        # Tag all tracks
        tag_all(track_paths, album, cover_data=cover_bytes)

        # Save cover.jpg
        cover_path = album_dir / "cover.jpg"
        cover_path.write_bytes(cover_bytes)

    # Save chapter cache
    _save_chapter_cache(album_dir, chapters)

    # Artist cover (only if not already present)
    artist_dir = output_dir / safe_filename(album.artist_folder)
    artist_cover_path = artist_dir / "folder.jpg"
    if not artist_cover_path.exists():
        artist_bytes = compose_artist_cover(
            artist=album.artist,
            dj_artwork_data=dj_artwork_data,
        )
        artist_cover_path.write_bytes(artist_bytes)
        # Also save as artist.jpg for Lyrion
        (artist_dir / "artist.jpg").write_bytes(artist_bytes)
        logger.info("Created artist cover: %s", artist_dir.name)

    logger.info("Processed %s -> %s", _safe_log_name(input_path), album_dir)
    return True


def process_directory(
    input_dir: Path,
    output_dir: Path,
    force: bool = False,
    dry_run: bool = False,
) -> int:
    """Process all video files in a directory.

    Iterates sorted video files, calls process_file for each, catches
    and logs exceptions per file. Returns the count of successfully
    processed files.
    """
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)

    video_files = sorted(
        f for f in input_dir.iterdir() if f.is_file() and is_video_file(f)
    )

    if not video_files:
        logger.warning("No video files found in %s", input_dir)
        return 0

    success_count = 0
    for video_file in video_files:
        try:
            if process_file(video_file, output_dir, force=force, dry_run=dry_run):
                success_count += 1
        except Exception:
            logger.exception("Failed to process %s", video_file.name)

    return success_count
