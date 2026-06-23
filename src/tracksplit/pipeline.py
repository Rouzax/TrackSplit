"""Pipeline orchestration for TrackSplit.

Coordinates probing, extraction, splitting, tagging, and cover art
composition for individual video files and directories of video files.
"""

from __future__ import annotations

import contextlib
import errno
import hashlib
import logging
import os
import shutil
import tempfile
import threading
from collections.abc import Callable
from dataclasses import replace as dataclass_replace
from enum import Enum
from pathlib import Path
from typing import TypedDict

from tracksplit.cover import (
    COVER_SCHEMA_VERSION,
    compose_artist_cover,
    compose_cover,
    extract_cover_from_mkv,
    find_dj_artwork,
)
from tracksplit.cratedigger import apply_cratedigger_canon_with, load_config
from tracksplit.extract import decide_codec, prepare_audio
from tracksplit.manifest import (
    ALBUM_MANIFEST_FILENAME,
    LEGACY_CHAPTER_CACHE_FILENAME,
    MANIFEST_SCHEMA,
    TAG_KEYS,
    AlbumManifest,
    ArtistManifest,
    SourceFingerprint,
    artwork_sha256,
    atomic_write_bytes,
    build_album_manifest,
    load_album_manifest,
    load_artist_manifest,
    save_album_manifest,
    save_artist_manifest,
    tag_default,
)
from tracksplit.metadata import build_album_meta, safe_filename
from tracksplit.models import AlbumMeta, Chapter, TrackMeta
from tracksplit.probe import (
    detect_tier,
    get_opus_packet_duration_ms,
    has_audio,
    is_video_file,
    parse_chapters,
    parse_tags,
    run_ffprobe,
)
from tracksplit.split import build_track_filename, split_tracks
from tracksplit.tagger import TAG_SCHEMA_VERSION, replace_cover_only, tag_all

logger = logging.getLogger(__name__)

FATAL_DISK_ERRNOS = (errno.ENOSPC, errno.EDQUOT, errno.EROFS)

INTRO_MIN_SECONDS = 5.0

TEMP_RENAME_SUFFIX = ".tsmv-"


class RegenLevel(Enum):
    SKIP = "skip"
    RETAG = "retag"
    FULL = "full"


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
            "tags": dict(ch.tags),
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
            logger.warning(
                'pipeline.orphan_prune_fail: file=%s error="%s"', p.name, exc
            )
    if removed:
        logger.info(
            "pipeline.orphan_prune: dir=%s count=%d",
            album_dir.name,
            len(removed),
        )
    return removed


def build_intro_track(chapters: list[Chapter]) -> TrackMeta | None:
    """Build an intro track if the first chapter starts at or after INTRO_MIN_SECONDS.

    Returns a TrackMeta with number=0 and title="Intro" spanning from
    0.0 to the first chapter's start time. Returns None if chapters is
    empty, the first chapter already starts at 0.0, or the gap before
    the first chapter is smaller than INTRO_MIN_SECONDS (the audio is
    folded into track 1 elsewhere in the pipeline).
    """
    if not chapters:
        return None
    if chapters[0].start < INTRO_MIN_SECONDS:
        return None
    return TrackMeta(
        number=0,
        title="Intro",
        start=0.0,
        end=chapters[0].start,
    )


def _apply_intro_track(album: AlbumMeta, chapters: list[Chapter]) -> None:
    """Insert an intro track, slide track 1, or leave the album alone.

    When the pre-chapter gap meets the INTRO_MIN_SECONDS threshold, prepend
    an Intro track. When the gap is positive but under the threshold, move
    the first track's start to 0.0 so no audio is dropped. Otherwise
    (zero gap, no chapters, no tracks) do nothing.
    """
    intro = build_intro_track(chapters)
    if intro is not None:
        album.tracks.insert(0, intro)
        return
    if chapters and chapters[0].start > 0.0 and album.tracks:
        logger.debug(
            "pipeline.intro_adjust: first_start=%.3fs",
            chapters[0].start,
        )
        album.tracks[0].start = 0.0


def find_prior_album_dirs(
    output_root: Path,
    source_path: Path,
    new_album_dir: Path,
) -> list[Path]:
    """Return album dirs under output_root whose manifest matches source_path
    by resolved path, but whose directory differs from new_album_dir.

    Matches are keyed on source path identity, not heuristic name similarity,
    so this is safe to call whenever ``should_regenerate`` returns True.
    """
    if not output_root.exists():
        return []
    try:
        src_resolved = source_path.resolve()
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
        matches.append(album_dir)
    return matches


