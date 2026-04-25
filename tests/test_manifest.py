from pathlib import Path

import pytest

from tracksplit.manifest import (
    ALBUM_MANIFEST_FILENAME,
    LEGACY_CHAPTER_CACHE_FILENAME,
    MANIFEST_SCHEMA,
    AlbumManifest,
    AudioFingerprint,
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
    tags = {"artist": "DJ", "festival": "F", "date": "2025"}
    ffprobe = {
        "streams": [{
            "codec_type": "audio", "codec_name": "opus",
            "sample_rate": "48000", "channels": 2,
            "duration_ts": 100, "time_base": "1/48000", "bit_rate": "192000",
        }],
    }
    m = build_album_manifest(
        source_path=src,
        ffprobe_data=ffprobe,
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
    assert m.source.path == str(src)
    assert m.source.audio.codec_name == "opus"
    assert m.source.audio.sample_rate == 48000
    assert m.source.audio.channels == 2
    assert m.source.audio.duration_ts == 100
    assert m.resolved_artist_folder == "DJ"
    assert m.resolved_album_folder == "F 2025"
    assert m.output_format == "flac"
    assert m.codec_mode == "copy"
    assert m.chapters == chapters
    assert m.track_filenames == ["01 - DJ - A.flac"]
    assert m.tags["artist"] == "DJ"
    assert len(m.cover_sha256) == 64


def test_save_and_load_roundtrip(tmp_path):
    from tests._manifest_helpers import make_ffprobe
    src = _src(tmp_path)
    m = build_album_manifest(
        source_path=src, ffprobe_data=make_ffprobe(),
        chapters=[], tags={"artist": "A"},
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
    from tests._manifest_helpers import make_ffprobe
    src = _src(tmp_path)
    a = SourceFingerprint.from_ffprobe(src, make_ffprobe())
    b = SourceFingerprint.from_ffprobe(src, make_ffprobe())
    assert a == b


def test_load_album_manifest_schema_mismatch_returns_none(tmp_path):
    from tracksplit.manifest import ALBUM_MANIFEST_FILENAME, load_album_manifest
    (tmp_path / ALBUM_MANIFEST_FILENAME).write_text(
        '{"schema": 999, "source": {"path":"","audio":{"codec_name":"","sample_rate":0,'
        '"channels":0,"duration_ts":0,"time_base":"","bit_rate":0}},'
        ' "resolved_artist_folder":"","resolved_album_folder":"","output_format":"",'
        ' "codec_mode":"","chapters":[],"tags":{},"track_filenames":[],"cover_sha256":""}'
    )
    assert load_album_manifest(tmp_path) is None


def test_load_album_manifest_schema_2_is_rejected(tmp_path, caplog):
    """Schema-2 manifests on disk after upgrade must trigger forced regen."""
    import logging
    from tracksplit.manifest import ALBUM_MANIFEST_FILENAME, load_album_manifest
    (tmp_path / ALBUM_MANIFEST_FILENAME).write_text(
        '{"schema": 2, "source": {"path":"","mtime_ns":1,"size":2,"enriched_at":""},'
        ' "resolved_artist_folder":"","resolved_album_folder":"","output_format":"",'
        ' "codec_mode":"","chapters":[],"tags":{},"track_filenames":[],"cover_sha256":""}'
    )
    with caplog.at_level(logging.DEBUG, logger="tracksplit.manifest"):
        assert load_album_manifest(tmp_path) is None
    assert any("schema mismatch" in rec.getMessage().lower() for rec in caplog.records)


def test_load_artist_manifest_schema_mismatch_returns_none(tmp_path):
    from tracksplit.manifest import ARTIST_MANIFEST_FILENAME, load_artist_manifest
    (tmp_path / ARTIST_MANIFEST_FILENAME).write_text(
        '{"schema": 999, "artist": "X", "dj_artwork_sha256": "abc"}'
    )
    assert load_artist_manifest(tmp_path) is None


def test_save_album_manifest_is_atomic(tmp_path, monkeypatch):
    """A failure inside the atomic write leaves no partial file behind."""
    from tests._manifest_helpers import make_ffprobe
    from tracksplit.manifest import (
        ALBUM_MANIFEST_FILENAME, build_album_manifest, save_album_manifest,
    )
    src = tmp_path / "s.mkv"
    src.write_bytes(b"x")
    album = tmp_path / "album"
    album.mkdir()
    m = build_album_manifest(
        source_path=src, ffprobe_data=make_ffprobe(),
        chapters=[], tags={}, artist_folder="A",
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
    # Direct from_dict with no intro_min_seconds key: simulates loading
    # a manifest dict (e.g. via downstream tooling) that omits the optional field.
    raw = {
        "schema": MANIFEST_SCHEMA,
        "source": {"path": "/x.mkv", "audio": {
            "codec_name": "opus", "sample_rate": 48000, "channels": 2,
            "duration_ts": 0, "time_base": "1/48000", "bit_rate": 0,
        }},
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
    from tests._manifest_helpers import make_ffprobe
    from tracksplit.pipeline import INTRO_MIN_SECONDS
    src = tmp_path / "x.mkv"
    src.write_bytes(b"\x00")
    m = build_album_manifest(
        source_path=src,
        ffprobe_data=make_ffprobe(),
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


def test_album_manifest_legacy_dict_without_cover_schema_version_defaults_to_zero():
    raw = {
        "schema": MANIFEST_SCHEMA,
        "source": {"path": "/x.mkv", "audio": {
            "codec_name": "opus", "sample_rate": 48000, "channels": 2,
            "duration_ts": 0, "time_base": "1/48000", "bit_rate": 0,
        }},
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
    assert m.cover_schema_version == 0


def test_album_manifest_round_trip_preserves_cover_schema_version(tmp_path):
    from tests._manifest_helpers import make_ffprobe
    from tracksplit.cover import COVER_SCHEMA_VERSION
    src = tmp_path / "x.mkv"
    src.write_bytes(b"\x00")
    m = build_album_manifest(
        source_path=src,
        ffprobe_data=make_ffprobe(),
        chapters=[],
        tags={},
        artist_folder="A",
        album_folder="B",
        output_format="flac",
        codec_mode="copy",
        track_filenames=[],
        cover_bytes=b"",
    )
    assert m.cover_schema_version == COVER_SCHEMA_VERSION
    roundtrip = AlbumManifest.from_dict(m.to_dict())
    assert roundtrip.cover_schema_version == COVER_SCHEMA_VERSION


def test_audio_fingerprint_from_ffprobe_picks_first_audio_stream():
    from tracksplit.manifest import AudioFingerprint
    ffprobe = {
        "streams": [
            {"codec_type": "video", "codec_name": "h264"},
            {
                "codec_type": "audio",
                "codec_name": "opus",
                "sample_rate": "48000",
                "channels": 2,
                "duration_ts": 14400000,
                "time_base": "1/48000",
                "bit_rate": "192000",
            },
            {"codec_type": "audio", "codec_name": "aac"},  # ignored
        ],
    }
    fp = AudioFingerprint.from_ffprobe(ffprobe)
    assert fp.codec_name == "opus"
    assert fp.sample_rate == 48000
    assert fp.channels == 2
    assert fp.duration_ts == 14400000
    assert fp.time_base == "1/48000"
    assert fp.bit_rate == 192000


def test_audio_fingerprint_handles_missing_optional_fields():
    from tracksplit.manifest import AudioFingerprint
    ffprobe = {
        "streams": [
            {
                "codec_type": "audio",
                "codec_name": "flac",
                "sample_rate": "44100",
                "channels": 2,
                # no duration_ts, time_base, bit_rate
            },
        ],
    }
    fp = AudioFingerprint.from_ffprobe(ffprobe)
    assert fp.codec_name == "flac"
    assert fp.sample_rate == 44100
    assert fp.channels == 2
    assert fp.duration_ts == 0
    assert fp.time_base == ""
    assert fp.bit_rate == 0


def test_audio_fingerprint_raises_when_no_audio_stream():
    from tracksplit.manifest import AudioFingerprint
    ffprobe = {"streams": [{"codec_type": "video", "codec_name": "h264"}]}
    with pytest.raises(ValueError, match="no audio stream"):
        AudioFingerprint.from_ffprobe(ffprobe)


def test_audio_fingerprint_equality():
    from tracksplit.manifest import AudioFingerprint
    a = AudioFingerprint("opus", 48000, 2, 100, "1/48000", 192000)
    b = AudioFingerprint("opus", 48000, 2, 100, "1/48000", 192000)
    c = AudioFingerprint("opus", 48000, 2, 100, "1/48000", 256000)
    assert a == b
    assert a != c
