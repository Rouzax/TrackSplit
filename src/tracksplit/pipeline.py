"""Pipeline orchestration for TrackSplit.

Coordinates probing, extraction, splitting, tagging, and cover art
composition for individual video files and directories of video files.
"""
from __future__ import annotations

import errno
import logging
import shutil
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
from tracksplit.cratedigger import apply_cratedigger_canon_with, load_config
from tracksplit.extract import decide_codec, prepare_audio
from tracksplit.manifest import (
    ArtistManifest,
    LEGACY_CHAPTER_CACHE_FILENAME,
    MANIFEST_SCHEMA,
    TAG_KEYS,
    SourceFingerprint,
    artwork_sha256,
    atomic_write_bytes,
    build_album_manifest,
    load_album_manifest,
    load_artist_manifest,
    save_album_manifest,
    save_artist_manifest,
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

FATAL_DISK_ERRNOS = (errno.ENOSPC, errno.EDQUOT, errno.EROFS)


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


_AUDIO_EXTS = (".flac", ".opus")


def prune_orphan_tracks(album_dir: Path, expected: set[str]) -> list[str]:
    """Delete audio files in album_dir whose filename is not in expected.

    Only top-level *.flac and *.opus files are considered. Subdirectories,
    cover.jpg, sidecar JSON files, and unrelated files are untouched.

    Returns the list of removed filenames. Returns an empty list and
    deletes nothing if ``expected`` is empty, which guards against
    mass-deletion when an upstream step silently produced no tracks.

    Assumes a single writer per album_dir: callers must not invoke this
    concurrently with split_tracks or tag_all for the same album.
    """
    if not expected:
        return []
    removed: list[str] = []
    for p in album_dir.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() not in _AUDIO_EXTS:
            continue
        if p.name in expected:
            continue
        try:
            p.unlink()
            removed.append(p.name)
        except OSError as exc:
            logger.warning("Could not remove orphan %s: %s", p, exc)
    if removed:
        logger.info(
            "Pruned %d orphan track file(s) from %s", len(removed), album_dir,
        )
    return removed


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


def find_prior_album_dirs(
    output_root: Path,
    source_path: Path,
    new_album_dir: Path,
) -> list[Path]:
    """Return album dirs under output_root whose manifest matches source_path
    (by resolved path AND size) but whose directory differs from new_album_dir.

    Matches are keyed on source identity, not heuristic name similarity, so
    this is safe to call whenever ``should_regenerate`` returns True.
    """
    if not output_root.exists():
        return []
    try:
        src_resolved = source_path.resolve()
        src_size = source_path.stat().st_size
    except OSError:
        return []

    new_resolved = new_album_dir.resolve(strict=False)

    matches: list[Path] = []
    for album_dir in output_root.glob("*/*"):
        if not album_dir.is_dir():
            continue
        if album_dir.is_symlink():
            continue
        if album_dir.resolve(strict=False) == new_resolved:
            continue
        manifest = load_album_manifest(album_dir)
        if manifest is None:
            continue
        try:
            stored_resolved = Path(manifest.source.path).resolve()
        except OSError:
            continue
        if stored_resolved != src_resolved:
            continue
        if manifest.source.size != src_size:
            continue
        matches.append(album_dir)
    return matches


def _remove_stale_album_dirs(
    output_root: Path, source_path: Path, new_album_dir: Path,
) -> None:
    for stale in find_prior_album_dirs(output_root, source_path, new_album_dir):
        logger.info(
            "Removing renamed album dir: %s -> %s", stale, new_album_dir,
        )
        try:
            shutil.rmtree(stale)
        except OSError as exc:
            logger.warning("Could not remove %s: %s", stale, exc)


def refresh_artist_cover(
    artist_dir: Path,
    *,
    artist_name: str,
    dj_artwork_data: bytes | None,
    compose,
) -> None:
    """Write folder.jpg / artist.jpg iff the DJ artwork hash changed.

    ``compose`` is a callable matching ``cover.compose_artist_cover``'s
    keyword signature, injected so tests can substitute a stub.
    """
    new_hash = artwork_sha256(dj_artwork_data)
    existing = load_artist_manifest(artist_dir)
    folder_jpg = artist_dir / "folder.jpg"
    artist_jpg = artist_dir / "artist.jpg"
    if (
        existing is not None
        and existing.dj_artwork_sha256 == new_hash
        and folder_jpg.exists()
        and artist_jpg.exists()
    ):
        return
    try:
        artist_dir.mkdir(parents=True, exist_ok=True)
        cover_bytes = compose(
            artist=artist_name, dj_artwork_data=dj_artwork_data,
        )
        atomic_write_bytes(folder_jpg, cover_bytes)
        atomic_write_bytes(artist_jpg, cover_bytes)
        save_artist_manifest(
            artist_dir,
            ArtistManifest(
                schema=MANIFEST_SCHEMA, artist=artist_name, dj_artwork_sha256=new_hash,
            ),
        )
        logger.info("Refreshed artist cover: %s", artist_dir.name)
    except OSError as exc:
        if exc.errno in FATAL_DISK_ERRNOS:
            raise
        logger.warning(
            "Could not refresh artist cover for %s: %s", artist_dir, exc,
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
    on_complete: Callable[[Path, int], None] | None = None,
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
    cd_cfg = load_config(input_path)
    apply_cratedigger_canon_with(tags, cd_cfg)
    tier = detect_tier(tags)

    # Build album metadata
    album = build_album_meta(tags, chapters, input_path.stem, tier, cd_config=cd_cfg)

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

    ext, codec_mode = decide_codec(ffprobe_data, output_format)
    chapter_dicts = _chapters_to_dicts(chapters)

    if not should_regenerate(
        album_dir, input_path, tags, chapter_dicts,
        artist_folder, album_folder, ext.lstrip("."), codec_mode,
        force=force,
    ):
        dj_artwork_data = find_dj_artwork(input_path, artist=album.artist)
        artist_dir = output_dir / safe_filename(album.artist_folder)
        refresh_artist_cover(
            artist_dir,
            artist_name=album.artist,
            dj_artwork_data=dj_artwork_data,
            compose=compose_artist_cover,
        )
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
        if on_complete:
            on_complete(album_dir, len(album.tracks))
        return True

    _remove_stale_album_dirs(output_dir, input_path, album_dir)

    # Extract, split, tag
    album_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp_dir = Path(tmp_str)

        # Prepare audio (detect codec, extract if needed)
        _progress("Extracting audio")
        audio_path, ext, codec_mode = prepare_audio(
            input_path, ext, codec_mode, tmp_dir,
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

        prune_orphan_tracks(album_dir, {p.name for p in track_paths})

        # Save cover.jpg
        _progress("Saving")
        cover_path = album_dir / "cover.jpg"
        atomic_write_bytes(cover_path, cover_bytes)

        manifest = build_album_manifest(
            source_path=input_path,
            chapters=chapter_dicts,
            tags=tags,
            artist_folder=artist_folder,
            album_folder=album_folder,
            output_format=ext.lstrip("."),
            codec_mode=codec_mode,
            track_filenames=[p.name for p in track_paths],
            cover_bytes=cover_bytes,
        )
        save_album_manifest(album_dir, manifest)
        legacy = album_dir / LEGACY_CHAPTER_CACHE_FILENAME
        if legacy.exists():
            try:
                legacy.unlink()
            except OSError:
                pass

    artist_dir = output_dir / safe_filename(album.artist_folder)
    refresh_artist_cover(
        artist_dir,
        artist_name=album.artist,
        dj_artwork_data=dj_artwork_data,
        compose=compose_artist_cover,
    )

    logger.info("Processed %s -> %s", _safe_log_name(input_path), album_dir)
    if on_complete:
        on_complete(album_dir, len(album.tracks))
    return True


def find_video_files(input_dir: Path) -> list[Path]:
    """Find all video files in a directory, sorted by name."""
    return sorted(
        f for f in input_dir.rglob("*") if f.is_file() and is_video_file(f)
    )


