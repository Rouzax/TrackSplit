"""Tag FLAC files with Vorbis comments and cover art."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

from mutagen.flac import FLAC, Picture

from tracksplit.models import AlbumMeta, TrackMeta


def build_tag_dict(album: AlbumMeta, track: TrackMeta) -> dict[str, list[str]]:
    """Build a Vorbis comment dict from album and track metadata.

    All values are lists of strings per the Vorbis comment specification.
    Optional tags are omitted when their source value is empty.
    """
    tags: dict[str, list[str]] = {
        "TITLE": [track.title],
        "ARTIST": [album.artist],
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

    if album.musicbrainz_artistid:
        tags["MUSICBRAINZ_ARTISTID"] = [album.musicbrainz_artistid]

    if album.festival:
        tags["FESTIVAL"] = [album.festival]

    if album.stage:
        tags["STAGE"] = [album.stage]

    if album.venue:
        tags["VENUE"] = [album.venue]

    return tags


def tag_flac(
    flac_path: str | Path,
    album: AlbumMeta,
    track: TrackMeta,
    cover_data: bytes | None = None,
) -> None:
    """Open a FLAC file, clear existing tags, write Vorbis comments, and
    optionally embed front cover art. Saves the file in place.
    """
    audio = FLAC(flac_path)
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


def tag_all(
    track_paths: Sequence[str | Path],
    album: AlbumMeta,
    cover_data: bytes | None = None,
) -> None:
    """Tag all track files by zipping paths with album.tracks."""
    for path, track in zip(track_paths, album.tracks, strict=True):
        tag_flac(path, album, track, cover_data=cover_data)
