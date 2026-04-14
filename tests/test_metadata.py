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
    assert meta.album == "Tomorrowland 2024 (Mainstage)"
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
    assert meta.album == "Ultra 2023"


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
    """Verify festival, stage, venue, comment are passed through."""
    tags = {
        "artist": "DJ Test",
        "festival": "Tomorrowland",
        "date": "2024-07-21",
        "genres": ["Trance"],
        "stage": "Mainstage",
        "venue": "Boom",
        "comment": "https://1001tl.com/abc",
    }
    chapters = _make_chapters(["Track A"])
    meta = build_album_meta(tags, chapters, "", tier=2)
    assert meta.festival == "Tomorrowland"
    assert meta.stage == "Mainstage"
    assert meta.venue == "Boom"
    assert meta.comment == "https://1001tl.com/abc"


def test_build_album_meta_tier2_no_festival():
    """Tier 2 with missing festival should not produce 'Artist @'."""
    tags = {
        "artist": "DJ Test",
        "festival": "",
        "date": "2024",
        "stage": "",
        "venue": "",
        "genres": [],
        "comment": "",
        "cratedigger": True,
    }
    chapters = [Chapter(index=1, title="Track 1", start=0.0, end=60.0)]
    album = build_album_meta(tags, chapters, "fallback_stem", tier=2)
    assert "@" not in album.album


def test_build_album_meta_tier2_venue_no_date_year_from_filename():
    """Tier 2 with venue but no CRATEDIGGER date: year extracted from filename.

    Also verifies B2B disambiguation: when ALBUMARTIST_DISPLAY is missing but
    albumartists has 2+ entries, the artist folder uses the joined names so
    a B2B set does not collide with a solo set at the same venue + year.
    """
    tags = {
        "artist": "Martin Garrix",
        "festival": "",
        "date": "",
        "stage": "",
        "venue": "Red Rocks Amphitheatre",
        "genres": [],
        "albumartists": ["Martin Garrix", "Alesso"],
        "albumartist_mbids": [],
    }
    chapters = _make_chapters(["Track 1"])
    meta = build_album_meta(
        tags, chapters, "2025 - Martin Garrix & Alesso - Red Rocks", tier=2
    )
    assert meta.album == "Red Rocks Amphitheatre 2025"
    assert meta.artist == "Martin Garrix & Alesso"


def test_build_album_meta_tier2_stage_contains_date_no_year_appended():
    """Tier 2 with stage that already contains the year: year not duplicated."""
    tags = {
        "artist": "FISHER",
        "festival": "",
        "date": "2026-01-31",
        "stage": "Bay Oval Park, New Zealand 2026-01-31",
        "venue": "",
        "genres": [],
    }
    chapters = _make_chapters(["Track 1"])
    meta = build_album_meta(
        tags, chapters, "2026 - FISHER [Bay Oval Park, New Zealand 2026-01-31]", tier=2
    )
    assert meta.album == "Bay Oval Park, New Zealand 2026-01-31"


def test_build_album_meta_tier2_venue_with_date_tag():
    """Tier 2 with venue and CRATEDIGGER date: year comes from date tag."""
    tags = {
        "artist": "Some DJ",
        "festival": "",
        "date": "2024-06-15",
        "stage": "",
        "venue": "Madison Square Garden",
        "genres": [],
    }
    chapters = _make_chapters(["Track 1"])
    meta = build_album_meta(tags, chapters, "2024 - Some DJ - MSG", tier=2)
    assert meta.album == "Madison Square Garden 2024"


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
                "CRATEDIGGER_1001TL_ARTISTS": "Martin Garrix",
                "CRATEDIGGER_ALBUMARTIST_MBIDS": "uuid-456",
            }
        }
    }
    tags = parse_tags(ffprobe_data)
    chapters = _make_chapters(["Animals [Spinnin]", "Ocean"])
    meta = build_album_meta(tags, chapters, "", tier=2)
    tag_dict = build_tag_dict(meta, meta.tracks[0])

    assert tag_dict["ARTIST"] == ["Martin Garrix"]
    assert tag_dict["ALBUM"] == ["Tomorrowland 2024 (Mainstage)"]
    assert tag_dict["GENRE"] == ["House", "Techno"]
    assert tag_dict["FESTIVAL"] == ["Tomorrowland"]
    assert tag_dict["STAGE"] == ["Mainstage"]
    assert tag_dict["VENUE"] == ["Boom"]
    assert tag_dict["COMMENT"] == ["https://1001tl.com/abc"]
    assert tag_dict["ALBUMARTISTS"] == ["Martin Garrix"]
    assert tag_dict["MUSICBRAINZ_ALBUMARTISTID"] == ["uuid-456"]
    assert tag_dict["PUBLISHER"] == ["Spinnin"]
    assert tag_dict["TITLE"] == ["Animals"]


