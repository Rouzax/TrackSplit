"""Metadata utilities for TrackSplit."""
import re


def safe_filename(name: str) -> str:
    """Sanitize a string for use as a filename.

    Removes characters that are unsafe on Windows or Unix filesystems:
    / \\ : * ? " < > |
    Collapses multiple spaces and strips leading/trailing whitespace.
    """
    cleaned = re.sub(r'[\\/*?:"<>|]', "", name)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()
