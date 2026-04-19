"""Album and artist manifest files used to detect rerun changes.

Stored alongside generated outputs so that a future invocation can
decide whether anything meaningful changed since the last run.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

ALBUM_MANIFEST_FILENAME = ".tracksplit_manifest.json"
ARTIST_MANIFEST_FILENAME = ".tracksplit_artist.json"
LEGACY_CHAPTER_CACHE_FILENAME = ".tracksplit_chapters.json"
MANIFEST_SCHEMA = 2


TAG_KEYS = (
    "artist", "album", "festival", "date", "stage", "venue",
    "mbid", "enriched_at",
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class SourceFingerprint:
    path: str
    mtime_ns: int
    size: int
    enriched_at: str

    @classmethod
    def from_path(cls, path: Path, enriched_at: str = "") -> "SourceFingerprint":
        st = path.stat()
        return cls(
            path=str(path),
            mtime_ns=st.st_mtime_ns,
            size=st.st_size,
            enriched_at=enriched_at,
        )


@dataclass
class AlbumManifest:
    """Sidecar manifest for a generated album.

    `output_format` holds the RESOLVED extension (``"flac"`` or ``"opus"``) that
    was actually written to disk, not the CLI argument (which may have been
    ``"auto"``). Compare against ``ext.lstrip('.')`` when deciding reruns.
    """
    schema: int
    source: SourceFingerprint
    resolved_artist_folder: str
    resolved_album_folder: str
    output_format: str
    codec_mode: str
    chapters: list[dict]
    tags: dict
    track_filenames: list[str]
    cover_sha256: str
    intro_min_seconds: float | None = None
    cover_schema_version: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "AlbumManifest":
        src = d["source"]
        return cls(
            schema=d["schema"],
            source=SourceFingerprint(
                path=src["path"],
                mtime_ns=src["mtime_ns"],
                size=src["size"],
                enriched_at=src.get("enriched_at", ""),
            ),
            resolved_artist_folder=d["resolved_artist_folder"],
            resolved_album_folder=d["resolved_album_folder"],
            output_format=d["output_format"],
            codec_mode=d["codec_mode"],
            chapters=d["chapters"],
            tags=d["tags"],
            track_filenames=d["track_filenames"],
            cover_sha256=d["cover_sha256"],
            intro_min_seconds=d.get("intro_min_seconds"),
            cover_schema_version=d.get("cover_schema_version", 0),
        )


def _filter_tags(tags: dict) -> dict:
    return {k: tags.get(k, "") for k in TAG_KEYS}


def build_album_manifest(
    *,
    source_path: Path,
    chapters: list[dict],
    tags: dict,
    artist_folder: str,
    album_folder: str,
    output_format: str,
    codec_mode: str,
    track_filenames: list[str],
    cover_bytes: bytes,
) -> AlbumManifest:
    from tracksplit.pipeline import INTRO_MIN_SECONDS  # local import avoids cycle
    from tracksplit.cover import COVER_SCHEMA_VERSION  # local import avoids cycle
    return AlbumManifest(
        schema=MANIFEST_SCHEMA,
        source=SourceFingerprint.from_path(
            source_path, enriched_at=tags.get("enriched_at", ""),
        ),
        resolved_artist_folder=artist_folder,
        resolved_album_folder=album_folder,
        output_format=output_format,
        codec_mode=codec_mode,
        chapters=list(chapters),
        tags=_filter_tags(tags),
        track_filenames=list(track_filenames),
        cover_sha256=_sha256(cover_bytes) if cover_bytes else "",
        intro_min_seconds=INTRO_MIN_SECONDS,
        cover_schema_version=COVER_SCHEMA_VERSION,
    )


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_text(path: Path, data: str) -> None:
    atomic_write_bytes(path, data.encode("utf-8"))


def save_album_manifest(album_dir: Path, manifest: AlbumManifest) -> None:
    path = album_dir / ALBUM_MANIFEST_FILENAME
    atomic_write_text(path, json.dumps(manifest.to_dict(), indent=2))


def load_album_manifest(album_dir: Path) -> AlbumManifest | None:
    path = album_dir / ALBUM_MANIFEST_FILENAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
        if data.get("schema") != MANIFEST_SCHEMA:
            logger.debug(
                "Manifest schema mismatch at %s: got %r, expected %r",
                path, data.get("schema"), MANIFEST_SCHEMA,
            )
            return None
        return AlbumManifest.from_dict(data)
    except (json.JSONDecodeError, OSError, KeyError, TypeError) as exc:
        logger.warning("Manifest unreadable at %s: %s", path, exc)
        return None


@dataclass
class ArtistManifest:
    schema: int
    artist: str
    dj_artwork_sha256: str

    def to_dict(self) -> dict:
        return asdict(self)


def load_artist_manifest(artist_dir: Path) -> ArtistManifest | None:
    path = artist_dir / ARTIST_MANIFEST_FILENAME
    if not path.is_file():
        return None
    try:
        d = json.loads(path.read_text())
        if d.get("schema") != MANIFEST_SCHEMA:
            logger.debug(
                "Artist manifest schema mismatch at %s: got %r, expected %r",
                path, d.get("schema"), MANIFEST_SCHEMA,
            )
            return None
        return ArtistManifest(
            schema=d["schema"], artist=d["artist"],
            dj_artwork_sha256=d["dj_artwork_sha256"],
        )
    except (json.JSONDecodeError, OSError, KeyError) as exc:
        logger.warning("Artist manifest unreadable at %s: %s", path, exc)
        return None


def save_artist_manifest(artist_dir: Path, manifest: ArtistManifest) -> None:
    path = artist_dir / ARTIST_MANIFEST_FILENAME
    atomic_write_text(path, json.dumps(manifest.to_dict(), indent=2))


def artwork_sha256(data: bytes | None) -> str:
    return _sha256(data) if data else ""
