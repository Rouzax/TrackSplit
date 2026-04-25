"""Shared test helpers for building manifest fixtures.

Tests should call ``make_audio_fp`` and ``make_manifest_dict`` instead of
hand-rolling JSON dicts, so future schema bumps only need updating in
one place.
"""
from __future__ import annotations

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
    """Build a complete schema-3 manifest dict for tests.

    Pass ``audio_fp=`` to override audio fields, ``tags=`` to override
    tag fields, or any top-level manifest key.
    """
    audio_fp = overrides.pop("audio_fp", None) or DEFAULT_AUDIO_FP
    tags = overrides.pop("tags", None) or default_tags()
    data = {
        "schema": MANIFEST_SCHEMA,
        "source": {"path": source_path, "audio": dict(audio_fp)},
        "resolved_artist_folder": overrides.pop("artist_folder", "A"),
        "resolved_album_folder": overrides.pop("album_folder", "B"),
        "output_format": overrides.pop("output_format", "flac"),
        "codec_mode": overrides.pop("codec_mode", "copy"),
        "chapters": overrides.pop("chapters",
            [{"index": 1, "title": "T", "start": 0.0, "end": 60.0}]),
        "tags": tags,
        "track_filenames": overrides.pop("track_filenames", ["01 - T.flac"]),
        "cover_sha256": overrides.pop("cover_sha256", "a" * 64),
    }
    if "intro_min_seconds" in overrides:
        data["intro_min_seconds"] = overrides.pop("intro_min_seconds")
    if "cover_schema_version" in overrides:
        data["cover_schema_version"] = overrides.pop("cover_schema_version")
    if overrides:
        raise TypeError(f"unexpected overrides: {sorted(overrides)}")
    return data
