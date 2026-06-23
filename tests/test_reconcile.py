# tests/test_reconcile.py
from pathlib import Path

from tracksplit.manifest import (
    MANIFEST_SCHEMA,
    AlbumManifest,
    AudioFingerprint,
    SourceIdentity,
    TrackEntry,
)
from tracksplit.models import AlbumMeta, TrackMeta
from tracksplit.reconcile import (
    DesiredAlbum,
    RegenLevel,
    build_desired_album,
    build_identity_index,
    plan_reconciliation,
)

AUDIO = AudioFingerprint("opus", 48000, 2, "1/1000")


def _stored(**over) -> AlbumManifest:
    base: dict = {
        "schema": MANIFEST_SCHEMA,
        "identity": SourceIdentity("xfg8qrk", AUDIO),
        "source_path": "E:/v/x.mkv",
        "resolved_artist_folder": "MORTEN",
        "resolved_album_folder": "TML 2025",
        "output_format": "opus",
        "codec_mode": "copy",
        "album_tags": {"artist": "MORTEN"},
        "tracks": [
            TrackEntry(
                2,
                "02 - A - Culture.opus",
                172.0,
                292.0,
                "Culture",
                artist="A",
                publisher="INSOMNIAC",
            )
        ],
        "cover_sha256": "abc",
        "cover_schema_version": 99,
        "tag_schema_version": 99,
    }
    base.update(over)
    return AlbumManifest(**base)


def _desired(**over) -> DesiredAlbum:
    base: dict = {
        "source_id": "xfg8qrk",
        "audio": AUDIO,
        "source_path": "E:/v/x.mkv",
        "artist_folder": "MORTEN",
        "album_folder": "TML 2025",
        "output_format": "opus",
        "codec_mode": "copy",
        "album_tags": {"artist": "MORTEN"},
        "tracks": [
            TrackEntry(
                2,
                "02 - A - Culture.opus",
                172.0,
                292.0,
                "Culture",
                artist="A",
                publisher="INSOMNIAC",
            )
        ],
        "cover_sha256": "abc",
        "cover_schema_version": 99,
        "tag_schema_version": 99,
    }
    base.update(over)
    return DesiredAlbum(**base)


def test_no_change_is_skip():
    p = plan_reconciliation(_stored(), _desired())
    assert p.level is RegenLevel.SKIP and not p.move and not p.renames and not p.retag


def test_moved_source_path_is_path_refresh_only():
    p = plan_reconciliation(_stored(), _desired(source_path="F:/new/x.mkv"))
    assert p.level is RegenLevel.SKIP and p.path_refresh and not p.retag


def test_folder_change_is_move_plus_retag():
    p = plan_reconciliation(_stored(), _desired(album_folder="TML 2025 (Mainstage)"))
    assert p.move and p.retag and p.level is RegenLevel.RETAG


def test_title_change_is_rename_plus_retag_not_full():
    d = _desired(
        tracks=[
            TrackEntry(
                2,
                "02 - A - Culture (Edit).opus",
                172.0,
                292.0,
                "Culture (Edit)",
                artist="A",
                publisher="INSOMNIAC",
            )
        ]
    )
    p = plan_reconciliation(_stored(), d)
    assert p.level is RegenLevel.RETAG
    assert p.renames == [("02 - A - Culture.opus", "02 - A - Culture (Edit).opus")]
    assert p.retag


def test_label_change_is_retag_only():
    d = _desired(
        tracks=[
            TrackEntry(
                2,
                "02 - A - Culture.opus",
                172.0,
                292.0,
                "Culture",
                artist="A",
                publisher="SPINNIN",
            )
        ]
    )
    p = plan_reconciliation(_stored(), d)
    assert p.level is RegenLevel.RETAG and not p.renames and not p.move


def test_boundary_change_is_full():
    d = _desired(
        tracks=[
            TrackEntry(
                2,
                "02 - A - Culture.opus",
                172.0,
                300.0,
                "Culture",
                artist="A",
                publisher="INSOMNIAC",
            )
        ]
    )
    p = plan_reconciliation(_stored(), d)
    assert p.level is RegenLevel.FULL and p.full_reason == "boundary"


def test_track_count_change_is_full():
    d = _desired(tracks=[])
    assert plan_reconciliation(_stored(), d).level is RegenLevel.FULL


def test_audio_change_is_full():
    assert (
        plan_reconciliation(
            _stored(), _desired(audio=AudioFingerprint("flac", 44100, 2, "1/44100"))
        ).level
        is RegenLevel.FULL
    )


def test_format_or_codec_change_is_full():
    assert (
        plan_reconciliation(_stored(), _desired(output_format="flac")).level
        is RegenLevel.FULL
    )
    assert (
        plan_reconciliation(_stored(), _desired(codec_mode="encode")).level
        is RegenLevel.FULL
    )


def test_nfd_vs_nfc_tag_is_skip():
    import unicodedata

    d = _desired(album_tags={"artist": unicodedata.normalize("NFD", "MORTEN")})
    assert plan_reconciliation(_stored(), d).level is RegenLevel.SKIP


def test_case_only_filename_diff_is_corrective_rename():
    d = _desired(
        tracks=[
            TrackEntry(
                2,
                "02 - a - culture.opus",
                172.0,
                292.0,
                "Culture",
                artist="A",
                publisher="INSOMNIAC",
            )
        ]
    )
    p = plan_reconciliation(_stored(), d)
    assert p.renames == [("02 - A - Culture.opus", "02 - a - culture.opus")]
    assert p.level in (RegenLevel.SKIP, RegenLevel.RETAG)


def test_outdated_schema_versions_force_retag():
    p = plan_reconciliation(_stored(), _desired(tag_schema_version=100))
    assert p.retag and p.level is RegenLevel.RETAG


