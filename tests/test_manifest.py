import json
from pathlib import Path

import pytest

from tracksplit.manifest import (
    ALBUM_MANIFEST_FILENAME,
    LEGACY_CHAPTER_CACHE_FILENAME,
    MANIFEST_SCHEMA,
    AlbumManifest,
    AudioFingerprint,
    SourceIdentity,
    TrackEntry,
    build_album_manifest,
    load_album_manifest,
    save_album_manifest,
)
from tracksplit.models import AlbumMeta, TrackMeta


def _sample_manifest() -> AlbumManifest:
    return AlbumManifest(
        schema=MANIFEST_SCHEMA,
        identity=SourceIdentity(
            "xfg8qrk", AudioFingerprint("opus", 48000, 2, "1/1000")
        ),
        source_path="E:\\\\v\\\\x.mkv",
        resolved_artist_folder="MORTEN",
        resolved_album_folder="Tomorrowland 2025 (Mainstage)",
        output_format="opus",
        codec_mode="copy",
        album_tags={"artist": "MORTEN", "genres": ["Trance"]},
        tracks=[TrackEntry(0, "00 - Intro.opus", 0.0, 12.0, "Intro")],
        cover_sha256="abc",
        cover_schema_version=3,
        tag_schema_version=2,
    )


def test_album_manifest_schema_is_4():
    assert MANIFEST_SCHEMA == 4


def test_album_manifest_roundtrip():
    m = _sample_manifest()
    again = AlbumManifest.from_dict(m.to_dict())
    assert again.to_dict() == m.to_dict()
    assert again.identity.source_id == "xfg8qrk"
    assert again.tracks[0].filename == "00 - Intro.opus"


def test_track_entry_from_dict_splits_legacy_pipe_values():
    """A pre-0.30.0 manifest stores publisher as a string and may carry a
    pipe-joined genre element; from_dict normalizes both to clean lists so an
    upgraded re-run reconciles to SKIP rather than a spurious retag."""
    d = {
        "index": 1,
        "filename": "01 - A - B.flac",
        "start": 0.0,
        "end": 1.0,
        "publisher": "STMPD|ASYLUM",
        "genre": ["House|Techno"],
    }
    t = TrackEntry.from_dict(d)
    assert t.publisher == ["STMPD", "ASYLUM"]
    assert t.genre == ["House", "Techno"]


def test_track_entry_from_dict_accepts_list_publisher():
    d = {
        "index": 1,
        "filename": "x.flac",
        "start": 0.0,
        "end": 1.0,
        "publisher": ["STMPD", "ASYLUM"],
        "genre": ["House", "Techno"],
    }
    t = TrackEntry.from_dict(d)
    assert t.publisher == ["STMPD", "ASYLUM"]
    assert t.genre == ["House", "Techno"]


def _src(tmp_path: Path) -> Path:
    p = tmp_path / "source.mkv"
    p.write_bytes(b"x" * 100)
    return p


def test_build_album_manifest_v4_maps_tracks_and_identity():
    album = AlbumMeta(
        artist="MORTEN",
        album="Tomorrowland 2025 (Mainstage)",
        genre=["Trance"],
        albumartists=["MORTEN"],
        tracks=[
            TrackMeta(number=0, title="Intro", start=0.0, end=12.0),
            TrackMeta(
                number=2,
                title="Culture",
                start=172.0,
                end=292.0,
                artist="MORTEN & ARTBAT",
                publisher=["INSOMNIAC"],
                genre=["Melodic House/Techno"],
                artists=["MORTEN", "ARTBAT"],
                artist_mbids=["m1", "m2"],
            ),
        ],
    )
    ffprobe = {
        "streams": [
            {
                "codec_type": "audio",
                "codec_name": "opus",
                "sample_rate": "48000",
                "channels": 2,
                "time_base": "1/1000",
            }
        ]
    }
    m = build_album_manifest(
        source_path=Path("E:/v/x.mkv"),
        ffprobe_data=ffprobe,
        album=album,
        track_filenames=["00 - Intro.opus", "02 - MORTEN & ARTBAT - Culture.opus"],
        artist_folder="MORTEN",
        album_folder="Tomorrowland 2025 (Mainstage)",
        output_format="opus",
        codec_mode="copy",
        source_id="xfg8qrk",
        cover_bytes=b"x",
    )
    assert m.schema == 4
    assert m.identity.source_id == "xfg8qrk"
    assert [t.filename for t in m.tracks] == [
        "00 - Intro.opus",
        "02 - MORTEN & ARTBAT - Culture.opus",
    ]
    assert m.tracks[1].artists == ["MORTEN", "ARTBAT"]
    assert m.tracks[1].publisher == ["INSOMNIAC"]
    assert m.album_tags["artist"] == "MORTEN"