def test_tier1_solo_synthesizes_albumartists_and_fills_mbid_from_cache():
    """Tier-1 MKV (no CrateDigger file tags) synthesizes a single-element
    ``albumartists`` from ``artist`` and fills the MBID from mbid_cache."""
    from tracksplit.cratedigger import CrateDiggerConfig

    cfg = CrateDiggerConfig(mbid_cache={"deadmau5": "cached-uuid"})
    # Tier-1 derives artist from the filename stem.
    chapters = [Chapter(index=1, title="Strobe", start=0.0, end=60.0)]
    meta = build_album_meta({}, chapters, "2024 - deadmau5 - EDC", tier=1, cd_config=cfg)
    assert meta.artist == "deadmau5"
    assert meta.albumartists == ["deadmau5"]
    assert meta.albumartist_mbids == ["cached-uuid"]


# --- Per-track artist case normalization (defense-in-depth) ---

def test_track_artist_case_normalized_uppercase_chapter():
    """Chapter 'AFROJACK - ID' with album ARTIST 'Afrojack' → normalized."""
    tags = {"artist": "Afrojack", "festival": "EDC", "date": "2025-05-17"}
    chapters = _make_chapters(["AFROJACK - ID", "AFROJACK - Bringin It Back"])
    meta = build_album_meta(tags, chapters, "", tier=2)
    assert meta.tracks[0].artist == "Afrojack"
    assert meta.tracks[1].artist == "Afrojack"


def test_track_artist_case_normalized_lowercase_chapter():
    """Chapter 'deadmau5 - Strobe' with album ARTIST 'Deadmau5' → normalized."""
    tags = {"artist": "Deadmau5", "festival": "Tomorrowland Brasil", "date": "2025"}
    chapters = _make_chapters(["deadmau5 - Strobe"])
    meta = build_album_meta(tags, chapters, "", tier=2)
    assert meta.tracks[0].artist == "Deadmau5"


def test_track_artist_preserved_when_not_whole_match():
    """Multi-artist strings containing the album artist stay as-is."""
    tags = {"artist": "Afrojack", "festival": "EDC", "date": "2025-05-17"}
    chapters = _make_chapters([
        "AFROJACK & Steve Aoki ft. Miss Palmer - No Beef",
        "AFROJACK & Martin Garrix - Turn Up The Speakers",
    ])
    meta = build_album_meta(tags, chapters, "", tier=2)
    assert meta.tracks[0].artist == "AFROJACK & Steve Aoki ft. Miss Palmer"
    assert meta.tracks[1].artist == "AFROJACK & Martin Garrix"


def test_track_artist_empty_when_chapter_has_no_separator():
    """Chapter 'Intro' (no ' - ') → track.artist stays empty, falls back later."""
    tags = {"artist": "Tiësto", "festival": "EDC", "date": "2025"}
    chapters = _make_chapters(["Intro", "ID"])
    meta = build_album_meta(tags, chapters, "", tier=2)
    assert meta.tracks[0].artist == ""
    assert meta.tracks[1].artist == ""


def test_unicode_artist_preserved_through_build_album_meta():
    """Diacritics in artist names must survive the pipeline untouched."""
    tags = {"artist": "Tiësto", "festival": "EDC", "date": "2025-05-17"}
    chapters = _make_chapters([
        "RÜFÜS DU SOL - Innerbloom",
        "Kölsch - Grey",
        "Amél - Birds Of A Feather",
    ])
    meta = build_album_meta(tags, chapters, "", tier=2)
    assert meta.artist == "Tiësto"
    assert meta.tracks[0].artist == "RÜFÜS DU SOL"
    assert meta.tracks[1].artist == "Kölsch"
    assert meta.tracks[2].artist == "Amél"
    assert meta.tracks[2].title == "Birds Of A Feather"


# --- Structured chapter tags (multi-artist) ---

from tracksplit.cratedigger import CrateDiggerConfig


