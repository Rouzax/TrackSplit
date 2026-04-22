"""Platform-dependent path resolution for TrackSplit.

Every config, cache, state, and log path in TrackSplit goes through this
module. Nothing else should call ``platformdirs`` or hand-craft paths under
``%APPDATA%``, ``$XDG_*``, or ``~/.config``.

Layout (Windows / Linux):

- Config + user data:    ``Documents\\TrackSplit\\config.toml`` / ``~/TrackSplit/config.toml``
- Cache:                 ``%LOCALAPPDATA%\\TrackSplit\\Cache\\`` / ``~/.cache/TrackSplit/``
- Logs:                  ``%LOCALAPPDATA%\\TrackSplit\\Logs\\`` / ``~/.local/state/TrackSplit/log/``

The user-edited config lives under a *visible* folder (Documents on Windows,
``$HOME`` root on Linux) because the grab-bag problem the rewrite solved was
partly one of discoverability: users edit this file and should not need to
teach themselves ``%APPDATA%`` navigation. Caches and logs use the platform
default because users never touch them, they get big, and backups should be
able to skip them.

CrateDigger data is looked up via :func:`resolve_cratedigger_data_dir`, which
returns the first valid source in this order:

1. ``$CRATEDIGGER_DATA_DIR`` env var (if set and directory exists)
2. ``.cratedigger/`` directory found by walking up from the input file
   (max 10 parents)
3. CrateDigger's visible data dir: ``Documents\\CrateDigger\\`` on Windows,
   ``~/CrateDigger/`` on Linux. Mirrors the same visible-folder choice
   CrateDigger uses for its own writable files.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import platformdirs

APP_NAME = "TrackSplit"
CRATEDIGGER_APP_NAME = "CrateDigger"
_WALK_UP_LIMIT = 10


def data_dir() -> Path:
    """Return the user data directory (also holds the user config file).

    Windows: ``<Documents>\\TrackSplit``. Linux/other: ``$HOME/TrackSplit``.
    Chosen for visibility; users expect to be able to open this in Explorer
    or their file manager and edit files directly.
    """
    if sys.platform == "win32":
        return Path(platformdirs.user_documents_dir()) / APP_NAME
    return Path.home() / APP_NAME


def config_file() -> Path:
    """Return the path to the user config file (``config.toml``)."""
    return data_dir() / "config.toml"


def cache_dir() -> Path:
    """Return the user cache directory."""
    return Path(platformdirs.user_cache_dir(APP_NAME, appauthor=False))


def log_file() -> Path:
    """Return the path to the rotating log file (``tracksplit.log``)."""
    return Path(platformdirs.user_log_dir(APP_NAME, appauthor=False)) / "tracksplit.log"


def ensure_parent(path: Path) -> Path:
    """Create ``path.parent`` if missing. Returns ``path`` unchanged."""
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def cratedigger_cache_dir() -> Path:
    """Return CrateDigger's platformdirs cache directory.

    CrateDigger stores auto-generated caches (dj_cache.json, mbid_cache.json)
    here. Curated data (festivals.json, artists.json) lives in the visible
    data dir instead; see :func:`resolve_cratedigger_data_dir`.
    """
    return Path(platformdirs.user_cache_dir(CRATEDIGGER_APP_NAME, appauthor=False))


def _cratedigger_visible_data_dir() -> Path:
    """Mirror CrateDigger's ``data_dir()`` without importing it (independent app)."""
    if sys.platform == "win32":
        return Path(platformdirs.user_documents_dir()) / CRATEDIGGER_APP_NAME
    return Path.home() / CRATEDIGGER_APP_NAME


def resolve_cratedigger_data_dir(input_path: Path) -> Path:
    """Resolve where to look for CrateDigger's shared data.

    Order: ``$CRATEDIGGER_DATA_DIR`` env (if set and exists) >
    walk-up from input (max 10 parents looking for ``.cratedigger/``) >
    CrateDigger's visible ``data_dir()`` (``Documents\\CrateDigger\\`` on Windows,
    ``~/CrateDigger/`` on Linux).

    The returned path is not guaranteed to exist; callers must still check.
    When ``input_path`` refers to an existing file, the walk starts at
    ``input_path.parent`` (the folder containing the file). Otherwise
    (a directory or a non-existent path) the walk starts at
    ``input_path`` itself, so callers can pass library roots directly.
    """
    env = os.environ.get("CRATEDIGGER_DATA_DIR")
    if env:
        env_path = Path(env)
        if env_path.is_dir():
            return env_path

    current = input_path.parent if input_path.is_file() else input_path
    for _ in range(_WALK_UP_LIMIT):
        candidate = current / ".cratedigger"
        if candidate.is_dir():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent

    return _cratedigger_visible_data_dir()


def _legacy_paths_present(home: Path | None = None) -> list[Path]:
    """Return legacy TrackSplit/CrateDigger paths still in use.

    Re-evaluated on every CLI invocation; the warning fires on every run
    while any listed path still exists. Callers rely on the returned
    list being empty when the user has migrated.
    """
    if home is None:
        home = Path.home()
    legacy: list[Path] = []

    for name in ("tracksplit.toml", ".tracksplit.toml"):
        p = home / name
        if p.is_file():
            legacy.append(p)
    old_config = home / ".config" / "tracksplit" / "config.toml"
    if old_config.is_file():
        legacy.append(old_config)
    old_cache = home / ".cache" / "tracksplit"
    if old_cache.is_dir():
        legacy.append(old_cache)

    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            for name in ("config.toml", "tracksplit.toml"):
                p = Path(appdata) / "tracksplit" / name
                if p.is_file():
                    legacy.append(p)
        localappdata = os.environ.get("LOCALAPPDATA")
        if localappdata:
            # Old cache lived directly under %LOCALAPPDATA%\tracksplit (no Cache\ subfolder).
            # New layout is %LOCALAPPDATA%\TrackSplit\Cache\, so the old dir is only
            # "legacy" if it contains the pre-0.7.0 cache file directly.
            old_win_cache = Path(localappdata) / "tracksplit" / "update-check.json"
            if old_win_cache.is_file():
                legacy.append(old_win_cache.parent)

    return legacy


def warn_if_legacy_paths_exist(home: Path | None = None) -> None:
    """Log a single WARNING if legacy TrackSplit/CrateDigger paths are found.

    Called once at CLI startup. No data is moved; this is a nudge to migrate.
    """
    legacy = _legacy_paths_present(home=home)
    if not legacy:
        return
    logger = logging.getLogger("tracksplit.paths")
    pretty = "\n  - ".join(str(p) for p in legacy)
    logger.warning(
        "Legacy TrackSplit/CrateDigger files detected at old locations:\n  - %s\n"
        "These are no longer read. Move contents to the new platformdirs "
        "locations (see docs/configuration.md) or delete them.",
        pretty,
    )
