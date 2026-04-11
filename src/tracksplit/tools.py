"""External tool path configuration for TrackSplit.

Reads tool paths from a config file, falling back to bare command names
(found via PATH). Config locations searched in order:

1. ./tracksplit.toml
2. ~/.config/tracksplit/config.toml  (Linux/macOS)
   %APPDATA%/tracksplit/config.toml  (Windows)

Example config::

    [tools]
    ffmpeg = "C:/ffmpeg/bin/ffmpeg.exe"
    ffprobe = "C:/ffmpeg/bin/ffprobe.exe"
    mkvmerge = "C:/Program Files/MKVToolNix/mkvmerge.exe"
    mkvextract = "C:/Program Files/MKVToolNix/mkvextract.exe"
"""
from __future__ import annotations

import logging
import os
import sys
import tomllib
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULTS = {
    "ffmpeg": "ffmpeg",
    "ffprobe": "ffprobe",
    "mkvmerge": "mkvmerge",
    "mkvextract": "mkvextract",
}

_tool_paths: dict[str, str] = {}


def _config_candidates() -> list[Path]:
    """Return config file paths to search, in priority order."""
    candidates = [Path("tracksplit.toml")]

    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / "tracksplit" / "config.toml")
    else:
        candidates.append(Path.home() / ".config" / "tracksplit" / "config.toml")

    return candidates


def _load_config() -> dict[str, str]:
    """Load tool paths from the first config file found."""
    for path in _config_candidates():
        if path.is_file():
            try:
                with open(path, "rb") as f:
                    data = tomllib.load(f)
                tools = data.get("tools", {})
                if tools:
                    logger.debug("Loaded tool config from %s", path)
                return {k: str(v) for k, v in tools.items()}
            except (tomllib.TOMLDecodeError, OSError) as exc:
                logger.warning("Failed to read config %s: %s", path, exc)
    return {}


def get_tool(name: str) -> str:
    """Return the configured path for a tool, or its default name."""
    if not _tool_paths:
        _tool_paths.update(_DEFAULTS)
        _tool_paths.update(_load_config())
    return _tool_paths.get(name, name)
