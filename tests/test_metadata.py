"""Tests for tracksplit.metadata module."""
from tracksplit.metadata import (
    strip_label,
    safe_filename,
    parse_filename,
    deduplicate_titles,
    split_track_artist,
    build_album_meta,
)
from tracksplit.models import Chapter


# --- strip_label ---

def test_strip_label_with_label():
    title, label = strip_label("Track Title [Armada Music]")
    assert title == "Track Title"
    assert label == "Armada Music"


def test_strip_label_without_label():
    title, label = strip_label("Track Title")
    assert title == "Track Title"
    assert label == ""


def test_strip_label_with_parens_and_label():
    title, label = strip_label("Track Title (Remix) [Spinnin Records]")
    assert title == "Track Title (Remix)"
    assert label == "Spinnin Records"


def test_strip_label_with_parens_no_label():
    title, label = strip_label("Track Title (Extended Mix)")
    assert title == "Track Title (Extended Mix)"
    assert label == ""


def test_strip_label_brackets_in_middle():
    """Brackets not at end should not be stripped."""
    title, label = strip_label("[Label] Track Title")
    assert title == "[Label] Track Title"
    assert label == ""


# --- safe_filename ---

def test_safe_filename_illegal_chars():
    result = safe_filename('Track: "Live" <2024> | Mix?')
    assert ":" not in result
    assert '"' not in result
    assert "<" not in result
    assert ">" not in result
    assert "|" not in result
    assert "?" not in result


def test_safe_filename_unicode_slashes():
    # U+2044 FRACTION SLASH, U+2215 DIVISION SLASH, U+FF0F FULLWIDTH SOLIDUS
    result = safe_filename("Artist\u2044Name\u2215Here\uff0fNow")
    assert "\u2044" not in result
    assert "\u2215" not in result
    assert "\uff0f" not in result


def test_safe_filename_max_length():
    long_name = "A" * 300
    result = safe_filename(long_name)
    assert len(result) <= 200


def test_safe_filename_whitespace_collapse():
    result = safe_filename("Track   Title   Here")
    assert result == "Track Title Here"


def test_safe_filename_trailing_dots_spaces():
    result = safe_filename("Track Title...")
    assert not result.endswith(".")
    result2 = safe_filename("Track Title   ")
    assert not result2.endswith(" ")


def test_safe_filename_control_chars():
    result = safe_filename("Track\x00Title\x1f")
    assert "\x00" not in result
    assert "\x1f" not in result


# --- parse_filename ---

def test_parse_filename_full_pattern():
    artist, year = parse_filename("2024 - Armin van Buuren - Tomorrowland")
    assert artist == "Armin van Buuren"
    assert year == "2024"


def test_parse_filename_no_year():
    artist, year = parse_filename("Armin van Buuren - Tomorrowland")
    assert artist == "Armin van Buuren"
    assert year == ""


def test_parse_filename_no_match():
    artist, year = parse_filename("RandomFilename")
    assert artist == ""
    assert year == ""


# --- split_track_artist ---


def test_split_track_artist_normal():
    artist, title = split_track_artist("Fred again.. & Jamie T - Lights Burn Dimmer")
    assert artist == "Fred again.. & Jamie T"
    assert title == "Lights Burn Dimmer"


def test_split_track_artist_with_vs():
    artist, title = split_track_artist(
        "Public Domain vs. Maddix - Operation Blade vs. Receive Life"
    )
    assert artist == "Public Domain vs. Maddix"
    assert title == "Operation Blade vs. Receive Life"


def test_split_track_artist_with_ft():
    artist, title = split_track_artist("Tiësto ft. Tegan & Sara - Feel It In My Bones")
    assert artist == "Tiësto ft. Tegan & Sara"
    assert title == "Feel It In My Bones"


def test_split_track_artist_no_separator():
    artist, title = split_track_artist("Just A Title")
    assert artist == ""
    assert title == "Just A Title"


def test_split_track_artist_x_connector():
    artist, title = split_track_artist(
        "PARISI x Sebastian Ingrosso x Steve Angello - U Ok?"
    )
    assert artist == "PARISI x Sebastian Ingrosso x Steve Angello"
    assert title == "U Ok?"


# --- deduplicate_titles ---

def test_deduplicate_titles_no_dupes():
    titles = ["Track A", "Track B", "Track C"]
    result = deduplicate_titles(titles)
    assert result == ["Track A", "Track B", "Track C"]


def test_deduplicate_titles_with_dupes():
    titles = ["ID", "Track B", "ID"]
    result = deduplicate_titles(titles)
    assert result == ["ID (01)", "Track B", "ID (03)"]


def test_deduplicate_titles_three_dupes():
    titles = ["ID", "ID", "Track C", "ID"]
    result = deduplicate_titles(titles)
    assert result == ["ID (01)", "ID (02)", "Track C", "ID (04)"]


# --- build_album_meta ---

def _make_chapters(titles):
    chapters = []
    for i, t in enumerate(titles):
        chapters.append(Chapter(index=i, title=t, start=float(i * 60), end=float((i + 1) * 60)))
    return chapters


def test_build_album_meta_tier2_with_stage():
    tags = {
        "artist": "Armin van Buuren",
        "festival": "Tomorrowland",
        "date": "2024-07-21",
        "stage": "Mainstage",
        "genres": ["Trance", "EDM"],
    }
    chapters = _make_chapters(["Track A [Armada]", "Track B"])
    meta = build_album_meta(tags, chapters, "ignored_stem", tier=2)
    assert meta.artist == "Armin van Buuren"
    assert meta.album == "Armin van Buuren @ Tomorrowland 2024 (Mainstage)"
    assert meta.date == "2024-07-21"
    assert meta.genre == ["Trance", "EDM"]
    assert len(meta.tracks) == 2
    assert meta.tracks[0].title == "Track A"
    assert meta.tracks[0].publisher == "Armada"
    assert meta.tracks[1].publisher == ""
    # Genre applied to all tracks
    assert meta.tracks[0].genre == ["Trance", "EDM"]
    assert meta.tracks[1].genre == ["Trance", "EDM"]