def _remove_stale_album_dirs(
    output_root: Path,
    source_path: Path,
    new_album_dir: Path,
) -> None:
    for stale in find_prior_album_dirs(output_root, source_path, new_album_dir):
        logger.info(
            "pipeline.stale_dir_remove: old=%s new=%s",
            stale.name,
            new_album_dir.name,
        )
        try:
            shutil.rmtree(stale)
        except OSError as exc:
            logger.warning(
                'pipeline.stale_dir_remove_fail: dir=%s error="%s"', stale.name, exc
            )


def rename_track_files(album_dir: Path, renames: list[tuple[str, str]]) -> None:
    """Rename track files inside album_dir according to the given list of (old, new) pairs.

    Case-only changes use a two-step rename via a temp name to satisfy
    case-insensitive filesystems. Missing source files are skipped with a
    warning. When the target already exists with different content, a warning
    is emitted and both files are kept (no overwrite).
    """
    for old_name, new_name in renames:
        src = album_dir / old_name
        dst = album_dir / new_name
        if not src.exists():
            logger.warning("pipeline.rename_skip: missing=%s", old_name)
            continue
        if src == dst:
            continue
        if dst.exists() and src.resolve() != dst.resolve():
            logger.warning(
                "pipeline.rename_conflict: target_exists=%s (kept both)", new_name
            )
            continue
        if old_name.casefold() == new_name.casefold():
            # Case-only: two-step via temp to satisfy case-insensitive FS.
            tmp = album_dir / (new_name + TEMP_RENAME_SUFFIX)
            os.replace(src, tmp)
            os.replace(tmp, dst)
        else:
            os.replace(src, dst)
        logger.info("pipeline.rename: %s -> %s", old_name, new_name)


def move_album_dir(old_dir: Path, new_dir: Path) -> Path:
    """Move old_dir to new_dir, returning the final directory path.

    Creates the new parent directory as needed. When old and new differ only
    in case, a two-step rename via a temp name is used to satisfy
    case-insensitive filesystems. If new_dir already exists (and is not the
    same inode), logs a warning and returns old_dir unchanged. After a
    successful move, prunes the old artist directory if it is now empty.
    """
    if old_dir.resolve() == new_dir.resolve():
        return new_dir
    new_dir.parent.mkdir(parents=True, exist_ok=True)
    if new_dir.exists():
        logger.warning(
            "pipeline.move_conflict: target_exists=%s (left source in place)",
            new_dir.name,
        )
        return old_dir
    if str(old_dir).casefold() == str(new_dir).casefold():
        tmp = new_dir.parent / (new_dir.name + TEMP_RENAME_SUFFIX)
        os.replace(old_dir, tmp)
        os.replace(tmp, new_dir)
    else:
        os.replace(old_dir, new_dir)
    logger.info("pipeline.move: %s -> %s", old_dir.name, new_dir.name)
    old_artist = old_dir.parent
    try:
        if old_artist.exists() and not any(old_artist.iterdir()):
            old_artist.rmdir()
    except OSError:
        pass
    return new_dir


def sweep_temp_renames(album_dir: Path) -> None:
    """Remove stray temp files left by an interrupted rename_track_files call."""
    for p in album_dir.glob("*" + TEMP_RENAME_SUFFIX):
        try:
            p.unlink()
            logger.info("pipeline.temp_sweep: removed=%s", p.name)
        except OSError:
            pass


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
        and existing.cover_schema_version >= COVER_SCHEMA_VERSION
        and folder_jpg.exists()
        and artist_jpg.exists()
    ):
        return
    try:
        artist_dir.mkdir(parents=True, exist_ok=True)
        cover_bytes = compose(
            artist=artist_name,
            dj_artwork_data=dj_artwork_data,
        )
        atomic_write_bytes(folder_jpg, cover_bytes)
        atomic_write_bytes(artist_jpg, cover_bytes)
        save_artist_manifest(
            artist_dir,
            ArtistManifest(
                schema=MANIFEST_SCHEMA,
                artist=artist_name,
                dj_artwork_sha256=new_hash,
                cover_schema_version=COVER_SCHEMA_VERSION,
            ),
        )
        logger.info("pipeline.cover_refresh: artist=%s", artist_dir.name)
    except OSError as exc:
        if exc.errno in FATAL_DISK_ERRNOS:
            raise
        logger.warning(
            'pipeline.cover_refresh_fail: artist=%s error="%s"',
            artist_dir.name,
            exc,
        )


