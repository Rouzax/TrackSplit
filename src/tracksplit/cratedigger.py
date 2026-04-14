"""CrateDigger config reader: festival/artist alias resolution and MBID lookup.

TrackSplit consumes MKVs produced by CrateDigger (sibling project). CrateDigger
stores canonical naming rules in ``~/.cratedigger/festivals.json`` and
``~/.cratedigger/artists.json`` plus an ``mbid_cache.json`` mapping artist
names to MusicBrainz IDs. This module mirrors the subset of CrateDigger's
resolver logic that TrackSplit needs so that album folders, vorbis tags, and
cover art all use consistent canonical names.

The lookup chain matches ``find_dj_artwork`` in cover.py: ``~/.cratedigger``
first, then any ``.cratedigger`` directory found by walking up from the input
file (up to 10 parent levels).
"""
from __future__ import annotations

import json
import logging
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_WALK_UP_LIMIT = 10


def find_cratedigger_dirs(
    input_path: Path, home_dir: Path | None = None
) -> list[Path]:
    """Return existing ``.cratedigger`` directories relevant to ``input_path``.

    Order: global (``~/.cratedigger``) first, then local directories found by
    walking up from ``input_path`` (nearest last). Callers should read
    later-found dirs with higher priority for per-project overrides.
    """
    if home_dir is None:
        home_dir = Path.home()

    dirs: list[Path] = []
    global_cd = home_dir / ".cratedigger"
    if global_cd.is_dir():
        dirs.append(global_cd)

    current = input_path.parent if input_path.is_file() else input_path
    for _ in range(_WALK_UP_LIMIT):
        candidate = current / ".cratedigger"
        if candidate.is_dir() and candidate != global_cd:
            dirs.append(candidate)
        parent = current.parent
        if parent == current:
            break
        current = parent

    return dirs


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("CrateDigger config read failed: %s (%s)", path, exc)
        return {}


def _strip_diacritics(s: str) -> str:
    """Fold diacritics for case/accent-insensitive matching ("Tiësto" -> "Tiesto")."""
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if not unicodedata.combining(c)
    )


def _ci_get(mapping: dict, key: str):
    """Case-insensitive dict get. Returns None when missing."""
    if key in mapping:
        return mapping[key]
    low = key.lower()
    for k, v in mapping.items():
        if k.lower() == low:
            return v
    return None


@dataclass
class CrateDiggerConfig:
    """Parsed CrateDigger config merged from one or more ``.cratedigger`` dirs.

    Later sources (local, closer to the input file) override earlier ones
    (global ``~/.cratedigger``).
    """

    festival_config: dict = field(default_factory=dict)
    festival_aliases: dict[str, str] = field(default_factory=dict)
    artist_aliases: dict[str, str] = field(default_factory=dict)
    mbid_cache: dict[str, str] = field(default_factory=dict)

    # -- Festival resolution -------------------------------------------------

    def resolve_festival(self, name: str) -> tuple[str, str]:
        """Return (canonical_name, edition) for the given festival string.

        Examples::

            "TML"                         -> ("Tomorrowland", "")
            "Tomorrowland Winter"         -> ("Tomorrowland", "Winter")
            "A State Of Trance Festival"  -> ("ASOT", "")
            "Unknown Fest"                -> ("Unknown Fest", "")
        """
        if not name:
            return "", ""

        canonical = self._resolve_festival_alias(name)

        # Alias matched: check for edition suffix or edition-specific alias.
        if canonical != name:
            fc = _ci_get(self.festival_config, canonical) or {}
            for ed_name, ed_conf in fc.get("editions", {}).items():
                aliases = [a.lower() for a in ed_conf.get("aliases", [])]
                if name.lower() in aliases:
                    return canonical, ed_name
            if name.lower().startswith(canonical.lower()):
                suffix = name[len(canonical):].strip()
                for ed_name in fc.get("editions", {}):
                    if ed_name.lower() == suffix.lower():
                        return canonical, ed_name
            return canonical, ""

        # No alias match. Try "Canonical Edition" decomposition.
        for fest_name, fc in self.festival_config.items():
            for ed_name in fc.get("editions", {}):
                if f"{fest_name} {ed_name}".lower() == name.lower():
                    return fest_name, ed_name

        # Try alias-prefixed edition, e.g. "Ultra Europe" via alias "Ultra".
        for alias, canon in self.festival_aliases.items():
            fc = _ci_get(self.festival_config, canon) or {}
            for ed_name in fc.get("editions", {}):
                if f"{alias} {ed_name}".lower() == name.lower():
                    return canon, ed_name

        return name, ""

    def _resolve_festival_alias(self, name: str) -> str:
        if name in self.festival_aliases:
            return self.festival_aliases[name]
        low = name.lower()
        for alias, canon in self.festival_aliases.items():
            if alias.lower() == low:
                return canon
        return name

    def festival_display(self, canonical: str, edition: str) -> str:
        """Return the display-name form of a canonical+edition pair."""
        if not canonical:
            return ""
        fc = _ci_get(self.festival_config, canonical) or {}
        if edition and edition in fc.get("editions", {}):
            return f"{canonical} {edition}"
        return canonical

    # -- Artist resolution ---------------------------------------------------

    def resolve_artist(self, name: str) -> str:
        """Map an artist alias/stage name to its canonical form.

        Only applies the alias table from artists.json. Unknown names (and
        groups) are returned as-is. Unlike CrateDigger we do not split B2Bs.
        """
        if not name:
            return ""
        if name in self.artist_aliases:
            return self.artist_aliases[name]
        low = name.lower()
        for alias, canon in self.artist_aliases.items():
            if alias.lower() == low:
                return canon
        # Diacritics-insensitive fallback: "Tiesto" -> "Tiësto" when the
        # canonical carries diacritics but the raw tag does not.
        folded = _strip_diacritics(name).lower()
        for alias, canon in self.artist_aliases.items():
            if _strip_diacritics(alias).lower() == folded:
                return canon
        for canon in set(self.artist_aliases.values()):
            if _strip_diacritics(canon).lower() == folded:
                return canon
        return name

    # -- MBID cache ----------------------------------------------------------

    def lookup_mbid(self, artist: str) -> str:
        """Return MBID for ``artist`` from mbid_cache.json, or ``""``."""
        if not artist or not self.mbid_cache:
            return ""
        entry = self.mbid_cache.get(artist)
        if entry is None:
            low = artist.lower()
            for k, v in self.mbid_cache.items():
                if k.lower() == low:
                    entry = v
                    break
        if isinstance(entry, str):
            return entry
        if isinstance(entry, dict):
            return entry.get("mbid", "") or ""
        return ""

    def fill_mbids(self, names: list[str], mbids: list[str]) -> list[str]:
        """Return an MBID list aligned positionally with ``names``.

        For each position where ``mbids`` is missing or empty, look the
        corresponding name up in ``mbid_cache.json`` (case-insensitive via
        ``lookup_mbid``). Unknown names stay as empty strings so downstream
        consumers can still zip the list positionally. Result length
        matches ``len(names)`` (input padded/truncated as needed).
        """
        result: list[str] = []
        for i, name in enumerate(names):
            current = mbids[i] if i < len(mbids) else ""
            if current:
                result.append(current)
            else:
                result.append(self.lookup_mbid(name))
        return result


