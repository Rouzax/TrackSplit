"""Parameterized invariant tests over the real CrateDigger MKV corpus.

Runs only when the local fixture directory is present. Every JSON sidecar
in the dump exercises the full path:

    ffprobe tags -> parse_tags -> build_album_meta -> build_tag_dict

and asserts invariants that must hold for every set. Gives us continuous
regression coverage against real data without shipping the corpus.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tracksplit.metadata import build_album_meta
from tracksplit.models import Chapter
from tracksplit.tagger import build_tag_dict

DUMP_DIR = Path("/home/user/_temp/cratedigger/data/mkv-info-dump")

pytestmark = pytest.mark.skipif(
    not DUMP_DIR.is_dir(),
    reason=f"MKV dump corpus not present at {DUMP_DIR}",
)

# Same regex as tagger._COLLAB_SEPARATOR_RE, duplicated here so the test
# breaks loudly if the two drift.
_COLLAB_RE = re.compile(r"\s(?:&|\||vs\.?|x)\s", re.IGNORECASE)


def _fixture_ids() -> list[str]:
    if not DUMP_DIR.is_dir():
        return []
    return sorted(p.name for p in DUMP_DIR.glob("*.json"))


def _tags_from_extra(extra: dict) -> dict:
    """Translate the MKV `extra` block into the dict shape parse_tags produces."""
    genres_raw = extra.get("CRATEDIGGER_1001TL_GENRES", "")
    return {
        "artist": extra.get("ARTIST", ""),
        "festival": extra.get("CRATEDIGGER_1001TL_FESTIVAL", ""),
        "date": extra.get("CRATEDIGGER_1001TL_DATE", ""),
        "stage": extra.get("CRATEDIGGER_1001TL_STAGE", ""),
        "venue": extra.get("CRATEDIGGER_1001TL_VENUE", ""),
        "genres": [g for g in genres_raw.split("|") if g],
        "comment": extra.get("CRATEDIGGER_1001TL_URL", ""),
        "musicbrainz_artistid": extra.get("CRATEDIGGER_MBID", ""),
    }


def _chapters_from_menu(menu_track: dict) -> list[Chapter]:
    """Extract chapters from the MediaInfo Menu track structure."""
    chapters: list[Chapter] = []
    extra = menu_track.get("extra", {})
    # Keys are timecodes like "_00_00_00000"; values are strings like "en:TITLE".
    entries = sorted(
        (k, v) for k, v in extra.items()
        if isinstance(k, str) and k.startswith("_")
    )
    times: list[float] = []
    titles: list[str] = []
    for k, v in entries:
        parts = k.lstrip("_").split("_")
        if len(parts) < 3:
            continue
        h, m, rest = parts[0], parts[1], parts[2]
        try:
            seconds = int(h) * 3600 + int(m) * 60 + int(rest[:2]) + int(rest[2:].ljust(3, "0")[:3]) / 1000
        except ValueError:
            continue
        if isinstance(v, str) and ":" in v:
            v = v.split(":", 1)[1]
        times.append(float(seconds))
        titles.append(v)

    if not times:
        return []
    for i, (start, title) in enumerate(zip(times, titles)):
        end = times[i + 1] if i + 1 < len(times) else start + 1.0
        chapters.append(Chapter(index=i + 1, title=title, start=start, end=end))
    return chapters


def _load_fixture(path: Path) -> tuple[dict, list[Chapter]] | None:
    raw = json.loads(path.read_text(encoding="utf-8"))
    tracks = raw.get("mediainfo", {}).get("media", {}).get("track", [])
    general = next((t for t in tracks if t.get("@type") == "General"), None)
    menu = next((t for t in tracks if t.get("@type") == "Menu"), None)
    if not general or not menu:
        return None
    tags = _tags_from_extra(general.get("extra", {}))
    chapters = _chapters_from_menu(menu)
    if not chapters:
        return None
    return tags, chapters


@pytest.mark.parametrize("fixture_name", _fixture_ids())
def test_corpus_invariants(fixture_name):
    loaded = _load_fixture(DUMP_DIR / fixture_name)
    if loaded is None:
        pytest.skip(f"{fixture_name}: no usable General+Menu tracks")
    tags, chapters = loaded
    stem = fixture_name.replace(".json", "")
    meta = build_album_meta(tags, chapters, stem, tier=2)

    assert meta.album, f"{fixture_name}: empty ALBUM"
    assert meta.artist, f"{fixture_name}: empty ALBUMARTIST"

    for track in meta.tracks:
        td = build_tag_dict(meta, track)

        # Required tags populated
        assert td["TITLE"] and td["TITLE"][0], f"{fixture_name} t{track.number}: empty TITLE"
        assert td["ARTIST"] and td["ARTIST"][0], f"{fixture_name} t{track.number}: empty ARTIST"
        assert td["ALBUMARTIST"] and td["ALBUMARTIST"][0], f"{fixture_name} t{track.number}: empty ALBUMARTIST"

        # Regression guard: the old tag key must never reappear
        assert "MUSICBRAINZ_ARTISTID" not in td, (
            f"{fixture_name} t{track.number}: MUSICBRAINZ_ARTISTID leaked back"
        )

        # Collab guard: when album-artist MBID is written, ALBUMARTIST must
        # unambiguously identify a single performer.
        if "MUSICBRAINZ_ALBUMARTISTID" in td:
            aa = td["ALBUMARTIST"][0]
            assert not _COLLAB_RE.search(aa), (
                f"{fixture_name} t{track.number}: album MBID written for "
                f"collab ALBUMARTIST {aa!r}"
            )
