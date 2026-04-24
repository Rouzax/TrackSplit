"""External tool path configuration for TrackSplit.

Reads tool paths from a single TOML config at
:func:`tracksplit.paths.config_file` (platformdirs-resolved). Missing or
malformed config = fall back to bare command names (resolved via PATH).

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
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from tracksplit import paths

logger = logging.getLogger(__name__)

_DEFAULTS = {
    "ffmpeg": "ffmpeg",
    "ffprobe": "ffprobe",
    "mkvmerge": "mkvmerge",
    "mkvextract": "mkvextract",
}

_tool_paths: dict[str, str] = {}
_config_loaded: bool = False


def find_active_config() -> Path | None:
    """Return the config file path if it exists, else None."""
    path = paths.config_file()
    return path if path.is_file() else None


def _load_config() -> dict[str, str]:
    """Load tool paths from the platformdirs config file."""
    path = paths.config_file()
    if not path.is_file():
        logger.debug("No tracksplit config found at %s; using defaults", path)
        return {}
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError) as exc:
        logger.warning("Failed to read config %s: %s", path, exc)
        return {}
    tools_section = data.get("tools", {})
    if not isinstance(tools_section, dict):
        logger.warning(
            "Config %s: [tools] must be a table, got %s. Using defaults.",
            path, type(tools_section).__name__,
        )
        return {}
    resolved = {k: str(v) for k, v in tools_section.items()}
    if resolved:
        logger.info("Loaded tool config from %s: %s", path, sorted(resolved))
        for name, tool_path in resolved.items():
            if tool_path != name and not Path(tool_path).is_file():
                logger.warning(
                    "Configured %s path does not exist: %s", name, tool_path,
                )
    else:
        logger.info("Config at %s has no [tools] section", path)
    return resolved


def get_tool(name: str) -> str:
    """Return the configured path for a tool, or its default name."""
    global _config_loaded
    if not _config_loaded:
        _tool_paths.update(_DEFAULTS)
        _tool_paths.update(_load_config())
        _config_loaded = True
    return _tool_paths.get(name, name)


_INSTALL_PACKAGES: dict[str, dict[str, str]] = {
    "ffmpeg":     {"brew": "ffmpeg",     "apt": "ffmpeg",     "winget": "Gyan.FFmpeg"},
    "ffprobe":    {"brew": "ffmpeg",     "apt": "ffmpeg",     "winget": "Gyan.FFmpeg"},
    "mkvextract": {"brew": "mkvtoolnix", "apt": "mkvtoolnix", "winget": "MKVToolNix.MKVToolNix"},
    "mkvmerge":   {"brew": "mkvtoolnix", "apt": "mkvtoolnix", "winget": "MKVToolNix.MKVToolNix"},
}


def _install_hint(tool: str) -> str:
    """Return an OS-specific install suggestion for a missing tool."""
    pkg = _INSTALL_PACKAGES.get(tool, {})
    if sys.platform == "darwin":
        return f"Install with: brew install {pkg.get('brew', tool)}"
    if sys.platform == "win32":
        return f"Install with: winget install {pkg.get('winget', tool)}"
    return f"Install with: apt install {pkg.get('apt', tool)}"


def verify_tool(name: str) -> tuple[bool, str]:
    """Probe a configured tool. Returns (ok, detail).

    ``detail`` is a version string on success, or an error message.
    """
    path = get_tool(name)
    # Absolute path: check file exists
    if os.path.sep in path or (sys.platform == "win32" and "/" in path):
        if not Path(path).is_file():
            return False, f"configured path not found: {path}"
    else:
        # Bare command: search PATH
        if shutil.which(path) is None:
            return False, f"not found on PATH (looked for '{path}')"

    version_flag = "--version" if name in ("mkvextract", "mkvmerge") else "-version"
    try:
        result = subprocess.run(
            [path, version_flag],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"failed to run: {exc}"
    if result.returncode != 0:
        return False, f"exited {result.returncode}"
    first_line = (result.stdout or result.stderr).splitlines()[0] if (result.stdout or result.stderr) else ""
    return True, first_line.strip()


def verify_required_tools() -> list[tuple[str, str]]:
    """Verify ffmpeg/ffprobe are available. Return list of (tool, error) for failures."""
    errors: list[tuple[str, str]] = []
    for name in ("ffmpeg", "ffprobe"):
        ok, detail = verify_tool(name)
        if not ok:
            errors.append((name, detail))
    return errors


def install_hint(tool: str) -> str:
    """Public wrapper for the install hint helper."""
    return _install_hint(tool)