def test_save_and_load_roundtrip(tmp_path):
    m = _sample_manifest()
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
    assert any(
        "schema_unsupported" in rec.getMessage().lower() for rec in caplog.records
    )


def test_load_artist_manifest_schema_mismatch_returns_none(tmp_path):
    from tracksplit.manifest import ARTIST_MANIFEST_FILENAME, load_artist_manifest

    (tmp_path / ARTIST_MANIFEST_FILENAME).write_text(
        '{"schema": 999, "artist": "X", "dj_artwork_sha256": "abc"}'
    )
    assert load_artist_manifest(tmp_path) is None


def test_save_album_manifest_is_atomic(tmp_path, monkeypatch):
    """A failure inside the atomic write leaves no partial file behind."""
    from tracksplit.manifest import (
        ALBUM_MANIFEST_FILENAME,
        save_album_manifest,
    )

    album = tmp_path / "album"
    album.mkdir()
    m = _sample_manifest()
    save_album_manifest(album, m)
    content = (album / ALBUM_MANIFEST_FILENAME).read_text()

    import os as _os

    orig_replace = _os.replace

    def _boom(a, b):
        raise OSError("boom")

    monkeypatch.setattr(_os, "replace", _boom)
    with pytest.raises(OSError):
        save_album_manifest(album, m)
    assert (album / ALBUM_MANIFEST_FILENAME).read_text() == content
    leftovers = [
        p.name
        for p in album.iterdir()
        if p.name.startswith(ALBUM_MANIFEST_FILENAME + ".")
    ]
    assert leftovers == []

    monkeypatch.setattr(_os, "replace", orig_replace)


def test_album_manifest_legacy_dict_without_cover_schema_version_defaults_to_zero():
    # A schema-4 manifest dict that omits cover_schema_version should default to 0.
    raw = {
        "schema": MANIFEST_SCHEMA,
        "identity": {
            "source_id": None,
            "audio": {
                "codec_name": "opus",
                "sample_rate": 48000,
                "channels": 2,
                "time_base": "1/48000",
            },
        },
        "source_path": "/x.mkv",
        "resolved_artist_folder": "Artist",
        "resolved_album_folder": "Album",
        "output_format": "flac",
        "codec_mode": "copy",
        "album_tags": {},
        "tracks": [],
        "cover_sha256": "",
        # cover_schema_version deliberately omitted
    }
    m = AlbumManifest.from_dict(raw)
    assert m.cover_schema_version == 0


def test_album_manifest_round_trip_preserves_cover_schema_version():
    from tracksplit.cover import COVER_SCHEMA_VERSION

    m = _sample_manifest()
    roundtrip = AlbumManifest.from_dict(m.to_dict())
    assert roundtrip.cover_schema_version == m.cover_schema_version
    assert m.cover_schema_version == COVER_SCHEMA_VERSION


def test_audio_fingerprint_omits_duration_and_bitrate():
    from tracksplit.manifest import AudioFingerprint

    data = {
        "streams": [
            {
                "codec_type": "audio",
                "codec_name": "opus",
                "sample_rate": "48000",
                "channels": 2,
                "time_base": "1/1000",
                "duration_ts": "N/A",
                "bit_rate": "N/A",
            }
        ]
    }
    fp = AudioFingerprint.from_ffprobe(data)
    assert fp == AudioFingerprint(
        codec_name="opus", sample_rate=48000, channels=2, time_base="1/1000"
    )
    assert not hasattr(fp, "duration_ts")
    assert not hasattr(fp, "bit_rate")


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
                "time_base": "1/48000",
            },
            {"codec_type": "audio", "codec_name": "aac"},  # ignored
        ],
    }
    fp = AudioFingerprint.from_ffprobe(ffprobe)
    assert fp.codec_name == "opus"
    assert fp.sample_rate == 48000
    assert fp.channels == 2
    assert fp.time_base == "1/48000"


