"""External tool path configuration for TrackSplit.

Reads tool paths from a config file, falling back to bare command names
(found via PATH). Config locations searched in order:

1. ./tracksplit.toml  (current directory)
2. ./config.toml  (current directory, alternate name)
3. ~/.config/tracksplit/config.toml  (Linux/macOS)
   %APPDATA%/tracksplit/config.toml  (Windows)
4. ~/tracksplit.toml  (home directory fallback)

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
_config_loaded: bool = False


def _config_candidates() -> list[Path]:
    """Return config file paths to search, in priority order."""
    cwd = Path.cwd()
    candidates = [
        cwd / "tracksplit.toml",
        cwd / "config.toml",
    ]

    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / "tracksplit" / "config.toml")
            candidates.append(Path(appdata) / "tracksplit" / "tracksplit.toml")
    else:
        candidates.append(Path.home() / ".config" / "tracksplit" / "config.toml")

    candidates.append(Path.home() / "tracksplit.toml")
    candidates.append(Path.home() / ".tracksplit.toml")

    return candidates


def _load_config() -> dict[str, str]:
    """Load tool paths from the first config file found."""
    candidates = _config_candidates()
    for path in candidates:
        if path.is_file():
            try:
                with open(path, "rb") as f:
                    data = tomllib.load(f)
                tools = data.get("tools", {})
                resolved = {k: str(v) for k, v in tools.items()}
                if resolved:
                    logger.info("Loaded tool config from %s: %s", path, sorted(resolved))
                    # Warn for missing tool paths
                    for name, tool_path in resolved.items():
                        if tool_path != name and not Path(tool_path).is_file():
                            logger.warning(
                                "Configured %s path does not exist: %s",
                                name, tool_path,
                            )
                else:
                    logger.info("Config at %s has no [tools] section", path)
                return resolved
            except (tomllib.TOMLDecodeError, OSError) as exc:
                logger.warning("Failed to read config %s: %s", path, exc)
    logger.debug(
        "No tracksplit config found; searched: %s",
        ", ".join(str(p) for p in candidates),
    )
    return {}


def get_tool(name: str) -> str:
    """Return the configured path for a tool, or its default name."""
    global _config_loaded
    if not _config_loaded:
        _tool_paths.update(_DEFAULTS)
        _tool_paths.update(_load_config())
        _config_loaded = True
    return _tool_paths.get(name, name)
