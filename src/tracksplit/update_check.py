"""Startup update-notification check for TrackSplit.

Hand-synced with festival_organizer/update_check.py in the CrateDigger repo.
Keep in sync when editing. Only PACKAGE_NAME, ENV_VAR, and REPO_URL differ.
"""
from __future__ import annotations

import re

PACKAGE_NAME = "tracksplit"
ENV_VAR = "TRACKSPLIT_NO_UPDATE_CHECK"
REPO_URL = "https://github.com/Rouzax/TrackSplit"

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_PRERELEASE_RE = re.compile(r"(a|b|rc|dev|post)", re.IGNORECASE)


def _parse_version(s: str) -> tuple[int, int, int] | None:
    m = _VERSION_RE.match(s.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _is_newer(installed: str, candidate: str) -> bool:
    a = _parse_version(installed)
    b = _parse_version(candidate)
    if a is None or b is None:
        return False
    return b > a


def _is_prerelease_string(v: str) -> bool:
    return bool(_PRERELEASE_RE.search(v))


def print_cached_update_notice(console) -> None:
    """Called at CLI startup. Prints a notice if the cache indicates a
    newer release is available. No network I/O. Silent on any failure."""
    raise NotImplementedError


def refresh_update_cache() -> None:
    """Called at CLI exit. Refreshes the cache by hitting the GitHub
    Releases API if the cache is stale. Silent on any failure."""
    raise NotImplementedError
