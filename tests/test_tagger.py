from unittest.mock import MagicMock, patch

from tracksplit.models import AlbumMeta, TrackMeta
from tracksplit.tagger import build_tag_dict, tag_ogg, tag_all


def _full_album():
    tracks = [
        TrackMeta(
            number=1,
            title="Intro",
            start=0.0,
            end=60.0,
            publisher="Armada Music",
            genre=["Trance"],
        ),
        TrackMeta(
            number=2,
            title="Main Set",
            start=60.0,
            end=180.0,
            genre=["Progressive Trance"],
        ),
    ]
    return AlbumMeta(
        artist="Armin van Buuren",
        album="Live @ Ultra 2024",
        date="2024-03-22",
        genre=["Trance", "Progressive"],
        festival="Ultra Music Festival",
        stage="Mainstage",
        venue="Bayfront Park",
        comment="Full set recording",
        musicbrainz_artistid="test-mbid-1234",
        tracks=tracks,
    )


def test_build_tag_dict_all_fields():
    album = _full_album()
    track = album.tracks[0]
    tags = build_tag_dict(album, track)

    assert tags["TITLE"] == ["Intro"]
    assert tags["ARTIST"] == ["Armin van Buuren"]
    assert tags["ALBUMARTIST"] == ["Armin van Buuren"]
    assert tags["ALBUM"] == ["Live @ Ultra 2024"]
    assert tags["TRACKNUMBER"] == ["1"]
    assert tags["DISCNUMBER"] == ["1"]
    assert tags["TRACKTOTAL"] == ["2"]
    assert tags["DATE"] == ["2024-03-22"]
    # Track-level genre takes precedence
    assert tags["GENRE"] == ["Trance"]
    assert tags["PUBLISHER"] == ["Armada Music"]
    assert tags["COMMENT"] == ["Full set recording"]
    assert tags["MUSICBRAINZ_ALBUMARTISTID"] == ["test-mbid-1234"]
    assert tags["FESTIVAL"] == ["Ultra Music Festival"]
    assert tags["STAGE"] == ["Mainstage"]
    assert tags["VENUE"] == ["Bayfront Park"]


def test_build_tag_dict_album_genre_fallback():
    """When track has no genre, album genre is used."""
    album = _full_album()
    # Track 2 has its own genre, so clear it to test fallback
    track = TrackMeta(number=3, title="Outro", start=180.0, end=240.0)
    tags = build_tag_dict(album, track)

    assert tags["GENRE"] == ["Trance", "Progressive"]


def test_build_tag_dict_minimal():
    album = AlbumMeta(artist="DJ Test", album="Minimal Set")
    track = TrackMeta(number=1, title="Track 1", start=0.0, end=60.0)
    tags = build_tag_dict(album, track)

    # Required tags present
    assert tags["TITLE"] == ["Track 1"]
    assert tags["ARTIST"] == ["DJ Test"]
    assert tags["ALBUMARTIST"] == ["DJ Test"]
    assert tags["ALBUM"] == ["Minimal Set"]
    assert tags["TRACKNUMBER"] == ["1"]
    assert tags["DISCNUMBER"] == ["1"]

    # Optional tags absent
    for key in (
        "TRACKTOTAL", "DATE", "GENRE", "PUBLISHER", "COMMENT",
        "MUSICBRAINZ_ALBUMARTISTID", "FESTIVAL", "STAGE", "VENUE",
    ):
        assert key not in tags, f"{key} should not be present when empty"


def test_build_tag_dict_tracktotal_from_tracks():
    tracks = [
        TrackMeta(number=i, title=f"Track {i}", start=float(i), end=float(i + 1))
        for i in range(1, 6)
    ]
    album = AlbumMeta(artist="Test", album="Five Tracks", tracks=tracks)
    tags = build_tag_dict(album, tracks[0])

    assert tags["TRACKTOTAL"] == ["5"]


def test_tag_ogg_writes_vorbis_comments():
    """tag_ogg should open, clear, write tags, and save."""
    album = AlbumMeta(artist="DJ Test", album="Test Album")
    track = TrackMeta(number=1, title="Track 1", start=0.0, end=60.0)

    mock_audio = MagicMock()
    with patch("tracksplit.tagger.OggOpus", return_value=mock_audio) as mock_cls:
        tag_ogg("/tmp/track.opus", album, track)

    mock_cls.assert_called_once_with("/tmp/track.opus")
    mock_audio.delete.assert_called_once()
    mock_audio.save.assert_called_once()
    # Check that tags were written
    assert mock_audio.__setitem__.call_count > 0