def test_migrated_manifest_unchanged_is_skip_not_retag():
    # Migrated v3 manifests carry no real per-track tag values; an unchanged
    # album must reconcile to SKIP (trust source), not a blanket retag.
    stored = _stored(
        migrated_from=3,
        tracks=[
            TrackEntry(
                2, "02 - A - Culture.opus", 172.0, 292.0, "Culture"
            )  # no embedded tags
        ],
    )
    p = plan_reconciliation(stored, _desired())
    assert p.level is RegenLevel.SKIP and not p.retag


def test_migrated_manifest_with_renamed_folder_is_move_plus_retag():
    stored = _stored(
        migrated_from=3,
        tracks=[TrackEntry(2, "02 - A - Culture.opus", 172.0, 292.0, "Culture")],
    )
    p = plan_reconciliation(stored, _desired(album_folder="TML 2025 (Mainstage)"))
    assert p.move and p.retag and p.level is RegenLevel.RETAG


def test_migrated_manifest_intro_duration_change_still_full():
    # Even for a migrated manifest (which trusts the source for tags), a genuine
    # intro DURATION change must still force a FULL re-split. The migration
    # normalizes only the first track's START to 0.0 (an invariant); the intro's
    # END still carries its duration and is compared, so a real change is caught.
    stored = _stored(
        migrated_from=3,
        tracks=[
            TrackEntry(0, "00 - Intro.opus", 0.0, 12.0, "Intro"),
            TrackEntry(1, "01 - A - T.opus", 12.0, 200.0, "T"),
        ],
    )
    unchanged = _desired(
        tracks=[
            TrackEntry(0, "00 - Intro.opus", 0.0, 12.0, "Intro"),
            TrackEntry(1, "01 - A - T.opus", 12.0, 200.0, "T"),
        ]
    )
    assert plan_reconciliation(stored, unchanged).level is RegenLevel.SKIP
    # Intro end moves 12.0 -> 15.0 (the intro got longer): boundary change.
    changed = _desired(
        tracks=[
            TrackEntry(0, "00 - Intro.opus", 0.0, 15.0, "Intro"),
            TrackEntry(1, "01 - A - T.opus", 15.0, 200.0, "T"),
        ]
    )
    p = plan_reconciliation(stored, changed)
    assert p.level is RegenLevel.FULL and p.full_reason == "boundary"


def test_index_finds_by_source_id_regardless_of_folder(tmp_path):
    # Two album dirs; one matches by source_id even though folder name differs.
    a = tmp_path / "ArtistA" / "OldName"
    a.mkdir(parents=True)

    def fake_load(d: Path):
        if d == a:
            return AlbumManifest(
                schema=4,
                identity=SourceIdentity("xfg8qrk", AUDIO),
                source_path="x",
                resolved_artist_folder="ArtistA",
                resolved_album_folder="OldName",
                output_format="opus",
                codec_mode="copy",
                album_tags={},
                tracks=[],
                cover_sha256="",
            )
        return None

    idx = build_identity_index(tmp_path, load=fake_load)
    assert idx.lookup("xfg8qrk", AUDIO, []) == a
    assert idx.lookup("nope", AUDIO, []) is None


def test_build_desired_album_pulls_source_id_and_tracks():
    album = AlbumMeta(
        artist="MORTEN",
        album="TML 2025",
        albumartists=["MORTEN"],
        tracks=[
            TrackMeta(2, "Culture", 172.0, 292.0, artist="A", publisher="INSOMNIAC")
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
    d = build_desired_album(
        album=album,
        ffprobe_data=ffprobe,
        tags={"CRATEDIGGER_1001TL_ID": "xfg8qrk", "artist": "MORTEN"},
        artist_folder="MORTEN",
        album_folder="TML 2025",
        output_format="opus",
        codec_mode="copy",
        source_path="E:/v/x.mkv",
        cover_sha256="abc",
        track_filenames=["02 - A - Culture.opus"],
    )
    assert d.source_id == "xfg8qrk"
    assert d.tracks[0].filename == "02 - A - Culture.opus"
    assert d.album_tags["artist"] == "MORTEN"


# ---------------------------------------------------------------------------
# FIX 2: migrated manifests must still compare album-level tags
# ---------------------------------------------------------------------------


def test_migrated_manifest_changed_album_tag_is_retag():
    # A migrated (schema-3) manifest with empty per-track tags but a changed
    # album_tag must reconcile to RETAG, not SKIP.
    stored = _stored(
        migrated_from=3,
        album_tags={"artist": "MORTEN", "festival": "OLD FEST"},
        tracks=[
            TrackEntry(
                2, "02 - A - Culture.opus", 172.0, 292.0, "Culture"
            )  # no embedded per-track tags
        ],
    )
    desired = _desired(album_tags={"artist": "MORTEN", "festival": "NEW FEST"})
    p = plan_reconciliation(stored, desired)
    assert p.level is RegenLevel.RETAG and p.retag, (
        "changed album_tag on migrated manifest must trigger RETAG"
    )


def test_migrated_manifest_unchanged_album_tag_is_skip():
    # An unchanged migrated album must still reconcile to SKIP: the album_tag
    # comparison finds no drift, so trust_source_per_track keeps it quiet.
    stored = _stored(
        migrated_from=3,
        tracks=[
            TrackEntry(
                2, "02 - A - Culture.opus", 172.0, 292.0, "Culture"
            )  # no embedded per-track tags; album_tags match _desired() default
        ],
    )
    p = plan_reconciliation(stored, _desired())
    assert p.level is RegenLevel.SKIP and not p.retag, (
        "unchanged migrated manifest must still reconcile to SKIP"
    )
