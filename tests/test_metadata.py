"""Tests for tracksplit.metadata module."""
from tracksplit.metadata import (
    strip_label,
    safe_filename,
    parse_filename,
    deduplicate_titles,
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
        "genre": ["Trance", "EDM"],
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
        "genre": ["EDM"],
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
