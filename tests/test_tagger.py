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
    assert tags["MUSICBRAINZ_ARTISTID"] == ["test-mbid-1234"]
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
        "MUSICBRAINZ_ARTISTID", "FESTIVAL", "STAGE", "VENUE",
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
