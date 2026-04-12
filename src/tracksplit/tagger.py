"""Tag FLAC and OGG/Opus files with Vorbis comments and cover art."""
from __future__ import annotations

import base64
import logging
import re
from collections.abc import Callable, Sequence
from pathlib import Path

from mutagen.flac import FLAC, Picture
from mutagen.oggopus import OggOpus

from tracksplit.models import AlbumMeta, TrackMeta

# Matches collab separators in an album-artist string. A single MBID cannot
# identify two performers, so we suppress MUSICBRAINZ_ALBUMARTISTID when any
# of these appear as whitespace-delimited tokens: "X & Y", "X | Y", "X vs Y"
# (with or without trailing dot), "X x Y". Whitespace-delimited so names like
# "Axwell", "deadmau5", or "Eric Prydz" do not false-positive.
_COLLAB_SEPARATOR_RE = re.compile(r"\s(?:&|\||vs\.?|x)\s", re.IGNORECASE)


def _is_collab_artist(artist: str) -> bool:
    return bool(_COLLAB_SEPARATOR_RE.search(artist))


def build_tag_dict(album: AlbumMeta, track: TrackMeta) -> dict[str, list[str]]:
    """Build a Vorbis comment dict from album and track metadata.

    Tag policy (single source of truth for both FLAC and OggOpus):

    - ``TITLE`` / ``ARTIST``: per-track. ``ARTIST`` falls back to ``album.artist``
      when the chapter title had no "Artist - Title" separator.
    - ``ALBUMARTIST``: always the album-level artist (the set headliner).
    - ``MUSICBRAINZ_ALBUMARTISTID``: the album artist's MusicBrainz ID, under the
      Picard-canonical key. Suppressed for B2B/collab album artists (those
      containing "&", "|", "vs.", or " x ") because a single MBID cannot
      identify two performers; writing it anyway would merge the collab album
      into one member's solo discography in LMS/Jellyfin.
    - ``MUSICBRAINZ_ARTISTID`` (per-track MBID) is **never** emitted: TrackSplit
      has no per-track-artist MBIDs. Writing the album-artist MBID here (the
      pre-fix behavior) caused Lyrion to dedupe every track to a single
      contributor row.

    All values are lists of strings per the Vorbis comment specification.
    Optional tags are omitted when their source value is empty.
    """
    tags: dict[str, list[str]] = {
        "TITLE": [track.title],
        "ARTIST": [track.artist or album.artist],
        "ALBUMARTIST": [album.artist],
        "ALBUM": [album.album],
        "TRACKNUMBER": [str(track.number)],
        "DISCNUMBER": ["1"],
    }

    if album.tracks:
        tags["TRACKTOTAL"] = [str(len(album.tracks))]

    # Conditional tags: only include when non-empty
    if album.date:
        tags["DATE"] = [album.date]

    # Track genre takes precedence over album genre
    genre = track.genre or album.genre
    if genre:
        tags["GENRE"] = list(genre)

    if track.publisher:
        tags["PUBLISHER"] = [track.publisher]

    if album.comment:
        tags["COMMENT"] = [album.comment]

    if album.musicbrainz_artistid and not _is_collab_artist(album.artist):
        tags["MUSICBRAINZ_ALBUMARTISTID"] = [album.musicbrainz_artistid]

    if album.festival:
        tags["FESTIVAL"] = [album.festival]

    if album.stage:
        tags["STAGE"] = [album.stage]

    if album.venue:
        tags["VENUE"] = [album.venue]

    return tags


def tag_flac(
    path: str | Path,
    album: AlbumMeta,
    track: TrackMeta,
    cover_data: bytes | None = None,
) -> None:
    """Open a FLAC file, clear existing tags, write Vorbis comments, and
    optionally embed front cover art. Saves the file in place.
    """
    audio = FLAC(path)
    audio.clear()
    audio.clear_pictures()

    tag_dict = build_tag_dict(album, track)
    for key, values in tag_dict.items():
        audio[key] = values

    if cover_data is not None:
        pic = Picture()
        pic.type = 3  # front cover
        pic.mime = "image/jpeg"
        pic.data = cover_data
        audio.add_picture(pic)

    audio.save()


def tag_ogg(
    path: str | Path,
    album: AlbumMeta,
    track: TrackMeta,
    cover_data: bytes | None = None,
) -> None:
    """Write Vorbis comments to an OGG/Opus file."""
    audio = OggOpus(str(path))
    audio.delete()

    tag_dict = build_tag_dict(album, track)
    for key, values in tag_dict.items():
        audio[key] = values

    if cover_data is not None:
        pic = Picture()
        pic.type = 3  # front cover
        pic.mime = "image/jpeg"
        pic.desc = "Cover"
        pic.data = cover_data
        audio["METADATA_BLOCK_PICTURE"] = [
            base64.b64encode(pic.write()).decode("ascii")
        ]

    audio.save()


def tag_all(
    track_paths: Sequence[str | Path],
    album: AlbumMeta,
    cover_data: bytes | None = None,
    on_progress: Callable[[str, int, int], None] | None = None,
) -> None:
    """Tag all track files by zipping paths with album.tracks.

    Dispatches to tag_flac or tag_ogg based on file extension.
    """
    total = len(track_paths)
    for i, (path, track) in enumerate(zip(track_paths, album.tracks, strict=True)):
        if on_progress:
            on_progress("Tagging tracks", i + 1, total)
        p = Path(path)
        if p.suffix.lower() in (".ogg", ".opus"):
            tag_ogg(p, album, track, cover_data=cover_data)
        else:
            tag_flac(p, album, track, cover_data=cover_data)
