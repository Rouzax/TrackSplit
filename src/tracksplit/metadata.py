"""Metadata extraction, sanitization, and album building for TrackSplit."""
import re

from tracksplit.models import AlbumMeta, Chapter, TrackMeta

# Characters illegal in Windows filenames
_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*]')

# Unicode slash lookalikes
_UNICODE_SLASHES = "\u2044\u2215\u29f8\u29f9\uff0f"

# Control characters (U+0000 to U+001F)
_CONTROL_CHARS = re.compile(r"[\x00-\x1f]")

# Label in square brackets at end of string
_LABEL_RE = re.compile(r"\s*\[([^\]]+)\]\s*$")

# Filename patterns: "YYYY - Artist - Festival" or "Artist - Festival"
_FILENAME_YEAR_RE = re.compile(r"^(\d{4})\s*-\s*(.+?)\s*-\s*.+$")
_FILENAME_NO_YEAR_RE = re.compile(r"^(.+?)\s*-\s*.+$")


def strip_label(title: str) -> tuple[str, str]:
    """Remove [Label Name] from end of track title.

    Returns (clean_title, label). Only matches square brackets at end.
    Preserves parentheses like (Remix).
    """
    m = _LABEL_RE.search(title)
    if m:
        clean = title[: m.start()].rstrip()
        return clean, m.group(1)
    return title, ""


def safe_filename(name: str) -> str:
    """Strip characters illegal in Windows filenames.

    Removes: < > : " / \\ | ? * and control chars.
    Removes unicode slash lookalikes (U+2044, U+2215, U+29F8, U+29F9, U+FF0F).
    Collapses whitespace, strips trailing dots/spaces.
    Truncates to 200 characters.
    """
    # Remove control characters
    name = _CONTROL_CHARS.sub("", name)
    # Remove illegal characters
    name = _ILLEGAL_CHARS.sub("", name)
    # Remove unicode slash lookalikes
    for ch in _UNICODE_SLASHES:
        name = name.replace(ch, "")
    # Collapse whitespace
    name = re.sub(r"\s+", " ", name).strip()
    # Strip trailing dots and spaces
    name = name.rstrip(". ")
    # Truncate
    if len(name) > 200:
        name = name[:200].rstrip(". ")
    return name


def parse_filename(stem: str) -> tuple[str, str]:
    """Parse artist and year from filename stem.

    Patterns:
        "2024 - Artist - Festival" -> ("Artist", "2024")
        "Artist - Festival" -> ("Artist", "")
        no match -> ("", "")
    """
    m = _FILENAME_YEAR_RE.match(stem)
    if m:
        return m.group(2), m.group(1)
    m = _FILENAME_NO_YEAR_RE.match(stem)
    if m:
        return m.group(1), ""
    return "", ""


def split_track_artist(title: str) -> tuple[str, str]:
    """Split 'Artist - Track Title' into (artist, title).

    Uses the first ' - ' as the boundary. Returns ("", title) if no
    separator is found.
    """
    if " - " in title:
        artist, track = title.split(" - ", 1)
        return artist.strip(), track.strip()
    return "", title


def deduplicate_titles(titles: list[str]) -> list[str]:
    """Append track number in parens to duplicate titles.

    "ID", "Track B", "ID" -> "ID (01)", "Track B", "ID (03)"
    Non-duplicates are unchanged.
    """
    counts: dict[str, int] = {}
    for t in titles:
        counts[t] = counts.get(t, 0) + 1

    duplicated = {t for t, c in counts.items() if c > 1}

    result = []
    for i, t in enumerate(titles):
        if t in duplicated:
            result.append(f"{t} ({i + 1:02d})")
        else:
            result.append(t)
    return result


def build_album_meta(
    tags: dict,
    chapters: list[Chapter],
    filename_stem: str,
    tier: int,
) -> AlbumMeta:
    """Build album metadata from parsed tags and chapters.

    Tier 2: album = "Festival Year (Stage)" with full tag data.
    Tier 1: album = filename_stem, artist/date parsed from filename.
    """
    # Resolve album-level fields up front so we can case-normalize per-track
    # artists against the album artist below (see loop).
    if tier == 2:
        artist = tags.get("artist", "")
        festival = tags.get("festival", "")
        date = tags.get("date", "")
        stage = tags.get("stage", "")
        year = date[:4] if date else ""

        if festival:
            album = f"{festival} {year}".strip()
            if stage:
                album = f"{album} ({stage})"
        else:
            # No festival metadata: fall back to filename
            album = filename_stem
    else:
        # Tier 1: fallback to filename parsing
        artist, year = parse_filename(filename_stem)
        date = year
        album = filename_stem

    # Strip labels, then split artist from title.
    #
    # Defense-in-depth: if a chapter's per-track artist matches the album
    # artist case-insensitively (e.g. chapter "AFROJACK - ID" with album
    # ARTIST "Afrojack"), normalize to the album artist's canonical casing.
    # Without this, Lyrion treats "AFROJACK" and "Afrojack" as two separate
    # contributors, and Jellyfin collapses them but keeps the first-scanned
    # casing as the display name. CrateDigger ideally normalizes upstream,
    # but 40% of DJs are missing from its cache and tier-1 (non-CrateDigger)
    # sources make no such guarantee, so we apply the cheap local fix here.
    # Whole-string match only: "AFROJACK & Steve Aoki" stays as-is because
    # that's a genuinely different contributor string.
    clean_titles = []
    track_artists = []
    publishers = []
    for ch in chapters:
        title, label = strip_label(ch.title)
        track_artist, track_title = split_track_artist(title)
        if (
            track_artist
            and artist
            and track_artist.casefold() == artist.casefold()
        ):
            track_artist = artist
        clean_titles.append(track_title)
        track_artists.append(track_artist)
        publishers.append(label)

    # Deduplicate titles
    clean_titles = deduplicate_titles(clean_titles)

    # Get genres from tags
    genres = tags.get("genres", [])

    # Build tracks
    tracks = []
    for i, ch in enumerate(chapters):
        tracks.append(
            TrackMeta(
                number=i + 1,
                title=clean_titles[i],
                start=ch.start,
                end=ch.end,
                artist=track_artists[i],
                publisher=publishers[i],
                genre=list(genres),
            )
        )

    return AlbumMeta(
        artist=artist,
        album=album,
        date=date,
        genre=list(genres),
        festival=tags.get("festival", ""),
        stage=tags.get("stage", ""),
        venue=tags.get("venue", ""),
        comment=tags.get("comment", ""),
        musicbrainz_artistid=tags.get("musicbrainz_artistid", ""),
        tracks=tracks,
    )