def _structured_chapter(start, end, title_full, structured):
    """Build a Chapter with both a legacy title and a structured tag dict."""
    return Chapter(index=1, title=title_full, start=start, end=end, tags=structured)


def test_structured_chapter_tags_drive_track_fields():
    tags = {
        "artist": "Armin van Buuren",
        "festival": "AMF",
        "date": "2025-10-25",
        "genres": ["Trance"],
    }
    chapters = [
        _structured_chapter(
            0.0, 60.0,
            "Armin van Buuren & Alle Farben ft. ROSY - Lost In Time [ARMADA]",
            {
                "TITLE": "Lost In Time",
                "PERFORMER": "Armin van Buuren & Alle Farben ft. ROSY",
                "PERFORMER_NAMES": "Armin van Buuren|Alle Farben",
                "MUSICBRAINZ_ARTISTIDS": "mbid-arm|mbid-af",
                "LABEL": "ARMADA",
                "GENRE": "Trance",
            },
        ),
    ]
    album = build_album_meta(tags, chapters, "stem", tier=2)
    t = album.tracks[0]
    assert t.title == "Lost In Time"
    assert t.artist == "Armin van Buuren & Alle Farben ft. ROSY"
    assert t.artists == ["Armin van Buuren", "Alle Farben"]
    assert t.artist_mbids == ["mbid-arm", "mbid-af"]
    assert t.publisher == "ARMADA"
    assert t.genre == ["Trance"]


def test_missing_per_artist_mbids_filled_from_cache():
    cfg = CrateDiggerConfig(mbid_cache={"JOA": "mbid-joa"})
    tags = {"artist": "Armin van Buuren"}
    chapters = [
        _structured_chapter(
            0.0, 60.0, "Armin van Buuren & JOA - Heavy",
            {
                "TITLE": "Heavy",
                "PERFORMER": "Armin van Buuren & JOA",
                "PERFORMER_NAMES": "Armin van Buuren|JOA",
                "MUSICBRAINZ_ARTISTIDS": "mbid-arm|",
            },
        ),
    ]
    album = build_album_meta(tags, chapters, "stem", tier=2, cd_config=cfg)
    assert album.tracks[0].artist_mbids == ["mbid-arm", "mbid-joa"]


def test_remixer_included_in_artists_but_not_display():
    tags = {"artist": "X"}
    chapters = [
        _structured_chapter(
            0.0, 60.0, "A & B - Song (C Remix)",
            {
                "TITLE": "Song (C Remix)",
                "PERFORMER": "A & B",
                "PERFORMER_NAMES": "A|B|C",
                "MUSICBRAINZ_ARTISTIDS": "m-a|m-b|m-c",
            },
        ),
    ]
    album = build_album_meta(tags, chapters, "stem", tier=2)
    assert album.tracks[0].artist == "A & B"
    assert album.tracks[0].artists == ["A", "B", "C"]


def test_falls_back_to_string_parse_when_no_structured_tags():
    tags = {"artist": "Afrojack"}
    chapters = [
        Chapter(index=1, title="AFROJACK - ID [Wall]", start=0.0, end=60.0),
    ]
    album = build_album_meta(tags, chapters, "stem", tier=2)
    t = album.tracks[0]
    assert t.artist == "Afrojack"
    assert t.title == "ID"
    assert t.publisher == "Wall"
    assert t.artists == []
    assert t.artist_mbids == []


def test_albumartists_populated_from_file_tags():
    tags = {
        "artist": "Armin van Buuren",
        "albumartist_display": "Armin van Buuren & KI/KI",
        "albumartists": ["Armin van Buuren", "KI/KI"],
        "albumartist_mbids": ["mbid-arm", "mbid-ki"],
    }
    chapters = [Chapter(index=1, title="x", start=0.0, end=60.0)]
    album = build_album_meta(tags, chapters, "stem", tier=2)
    assert album.artist == "Armin van Buuren & KI/KI"
    assert album.albumartists == ["Armin van Buuren", "KI/KI"]
    assert album.albumartist_mbids == ["mbid-arm", "mbid-ki"]


def test_per_artist_case_normalization_against_albumartists():
    tags = {
        "artist": "Afrojack",
        "albumartists": ["Afrojack"],
    }
    chapters = [
        _structured_chapter(
            0.0, 60.0, "AFROJACK - ID",
            {
                "TITLE": "ID",
                "PERFORMER": "AFROJACK",
                "PERFORMER_NAMES": "AFROJACK",
            },
        ),
    ]
    album = build_album_meta(tags, chapters, "stem", tier=2)
    assert album.tracks[0].artists == ["Afrojack"]
    assert album.tracks[0].artist == "Afrojack"


