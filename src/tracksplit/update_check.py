"""Startup update-notification check for TrackSplit.

Hand-synced with festival_organizer/update_check.py in the CrateDigger repo.
Keep in sync when editing. Only PACKAGE_NAME, ENV_VAR, and REPO_URL differ.
"""
from __future__ import annotations

PACKAGE_NAME = "tracksplit"
ENV_VAR = "TRACKSPLIT_NO_UPDATE_CHECK"
REPO_URL = "https://github.com/Rouzax/TrackSplit"


def print_cached_update_notice(console) -> None:
    """Called at CLI startup. Prints a notice if the cache indicates a
    newer release is available. No network I/O. Silent on any failure."""
    raise NotImplementedError


def refresh_update_cache() -> None:
    """Called at CLI exit. Refreshes the cache by hitting the GitHub
    Releases API if the cache is stale. Silent on any failure."""
    raise NotImplementedError