def test_audio_fingerprint_handles_missing_optional_fields():
    from tracksplit.manifest import AudioFingerprint

    ffprobe = {
        "streams": [
            {
                "codec_type": "audio",
                "codec_name": "flac",
                "sample_rate": "44100",
                "channels": 2,
                # no time_base
            },
        ],
    }
    fp = AudioFingerprint.from_ffprobe(ffprobe)
    assert fp.codec_name == "flac"
    assert fp.sample_rate == 44100
    assert fp.channels == 2
    assert fp.time_base == ""


def test_audio_fingerprint_raises_when_no_audio_stream():
    from tracksplit.manifest import AudioFingerprint

    ffprobe = {"streams": [{"codec_type": "video", "codec_name": "h264"}]}
    with pytest.raises(ValueError, match="no audio stream"):
        AudioFingerprint.from_ffprobe(ffprobe)


def test_audio_fingerprint_equality():
    from tracksplit.manifest import AudioFingerprint

    a = AudioFingerprint("opus", 48000, 2, "1/48000")
    b = AudioFingerprint("opus", 48000, 2, "1/48000")
    c = AudioFingerprint("opus", 48000, 2, "1/96000")
    assert a == b
    assert a != c


def test_track_entry_roundtrip_and_nfc():
    import unicodedata

    e = TrackEntry(
        index=2,
        filename="02 - A - B.opus",
        start=1.0,
        end=2.0,
        title=unicodedata.normalize("NFD", "Café"),
        artist="A",
        publisher=["LABEL"],
        genre=["Trance"],
        artists=["A", "B"],
        artist_mbids=["m1", "m2"],
    )
    d = e.to_dict()
    assert d["title"] == unicodedata.normalize("NFC", "Café")  # stored NFC
    assert TrackEntry.from_dict(d) == TrackEntry.from_dict(e.to_dict())


def test_source_identity_roundtrip():
    si = SourceIdentity(
        source_id="xfg8qrk",
        audio=AudioFingerprint("opus", 48000, 2, "1/1000"),
    )
    assert SourceIdentity.from_dict(si.to_dict()) == si


def test_manifest_written_with_literal_unicode(tmp_path):
    m = _sample_manifest()
    m.album_tags = {"artist": "Beyoncé"}
    save_album_manifest(tmp_path, m)
    text = (tmp_path / ALBUM_MANIFEST_FILENAME).read_text(encoding="utf-8")
    assert "Beyoncé" in text
    assert "Beyonc\\u00e9" not in text


def test_load_migrates_schema_3_without_discarding(tmp_path):
    v3 = {
        "schema": 3,
        "source": {
            "path": "E:/v/x.mkv",
            "audio": {
                "codec_name": "opus",
                "sample_rate": 48000,
                "channels": 2,
                "duration_ts": 0,
                "time_base": "1/1000",
                "bit_rate": 0,
            },
        },
        "resolved_artist_folder": "MORTEN",
        "resolved_album_folder": "TML 2025",
        "output_format": "opus",
        "codec_mode": "copy",
        "chapters": [
            {
                "index": 2,
                "title": "Culture",
                "start": 172.0,
                "end": 292.0,
                "tags": {"CRATEDIGGER_TRACK_LABEL": "INSOMNIAC"},
            }
        ],
        "tags": {"artist": "MORTEN", "genres": ["Trance"]},
        "track_filenames": ["00 - Intro.opus", "02 - MORTEN & ARTBAT - Culture.opus"],
        "cover_sha256": "abc",
        "intro_min_seconds": 5.0,
        "cover_schema_version": 3,
        "tag_schema_version": 2,
    }
    (tmp_path / ".tracksplit_manifest.json").write_text(json.dumps(v3))
    m = load_album_manifest(tmp_path)
    assert m is not None
    assert m.migrated_from == 3
    assert m.source_path == "E:/v/x.mkv"
    assert m.identity.source_id is None  # not in a v3 manifest
    assert m.identity.audio.codec_name == "opus"
    assert [t.filename for t in m.tracks] == [
        "00 - Intro.opus",
        "02 - MORTEN & ARTBAT - Culture.opus",
    ]
    assert m.album_tags["artist"] == "MORTEN"


