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


def test_load_album_manifest_schema_mismatch_returns_none(tmp_path):
    from tracksplit.manifest import ALBUM_MANIFEST_FILENAME, load_album_manifest
    (tmp_path / ALBUM_MANIFEST_FILENAME).write_text(
        '{"schema": 999, "source": {"path":"","mtime_ns":0,"size":0,"enriched_at":""},'
        ' "resolved_artist_folder":"","resolved_album_folder":"","output_format":"",'
        ' "codec_mode":"","chapters":[],"tags":{},"track_filenames":[],"cover_sha256":""}'
    )
    assert load_album_manifest(tmp_path) is None


def test_load_artist_manifest_schema_mismatch_returns_none(tmp_path):
    from tracksplit.manifest import ARTIST_MANIFEST_FILENAME, load_artist_manifest
    (tmp_path / ARTIST_MANIFEST_FILENAME).write_text(
        '{"schema": 999, "artist": "X", "dj_artwork_sha256": "abc"}'
    )
    assert load_artist_manifest(tmp_path) is None


def test_save_album_manifest_is_atomic(tmp_path, monkeypatch):
    """A failure inside the atomic write leaves no partial file behind."""
    from tracksplit.manifest import (
        ALBUM_MANIFEST_FILENAME, build_album_manifest, save_album_manifest,
    )
    src = tmp_path / "s.mkv"
    src.write_bytes(b"x")
    album = tmp_path / "album"
    album.mkdir()
    m = build_album_manifest(
        source_path=src, chapters=[], tags={}, artist_folder="A",
        album_folder="B", output_format="flac", codec_mode="copy",
        track_filenames=[], cover_bytes=b"",
    )
    save_album_manifest(album, m)
    content = (album / ALBUM_MANIFEST_FILENAME).read_text()

    import os as _os
    orig_replace = _os.replace
    def _boom(a, b): raise OSError("boom")
    monkeypatch.setattr(_os, "replace", _boom)
    with pytest.raises(OSError):
        save_album_manifest(album, m)
    assert (album / ALBUM_MANIFEST_FILENAME).read_text() == content
    leftovers = [p.name for p in album.iterdir()
                 if p.name.startswith(ALBUM_MANIFEST_FILENAME + ".")]
    assert leftovers == []

    monkeypatch.setattr(_os, "replace", orig_replace)


def test_album_manifest_from_dict_defaults_intro_min_seconds_to_none():
    # Simulates an on-disk manifest written before the field existed.
    raw = {
        "schema": 1,
        "source": {"path": "/x.mkv", "mtime_ns": 1, "size": 2, "enriched_at": ""},
        "resolved_artist_folder": "Artist",
        "resolved_album_folder": "Album",
        "output_format": "flac",
        "codec_mode": "copy",
        "chapters": [],
        "tags": {},
        "track_filenames": [],
        "cover_sha256": "",
    }
    m = AlbumManifest.from_dict(raw)
    assert m.intro_min_seconds is None


def test_album_manifest_round_trip_preserves_intro_min_seconds(tmp_path):
    # Build, save, load. The value written now should be the current constant.
    from tracksplit.pipeline import INTRO_MIN_SECONDS
    src = tmp_path / "x.mkv"
    src.write_bytes(b"\x00")
    m = build_album_manifest(
        source_path=src,
        chapters=[],
        tags={},
        artist_folder="A",
        album_folder="B",
        output_format="flac",
        codec_mode="copy",
        track_filenames=[],
        cover_bytes=b"",
    )
    assert m.intro_min_seconds == INTRO_MIN_SECONDS