def test_tag_ogg_embeds_cover():
    """tag_ogg should embed cover as METADATA_BLOCK_PICTURE."""
    album = AlbumMeta(artist="DJ Test", album="Test Album")
    track = TrackMeta(number=1, title="Track 1", start=0.0, end=60.0)

    mock_audio = MagicMock()
    with patch("tracksplit.tagger.OggOpus", return_value=mock_audio):
        tag_ogg("/tmp/track.opus", album, track, cover_data=b"\xff\xd8fake-jpeg")

    # Check METADATA_BLOCK_PICTURE was set
    calls = {c[0][0]: c[0][1] for c in mock_audio.__setitem__.call_args_list}
    assert "METADATA_BLOCK_PICTURE" in calls


def test_tag_all_dispatches_by_extension():
    """tag_all should dispatch to tag_ogg for .opus files and tag_flac for .flac."""
    album = AlbumMeta(
        artist="DJ Test",
        album="Mixed Album",
        tracks=[
            TrackMeta(number=1, title="Flac Track", start=0.0, end=60.0),
            TrackMeta(number=2, title="Ogg Track", start=60.0, end=120.0),
        ],
    )

    with patch("tracksplit.tagger.tag_flac") as mock_flac, \
         patch("tracksplit.tagger.tag_ogg") as mock_ogg:
        tag_all(
            ["/tmp/01 - Flac Track.flac", "/tmp/02 - Opus Track.opus"],
            album,
            cover_data=b"cover",
        )

    mock_flac.assert_called_once()
    mock_ogg.assert_called_once()


# --- MBID policy: no per-track MBID, collab guard ---

def test_no_musicbrainz_artistid_emitted():
    """The per-track MBID key must never be written (regression guard).

    Writing album-artist MBID as per-track MBID caused Lyrion to collapse
    every track to a single contributor row. We never have real per-track
    MBIDs, so the key stays out of the dict entirely.
    """
    album = _full_album()
    tags = build_tag_dict(album, album.tracks[0])
    assert "MUSICBRAINZ_ARTISTID" not in tags


def test_albumartist_mbid_written_for_solo_artist():
    album = _full_album()  # artist="Armin van Buuren", MBID="test-mbid-1234"
    tags = build_tag_dict(album, album.tracks[0])
    assert tags["MUSICBRAINZ_ALBUMARTISTID"] == ["test-mbid-1234"]


def test_albumartist_mbid_suppressed_for_ampersand_collab():
    """'X & Y' album artists have no single-person MBID; don't write one."""
    album = AlbumMeta(
        artist="Armin van Buuren & KI/KI",
        album="AMF 2025 (Two Is One)",
        musicbrainz_artistid="477b8c0c-c5fc-4ad2-b5b2-191f0bf2a9df",
        tracks=[TrackMeta(number=1, title="Track", start=0.0, end=60.0)],
    )
    tags = build_tag_dict(album, album.tracks[0])
    assert "MUSICBRAINZ_ALBUMARTISTID" not in tags


def test_albumartist_mbid_suppressed_for_vs_collab():
    album = AlbumMeta(
        artist="Armin van Buuren vs. Hardwell",
        album="Collab Set",
        musicbrainz_artistid="some-mbid",
        tracks=[TrackMeta(number=1, title="Track", start=0.0, end=60.0)],
    )
    tags = build_tag_dict(album, album.tracks[0])
    assert "MUSICBRAINZ_ALBUMARTISTID" not in tags


def test_albumartist_mbid_suppressed_for_x_collab():
    album = AlbumMeta(
        artist="Martin Garrix x Alesso",
        album="Collab Set",
        musicbrainz_artistid="some-mbid",
        tracks=[TrackMeta(number=1, title="Track", start=0.0, end=60.0)],
    )
    tags = build_tag_dict(album, album.tracks[0])
    assert "MUSICBRAINZ_ALBUMARTISTID" not in tags


