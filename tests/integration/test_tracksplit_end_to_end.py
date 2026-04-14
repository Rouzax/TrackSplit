"""End-to-end TrackSplit starting from fresh (unidentified) MKVs.

For each fixture, the test:
  1. Copies the fresh MKV to tmp_path (originals stay untouched).
  2. Runs ``cratedigger identify`` against the copy.
  3. Runs ``cratedigger enrich`` against the copy.
  4. Runs ``tracksplit`` to produce FLAC output.
  5. Asserts multi-artist Vorbis tags on the output.

Opt-in and machine-local (hits 1001TL). Requires:

- ``TRACKSPLIT_TEST_MKV_DIR``: directory holding the fresh fixture MKVs by
  filename (matching CrateDigger's ``test_enrichment_end_to_end.py`` FIXTURES).
- ``CRATEDIGGER_TEST_CONFIG``: path to ``config.json`` with 1001TL credentials.
- ``CRATEDIGGER_TEST_COOKIES``: path to the 1001TL cookies jar (if the
  CrateDigger version in use needs it; harmless when unused).

Auto-skips when any of these are absent or when a specific MKV is missing.

Run with:

    TRACKSPLIT_TEST_MKV_DIR=~/fresh-mkvs \\
    CRATEDIGGER_TEST_CONFIG=~/.cratedigger/config.json \\
    CRATEDIGGER_TEST_COOKIES=~/.1001tl-cookies.json \\
    pytest tests/integration/ -m integration -v
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from mutagen.flac import FLAC

pytestmark = pytest.mark.integration


def _env_dir(name: str) -> Path | None:
    raw = os.environ.get(name)
    if not raw:
        return None
    p = Path(os.path.expanduser(raw))
    return p if p.is_dir() else None


def _env_file(name: str) -> Path | None:
    raw = os.environ.get(name)
    if not raw:
        return None
    p = Path(os.path.expanduser(raw))
    return p if p.is_file() else None


MKV_DIR = _env_dir("TRACKSPLIT_TEST_MKV_DIR")
CD_CONFIG = _env_file("CRATEDIGGER_TEST_CONFIG")
CD_COOKIES = _env_file("CRATEDIGGER_TEST_COOKIES")  # may be unused


# Filenames match CrateDigger's fixture dict so a single shared directory
# feeds both suites. `tracklist_id` is passed to `cratedigger identify` so
# we don't rely on automatic URL detection.
FIXTURES = {
    "tiesto-solo": {
        "filename": "Tiësto - Live at We Belong Here Miami 2026 [2EQGqEvLAuE].mkv",
        "tracklist_id": "2dyq04n9",
        "expect_albumartists": ["Tiësto"],
        "expect_albumartist_mbids_any": True,
        "expect_per_track_artists_some_multi": False,
    },
    "armin-b2b-marlon": {
        "filename": "ARMIN VAN BUUREN B2B MARLON HOFFSTADT LIVE AT ULTRA MIAMI 2026 ASOT WORLDWIDE STAGE [XM0zfkqLMzI].mkv",
        "tracklist_id": "2gugf5b9",
        "expect_albumartists_contains": ["Armin van Buuren", "Marlon Hoffstadt"],
        "expect_albumartist_mbids_any": True,
        "expect_per_track_artists_some_multi": True,
    },
    "afrojack-solo": {
        "filename": "AFROJACK LIVE @ ULTRA MUSIC FESTIVAL MIAMI 2026 [fLyb8KvtSzw].mkv",
        "tracklist_id": "22r0yk79",
        "expect_albumartists": ["AFROJACK"],
        "expect_per_track_artists_some_multi": True,
    },
    "eric-prydz-solo": {
        "filename": "ERIC PRYDZ LIVE @ ULTRA MUSIC FESTIVAL MIAMI 2026 ｜ RESISTANCE MEGASTRUCTURE [hU-z3iV0LOg].mkv",
        "tracklist_id": "qy9yyy9",
        "expect_albumartists": ["Eric Prydz"],
        "expect_per_track_artists_some_multi": False,
    },
    "alok-something-else": {
        "filename": "Alok presents Something Else ｜ Tomorrowland Winter 2026 [kttWNVHJKDo].mkv",
        "tracklist_id": "upk4l6k",
        "expect_albumartists_contains": ["ALOK"],
        "expect_per_track_artists_some_multi": True,
    },
}


def _fixture_mkv(key: str) -> Path | None:
    if MKV_DIR is None:
        return None
    p = MKV_DIR / FIXTURES[key]["filename"]
    return p if p.exists() else None


def _cratedigger_identify(mkv: Path, tracklist_id: str) -> None:
    """Run CrateDigger's identify against *mkv* in place."""
    subprocess.run(
        [
            "cratedigger", "identify",
            "--config", str(CD_CONFIG),
            "--tracklist", tracklist_id,
            "--auto",
            str(mkv),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _cratedigger_enrich(mkv: Path) -> None:
    """Run CrateDigger's enrich against *mkv* in place."""
    subprocess.run(
        [
            "cratedigger", "enrich",
            "--config", str(CD_CONFIG),
            str(mkv),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _tracksplit_run(mkv: Path, out_dir: Path) -> None:
    subprocess.run(
        ["tracksplit", str(mkv), "--out-dir", str(out_dir)],
        check=True,
        capture_output=True,
        text=True,
    )


def _collect_flacs(out_dir: Path) -> list[Path]:
    return sorted(out_dir.rglob("*.flac"))


_SKIP_REASONS = []
if MKV_DIR is None:
    _SKIP_REASONS.append("TRACKSPLIT_TEST_MKV_DIR not set")
if CD_CONFIG is None:
    _SKIP_REASONS.append("CRATEDIGGER_TEST_CONFIG not set or missing")


@pytest.mark.skipif(bool(_SKIP_REASONS), reason="; ".join(_SKIP_REASONS))
@pytest.mark.parametrize("key", list(FIXTURES))
def test_identify_enrich_split(tmp_path, key):
    """Fresh MKV -> identify -> enrich -> tracksplit -> assert FLAC tags."""
    src = _fixture_mkv(key)
    if src is None:
        pytest.skip(f"fixture MKV missing: {FIXTURES[key]['filename']}")

    work = tmp_path / "work"
    work.mkdir()
    mkv = work / src.name
    shutil.copy2(src, mkv)

    _cratedigger_identify(mkv, FIXTURES[key]["tracklist_id"])
    _cratedigger_enrich(mkv)

    out = tmp_path / "out"
    out.mkdir()
    _tracksplit_run(mkv, out)

    flacs = _collect_flacs(out)
    assert flacs, "TrackSplit produced no FLAC output"

    first = FLAC(flacs[0])

    expected_aa = FIXTURES[key].get("expect_albumartists")
    if expected_aa is not None:
        assert list(first.get("ALBUMARTISTS", [])) == expected_aa

    expected_aa_contains = FIXTURES[key].get("expect_albumartists_contains")
    if expected_aa_contains is not None:
        aa = list(first.get("ALBUMARTISTS", []))
        for name in expected_aa_contains:
            assert any(name in v for v in aa), (
                f"{name!r} not found in ALBUMARTISTS={aa!r}"
            )

    if FIXTURES[key].get("expect_albumartist_mbids_any"):
        mbids = list(first.get("MUSICBRAINZ_ALBUMARTISTID", []))
        assert any(m for m in mbids), (
            f"expected at least one album-artist MBID, got {mbids!r}"
        )
        assert len(mbids) == len(list(first.get("ALBUMARTISTS", [])))

    saw_multi_artist_track = False
    for p in flacs:
        audio = FLAC(p)
        artists = list(audio.get("ARTISTS", []))
        mbids = list(audio.get("MUSICBRAINZ_ARTISTID", []))
        if artists and mbids:
            assert len(mbids) == len(artists), (
                f"{p.name}: ARTISTS={artists!r} MUSICBRAINZ_ARTISTID={mbids!r}"
            )
        if len(artists) > 1:
            saw_multi_artist_track = True
        assert len(list(audio.get("ARTIST", []))) == 1, (
            f"{p.name}: ARTIST must be single-valued"
        )
        titles = list(audio.get("TITLE", []))
        assert len(titles) == 1 and titles[0].strip(), f"{p.name}: bad TITLE"

    if FIXTURES[key].get("expect_per_track_artists_some_multi"):
        assert saw_multi_artist_track, (
            "expected at least one track with >1 ARTISTS in this fixture"
        )
