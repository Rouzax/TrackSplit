"""Pure reconciliation planner: diff a stored manifest against the desired
state and return the cheapest set of operations. No filesystem access."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from tracksplit.manifest import (
    AlbumManifest,
    AudioFingerprint,
    TrackEntry,
    load_album_manifest,
    nfc_tags,
)
from tracksplit.paths import fold, nfc


def build_desired_album(
    *,
    album,  # AlbumMeta
    ffprobe_data: dict,
    tags: dict,
    artist_folder: str,
    album_folder: str,
    output_format: str,
    codec_mode: str,
    source_path: str,
    cover_sha256: str,
    track_filenames: list[str],
) -> DesiredAlbum:
    # Local imports mirror manifest.build_album_manifest: cover/tagger pull in
    # heavier modules, and _album_tags_from_meta lives in manifest.
    from tracksplit.cover import COVER_SCHEMA_VERSION
    from tracksplit.manifest import _album_tags_from_meta  # projection helper
    from tracksplit.tagger import TAG_SCHEMA_VERSION

    tracks = [
        TrackEntry(
            index=t.number, filename=fn, start=t.start, end=t.end, title=t.title,
            artist=t.artist, publisher=t.publisher, genre=list(t.genre),
            artists=list(t.artists), artist_mbids=list(t.artist_mbids),
        )
        for t, fn in zip(album.tracks, track_filenames, strict=True)
    ]
    return DesiredAlbum(
        source_id=tags.get("CRATEDIGGER_1001TL_ID") or None,
        audio=AudioFingerprint.from_ffprobe(ffprobe_data),
        source_path=source_path,
        artist_folder=artist_folder,
        album_folder=album_folder,
        output_format=output_format,
        codec_mode=codec_mode,
        album_tags=_album_tags_from_meta(album),
        tracks=tracks,
        cover_sha256=cover_sha256,
        cover_schema_version=COVER_SCHEMA_VERSION,
        tag_schema_version=TAG_SCHEMA_VERSION,
    )


class RegenLevel(Enum):
    SKIP = "skip"
    RETAG = "retag"
    FULL = "full"


@dataclass
class DesiredAlbum:
    source_id: str | None
    audio: AudioFingerprint
    source_path: str
    artist_folder: str
    album_folder: str
    output_format: str
    codec_mode: str
    album_tags: dict
    tracks: list[TrackEntry]
    cover_sha256: str
    cover_schema_version: int
    tag_schema_version: int


@dataclass
class ReconcilePlan:
    level: RegenLevel
    move: bool = False
    renames: list[tuple[str, str]] = field(default_factory=list)
    retag: bool = False
    path_refresh: bool = False
    full_reason: str | None = None


def _track_tag_fields(t: TrackEntry) -> tuple:
    # The embedded per-track values (NFC). Filename and boundaries excluded.
    return (
        nfc(t.title),
        nfc(t.artist),
        nfc(t.publisher),
        tuple(nfc(g) for g in t.genre),
        tuple(nfc(a) for a in t.artists),
        tuple(t.artist_mbids),
    )


def plan_reconciliation(stored: AlbumManifest, desired: DesiredAlbum) -> ReconcilePlan:
    # --- FULL triggers (audio cuts must change) -------------------------
    if stored.identity.audio != desired.audio:
        return ReconcilePlan(RegenLevel.FULL, full_reason="audio")
    if stored.output_format != desired.output_format:
        return ReconcilePlan(RegenLevel.FULL, full_reason="output_format")
    if stored.codec_mode != desired.codec_mode:
        return ReconcilePlan(RegenLevel.FULL, full_reason="codec_mode")
    if len(stored.tracks) != len(desired.tracks):
        return ReconcilePlan(RegenLevel.FULL, full_reason="track_count")
    for s, d in zip(stored.tracks, desired.tracks, strict=True):
        if s.start != d.start or s.end != d.end:
            return ReconcilePlan(RegenLevel.FULL, full_reason="boundary")

    # --- cheap ops ------------------------------------------------------
    path_refresh = stored.source_path != desired.source_path

    move = fold(stored.resolved_artist_folder) != fold(desired.artist_folder) or fold(
        stored.resolved_album_folder
    ) != fold(desired.album_folder)
    # Also catch case/normalization-only folder drift (corrective move).
    if not move:
        move = stored.resolved_artist_folder != nfc(
            desired.artist_folder
        ) or stored.resolved_album_folder != nfc(desired.album_folder)

    renames: list[tuple[str, str]] = []
    for s, d in zip(stored.tracks, desired.tracks, strict=True):
        if nfc(s.filename) != nfc(d.filename):
            renames.append((s.filename, d.filename))

    # A migrated (schema-3) manifest has no real stored per-track tag values,
    # so we trust the source: the on-disk files were written from the same
    # source, so their embedded tags already match desired. Skipping the tag
    # comparison here makes an unchanged migrated album reconcile to SKIP,
    # not a blanket first-run retag.
    trust_source = stored.migrated_from is not None

    retag = False
    if not trust_source:
        if nfc_tags(stored.album_tags) != nfc_tags(desired.album_tags):
            retag = True
        if not retag:
            for s, d in zip(stored.tracks, desired.tracks, strict=True):
                if _track_tag_fields(s) != _track_tag_fields(d):
                    retag = True
                    break
    if stored.tag_schema_version < desired.tag_schema_version:
        retag = True
    if stored.cover_sha256 != desired.cover_sha256:
        retag = True
    if stored.cover_schema_version < desired.cover_schema_version:
        retag = True
    # A folder move implies an album-tag change in practice; pair with retag.
    if move:
        retag = True
    # A title-driven rename always coincides with a title-tag change; ensure
    # the embedded title is rewritten too.
    if renames:
        retag = retag or any(
            nfc(s.title) != nfc(d.title)
            for s, d in zip(stored.tracks, desired.tracks, strict=True)
        )

    level = RegenLevel.RETAG if retag else RegenLevel.SKIP
    return ReconcilePlan(
        level=level,
        move=move,
        renames=renames,
        retag=retag,
        path_refresh=path_refresh,
        full_reason=None,
    )


@dataclass
class IdentityIndex:
    by_id: dict[str, Path]
    by_fp: dict[tuple, list[Path]]  # (audio, boundaries) -> dirs (ambiguity guard)

    def lookup(
        self,
        source_id: str | None,
        audio: AudioFingerprint,
        boundaries: list[tuple[float, float]],
    ) -> Path | None:
        if source_id:
            return self.by_id.get(source_id)
        key = (audio, tuple(boundaries))
        hits = self.by_fp.get(key, [])
        return hits[0] if len(hits) == 1 else None


def build_identity_index(output_root: Path, load=load_album_manifest) -> IdentityIndex:
    by_id: dict[str, Path] = {}
    by_fp: dict[tuple, list[Path]] = {}
    if not output_root.exists():
        return IdentityIndex(by_id, by_fp)
    for album_dir in sorted(output_root.glob("*/*")):
        if not album_dir.is_dir() or album_dir.is_symlink():
            continue
        m = load(album_dir)
        if m is None:
            continue
        sid = m.identity.source_id
        if sid:
            # Keep the dir already at its canonical-looking location on conflict:
            # first writer wins deterministically by sorted scan order.
            by_id.setdefault(sid, album_dir)
        else:
            bounds = tuple((t.start, t.end) for t in m.tracks)
            by_fp.setdefault((m.identity.audio, bounds), []).append(album_dir)
    return IdentityIndex(by_id, by_fp)
