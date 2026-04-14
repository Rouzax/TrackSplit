"""Metadata extraction, sanitization, and album building for TrackSplit."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from tracksplit.models import AlbumMeta, Chapter, TrackMeta

if TYPE_CHECKING:
    from tracksplit.cratedigger import CrateDiggerConfig

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
    cd_config: "CrateDiggerConfig | None" = None,
) -> AlbumMeta:
    """Build album metadata from parsed tags and chapters.

    Prefers structured per-chapter tags (TITLE, PERFORMER, PERFORMER_NAMES,
    MUSICBRAINZ_ARTISTIDS, LABEL, GENRE) when present; falls back to the
    legacy string-parser on Chapter.title otherwise.

    ``cd_config`` is used to fill empty per-artist MBID slots from
    mbid_cache.json. When omitted, missing slots stay as empty strings.
    """
    # --- Album-level resolution --------------------------------------------
    if tier == 2:
        display_artist = tags.get("albumartist_display") or tags.get("artist", "")
        artist = display_artist
        festival = tags.get("festival", "")
        date = tags.get("date", "")
        stage = tags.get("stage", "")
        year = date[:4] if date else ""

        if festival:
            album = f"{festival} {year}".strip()
            if stage:
                album = f"{album} ({stage})"
        else:
            album = filename_stem
    else:
        artist, year = parse_filename(filename_stem)
        date = year
        album = filename_stem

    albumartists = list(tags.get("albumartists", []))
    albumartist_mbids = list(tags.get("albumartist_mbids", []))
    if albumartists:
        while len(albumartist_mbids) < len(albumartists):
            albumartist_mbids.append("")
        albumartist_mbids = albumartist_mbids[: len(albumartists)]

    # Canonical-casing reference set for whole-name matches.
    canon_names: dict[str, str] = {n.casefold(): n for n in albumartists}
    if not canon_names and artist:
        canon_names[artist.casefold()] = artist

    # --- Per-chapter mapping -----------------------------------------------
    album_genres = tags.get("genres", [])
    clean_titles: list[str] = []
    track_artists: list[str] = []
    track_artists_lists: list[list[str]] = []
    track_artist_mbids: list[list[str]] = []
    publishers: list[str] = []
    track_genres: list[list[str]] = []

    for ch in chapters:
        ctags = ch.tags or {}
        has_structured = any(
            k in ctags for k in ("PERFORMER", "PERFORMER_NAMES", "TITLE")
        )

        if has_structured:
            title = ctags.get("TITLE") or ch.title
            title, _ = strip_label(title)
            display = ctags.get("PERFORMER", "")
            names_raw = ctags.get("PERFORMER_NAMES", "")
            names = [n for n in names_raw.split("|") if n] if names_raw else []
            mbids_raw = ctags.get("MUSICBRAINZ_ARTISTIDS", "")
            mbids = mbids_raw.split("|") if mbids_raw else []
            label = ctags.get("LABEL", "")
            genre_raw = ctags.get("GENRE", "")
            genres = [genre_raw] if genre_raw else list(album_genres)

            names = [canon_names.get(n.casefold(), n) for n in names]
            display = canon_names.get(display.casefold(), display)

            if cd_config is not None and names:
                mbids = cd_config.fill_mbids(names, mbids)
            else:
                while len(mbids) < len(names):
                    mbids.append("")
                mbids = mbids[: len(names)]
        else:
            title_full, label = strip_label(ch.title)
            track_artist, title = split_track_artist(title_full)
            if (
                track_artist
                and artist
                and track_artist.casefold() == artist.casefold()
            ):
                track_artist = artist
            display = track_artist
            names = []
            mbids = []
            genres = list(album_genres)

        clean_titles.append(title)
        track_artists.append(display)
        track_artists_lists.append(names)
        track_artist_mbids.append(mbids)
        publishers.append(label)
        track_genres.append(genres)

    clean_titles = deduplicate_titles(clean_titles)

    tracks: list[TrackMeta] = []
    for i, ch in enumerate(chapters):
        tracks.append(
            TrackMeta(
                number=i + 1,
                title=clean_titles[i],
                start=ch.start,
                end=ch.end,
                artist=track_artists[i],
                publisher=publishers[i],
                genre=list(track_genres[i]),
                artists=list(track_artists_lists[i]),
                artist_mbids=list(track_artist_mbids[i]),
            )
        )

    return AlbumMeta(
        artist=artist,
        album=album,
        date=date,
        genre=list(album_genres),
        festival=tags.get("festival", ""),
        stage=tags.get("stage", ""),
        venue=tags.get("venue", ""),
        comment=tags.get("comment", ""),
        musicbrainz_artistid=tags.get("musicbrainz_artistid", ""),
        tracks=tracks,
        albumartists=albumartists,
        albumartist_mbids=albumartist_mbids,
    )