def rebuild_cover_only(
    *,
    album_dir: Path,
    manifest: AlbumManifest,
    source_path: Path,
    ffprobe_data: dict,
    extract: Callable = extract_cover_from_mkv,
    compose: Callable = compose_cover,
) -> None:
    """Recompose the album cover from the stored tag values and re-embed
    it into every existing track, without touching audio frames. Updates
    the on-disk manifest to record the new ``cover_schema_version`` and
    ``cover_sha256``.

    Short-circuits when the freshly composed bytes match the stored
    ``cover_sha256``: in that case only the schema version is bumped so
    future runs can skip this path cleanly.

    Raises on any failure. Callers on the skip branch are expected to
    catch, delete the manifest, and fall through to a full regen.
    """
    background_data = extract(source_path, ffprobe_data=ffprobe_data)
    if background_data is None:
        logger.debug(
            "pipeline.cover_rebuild: file=%s reason=no_embedded_cover",
            source_path.name,
        )
    tags = manifest.tags
    cover_bytes = compose(
        artist=tags.get("artist", ""),
        festival=tags.get("festival", ""),
        date=tags.get("date", ""),
        stage=tags.get("stage", ""),
        venue=tags.get("venue", ""),
        background_data=background_data,
        albumartists=tags.get("albumartists") or None,
    )
    new_sha = hashlib.sha256(cover_bytes).hexdigest() if cover_bytes else ""

    if new_sha == manifest.cover_sha256:
        updated = dataclass_replace(
            manifest,
            cover_schema_version=COVER_SCHEMA_VERSION,
        )
        save_album_manifest(album_dir, updated)
        logger.info(
            "pipeline.cover_rebuild: file=%s reason=schema_bump version=%d",
            album_dir.name,
            COVER_SCHEMA_VERSION,
        )
        return

    cover_path = album_dir / "cover.jpg"
    atomic_write_bytes(cover_path, cover_bytes)
    folder_path = album_dir / "folder.jpg"
    if folder_path.exists():
        atomic_write_bytes(folder_path, cover_bytes)

    missing: list[str] = []
    for name in manifest.track_filenames:
        track_path = album_dir / name
        if track_path.exists():
            replace_cover_only(track_path, cover_bytes)
        else:
            missing.append(name)
    if missing:
        logger.warning(
            "pipeline.cover_rebuild_missing: dir=%s count=%d",
            album_dir.name,
            len(missing),
        )

    updated = dataclass_replace(
        manifest,
        cover_schema_version=COVER_SCHEMA_VERSION,
        cover_sha256=new_sha,
    )
    save_album_manifest(album_dir, updated)
    logger.info(
        "pipeline.cover_rebuild: file=%s tracks=%d",
        album_dir.name,
        len(manifest.track_filenames),
    )


class _RetagKwargs(TypedDict):
    album_dir: Path
    album: AlbumMeta
    source_path: Path
    ffprobe_data: dict
    tags: dict
    chapter_dicts: list[dict]
    artist_folder: str
    album_folder: str
    codec_mode: str
    on_progress: Callable[[str, int, int], None] | None


