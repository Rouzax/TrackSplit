"""Shared test helpers for building manifest fixtures.

Tests should call ``make_audio_fp`` and ``make_manifest_dict`` instead of
hand-rolling JSON dicts, so future schema bumps only need updating in
one place.
"""

from __future__ import annotations

from pathlib import Path

from tracksplit.manifest import MANIFEST_SCHEMA

DEFAULT_AUDIO_FP = {
    "codec_name": "opus",
    "sample_rate": 48000,
    "channels": 2,
    "duration_ts": 14400000,
    "time_base": "1/48000",
    "bit_rate": 192000,
}


def make_audio_fp(**overrides) -> dict:
    return {**DEFAULT_AUDIO_FP, **overrides}


def make_ffprobe(audio_fp: dict | None = None) -> dict:
    """Build a minimal ffprobe dict whose first audio stream produces ``audio_fp``."""
    fp = audio_fp or DEFAULT_AUDIO_FP
    return {
        "streams": [
            {
                "codec_type": "audio",
                "codec_name": fp["codec_name"],
                "sample_rate": str(fp["sample_rate"]),
                "channels": fp["channels"],
                "duration_ts": fp["duration_ts"],
                "time_base": fp["time_base"],
                "bit_rate": str(fp["bit_rate"]),
            },
        ],
    }


def default_tags() -> dict:
    """Default stored-tag dict matching the new TAG_KEYS allowlist."""
    return {
        "artist": "A",
        "festival": "",
        "date": "",
        "stage": "",
        "venue": "",
        "genres": [],
        "comment": "",
        "albumartist_display": "",
        "albumartists": [],
        "albumartist_mbids": [],
    }


def make_manifest_dict(*, source_path: str = "/x.mkv", **overrides) -> dict:
    """Build a complete schema-4 manifest dict for tests.

    Accepted keyword overrides:
    - ``audio_fp=``          override audio fingerprint fields (only the 4 stored fields)
    - ``tags=`` / ``album_tags=``  override album_tags dict
    - ``track_filenames=``   list of filenames; synthesizes TrackEntry dicts
    - ``chapters=``          used only to derive track start/end boundaries;
                             NOT written to the output (schema-4 has no chapters)
    - ``source_id=``         identity.source_id
    - ``artist_folder=``     resolved_artist_folder
    - ``album_folder=``      resolved_album_folder
    - ``output_format=``     top-level output_format field
    - ``codec_mode=``        top-level codec_mode field
    - ``cover_sha256=``      top-level cover_sha256 field
    - ``cover_schema_version=``  top-level field
    - ``tag_schema_version=``    top-level field
    - ``intro_min_seconds=`` silently ignored (schema-4 has no such field)
    """
    audio_fp = overrides.pop("audio_fp", None) or DEFAULT_AUDIO_FP
    tags = overrides.pop("tags", overrides.pop("album_tags", None))
    if tags is None:
        tags = default_tags()

    track_filenames = overrides.pop("track_filenames", ["01 - T.flac"])
    chapters = overrides.pop(
        "chapters",
        [{"index": 1, "title": "T", "start": 0.0, "end": 60.0, "tags": {}}],
    )
    source_id = overrides.pop("source_id", None)
    overrides.pop("intro_min_seconds", None)  # silently ignored

    # Build tracks from track_filenames and chapters
    tracks = []
    for i, fn in enumerate(track_filenames):
        if i < len(chapters):
            ch = chapters[i]
            start = float(ch.get("start", i * 60.0))
            end = float(ch.get("end", (i + 1) * 60.0))
            title = ch.get("title", Path(fn).stem)
        else:
            start = float(i * 60.0)
            end = float((i + 1) * 60.0)
            title = Path(fn).stem
        tracks.append(
            {
                "index": i + 1,
                "filename": fn,
                "start": start,
                "end": end,
                "title": title,
                "artist": "",
                "publisher": "",
                "genre": [],
                "artists": [],
                "artist_mbids": [],
            }
        )

    # Build audio identity: only the 4 fields AudioFingerprint stores
    audio_identity = {
        "codec_name": audio_fp["codec_name"],
        "sample_rate": audio_fp["sample_rate"],
        "channels": audio_fp["channels"],
        "time_base": audio_fp["time_base"],
    }

    data: dict = {
        "schema": MANIFEST_SCHEMA,
        "identity": {"source_id": source_id, "audio": audio_identity},
        "source_path": source_path,
        "resolved_artist_folder": overrides.pop("artist_folder", "A"),
        "resolved_album_folder": overrides.pop("album_folder", "B"),
        "output_format": overrides.pop("output_format", "flac"),
        "codec_mode": overrides.pop("codec_mode", "copy"),
        "album_tags": tags,
        "tracks": tracks,
        "cover_sha256": overrides.pop("cover_sha256", "a" * 64),
        "cover_schema_version": overrides.pop("cover_schema_version", 0),
        "tag_schema_version": overrides.pop("tag_schema_version", 0),
    }

    if overrides:
        raise TypeError(f"unexpected overrides: {sorted(overrides)}")

    return data
