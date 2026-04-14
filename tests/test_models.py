from tracksplit.models import AlbumMeta, Chapter, TrackMeta


def test_chapter_duration():
    ch = Chapter(index=1, title="Track One", start=0.0, end=60.5)
    assert ch.duration == 60.5


def test_chapter_zero_duration():
    ch = Chapter(index=1, title="Marker", start=30.0, end=30.0)
    assert ch.duration == 0.0


def test_track_meta_defaults():
    t = TrackMeta(number=1, title="Song", start=0.0, end=60.0)
    assert t.publisher == ""
    assert t.genre == []


def test_album_meta_artist_folder():
    a = AlbumMeta(artist="Armin van Buuren", album="Test")
    assert a.artist_folder == "Armin van Buuren"


def test_album_meta_artist_folder_empty():
    a = AlbumMeta(artist="", album="Test")
    assert a.artist_folder == "Unknown Artist"


def test_album_meta_album_folder():
    a = AlbumMeta(artist="Test", album="Set @ Fest 2024")
    assert a.album_folder == "Set @ Fest 2024"


def test_album_meta_album_folder_empty():
    a = AlbumMeta(artist="Test", album="")
    assert a.album_folder == "Unknown Album"


def test_chapter_has_tags_dict_default_empty():
    ch = Chapter(index=1, title="x", start=0.0, end=1.0)
    assert ch.tags == {}


def test_chapter_tags_roundtrip():
    ch = Chapter(
        index=1, title="x", start=0.0, end=1.0,
        tags={"PERFORMER": "A & B", "LABEL": "Armada"},
    )
    assert ch.tags["PERFORMER"] == "A & B"


def test_trackmeta_multi_artist_defaults():
    t = TrackMeta(number=1, title="x", start=0.0, end=1.0)
    assert t.artists == []
    assert t.artist_mbids == []


def test_albummeta_albumartists_defaults():
    a = AlbumMeta(artist="X", album="Y")
    assert a.albumartists == []
    assert a.albumartist_mbids == []
