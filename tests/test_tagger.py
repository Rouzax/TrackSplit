import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from mutagen.flac import FLAC, Picture

from tracksplit.models import AlbumMeta, TrackMeta
from tracksplit.tagger import build_tag_dict, tag_flac, tag_ogg, tag_all


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
        albumartists=["Armin van Buuren"],
        albumartist_mbids=["test-mbid-1234"],
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


def test_albumartist_mbid_omitted_for_synth_collab_with_empty_mbids():
    """Collab display with no cache hit lands a single-element albumartists
    list whose only MBID slot is empty; tagger omits the tag rather than
    writing a row of empty strings (old _is_collab_artist behavior)."""
    album = AlbumMeta(
        artist="Armin van Buuren & KI/KI",
        album="AMF 2025 (Two Is One)",
        albumartists=["Armin van Buuren & KI/KI"],
        albumartist_mbids=[""],
        tracks=[TrackMeta(number=1, title="Track", start=0.0, end=60.0)],
    )
    tags = build_tag_dict(album, album.tracks[0])
    assert "MUSICBRAINZ_ALBUMARTISTID" not in tags


def test_solo_artist_mbid_written_via_albumartists_list():
    """Single-element albumartists list with an MBID writes the tag."""
    album = AlbumMeta(
        artist="deadmau5",
        album="Set",
        albumartists=["deadmau5"],
        albumartist_mbids=["mbid-abc"],
        tracks=[TrackMeta(number=1, title="T", start=0.0, end=60.0)],
    )
    tags = build_tag_dict(album, album.tracks[0])
    assert tags["MUSICBRAINZ_ALBUMARTISTID"] == ["mbid-abc"]


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
        albumartists=["Tiësto"],
        albumartist_mbids=["mbid-ti"],
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


def test_all_empty_track_mbids_omit_tag():
    track = _track(artist="A & B", artists=["A", "B"], artist_mbids=["", ""])
    tags = build_tag_dict(_album(), track)
    assert tags["ARTISTS"] == ["A", "B"]
    assert "MUSICBRAINZ_ARTISTID" not in tags


def test_all_empty_albumartist_mbids_omit_tag():
    # ALBUMARTISTS still emitted (individuals matter), but
    # MUSICBRAINZ_ALBUMARTISTID is omitted rather than written as [""].
    album = _album(albumartists=["AFROJACK"], albumartist_mbids=[""])
    tags = build_tag_dict(album, _track(artist="x"))
    assert tags["ALBUMARTISTS"] == ["AFROJACK"]
    assert "MUSICBRAINZ_ALBUMARTISTID" not in tags