# --- CrateDigger 0.12.5 per-chapter tag rename (CRATEDIGGER_TRACK_*) ---

def test_structured_chapter_tags_drive_track_fields_new_names():
    """Same as the legacy test but with CRATEDIGGER_TRACK_* prefixed names.

    Verifies the rename compat path: a file enriched by CrateDigger 0.12.5+
    carries the prefixed names only, and TrackSplit must pick them up.
    """
    tags = {
        "artist": "Armin van Buuren",
        "festival": "AMF",
        "date": "2025-10-25",
        "genres": ["Trance"],
    }
    chapters = [
        _structured_chapter(
            0.0, 60.0,
            "Armin van Buuren & Alle Farben ft. ROSY - Lost In Time [ARMADA]",
            {
                "TITLE": "Lost In Time",
                "CRATEDIGGER_TRACK_PERFORMER": "Armin van Buuren & Alle Farben ft. ROSY",
                "CRATEDIGGER_TRACK_PERFORMER_NAMES": "Armin van Buuren|Alle Farben",
                "MUSICBRAINZ_ARTISTIDS": "mbid-arm|mbid-af",
                "CRATEDIGGER_TRACK_LABEL": "ARMADA",
                "CRATEDIGGER_TRACK_GENRE": "Trance",
            },
        ),
    ]
    album = build_album_meta(tags, chapters, "stem", tier=2)
    t = album.tracks[0]
    assert t.title == "Lost In Time"
    assert t.artist == "Armin van Buuren & Alle Farben ft. ROSY"
    assert t.artists == ["Armin van Buuren", "Alle Farben"]
    assert t.artist_mbids == ["mbid-arm", "mbid-af"]
    assert t.publisher == "ARMADA"
    assert t.genre == ["Trance"]


# --- B2B album-artist display synthesis (Red Rocks venue collision fix) ---

def test_tier2_synthesizes_b2b_display_when_explicit_missing():
    """No ALBUMARTIST_DISPLAY but multi-entry albumartists -> joined display.

    Prevents Red Rocks B2B sets (where CrateDigger does not populate
    CRATEDIGGER_ALBUMARTIST_DISPLAY) from collapsing into the uploader's
    artist folder and colliding with the same uploader's solo set at the
    same venue + year.
    """
    tags = {
        "artist": "Martin Garrix",
        "albumartist_display": "",
        "albumartists": ["Martin Garrix", "Alesso"],
        "festival": "",
        "venue": "Red Rocks Amphitheatre",
    }
    chapters = _make_chapters(["Track 1"])
    meta = build_album_meta(
        tags, chapters, "2025 - Martin Garrix & Alesso - Red Rocks", tier=2
    )
    assert meta.artist == "Martin Garrix & Alesso"


def test_tier2_explicit_display_wins_over_synthesized_join():
    """When CrateDigger sets ALBUMARTIST_DISPLAY, it is used verbatim.

    Festivals already populate this field (e.g. for B2B sets at Tomorrowland)
    and may use different separators than ' & '. The synthesis must not
    override an explicit value.
    """
    tags = {
        "artist": "Armin van Buuren",
        "albumartist_display": "Armin van Buuren b2b KI/KI",
        "albumartists": ["Armin van Buuren", "KI/KI"],
        "festival": "Tomorrowland",
        "date": "2025-07-21",
    }
    chapters = _make_chapters(["Track 1"])
    meta = build_album_meta(tags, chapters, "stem", tier=2)
    assert meta.artist == "Armin van Buuren b2b KI/KI"


def test_tier2_solo_uses_file_artist_when_no_display():
    """Single-entry albumartists falls through to file ARTIST tag (unchanged)."""
    tags = {
        "artist": "Martin Garrix",
        "albumartist_display": "",
        "albumartists": ["Martin Garrix"],
        "festival": "",
        "venue": "Red Rocks Amphitheatre",
    }
    chapters = _make_chapters(["Track 1"])
    meta = build_album_meta(
        tags, chapters, "2025 - Martin Garrix - Red Rocks", tier=2
    )
    assert meta.artist == "Martin Garrix"
