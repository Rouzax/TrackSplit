"""Album and artist manifest files used to detect rerun changes.

Stored alongside generated outputs so that a future invocation can
decide whether anything meaningful changed since the last run.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

ALBUM_MANIFEST_FILENAME = ".tracksplit_manifest.json"
ARTIST_MANIFEST_FILENAME = ".tracksplit_artist.json"
LEGACY_CHAPTER_CACHE_FILENAME = ".tracksplit_chapters.json"
MANIFEST_SCHEMA = 4


TAG_KEYS = (
    "artist",
    "festival",
    "date",
    "stage",
    "venue",
    "genres",
    "comment",
    "country",
    "albumartist_display",
    "albumartists",
    "albumartist_mbids",
)

_LIST_TAG_KEYS = frozenset({"genres", "albumartists", "albumartist_mbids"})


def tag_default(key: str):
    return [] if key in _LIST_TAG_KEYS else ""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class AudioFingerprint:
    """Fingerprint of the source file's audio stream.

    Stable across container rewrites (mkvpropedit tag edits) but moves on a
    real audio change: re-encode, re-mux to a different codec, channel-layout
    change. Duration is deliberately not stored: Matroska reports it as N/A on
    the stream, and a length change already surfaces as a moved track boundary.
    """

    codec_name: str
    sample_rate: int
    channels: int
    time_base: str

    @classmethod
    def from_ffprobe(cls, ffprobe_data: dict) -> AudioFingerprint:
        for stream in ffprobe_data.get("streams", []):
            if stream.get("codec_type") == "audio":
                return cls(
                    codec_name=stream.get("codec_name", ""),
                    sample_rate=int(stream.get("sample_rate", 0) or 0),
                    channels=int(stream.get("channels", 0) or 0),
                    time_base=stream.get("time_base", ""),
                )
        raise ValueError("ffprobe data has no audio stream")

    @classmethod
    def from_dict(cls, d: dict) -> AudioFingerprint:
        return cls(
            codec_name=d.get("codec_name", ""),
            sample_rate=int(d.get("sample_rate", 0) or 0),
            channels=int(d.get("channels", 0) or 0),
            time_base=d.get("time_base", ""),
        )


@dataclass(frozen=True)
class SourceFingerprint:
    path: str
    audio: AudioFingerprint

    @classmethod
    def from_ffprobe(cls, path: Path, ffprobe_data: dict) -> SourceFingerprint:
        return cls(
            path=str(path),
            audio=AudioFingerprint.from_ffprobe(ffprobe_data),
        )


@dataclass(frozen=True)
class SourceIdentity:
    source_id: str | None
    audio: AudioFingerprint

    def to_dict(self) -> dict:
        return {"source_id": self.source_id, "audio": asdict(self.audio)}

    @classmethod
    def from_dict(cls, d: dict) -> SourceIdentity:
        return cls(
            source_id=d.get("source_id"),
            audio=AudioFingerprint.from_dict(d.get("audio", {})),
        )


@dataclass
class TrackEntry:
    index: int
    filename: str
    start: float
    end: float
    title: str = ""
    artist: str = ""
    publisher: str = ""
    genre: list[str] = field(default_factory=list)
    artists: list[str] = field(default_factory=list)
    artist_mbids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        from tracksplit.paths import nfc

        return {
            "index": self.index,
            "filename": nfc(self.filename),
            "start": self.start,
            "end": self.end,
            "title": nfc(self.title),
            "artist": nfc(self.artist),
            "publisher": nfc(self.publisher),
            "genre": [nfc(g) for g in self.genre],
            "artists": [nfc(a) for a in self.artists],
            "artist_mbids": list(self.artist_mbids),
        }

    @classmethod
    def from_dict(cls, d: dict) -> TrackEntry:
        from tracksplit.paths import nfc

        return cls(
            index=int(d["index"]),
            filename=nfc(d.get("filename", "")),
            start=float(d.get("start", 0.0)),
            end=float(d.get("end", 0.0)),
            title=nfc(d.get("title", "")),
            artist=nfc(d.get("artist", "")),
            publisher=nfc(d.get("publisher", "")),
            genre=[nfc(g) for g in d.get("genre", [])],
            artists=[nfc(a) for a in d.get("artists", [])],
            artist_mbids=list(d.get("artist_mbids", [])),
        )


@dataclass
class AlbumManifest:
    """Sidecar manifest for a generated album (schema 4).

    `output_format` holds the RESOLVED extension ("flac"/"opus") written to
    disk, not the CLI argument. `tracks` is the ordered list of output tracks
    (the intro is index 0); each entry carries its filename, boundaries, and
    the embedded per-track tag values.
    """

    schema: int
    identity: SourceIdentity
    source_path: str
    resolved_artist_folder: str
    resolved_album_folder: str
    output_format: str
    codec_mode: str
    album_tags: dict
    tracks: list[TrackEntry]
    cover_sha256: str
    cover_schema_version: int = 0
    tag_schema_version: int = 0
    migrated_from: int | None = None

    def to_dict(self) -> dict:
        from tracksplit.paths import nfc  # local: paths imports manifest (cycle)

        return {
            "schema": self.schema,
            "identity": self.identity.to_dict(),
            "source_path": self.source_path,
            "resolved_artist_folder": nfc(self.resolved_artist_folder),
            "resolved_album_folder": nfc(self.resolved_album_folder),
            "output_format": self.output_format,
            "codec_mode": self.codec_mode,
            "album_tags": nfc_tags(self.album_tags),
            "tracks": [t.to_dict() for t in self.tracks],
            "cover_sha256": self.cover_sha256,
            "cover_schema_version": self.cover_schema_version,
            "tag_schema_version": self.tag_schema_version,
        }

    @classmethod
    def from_dict(cls, d: dict) -> AlbumManifest:
        from tracksplit.paths import nfc  # local: paths imports manifest (cycle)

        return cls(
            schema=d["schema"],
            identity=SourceIdentity.from_dict(d["identity"]),
            source_path=d.get("source_path", ""),
            resolved_artist_folder=nfc(d["resolved_artist_folder"]),
            resolved_album_folder=nfc(d["resolved_album_folder"]),
            output_format=d["output_format"],
            codec_mode=d["codec_mode"],
            album_tags=d.get("album_tags", {}),
            tracks=[TrackEntry.from_dict(t) for t in d.get("tracks", [])],
            cover_sha256=d.get("cover_sha256", ""),
            cover_schema_version=d.get("cover_schema_version", 0),
            tag_schema_version=d.get("tag_schema_version", 0),
        )


def _filter_tags(tags: dict) -> dict:
    return {k: tags.get(k, tag_default(k)) for k in TAG_KEYS}


def nfc_tags(tags: dict) -> dict:
    from tracksplit.paths import nfc  # local: paths imports manifest (cycle)

    out: dict = {}
    for k, v in tags.items():
        if isinstance(v, str):
            out[k] = nfc(v)
        elif isinstance(v, list):
            out[k] = [nfc(x) if isinstance(x, str) else x for x in v]
        else:
            out[k] = v
    return out


def _album_tags_from_meta(album) -> dict:
    """Project album-level fields from an AlbumMeta into the manifest tag dict."""
    return {
        "artist": album.artist,
        "festival": album.festival,
        "date": album.date,
        "stage": album.stage,
        "venue": album.venue,
        "genres": list(album.genre),
        "comment": album.comment,
        "country": album.country,
        "albumartist_display": album.artist,
        "albumartists": list(album.albumartists),
        "albumartist_mbids": list(album.albumartist_mbids),
    }


def build_album_manifest(
    *,
    source_path: Path,
    ffprobe_data: dict,
    album,  # AlbumMeta (untyped import-cycle avoidance)
    track_filenames: list[str],
    artist_folder: str,
    album_folder: str,
    output_format: str,
    codec_mode: str,
    source_id: str | None,
    cover_bytes: bytes,
) -> AlbumManifest:
    from tracksplit.cover import COVER_SCHEMA_VERSION  # local import avoids cycle
    from tracksplit.tagger import TAG_SCHEMA_VERSION  # local import avoids cycle

    tracks = [
        TrackEntry(
            index=t.number,
            filename=fn,
            start=t.start,
            end=t.end,
            title=t.title,
            artist=t.artist,
            publisher=t.publisher,
            genre=list(t.genre),
            artists=list(t.artists),
            artist_mbids=list(t.artist_mbids),
        )
        for t, fn in zip(album.tracks, track_filenames, strict=True)
    ]
    return AlbumManifest(
        schema=MANIFEST_SCHEMA,
        identity=SourceIdentity(
            source_id=source_id or None,
            audio=AudioFingerprint.from_ffprobe(ffprobe_data),
        ),
        source_path=str(source_path),
        resolved_artist_folder=artist_folder,
        resolved_album_folder=album_folder,
        output_format=output_format,
        codec_mode=codec_mode,
        album_tags=_album_tags_from_meta(album),
        tracks=tracks,
        cover_sha256=_sha256(cover_bytes) if cover_bytes else "",
        cover_schema_version=COVER_SCHEMA_VERSION,
        tag_schema_version=TAG_SCHEMA_VERSION,
    )


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def atomic_write_text(path: Path, data: str) -> None:
    atomic_write_bytes(path, data.encode("utf-8"))


def save_album_manifest(album_dir: Path, manifest: AlbumManifest) -> None:
    path = album_dir / ALBUM_MANIFEST_FILENAME
    atomic_write_text(
        path, json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False)
    )


def load_album_manifest(album_dir: Path) -> AlbumManifest | None:
    path = album_dir / ALBUM_MANIFEST_FILENAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning('manifest.unreadable: file=%s error="%s"', path.name, exc)
        return None
    schema = data.get("schema")
    try:
        if schema == MANIFEST_SCHEMA:
            return AlbumManifest.from_dict(data)
        if schema == 3:
            return _migrate_v3(data)
        logger.debug(
            "manifest.schema_mismatch: file=%s found=%s expected=%d",
            path.name,
            schema,
            MANIFEST_SCHEMA,
        )
        return None
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning('manifest.unreadable: file=%s error="%s"', path.name, exc)
        return None


def _migrate_v3(data: dict) -> AlbumManifest:
    """Map a schema-3 manifest into the schema-4 model in memory.

    The filename list and chapter boundaries are preserved; per-track embedded
    tag values are left empty (re-derived from the source during reconciliation),
    so a migrated manifest yields SKIP/RETAG, never a forced resplit.
    """
    from tracksplit.paths import nfc  # local: paths imports manifest (cycle)

    src = data["source"]
    filenames = list(data.get("track_filenames", []))
    chapters = list(data.get("chapters", []))
    tracks: list[TrackEntry] = []
    has_intro = bool(filenames) and "intro" in Path(filenames[0]).stem.lower()
    fn_iter = iter(filenames)
    if has_intro:
        intro_fn = next(fn_iter)
        first_start = chapters[0]["start"] if chapters else 0.0
        tracks.append(TrackEntry(0, intro_fn, 0.0, float(first_start), "Intro"))
    for ch in chapters:
        try:
            fn = next(fn_iter)
        except StopIteration:
            break
        tracks.append(
            TrackEntry(
                index=int(ch.get("index", len(tracks))),
                filename=fn,
                start=float(ch.get("start", 0.0)),
                end=float(ch.get("end", 0.0)),
                title=ch.get("title", ""),
            )
        )
    return AlbumManifest(
        schema=MANIFEST_SCHEMA,
        identity=SourceIdentity(None, AudioFingerprint.from_dict(src.get("audio", {}))),
        source_path=src.get("path", ""),
        resolved_artist_folder=nfc(data.get("resolved_artist_folder", "")),
        resolved_album_folder=nfc(data.get("resolved_album_folder", "")),
        output_format=data.get("output_format", ""),
        codec_mode=data.get("codec_mode", ""),
        album_tags=data.get("tags", {}),
        tracks=tracks,
        cover_sha256=data.get("cover_sha256", ""),
        cover_schema_version=data.get("cover_schema_version", 0),
        tag_schema_version=data.get("tag_schema_version", 0),
        migrated_from=3,
    )


@dataclass
class ArtistManifest:
    schema: int
    artist: str
    dj_artwork_sha256: str
    cover_schema_version: int = 0

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
                "manifest.schema_mismatch: file=%s found=%s expected=%d",
                path.name,
                d.get("schema"),
                MANIFEST_SCHEMA,
            )
            return None
        return ArtistManifest(
            schema=d["schema"],
            artist=d["artist"],
            dj_artwork_sha256=d["dj_artwork_sha256"],
            cover_schema_version=d.get("cover_schema_version", 0),
        )
    except (json.JSONDecodeError, OSError, KeyError) as exc:
        logger.warning('manifest.unreadable: file=%s error="%s"', path.name, exc)
        return None


def save_artist_manifest(artist_dir: Path, manifest: ArtistManifest) -> None:
    path = artist_dir / ARTIST_MANIFEST_FILENAME
    atomic_write_text(path, json.dumps(manifest.to_dict(), indent=2))


def artwork_sha256(data: bytes | None) -> str:
    return _sha256(data) if data else ""