def _make_silent_flac(path: Path, duration: float = 0.5) -> None:
    """Create a tiny silent FLAC at ``path`` via ffmpeg."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t", str(duration), "-c:a", "flac",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_multi_artist_tags_survive_flac_roundtrip(tmp_path):
    flac_path = tmp_path / "test.flac"
    _make_silent_flac(flac_path)

    album = AlbumMeta(
        artist="Armin van Buuren & KI/KI",
        album="AMF 2025",
        albumartists=["Armin van Buuren", "KI/KI"],
        albumartist_mbids=["m-arm", "m-ki"],
    )
    track = TrackMeta(
        number=1, title="t", start=0.0, end=1.0,
        artist="A & B",
        artists=["A", "B", "C"],
        artist_mbids=["m-a", "", "m-c"],
    )
    tag_flac(flac_path, album, track)

    audio = FLAC(flac_path)
    assert list(audio["ARTISTS"]) == ["A", "B", "C"]
    assert list(audio["MUSICBRAINZ_ARTISTID"]) == ["m-a", "", "m-c"]
    assert list(audio["ALBUMARTISTS"]) == ["Armin van Buuren", "KI/KI"]
    assert list(audio["MUSICBRAINZ_ALBUMARTISTID"]) == ["m-arm", "m-ki"]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_replace_cover_only_flac_preserves_tags(tmp_path):
    flac_path = tmp_path / "test.flac"
    _make_silent_flac(flac_path)

    # Seed with tags and an initial picture so we can confirm
    # only the picture is replaced, not the tags.
    audio = FLAC(flac_path)
    audio["artist"] = ["Original Artist"]
    audio["title"] = ["Original Title"]
    initial_pic = Picture()
    initial_pic.type = 3
    initial_pic.mime = "image/jpeg"
    initial_pic.data = b"old-cover-bytes"
    audio.add_picture(initial_pic)
    audio.save()

    new_cover = b"\xff\xd8\xff\xe0new-cover-bytes"
    from tracksplit.tagger import replace_cover_only
    replace_cover_only(flac_path, new_cover)

    reread = FLAC(flac_path)
    assert reread["artist"] == ["Original Artist"]
    assert reread["title"] == ["Original Title"]
    assert len(reread.pictures) == 1
    assert reread.pictures[0].data == new_cover
    assert reread.pictures[0].type == 3
    assert reread.pictures[0].mime == "image/jpeg"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_replace_cover_only_opus_preserves_tags(tmp_path):
    opus_path = tmp_path / "test.opus"
    subprocess.run(
        ["ffmpeg", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
         "-t", "0.5", "-c:a", "libopus", "-b:a", "32k",
         str(opus_path), "-y", "-loglevel", "error"],
        check=True,
    )

    # Seed with tags
    from mutagen.oggopus import OggOpus
    audio = OggOpus(str(opus_path))
    audio["artist"] = ["Original Artist"]
    audio["title"] = ["Original Title"]
    audio.save()

    new_cover = b"\xff\xd8\xff\xe0new-cover-bytes"
    from tracksplit.tagger import replace_cover_only
    replace_cover_only(opus_path, new_cover)

    reread = OggOpus(str(opus_path))
    assert reread["artist"] == ["Original Artist"]
    assert reread["title"] == ["Original Title"]
    # Opus stores pics as base64 METADATA_BLOCK_PICTURE
    key_lower = {k.lower() for k in reread.keys()}
    assert "metadata_block_picture" in key_lower


# --- tag-diff DEBUG logging ---

@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_tag_flac_logs_diff_all_adds_on_fresh_file(tmp_path, caplog):
    """Fresh FLAC has only seeded encoder tags; tag_flac should report
    mostly adds with deltas reflected in the DEBUG line."""
    import logging
    flac_path = tmp_path / "test.flac"
    _make_silent_flac(flac_path)

    album = _full_album()
    track = album.tracks[0]
    with caplog.at_level(logging.DEBUG, logger="tracksplit.tagger"):
        tag_flac(flac_path, album, track)
    joined = "\n".join(r.message for r in caplog.records)
    assert "Tags for test.flac" in joined
    # Format: "Tags for X: +N -M ~K"
    import re
    m = re.search(r"Tags for test\.flac: \+(\d+) -(\d+) ~(\d+)", joined)
    assert m is not None, joined
    added, removed, changed = int(m.group(1)), int(m.group(2)), int(m.group(3))
    # Fresh file has few or no pre-existing tags; build_tag_dict emits many.
    assert added >= 5


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_tag_flac_logs_diff_changes_and_additions(tmp_path, caplog):
    """Seed the FLAC with tags that overlap the next write's tags, then
    retag: the DEBUG diff counts ~changed for overlapping keys with new
    values and +added for the rest."""
    import logging
    flac_path = tmp_path / "test.flac"
    _make_silent_flac(flac_path)

    # Seed with ARTIST=Old (will be changed) and TITLE=Original (will be changed)
    audio = FLAC(flac_path)
    audio["ARTIST"] = ["Old Artist"]
    audio["TITLE"] = ["Original"]
    audio["ALBUM"] = ["Old Album"]
    audio.save()

    album = _full_album()
    track = album.tracks[0]  # ARTIST=Armin van Buuren, TITLE=Intro, ALBUM=Live @ Ultra 2024
    with caplog.at_level(logging.DEBUG, logger="tracksplit.tagger"):
        tag_flac(flac_path, album, track)
    joined = "\n".join(r.message for r in caplog.records)
    import re
    m = re.search(r"Tags for test\.flac: \+(\d+) -(\d+) ~(\d+)", joined)
    assert m is not None, joined
    added, removed, changed = int(m.group(1)), int(m.group(2)), int(m.group(3))
    # ARTIST, TITLE, ALBUM all change from seeded values to the new ones
    assert changed >= 3


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_tag_all_logs_warning_on_mutagen_error(tmp_path, caplog):
    """If tag_flac raises (corrupted file), tag_all logs WARNING naming
    the failing file before propagating. Preserves pipeline behaviour
    (exception is re-raised) but leaves a trail in the rotating log."""
    import logging
    broken = tmp_path / "broken.flac"
    broken.write_bytes(b"not a flac file")

    album = _full_album()
    with caplog.at_level(logging.WARNING, logger="tracksplit.tagger"):
        with pytest.raises(Exception):
            tag_all([broken], album)
    joined = "\n".join(r.message for r in caplog.records if r.levelno >= logging.WARNING)
    assert "broken.flac" in joined


def test_count_tag_deltas_none_existing():
    """_count_tag_deltas with existing=None counts every new tag as added."""
    from tracksplit.tagger import _count_tag_deltas
    new_tags = {"ARTIST": ["X"], "TITLE": ["Y"], "ALBUM": ["Z"]}
    assert _count_tag_deltas(None, new_tags) == (3, 0, 0)


def test_count_tag_deltas_empty_existing_dict():
    """_count_tag_deltas with an empty dict (not None) also counts all as added."""
    from tracksplit.tagger import _count_tag_deltas
    new_tags = {"ARTIST": ["X"], "TITLE": ["Y"]}
    assert _count_tag_deltas({}, new_tags) == (2, 0, 0)


def test_count_tag_deltas_case_insensitive():
    """Vorbis key comparison folds case, so 'artist' in existing and
    'ARTIST' in new with equal values is a no-op."""
    from tracksplit.tagger import _count_tag_deltas
    existing = {"artist": ["X"], "title": ["Y"]}
    new_tags = {"ARTIST": ["X"], "TITLE": ["Y"]}
    assert _count_tag_deltas(existing, new_tags) == (0, 0, 0)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_tag_flac_no_debug_on_no_op_retag(tmp_path, caplog):
    """Retagging a file with the exact same album+track emits no diff DEBUG
    line, keeping the rotating log quiet on idempotent re-runs."""
    import logging
    flac_path = tmp_path / "test.flac"
    _make_silent_flac(flac_path)

    album = _full_album()
    track = album.tracks[0]
    # First tag-write: pre-existing encoder tags, expect a DEBUG.
    tag_flac(flac_path, album, track)
    # Second tag-write with the same metadata: should be a no-op diff.
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="tracksplit.tagger"):
        tag_flac(flac_path, album, track)
    joined = "\n".join(r.message for r in caplog.records)
    assert "Tags for test.flac" not in joined


def _make_silent_opus(path: Path, duration: float = 0.2) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-t", str(duration), "-c:a", "libopus", "-b:a", "64k",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_tag_ogg_logs_diff(tmp_path, caplog):
    """tag_ogg emits the same 'Tags for X: +N -M ~K' DEBUG line as tag_flac."""
    import logging
    opus_path = tmp_path / "test.opus"
    _make_silent_opus(opus_path)

    album = _full_album()
    track = album.tracks[0]
    with caplog.at_level(logging.DEBUG, logger="tracksplit.tagger"):
        tag_ogg(opus_path, album, track)
    joined = "\n".join(r.message for r in caplog.records)
    assert "Tags for test.opus" in joined
    import re
    m = re.search(r"Tags for test\.opus: \+(\d+) -(\d+) ~(\d+)", joined)
    assert m is not None, joined
    added = int(m.group(1))
    assert added >= 5