def retag_album(
    *,
    album_dir: Path,
    album: AlbumMeta,
    source_path: Path,
    ffprobe_data: dict,
    tags: dict,
    chapter_dicts: list[dict],
    artist_folder: str,
    album_folder: str,
    codec_mode: str,
    on_progress: Callable[[str, int, int], None] | None = None,
    reuse_cover: bool = False,
) -> None:
    """Re-tag existing track files and rebuild cover art without
    re-extracting or re-splitting audio. Updates the on-disk manifest.

    When ``reuse_cover`` is True and the cover schema is current, the
    existing ``cover.jpg`` is read from disk instead of recomposing from
    the source MKV. Falls back to recomposition when the cover schema is
    outdated or ``cover.jpg`` is missing.

    Raises ``FileNotFoundError`` when any expected track file is missing.
    Callers should catch and fall through to a full regeneration.
    """
    manifest = load_album_manifest(album_dir)
    if manifest is None:
        raise FileNotFoundError("no manifest in album dir")

    track_paths = [album_dir / name for name in manifest.track_filenames]
    missing = [p for p in track_paths if not p.exists()]
    if missing:
        raise FileNotFoundError(f"{len(missing)} track(s) missing: {missing[0].name}")

    cover_path = album_dir / "cover.jpg"
    can_reuse = (
        reuse_cover
        and manifest.cover_schema_version >= COVER_SCHEMA_VERSION
        and cover_path.exists()
    )
    if can_reuse:
        cover_bytes = cover_path.read_bytes()
    else:
        cover_data = extract_cover_from_mkv(source_path, ffprobe_data=ffprobe_data)
        cover_bytes = compose_cover(
            artist=album.artist,
            festival=album.festival,
            date=album.date,
            stage=album.stage,
            venue=album.venue or album.location,
            background_data=cover_data,
            albumartists=tags.get("albumartists") or None,
        )
        atomic_write_bytes(cover_path, cover_bytes)
        folder_jpg = album_dir / "folder.jpg"
        if folder_jpg.exists():
            atomic_write_bytes(folder_jpg, cover_bytes)

    tag_all(track_paths, album, cover_data=cover_bytes, on_progress=on_progress)

    ext = Path(manifest.track_filenames[0]).suffix.lstrip(".")
    updated = build_album_manifest(
        source_path=source_path,
        ffprobe_data=ffprobe_data,
        chapters=chapter_dicts,
        tags=tags,
        artist_folder=artist_folder,
        album_folder=album_folder,
        output_format=ext,
        codec_mode=codec_mode,
        track_filenames=manifest.track_filenames,
        cover_bytes=cover_bytes,
    )
    save_album_manifest(album_dir, updated)
    logger.info(
        "pipeline.retag: file=%s tracks=%d",
        album_dir.name,
        len(manifest.track_filenames),
    )


