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

CrateDigger curated data (festivals.json, artists.json) is resolved per-file
across candidate directories in priority order, matching CrateDigger's own
``_load_external_config`` semantics:

1. Walk-up ``.cratedigger/`` from the input file (max 10 parents)
2. CrateDigger's visible data dir: ``Documents\\CrateDigger\\`` on Windows,
   ``~/CrateDigger/`` on Linux.

If ``$CRATEDIGGER_DATA_DIR`` is set and exists, it replaces both sources.
For each curated file, the first directory containing it wins; files not
present in the walk-up dir fall through to the visible data dir.
Cache files are read from :func:`cratedigger_cache_dir` (platformdirs cache).
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


def cratedigger_data_dir() -> Path:
    """Return CrateDigger's visible data directory.

    Windows: ``<Documents>\\CrateDigger``. Linux/other: ``$HOME/CrateDigger``.
    Mirrors CrateDigger's own ``data_dir()`` without importing it.
    """
    if sys.platform == "win32":
        return Path(platformdirs.user_documents_dir()) / CRATEDIGGER_APP_NAME
    return Path.home() / CRATEDIGGER_APP_NAME


def walkup_cratedigger_dir(input_path: Path) -> Path | None:
    """Walk up from ``input_path`` looking for a ``.cratedigger/`` directory.

    Returns the first match, or ``None``. When ``input_path`` is an existing
    file the walk starts at its parent; otherwise at ``input_path`` itself.
    """
    current = input_path.parent if input_path.is_file() else input_path
    for _ in range(_WALK_UP_LIMIT):
        candidate = current / ".cratedigger"
        if candidate.is_dir():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def resolve_cratedigger_data_dir(input_path: Path) -> Path:
    """Resolve a single CrateDigger data directory for ``input_path``.

    Returns the first valid source: ``$CRATEDIGGER_DATA_DIR`` env >
    walk-up ``.cratedigger/`` > visible data dir. The returned path is
    not guaranteed to exist; callers must still check.

    Most callers should use
    :func:`tracksplit.cratedigger.find_cratedigger_dirs` instead, which
    returns a candidate list for per-file first-found-wins lookup.
    """
    env = os.environ.get("CRATEDIGGER_DATA_DIR")
    if env:
        env_path = Path(env)
        if env_path.is_dir():
            return env_path
    walkup = walkup_cratedigger_dir(input_path)
    if walkup is not None:
        return walkup
    return cratedigger_data_dir()


def _legacy_paths_present(home: Path | None = None) -> list[Path]:
    """Return legacy TrackSplit config paths still in use.

    Only config files are checked; cache directories are transient data
    and not worth warning about.

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

    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            for name in ("config.toml", "tracksplit.toml"):
                p = Path(appdata) / "tracksplit" / name
                if p.is_file():
                    legacy.append(p)

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