def test_migrate_v3_normalizes_first_track_start_to_zero(tmp_path):
    """A schema-3 manifest with no intro track stored the RAW first-chapter
    start (e.g. 1.0s). The actual split slides the first track to 0.0, so the
    migrated first track's start must be normalized to 0.0; otherwise the
    boundary mismatch forces a needless full re-split on the upgrade run.
    Regression for the 0.15.0 first-run resplit bug."""
    v3 = {
        "schema": 3,
        "source": {
            "path": "E:/v/x.mkv",
            "audio": {
                "codec_name": "opus",
                "sample_rate": 48000,
                "channels": 2,
                "duration_ts": 0,
                "time_base": "1/1000",
                "bit_rate": 0,
            },
        },
        "resolved_artist_folder": "Tiesto",
        "resolved_album_folder": "Set 2026",
        "output_format": "opus",
        "codec_mode": "copy",
        "chapters": [
            {"index": 1, "title": "A", "start": 1.0, "end": 76.0, "tags": {}},
            {"index": 2, "title": "B", "start": 76.0, "end": 150.0, "tags": {}},
        ],
        "tags": {"artist": "Tiesto"},
        "track_filenames": ["01 - X - A.opus", "02 - X - B.opus"],
        "cover_sha256": "abc",
        "intro_min_seconds": 5.0,
        "cover_schema_version": 3,
        "tag_schema_version": 2,
    }
    (tmp_path / ".tracksplit_manifest.json").write_text(json.dumps(v3))
    m = load_album_manifest(tmp_path)
    assert m is not None
    # First track normalized to 0.0 (was raw 1.0); others untouched.
    assert m.tracks[0].start == 0.0
    assert m.tracks[0].end == 76.0
    assert m.tracks[1].start == 76.0
    assert len(m.tracks) == 2


def test_migrate_v3_intro_in_track_title_is_not_an_intro_track(tmp_path):
    """The first track's TITLE contains the word "Intro" (e.g. an "Intro Mix")
    but there is NO separate intro file: filename count equals chapter count.
    Intro detection must use the count relationship, not a filename substring;
    otherwise the first track is mistaken for an intro and every track shifts by
    one, forcing a spurious full re-split. Regression for the 0.15.0 prod resplit
    on sets like "... (Roman Messer Intro Mix)"."""
    v3 = {
        "schema": 3,
        "source": {
            "path": "E:/v/x.mkv",
            "audio": {
                "codec_name": "opus",
                "sample_rate": 48000,
                "channels": 2,
                "duration_ts": 0,
                "time_base": "1/1000",
                "bit_rate": 0,
            },
        },
        "resolved_artist_folder": "Roman Messer",
        "resolved_album_folder": "Set 2025",
        "output_format": "opus",
        "codec_mode": "copy",
        "chapters": [
            {
                "index": 1,
                "title": "Judgment Day (Intro Mix)",
                "start": 0.0,
                "end": 164.0,
                "tags": {},
            },
            {"index": 2, "title": "Closer", "start": 164.0, "end": 327.0, "tags": {}},
        ],
        "tags": {"artist": "Roman Messer"},
        "track_filenames": [
            "01 - Adip Kiyoi - Judgment Day (Intro Mix).opus",
            "02 - Roman Messer - Closer.opus",
        ],
        "cover_sha256": "abc",
        "intro_min_seconds": 5.0,
        "cover_schema_version": 3,
        "tag_schema_version": 2,
    }
    (tmp_path / ".tracksplit_manifest.json").write_text(json.dumps(v3))
    m = load_album_manifest(tmp_path)
    assert m is not None
    # Two chapters, two filenames -> no intro, no shift.
    assert len(m.tracks) == 2
    assert m.tracks[0].filename == "01 - Adip Kiyoi - Judgment Day (Intro Mix).opus"
    assert m.tracks[0].start == 0.0 and m.tracks[0].end == 164.0
    assert m.tracks[1].filename == "02 - Roman Messer - Closer.opus"
    assert m.tracks[1].start == 164.0 and m.tracks[1].end == 327.0