def test_collab_guard_does_not_false_positive_on_embedded_letters():
    """Names like 'Axwell', 'deadmau5', 'Eric Prydz' must not trip the guard."""
    for name in ("Axwell", "deadmau5", "Eric Prydz", "Tiësto", "R3HAB"):
        album = AlbumMeta(
            artist=name,
            album="Set",
            musicbrainz_artistid="mbid-abc",
            tracks=[TrackMeta(number=1, title="T", start=0.0, end=60.0)],
        )
        tags = build_tag_dict(album, album.tracks[0])
        assert tags["MUSICBRAINZ_ALBUMARTISTID"] == ["mbid-abc"], f"false positive on {name!r}"


def test_opus_round_trip_preserves_unicode_tags(tmp_path):
    """Write an opus, tag with unicode, read it back, expect exact strings."""
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        import pytest
        pytest.skip("ffmpeg not available")

    opus_path = tmp_path / "test.opus"
    subprocess.run(
        [ffmpeg, "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
         "-t", "0.5", "-c:a", "libopus", "-b:a", "32k",
         str(opus_path), "-y", "-loglevel", "error"],
        check=True,
    )

    album = AlbumMeta(
        artist="Tiësto",
        album="EDC",
        musicbrainz_artistid="mbid-ti",
        tracks=[TrackMeta(number=1, title="Strobe", start=0.0, end=30.0,
                          artist="RÜFÜS DU SOL")],
    )
    from tracksplit.tagger import tag_ogg
    from mutagen.oggopus import OggOpus

    tag_ogg(opus_path, album, album.tracks[0])
    reread = OggOpus(str(opus_path))

    assert reread["ARTIST"] == ["RÜFÜS DU SOL"]
    assert reread["ALBUMARTIST"] == ["Tiësto"]
    assert reread["MUSICBRAINZ_ALBUMARTISTID"] == ["mbid-ti"]
    assert "MUSICBRAINZ_ARTISTID" not in reread


# --- Multi-value ARTISTS / ALBUMARTISTS (Picard convention) ---


def _track(**kw):
    return TrackMeta(number=1, title="t", start=0.0, end=1.0, **kw)


def _album(**kw):
    return AlbumMeta(artist="Armin van Buuren", album="AMF 2025", **kw)


def test_artists_tag_emitted_when_track_has_individuals():
    track = _track(
        artist="Armin van Buuren & JOA",
        artists=["Armin van Buuren", "JOA", "DJ KUBA & NEITAN"],
        artist_mbids=["m-arm", "m-joa", ""],
    )
    tags = build_tag_dict(_album(), track)
    assert tags["ARTIST"] == ["Armin van Buuren & JOA"]
    assert tags["ARTISTS"] == ["Armin van Buuren", "JOA", "DJ KUBA & NEITAN"]
    assert tags["MUSICBRAINZ_ARTISTID"] == ["m-arm", "m-joa", ""]


def test_artists_tag_absent_when_no_individuals():
    track = _track(artist="Armin van Buuren")
    tags = build_tag_dict(_album(), track)
    assert "ARTISTS" not in tags
    assert "MUSICBRAINZ_ARTISTID" not in tags


def test_albumartists_and_multi_albumartistid():
    album = _album(
        albumartists=["Armin van Buuren", "KI/KI"],
        albumartist_mbids=["m-arm", "m-ki"],
    )
    track = _track(artist="x")
    tags = build_tag_dict(album, track)
    assert tags["ALBUMARTIST"] == ["Armin van Buuren"]  # display unchanged from album.artist
    assert tags["ALBUMARTISTS"] == ["Armin van Buuren", "KI/KI"]
    assert tags["MUSICBRAINZ_ALBUMARTISTID"] == ["m-arm", "m-ki"]


def test_albumartists_empty_mbid_slots_preserved():
    album = _album(
        albumartists=["A", "B"],
        albumartist_mbids=["m-a", ""],
    )
    tags = build_tag_dict(album, _track(artist="x"))
    assert tags["MUSICBRAINZ_ALBUMARTISTID"] == ["m-a", ""]


def test_legacy_collab_suppression_only_when_no_mbid_list():
    album = AlbumMeta(
        artist="A & B",
        album="x",
        musicbrainz_artistid="m-single",
    )
    tags = build_tag_dict(album, _track(artist="x"))
    assert "MUSICBRAINZ_ALBUMARTISTID" not in tags


def test_single_artist_single_mbid_legacy_path():
    album = AlbumMeta(
        artist="Armin van Buuren",
        album="x",
        musicbrainz_artistid="m-arm",
    )
    tags = build_tag_dict(album, _track(artist="x"))
    assert tags["MUSICBRAINZ_ALBUMARTISTID"] == ["m-arm"]