def check_regen_level(
    album_dir: Path,
    source_path: Path,
    ffprobe_data: dict,
    tags: dict,
    chapter_dicts: list[dict],
    artist_folder: str,
    album_folder: str,
    output_format: str,
    codec_mode: str,
    *,
    force: bool,
    manifest: AlbumManifest | None = None,
    track_filenames: list[str] | None = None,
) -> RegenLevel:
    """Return the level of regeneration needed for the album.

    ``manifest``: pre-loaded album manifest. If provided, the function
    reuses it instead of reading from disk so callers that also need the
    manifest (for example, to check ``cover_schema_version``) can avoid
    a second load.

    Returns ``RegenLevel.FULL`` when audio, chapters, or structure changed,
    ``RegenLevel.RETAG`` when only tags changed, and ``RegenLevel.SKIP``
    when nothing changed.
    """
    name = source_path.name
    if force:
        logger.debug("pipeline.regenerate: file=%s reason=force", name)
        return RegenLevel.FULL
    if not album_dir.exists():
        logger.debug("pipeline.regenerate: file=%s reason=no_album_dir", name)
        return RegenLevel.FULL

    if manifest is None:
        manifest = load_album_manifest(album_dir)
    if manifest is None:
        logger.debug("pipeline.regenerate: file=%s reason=no_manifest", name)
        return RegenLevel.FULL

    try:
        current_source = SourceFingerprint.from_ffprobe(source_path, ffprobe_data)
    except ValueError as exc:
        logger.debug(
            'pipeline.regenerate: file=%s reason=fingerprint_failed error="%s"',
            name,
            exc,
        )
        return RegenLevel.FULL

    if manifest.source.path != current_source.path:
        logger.debug(
            "pipeline.regenerate: file=%s reason=source_path_changed",
            name,
        )
        return RegenLevel.FULL
    if manifest.source.audio != current_source.audio:
        for field in (
            "codec_name",
            "sample_rate",
            "channels",
            "duration_ts",
            "time_base",
            "bit_rate",
        ):
            old = getattr(manifest.source.audio, field)
            new = getattr(current_source.audio, field)
            if old != new:
                logger.debug(
                    "pipeline.regenerate: file=%s reason=audio_changed field=%s old=%r new=%r",
                    name,
                    field,
                    old,
                    new,
                )
        return RegenLevel.FULL
    if manifest.resolved_artist_folder != artist_folder:
        logger.debug(
            'pipeline.regenerate: file=%s reason=artist_folder_changed old="%s" new="%s"',
            name,
            manifest.resolved_artist_folder,
            artist_folder,
        )
        return RegenLevel.FULL
    if manifest.resolved_album_folder != album_folder:
        logger.debug(
            'pipeline.regenerate: file=%s reason=album_folder_changed old="%s" new="%s"',
            name,
            manifest.resolved_album_folder,
            album_folder,
        )
        return RegenLevel.FULL
    if manifest.output_format != output_format:
        logger.debug(
            "pipeline.regenerate: file=%s reason=output_format_changed old=%s new=%s",
            name,
            manifest.output_format,
            output_format,
        )
        return RegenLevel.FULL
    if manifest.codec_mode != codec_mode:
        logger.debug(
            "pipeline.regenerate: file=%s reason=codec_mode_changed old=%s new=%s",
            name,
            manifest.codec_mode,
            codec_mode,
        )
        return RegenLevel.FULL
    stored_intro = manifest.intro_min_seconds
    if stored_intro is None:
        first_start = chapter_dicts[0]["start"] if chapter_dicts else 0.0
        if 0 < first_start < INTRO_MIN_SECONDS:
            logger.debug(
                "pipeline.regenerate: file=%s reason=intro_policy_upgrade gap=%.3f threshold=%.1f",
                name,
                first_start,
                INTRO_MIN_SECONDS,
            )
            return RegenLevel.FULL
    elif stored_intro != INTRO_MIN_SECONDS:
        logger.debug(
            "pipeline.regenerate: file=%s reason=intro_min_changed old=%s new=%.1f",
            name,
            stored_intro,
            INTRO_MIN_SECONDS,
        )
        return RegenLevel.FULL
    stored_chapters = manifest.chapters
    if stored_chapters and "tags" not in stored_chapters[0]:
        stored_chapters = [{**ch, "tags": {}} for ch in stored_chapters]
    if stored_chapters != chapter_dicts:
        logger.debug(
            "pipeline.regenerate: file=%s reason=chapters_changed stored=%d current=%d",
            name,
            len(stored_chapters),
            len(chapter_dicts),
        )
        if len(stored_chapters) == len(chapter_dicts):
            for i, (old, new) in enumerate(
                zip(stored_chapters, chapter_dicts, strict=True)
            ):
                if old != new:
                    logger.debug(
                        "pipeline.regenerate: file=%s reason=chapter_detail index=%d",
                        name,
                        i,
                    )
        return RegenLevel.FULL

    if track_filenames is not None and manifest.track_filenames != track_filenames:
        logger.debug(
            "pipeline.regenerate: file=%s reason=track_filenames_changed",
            name,
        )
        return RegenLevel.FULL

    for k in TAG_KEYS:
        old = manifest.tags.get(k, tag_default(k))
        new = tags.get(k, tag_default(k))
        if old != new:
            logger.debug(
                "pipeline.retag: file=%s reason=tag_changed tag=%s",
                name,
                k,
            )
            return RegenLevel.RETAG
    return RegenLevel.SKIP


