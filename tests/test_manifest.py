import json
from pathlib import Path

import pytest

from tracksplit.manifest import (
    ALBUM_MANIFEST_FILENAME,
    LEGACY_CHAPTER_CACHE_FILENAME,
    MANIFEST_SCHEMA,
    AlbumManifest,
    SourceFingerprint,
    build_album_manifest,
    load_album_manifest,
    save_album_manifest,
)


def _src(tmp_path: Path) -> Path:
    p = tmp_path / "source.mkv"
    p.write_bytes(b"x" * 100)
    return p


def test_build_album_manifest_captures_source(tmp_path):
    src = _src(tmp_path)
    chapters = [{"index": 1, "title": "A", "start": 0.0, "end": 60.0}]
    tags = {"artist": "DJ", "festival": "F", "date": "2025", "stage": "",
            "venue": "", "mbid": "", "enriched_at": "2026-04-10"}
    m = build_album_manifest(
        source_path=src,
        chapters=chapters,
        tags=tags,
        artist_folder="DJ",
        album_folder="F 2025",
        output_format="flac",
        codec_mode="copy",
        track_filenames=["01 - DJ - A.flac"],
        cover_bytes=b"jpeg",
    )
    assert m.schema == MANIFEST_SCHEMA
    assert m.source.size == 100
    assert m.source.path == str(src)
    assert m.source.enriched_at == "2026-04-10"
    assert m.resolved_artist_folder == "DJ"
    assert m.resolved_album_folder == "F 2025"
    assert m.output_format == "flac"
    assert m.codec_mode == "copy"
    assert m.chapters == chapters
    assert m.tags["artist"] == "DJ"
    assert m.track_filenames == ["01 - DJ - A.flac"]
    assert len(m.cover_sha256) == 64


def test_save_and_load_roundtrip(tmp_path):
    src = _src(tmp_path)
    m = build_album_manifest(
        source_path=src, chapters=[], tags={"artist": "A"},
        artist_folder="A", album_folder="B",
        output_format="flac", codec_mode="copy",
        track_filenames=[], cover_bytes=b"",
    )
    album_dir = tmp_path / "album"
    album_dir.mkdir()
    save_album_manifest(album_dir, m)
    assert (album_dir / ALBUM_MANIFEST_FILENAME).is_file()
    loaded = load_album_manifest(album_dir)
    assert loaded == m


def test_load_missing_returns_none(tmp_path):
    assert load_album_manifest(tmp_path) is None


def test_load_corrupt_returns_none(tmp_path):
    (tmp_path / ALBUM_MANIFEST_FILENAME).write_text("{not json")
    assert load_album_manifest(tmp_path) is None


def test_legacy_chapter_cache_name_is_stable():
    assert LEGACY_CHAPTER_CACHE_FILENAME == ".tracksplit_chapters.json"


def test_source_fingerprint_equality(tmp_path):
    src = _src(tmp_path)
    a = SourceFingerprint.from_path(src, enriched_at="x")
    b = SourceFingerprint.from_path(src, enriched_at="x")
    assert a == b