def test_build_album_meta_tier2_without_stage():
    tags = {
        "artist": "Hardwell",
        "festival": "Ultra",
        "date": "2023-03-25",
        "genres": ["EDM"],
    }
    chapters = _make_chapters(["Track A"])
    meta = build_album_meta(tags, chapters, "ignored", tier=2)
    assert meta.album == "Hardwell @ Ultra 2023"


def test_build_album_meta_tier1():
    tags = {}
    chapters = _make_chapters(["Track A [Label]", "Track B"])
    meta = build_album_meta(tags, chapters, "2024 - Armin van Buuren - Tomorrowland", tier=1)
    assert meta.artist == "Armin van Buuren"
    assert meta.album == "2024 - Armin van Buuren - Tomorrowland"
    assert meta.date == "2024"
    assert len(meta.tracks) == 2
    assert meta.tracks[0].publisher == "Label"


def test_build_album_meta_tier1_no_year():
    tags = {}
    chapters = _make_chapters(["Track A"])
    meta = build_album_meta(tags, chapters, "Armin van Buuren - Tomorrowland", tier=1)
    assert meta.artist == "Armin van Buuren"
    assert meta.date == ""


def test_build_album_meta_deduplicates_titles():
    tags = {
        "artist": "Test",
        "festival": "Fest",
        "date": "2024-01-01",
    }
    chapters = _make_chapters(["ID", "Track B", "ID"])
    meta = build_album_meta(tags, chapters, "", tier=2)
    assert meta.tracks[0].title == "ID (01)"
    assert meta.tracks[1].title == "Track B"
    assert meta.tracks[2].title == "ID (03)"


def test_build_album_meta_splits_track_artists():
    tags = {
        "artist": "Tiësto",
        "festival": "EDC",
        "date": "2024-05-18",
        "genres": ["Trance"],
    }
    chapters = _make_chapters([
        "Fred again.. & Jamie T - Lights Burn Dimmer [Atlantic]",
        "Tiësto - Adagio For Strings [Magik Muzik]",
        "ID",  # no artist separator
    ])
    meta = build_album_meta(tags, chapters, "", tier=2)
    assert meta.tracks[0].artist == "Fred again.. & Jamie T"
    assert meta.tracks[0].title == "Lights Burn Dimmer"
    assert meta.tracks[0].publisher == "Atlantic"
    assert meta.tracks[1].artist == "Tiësto"
    assert meta.tracks[1].title == "Adagio For Strings"
    assert meta.tracks[2].artist == ""
    assert meta.tracks[2].title == "ID"


def test_build_album_meta_propagates_fields():
    """Verify festival, stage, venue, comment, mbid are passed through."""
    tags = {
        "artist": "DJ Test",
        "festival": "Tomorrowland",
        "date": "2024-07-21",
        "genres": ["Trance"],
        "stage": "Mainstage",
        "venue": "Boom",
        "comment": "https://1001tl.com/abc",
        "musicbrainz_artistid": "uuid-123",
    }
    chapters = _make_chapters(["Track A"])
    meta = build_album_meta(tags, chapters, "", tier=2)
    assert meta.festival == "Tomorrowland"
    assert meta.stage == "Mainstage"
    assert meta.venue == "Boom"
    assert meta.comment == "https://1001tl.com/abc"
    assert meta.musicbrainz_artistid == "uuid-123"


def test_probe_to_metadata_to_tagger_contract():
    """Integration: verify data flows correctly across module boundaries."""
    from tracksplit.probe import parse_tags
    from tracksplit.tagger import build_tag_dict

    # Simulate ffprobe data with CrateDigger tags
    ffprobe_data = {
        "format": {
            "tags": {
                "ARTIST": "Martin Garrix",
                "CRATEDIGGER_1001TL_FESTIVAL": "Tomorrowland",
                "CRATEDIGGER_1001TL_DATE": "2024-07-21",
                "CRATEDIGGER_1001TL_GENRES": "House|Techno",
                "CRATEDIGGER_1001TL_STAGE": "Mainstage",
                "CRATEDIGGER_1001TL_VENUE": "Boom",
                "CRATEDIGGER_1001TL_URL": "https://1001tl.com/abc",
                "CRATEDIGGER_MBID": "uuid-456",
            }
        }
    }
    tags = parse_tags(ffprobe_data)
    chapters = _make_chapters(["Animals [Spinnin]", "Ocean"])
    meta = build_album_meta(tags, chapters, "", tier=2)
    tag_dict = build_tag_dict(meta, meta.tracks[0])

    assert tag_dict["ARTIST"] == ["Martin Garrix"]
    assert tag_dict["ALBUM"] == ["Martin Garrix @ Tomorrowland 2024 (Mainstage)"]
    assert tag_dict["GENRE"] == ["House", "Techno"]
    assert tag_dict["FESTIVAL"] == ["Tomorrowland"]
    assert tag_dict["STAGE"] == ["Mainstage"]
    assert tag_dict["VENUE"] == ["Boom"]
    assert tag_dict["COMMENT"] == ["https://1001tl.com/abc"]
    assert tag_dict["MUSICBRAINZ_ARTISTID"] == ["uuid-456"]
    assert tag_dict["PUBLISHER"] == ["Spinnin"]
    assert tag_dict["TITLE"] == ["Animals"]