def _invert_alias_map(raw: dict[str, list[str]]) -> dict[str, str]:
    """CrateDigger stores {canonical: [aliases]}; flatten to {alias: canonical}."""
    flat: dict[str, str] = {}
    for canon, aliases in raw.items():
        for alias in aliases or []:
            flat[alias] = canon
    return flat


def load_config(
    input_path: Path, home_dir: Path | None = None
) -> CrateDiggerConfig:
    """Build a merged config view from all relevant CrateDigger directories.

    Later directories (local, near the input file) override earlier ones.
    Missing or malformed files are silently skipped: TrackSplit must keep
    working when no CrateDigger config exists.
    """
    cfg = CrateDiggerConfig()
    for cd_dir in find_cratedigger_dirs(input_path, home_dir=home_dir):
        fest = _load_json(cd_dir / "festivals.json")
        fest = {
            k: v for k, v in fest.items()
            if not k.startswith("_") and isinstance(v, dict)
        }
        cfg.festival_config.update(fest)

        # Build festival alias map: top-level aliases + per-edition aliases.
        raw_aliases: dict[str, list[str]] = {}
        for canon, fc in fest.items():
            raw_aliases.setdefault(canon, []).extend(fc.get("aliases", []))
            for ed_conf in fc.get("editions", {}).values():
                raw_aliases.setdefault(canon, []).extend(
                    ed_conf.get("aliases", [])
                )
        cfg.festival_aliases.update(_invert_alias_map(raw_aliases))

        # dj_cache.json first so manual artists.json overrides auto-derived
        # aliases from the scrape cache.
        dj = _load_json(cd_dir / "dj_cache.json")
        if isinstance(dj, dict):
            for entry in dj.values():
                if not isinstance(entry, dict):
                    continue
                canonical = entry.get("name", "")
                if not canonical:
                    continue
                for alias in entry.get("aliases", []) or []:
                    alias_name = alias.get("name", "") if isinstance(alias, dict) else ""
                    if alias_name:
                        cfg.artist_aliases[alias_name] = canonical

        artists = _load_json(cd_dir / "artists.json")
        raw_artist_aliases = artists.get("aliases", {}) or {}
        cfg.artist_aliases.update(_invert_alias_map(raw_artist_aliases))

        mbid = _load_json(cd_dir / "mbid_cache.json")
        if isinstance(mbid, dict):
            cfg.mbid_cache.update(mbid)

    return cfg


def apply_cratedigger_canon_with(tags: dict, cfg: CrateDiggerConfig) -> dict:
    """Variant of apply_cratedigger_canon that uses an already-loaded config."""
    raw_festival = tags.get("festival", "")
    if raw_festival:
        canon, edition = cfg.resolve_festival(raw_festival)
        tags["festival"] = cfg.festival_display(canon, edition) or raw_festival
        tags["edition"] = edition
    else:
        tags.setdefault("edition", "")

    raw_artist = tags.get("artist", "")
    if raw_artist:
        tags["artist"] = cfg.resolve_artist(raw_artist)

    return tags


def apply_cratedigger_canon(tags: dict, input_path: Path) -> dict:
    """Rewrite ``tags`` in place with canonical festival/artist + MBID fallback.

    Adds ``edition`` key. Safe to call with or without a CrateDigger config
    available: when no config exists the tags are returned unchanged.
    """
    return apply_cratedigger_canon_with(tags, load_config(input_path))
