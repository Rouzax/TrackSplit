"""Tag FLAC and OGG/Opus files with Vorbis comments and cover art."""
from __future__ import annotations

import base64
import logging
from collections.abc import Callable, Sequence
from pathlib import Path

from mutagen.flac import FLAC, Picture
from mutagen.oggopus import OggOpus

from tracksplit.models import AlbumMeta, TrackMeta

logger = logging.getLogger(__name__)


def _count_tag_deltas(
    existing: dict | None,
    new_tags: dict[str, list[str]],
) -> tuple[int, int, int]:
    """Return (added, removed, changed) between existing tags (a Mutagen
    tag dict or None) and the new tag dict that build_tag_dict produced.

    Keys are compared case-insensitively since Vorbis comments fold case
    on disk. A key in ``new_tags`` but not in ``existing`` is ``added``;
    a key in ``existing`` but not in ``new_tags`` is ``removed``; a key
    in both whose list-of-values differs is ``changed``.
    """
    existing_map: dict[str, list[str]] = {}
    if existing:
        for key in existing.keys():
            try:
                existing_map[key.upper()] = list(existing[key])
            except Exception:
                existing_map[key.upper()] = []
    new_map = {k.upper(): list(v) for k, v in new_tags.items()}
    existing_keys = set(existing_map.keys())
    new_keys = set(new_map.keys())
    added = len(new_keys - existing_keys)
    removed = len(existing_keys - new_keys)
    changed = sum(
        1 for k in existing_keys & new_keys
        if existing_map[k] != new_map[k]
    )
    return added, removed, changed


def build_tag_dict(album: AlbumMeta, track: TrackMeta) -> dict[str, list[str]]:
    """Build a Vorbis comment dict from album and track metadata.

    Multi-artist policy (Picard convention):

    - ``ARTIST`` / ``ALBUMARTIST``: single-value display strings.
    - ``ARTISTS`` / ``ALBUMARTISTS``: multi-value individual artist names.
      Emitted only when non-empty.
    - ``MUSICBRAINZ_ARTISTID`` / ``MUSICBRAINZ_ALBUMARTISTID``: multi-value,
      positionally aligned with ``ARTISTS`` / ``ALBUMARTISTS``. Empty-string
      slots preserved so positional consumers stay aligned; the tag is
      omitted entirely when every slot is empty (a single MBID cannot
      identify a collab, and nothing non-empty is worth writing).
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

    # Per-track individual artists + aligned MBIDs. When every MBID slot
    # is empty, omit MUSICBRAINZ_ARTISTID entirely rather than writing a
    # row of empty strings (nothing to link against).
    if track.artists:
        tags["ARTISTS"] = list(track.artists)
        if track.artist_mbids:
            mbids = list(track.artist_mbids)
            while len(mbids) < len(track.artists):
                mbids.append("")
            mbids = mbids[: len(track.artists)]
            if any(mbids):
                tags["MUSICBRAINZ_ARTISTID"] = mbids

    # Album-level individuals + aligned MBIDs.
    if album.albumartists:
        tags["ALBUMARTISTS"] = list(album.albumartists)
        mbids = list(album.albumartist_mbids)
        while len(mbids) < len(album.albumartists):
            mbids.append("")
        mbids = mbids[: len(album.albumartists)]
        if any(mbids):
            tags["MUSICBRAINZ_ALBUMARTISTID"] = mbids

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
    tag_dict = build_tag_dict(album, track)
    added, removed, changed = _count_tag_deltas(audio.tags, tag_dict)
    if added or removed or changed:
        logger.debug(
            "Tags for %s: +%d -%d ~%d",
            Path(path).name, added, removed, changed,
        )
    audio.clear()
    audio.clear_pictures()

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
    tag_dict = build_tag_dict(album, track)
    added, removed, changed = _count_tag_deltas(audio.tags, tag_dict)
    if added or removed or changed:
        logger.debug(
            "Tags for %s: +%d -%d ~%d",
            Path(path).name, added, removed, changed,
        )
    audio.delete()

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
        try:
            if p.suffix.lower() in (".ogg", ".opus"):
                tag_ogg(p, album, track, cover_data=cover_data)
            else:
                tag_flac(p, album, track, cover_data=cover_data)
        except Exception as exc:
            logger.warning(
                "Failed to tag %s: %s: %s",
                p.name, type(exc).__name__, exc,
            )
            raise


def replace_cover_only(path: str | Path, cover_data: bytes) -> None:
    """Replace the front cover picture on a FLAC or Opus file without
    touching other tags. Used by the cover-only rebuild path.
    """
    p = Path(path)
    ext = p.suffix.lower()
    if ext in (".ogg", ".opus"):
        audio = OggOpus(str(p))
        pic = Picture()
        pic.type = 3
        pic.mime = "image/jpeg"
        pic.desc = "Cover"
        pic.data = cover_data
        audio["METADATA_BLOCK_PICTURE"] = [
            base64.b64encode(pic.write()).decode("ascii")
        ]
        audio.save()
    elif ext == ".flac":
        audio = FLAC(str(p))
        audio.clear_pictures()
        pic = Picture()
        pic.type = 3
        pic.mime = "image/jpeg"
        pic.data = cover_data
        audio.add_picture(pic)
        audio.save()
    else:
        raise ValueError(f"Unsupported extension for cover replace: {ext!r}")
