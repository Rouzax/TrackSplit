"""Platform-dependent path resolution for TrackSplit.

Every config, cache, state, and log path in TrackSplit goes through this
module. Nothing else should call ``platformdirs`` or hand-craft paths under
``%APPDATA%``, ``$XDG_*``, or ``~/.config``.

Layout (Windows / Linux):

- Config + user data:    ``Documents\\TrackSplit\\config.toml`` / ``~/TrackSplit/config.toml``
- Cache:                 ``%LOCALAPPDATA%\\TrackSplit\\Cache\\`` / ``~/.cache/TrackSplit/``
- Logs:                  ``%LOCALAPPDATA%\\TrackSplit\\Logs\\`` / ``~/.local/state/TrackSplit/log/`` (per-command files)

The user-edited config lives under a *visible* folder (Documents on Windows,
``$HOME`` root on Linux) because the grab-bag problem the rewrite solved was
partly one of discoverability: users edit this file and should not need to
teach themselves ``%APPDATA%`` navigation. Caches and logs use the platform
default because users never touch them, they get big, and backups should be
able to skip them.

CrateDigger curated data (places.json, artists.json) is resolved per-file
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

import contextlib
import logging
import os
import re
import sys
import tempfile
import unicodedata
from datetime import date
from pathlib import Path

import platformdirs

from tracksplit.manifest import (
    ALBUM_MANIFEST_FILENAME,
    ARTIST_MANIFEST_FILENAME,
)

APP_NAME = "TrackSplit"
CRATEDIGGER_APP_NAME = "CrateDigger"
_WALK_UP_LIMIT = 10

_LEGACY_STAMP_NAME = "legacy-warning.stamp"


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


def state_dir() -> Path:
    """Return the user state directory (non-disposable per-user state)."""
    return Path(platformdirs.user_state_dir(APP_NAME, appauthor=False))


def log_dir() -> Path:
    """Return the directory for per-command log files."""
    return Path(platformdirs.user_log_dir(APP_NAME, appauthor=False))


def ensure_parent(path: Path) -> Path:
    """Create ``path.parent`` if missing. Returns ``path`` unchanged."""
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def cratedigger_cache_dir() -> Path:
    """Return CrateDigger's platformdirs cache directory.

    CrateDigger stores auto-generated caches (dj_cache.json, mbid_cache.json)
    here. Curated data (places.json, artists.json) lives in the visible
    data dir instead; see :func:`resolve_cratedigger_data_dir`.
    """
    return Path(platformdirs.user_cache_dir(CRATEDIGGER_APP_NAME, appauthor=False))


# --- Slug helpers (hand-synced with CrateDigger normalization.py) -----------
# These resolve the shared slug-keyed artwork cache and MUST stay byte-identical
# to CrateDigger ``festival_organizer/normalization.py`` (slugify / folder_slug /
# strip_diacritics), the same hand-sync discipline used for update_check.py.


def strip_diacritics(text: str) -> str:
    """Remove diacritics: 'Tiësto' -> 'Tiesto'."""
    nfkd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def slugify(name: str) -> str:
    """1001TL-style slug from a display name: ASCII-fold, lowercase,
    '&' -> 'and', then keep only [a-z0-9].

    The deterministic fallback cache key for an artist with no embedded slug.
    """
    folded = strip_diacritics(name).lower()
    folded = folded.replace("&", "and")
    return re.sub(r"[^a-z0-9]", "", folded)


def folder_slug(slug: str) -> str:
    """Make a real 1001TL slug safe as a directory name.

    Windows silently strips trailing dots/spaces, so 'fredagain..' must become
    the folder 'fredagain'. A real slug's internal characters are already
    URL-safe, so only the trailing strip is needed.
    """
    return slug.rstrip(" .")


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
    """Log a WARNING at most once per day if legacy TrackSplit paths are found.

    Called at CLI startup. No data is moved; this is a nudge to migrate.

    Suppression uses an ISO-date stamp file at
    ``state_dir() / "legacy-warning.stamp"``. First call on a given day emits
    the WARNING and writes today's date. Subsequent calls the same day stay
    silent. A stamp dated today or later (clock skew, manual edit) suppresses;
    a corrupt or unparseable stamp behaves as if absent and is overwritten.
    """
    legacy = _legacy_paths_present(home=home)
    if not legacy:
        return
    if _legacy_stamp_is_fresh():
        return
    logger = logging.getLogger("tracksplit.paths")
    pretty = "\n  - ".join(str(p) for p in legacy)
    logger.warning(
        "Legacy TrackSplit/CrateDigger files detected at old locations:\n  - %s\n"
        "These are no longer read. Move contents to the new platformdirs "
        "locations (see docs/configuration.md) or delete them.",
        pretty,
    )
    _write_legacy_stamp()


def _legacy_stamp_path() -> Path:
    return state_dir() / _LEGACY_STAMP_NAME


def _legacy_stamp_is_fresh() -> bool:
    """Return True iff the stamp file contains today's ISO date or a later one."""
    try:
        content = _legacy_stamp_path().read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return False
    try:
        stamped = date.fromisoformat(content)
    except ValueError:
        return False
    return stamped >= date.today()


def _write_legacy_stamp() -> None:
    """Atomically write today's ISO date to the stamp file. Silent on failure."""
    logger = logging.getLogger("tracksplit.paths")
    target = _legacy_stamp_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(target.parent),
            prefix=target.name + ".",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(date.today().isoformat())
            os.replace(tmp_path, target)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise
    except OSError as e:
        logger.debug("Failed to write legacy-warning stamp at %s: %s", target, e)


def detect_library_interior(output_dir: Path) -> tuple[Path, str] | None:
    """Detect when ``output_dir`` points *inside* a TrackSplit library.

    ``output_dir`` is meant to be a library *root*; TrackSplit appends
    ``<artist>/<album>`` to it. If the user instead points it at an artist or
    album folder, the run would silently create a doubled path. Recognize that
    case by TrackSplit's private marker files and return the library root the
    user almost certainly meant, paired with the kind of folder detected
    (``"artist"`` or ``"album"``). Return ``None`` for a plausible root or any
    non-library directory (including one that does not exist).
    """
    if (output_dir / ARTIST_MANIFEST_FILENAME).is_file():
        return output_dir.parent, "artist"
    if (output_dir / ALBUM_MANIFEST_FILENAME).is_file():
        return output_dir.parent.parent, "album"
    return None
