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

    Multi-artist policy (Picard convention):

    - ``ARTIST`` / ``ALBUMARTIST``: single-value display strings.
    - ``ARTISTS`` / ``ALBUMARTISTS``: multi-value individual artist names.
      Emitted only when non-empty.
    - ``MUSICBRAINZ_ARTISTID`` / ``MUSICBRAINZ_ALBUMARTISTID``: multi-value
      when the corresponding ``*ARTISTS`` list is populated, positionally
      aligned with empty-string slots preserved. Single-value legacy path
      kept for old enrichments, with collab-suppression safeguard for the
      album artist (a single MBID can't identify two performers).
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

    if album.date:
        tags["DATE"] = [album.date]

    genre = track.genre or album.genre
    if genre:
        tags["GENRE"] = list(genre)

    if track.publisher:
        tags["PUBLISHER"] = [track.publisher]

    if album.comment:
        tags["COMMENT"] = [album.comment]

    # Per-track individual artists + aligned MBIDs.
    if track.artists:
        tags["ARTISTS"] = list(track.artists)
        if track.artist_mbids:
            mbids = list(track.artist_mbids)
            while len(mbids) < len(track.artists):
                mbids.append("")
            tags["MUSICBRAINZ_ARTISTID"] = mbids[: len(track.artists)]

    # Album-level individuals + aligned MBIDs (new), with legacy fallback.
    if album.albumartists:
        tags["ALBUMARTISTS"] = list(album.albumartists)
        mbids = list(album.albumartist_mbids)
        while len(mbids) < len(album.albumartists):
            mbids.append("")
        tags["MUSICBRAINZ_ALBUMARTISTID"] = mbids[: len(album.albumartists)]
    elif album.musicbrainz_artistid and not _is_collab_artist(album.artist):
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