def _resolve_opus_copy_packet_ms(
    audio_path: Path,
    ext: str,
    codec_mode: str,
) -> tuple[str, int | None]:
    """Decide whether the Opus copy path can use the prefix-frame fix.

    Returns (codec_mode, opus_packet_ms). For non-opus or non-copy cases
    the inputs are returned unchanged with packet_ms=None. For the opus
    copy case, probes the source and either confirms 20 ms packets or
    escalates to libopus re-encode (logging a warning) when the packet
    duration is anything else.
    """
    if ext != ".opus" or codec_mode != "copy":
        return codec_mode, None
    packet_ms = get_opus_packet_duration_ms(audio_path)
    if packet_ms == 20:
        return "copy", 20
    logger.warning(
        "pipeline.opus_fallback: file=%s packet_ms=%s mode=libopus",
        audio_path.name,
        packet_ms,
    )
    return "libopus", None


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
        logger.warning(
            "pipeline.skip: file=%s reason=no_audio", _safe_log_name(input_path)
        )
        return False

    chapters = parse_chapters(ffprobe_data)
    tags = parse_tags(ffprobe_data)
    cd_cfg = load_config(input_path)
    apply_cratedigger_canon_with(tags, cd_cfg)
    tier = detect_tier(tags)

    # Build album metadata
    album = build_album_meta(tags, chapters, input_path.stem, tier, cd_config=cd_cfg)

    # Handle intro track and short-gap merge
    _apply_intro_track(album, chapters)

    # Handle no chapters: single track spanning full duration
    if not chapters:
        duration = float(ffprobe_data.get("format", {}).get("duration", 0))
        if duration <= 0:
            logger.warning(
                "pipeline.skip: file=%s reason=no_chapters_no_duration",
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
    expected_filenames = [build_track_filename(t, ext) for t in album.tracks]

    skip_manifest = load_album_manifest(album_dir)
    level = check_regen_level(
        album_dir,
        input_path,
        ffprobe_data,
        tags,
        chapter_dicts,
        artist_folder,
        album_folder,
        ext.lstrip("."),
        codec_mode,
        force=force,
        manifest=skip_manifest,
        track_filenames=expected_filenames,
    )

    _retag_done = False
    _retag_kwargs: _RetagKwargs = {
        "album_dir": album_dir,
        "album": album,
        "source_path": input_path,
        "ffprobe_data": ffprobe_data,
        "tags": tags,
        "chapter_dicts": chapter_dicts,
        "artist_folder": artist_folder,
        "album_folder": album_folder,
        "codec_mode": codec_mode,
        "on_progress": on_progress,
    }

    # -- SKIP path: check schema version bumps -------------------------
    if level == RegenLevel.SKIP:
        if (
            skip_manifest is not None
            and skip_manifest.tag_schema_version < TAG_SCHEMA_VERSION
        ):
            try:
                retag_album(**_retag_kwargs, reuse_cover=True)
            except OSError as exc:
                if exc.errno in FATAL_DISK_ERRNOS:
                    raise
                logger.warning(
                    'pipeline.retag: file=%s reason=failed error="%s"',
                    _safe_log_name(input_path),
                    exc,
                )
                (album_dir / ALBUM_MANIFEST_FILENAME).unlink(missing_ok=True)
                level = RegenLevel.FULL
            except Exception as exc:
                logger.warning(
                    'pipeline.retag: file=%s reason=failed error="%s"',
                    _safe_log_name(input_path),
                    exc,
                )
                (album_dir / ALBUM_MANIFEST_FILENAME).unlink(missing_ok=True)
                level = RegenLevel.FULL
            else:
                level = RegenLevel.RETAG
                _retag_done = True
        elif (
            skip_manifest is not None
            and skip_manifest.cover_schema_version < COVER_SCHEMA_VERSION
        ):
            try:
                rebuild_cover_only(
                    album_dir=album_dir,
                    manifest=skip_manifest,
                    source_path=input_path,
                    ffprobe_data=ffprobe_data,
                )
            except OSError as exc:
                if exc.errno in FATAL_DISK_ERRNOS:
                    raise
                logger.warning(
                    'pipeline.cover_rebuild: file=%s reason=failed error="%s"',
                    _safe_log_name(input_path),
                    exc,
                )
                (album_dir / ALBUM_MANIFEST_FILENAME).unlink(missing_ok=True)
                level = RegenLevel.FULL
            except Exception as exc:
                logger.warning(
                    'pipeline.cover_rebuild: file=%s reason=failed error="%s"',
                    _safe_log_name(input_path),
                    exc,
                )
                (album_dir / ALBUM_MANIFEST_FILENAME).unlink(missing_ok=True)
                level = RegenLevel.FULL

    if level == RegenLevel.SKIP:
        primary_artist = album.albumartists[0] if album.albumartists else album.artist
        primary_slug = (tags.get("albumartist_slugs") or [""])[0]
        dj_artwork_data = find_dj_artwork(
            input_path,
            slug=primary_slug,
            artist=primary_artist,
        )
        artist_dir = output_dir / safe_filename(album.artist_folder)
        refresh_artist_cover(
            artist_dir,
            artist_name=primary_artist,
            dj_artwork_data=dj_artwork_data,
            compose=compose_artist_cover,
        )
        logger.info(
            "pipeline.skip: file=%s reason=unchanged",
            _safe_log_name(input_path),
        )
        return False

    # -- RETAG path: tags changed but audio/chapters identical ----------
    if level == RegenLevel.RETAG and not _retag_done:
        try:
            retag_album(**_retag_kwargs)
        except OSError as exc:
            if exc.errno in FATAL_DISK_ERRNOS:
                raise
            logger.warning(
                'pipeline.retag: file=%s reason=failed error="%s"',
                _safe_log_name(input_path),
                exc,
            )
            (album_dir / ALBUM_MANIFEST_FILENAME).unlink(missing_ok=True)
            level = RegenLevel.FULL
        except Exception as exc:
            logger.warning(
                'pipeline.retag: file=%s reason=failed error="%s"',
                _safe_log_name(input_path),
                exc,
            )
            (album_dir / ALBUM_MANIFEST_FILENAME).unlink(missing_ok=True)
            level = RegenLevel.FULL

    if level == RegenLevel.RETAG:
        primary_artist = album.albumartists[0] if album.albumartists else album.artist
        primary_slug = (tags.get("albumartist_slugs") or [""])[0]
        dj_artwork_data = find_dj_artwork(
            input_path,
            slug=primary_slug,
            artist=primary_artist,
        )
        artist_dir = output_dir / safe_filename(album.artist_folder)
        refresh_artist_cover(
            artist_dir,
            artist_name=primary_artist,
            dj_artwork_data=dj_artwork_data,
            compose=compose_artist_cover,
        )
        logger.info(
            "pipeline.retag_done: file=%s dir=%s",
            _safe_log_name(input_path),
            album_dir.name,
        )
        if on_complete:
            on_complete(album_dir, len(album.tracks))
        return True

    # Dry run: log and return
    if dry_run:
        logger.info(
            "pipeline.process_start: file=%s dir=%s tracks=%d dry_run=true",
            _safe_log_name(input_path),
            album_dir.name,
            len(album.tracks),
        )
        if on_complete:
            on_complete(album_dir, len(album.tracks))
        return True

    _remove_stale_album_dirs(output_dir, input_path, album_dir)

    # Extract, split, tag
    album_dir.mkdir(parents=True, exist_ok=True)
    logger.debug(
        "pipeline.process_start: file=%s tracks=%d codec=%s",
        _safe_log_name(input_path),
        len(album.tracks),
        ext.lstrip("."),
    )

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp_dir = Path(tmp_str)

        # Prepare audio (detect codec, extract if needed)
        _progress("Extracting audio")
        audio_path, ext, codec_mode = prepare_audio(
            input_path,
            ext,
            codec_mode,
            tmp_dir,
            cancel_event=cancel_event,
        )
        from_video = audio_path == input_path

        codec_mode, opus_packet_ms = _resolve_opus_copy_packet_ms(
            audio_path,
            ext,
            codec_mode,
        )

        # Split into tracks
        _progress("Splitting tracks")
        track_paths = split_tracks(
            audio_path,
            album.tracks,
            album_dir,
            ext=ext,
            codec_mode=codec_mode,
            from_video=from_video,
            on_progress=on_progress,
            cancel_event=cancel_event,
            opus_packet_ms=opus_packet_ms,
        )

        # Cover art
        _progress("Extracting cover art")
        cover_data = extract_cover_from_mkv(input_path, ffprobe_data=ffprobe_data)
        primary_artist = album.albumartists[0] if album.albumartists else album.artist
        primary_slug = (tags.get("albumartist_slugs") or [""])[0]
        dj_artwork_data = find_dj_artwork(
            input_path,
            slug=primary_slug,
            artist=primary_artist,
        )

        _progress("Composing covers")
        cover_bytes = compose_cover(
            artist=album.artist,
            festival=album.festival,
            date=album.date,
            stage=album.stage,
            venue=album.venue or album.location,
            background_data=cover_data,
            albumartists=tags.get("albumartists") or None,
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
            ffprobe_data=ffprobe_data,
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
            with contextlib.suppress(OSError):
                legacy.unlink()

    artist_dir = output_dir / safe_filename(album.artist_folder)
    refresh_artist_cover(
        artist_dir,
        artist_name=primary_artist,
        dj_artwork_data=dj_artwork_data,
        compose=compose_artist_cover,
    )

    logger.info(
        "pipeline.process_done: file=%s dir=%s",
        _safe_log_name(input_path),
        album_dir.name,
    )
    if on_complete:
        on_complete(album_dir, len(album.tracks))
    return True


def find_video_files(input_dir: Path) -> list[Path]:
    """Find all video files in a directory, sorted by name."""
    return sorted(f for f in input_dir.rglob("*") if f.is_file() and is_video_file(f))
