"""Tests for the CrateDigger config reader and alias resolvers."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tracksplit.cratedigger import (
    CrateDiggerConfig,
    apply_cratedigger_canon,
    find_cratedigger_dirs,
    load_config,
)


@pytest.fixture
def cd_home(tmp_path: Path) -> Path:
    """Create a ``~/.cratedigger`` fixture with representative config."""
    home = tmp_path / "home"
    cd = home / ".cratedigger"
    cd.mkdir(parents=True)
    (cd / "festivals.json").write_text(json.dumps({
        "_comment": "test",
        "ASOT": {"aliases": ["A State Of Trance Festival", "A State Of Trance"]},
        "Tomorrowland": {
            "aliases": ["TML", "Tomorrowland Weekend 1"],
            "editions": {
                "Brasil": {},
                "Winter": {"aliases": ["TML Winter"]},
            },
        },
        "UMF": {
            "aliases": ["Ultra"],
            "editions": {"Europe": {}, "Miami": {"aliases": ["UMF Miami"]}},
        },
        "Awakenings": {},
    }))
    (cd / "artists.json").write_text(json.dumps({
        "aliases": {
            "Deadmau5": ["deadmau5", "Testpilot"],
            "David Guetta": ["Jack Back"],
        },
        "groups": ["Swedish House Mafia"],
    }))
    (cd / "dj_cache.json").write_text(json.dumps({
        "tiesto": {
            "name": "Tiësto",
            "aliases": [
                {"slug": "verwest", "name": "VER:WEST"},
                {"slug": "allurenl", "name": "Allure"},
            ],
            "member_of": [],
        },
        "martingarrix": {
            "name": "Martin Garrix",
            "aliases": [{"slug": "ytram", "name": "YTRAM"}],
            "member_of": [{"slug": "area21", "name": "AREA21"}],
        },
        # Conflict with artists.json: dj_cache says Deadmau5's alias maps to
        # something else. artists.json should win.
        "othermau5": {
            "name": "Someone Else",
            "aliases": [{"slug": "testpilot", "name": "Testpilot"}],
            "member_of": [],
        },
    }))
    (cd / "mbid_cache.json").write_text(json.dumps({
        "Deadmau5": "2f9ecbed-27be-40e6-abca-6de49d50299e",
        "David Guetta": {"mbid": "abc-123"},
    }))
    return home


@pytest.fixture
def cfg(cd_home: Path) -> CrateDiggerConfig:
    return load_config(cd_home / "video.mkv", home_dir=cd_home)


class TestResolveFestival:
    def test_simple_alias(self, cfg):
        assert cfg.resolve_festival("TML") == ("Tomorrowland", "")

    def test_alias_is_weekend(self, cfg):
        assert cfg.resolve_festival("Tomorrowland Weekend 1") == ("Tomorrowland", "")

    def test_edition_suffix(self, cfg):
        assert cfg.resolve_festival("Tomorrowland Winter") == ("Tomorrowland", "Winter")

    def test_edition_alias(self, cfg):
        assert cfg.resolve_festival("TML Winter") == ("Tomorrowland", "Winter")

    def test_long_alias_for_canon(self, cfg):
        assert cfg.resolve_festival("A State Of Trance Festival") == ("ASOT", "")

    def test_unknown_passes_through(self, cfg):
        assert cfg.resolve_festival("Unknown Fest") == ("Unknown Fest", "")

    def test_alias_prefixed_edition(self, cfg):
        # "Ultra" is alias for UMF; "Ultra Europe" should resolve to UMF Europe.
        assert cfg.resolve_festival("Ultra Europe") == ("UMF", "Europe")

    def test_case_insensitive_alias(self, cfg):
        assert cfg.resolve_festival("tml") == ("Tomorrowland", "")

    def test_empty(self, cfg):
        assert cfg.resolve_festival("") == ("", "")

    def test_canonical_is_idempotent(self, cfg):
        assert cfg.resolve_festival("Tomorrowland") == ("Tomorrowland", "")


class TestFestivalDisplay:
    def test_no_edition(self, cfg):
        assert cfg.festival_display("Tomorrowland", "") == "Tomorrowland"

    def test_with_edition(self, cfg):
        assert cfg.festival_display("Tomorrowland", "Winter") == "Tomorrowland Winter"

    def test_unknown_edition_ignored(self, cfg):
        assert cfg.festival_display("Tomorrowland", "Fake") == "Tomorrowland"

    def test_empty_canonical(self, cfg):
        assert cfg.festival_display("", "") == ""


class TestResolveArtist:
    def test_alias(self, cfg):
        assert cfg.resolve_artist("deadmau5") == "Deadmau5"

    def test_alias_case_insensitive(self, cfg):
        assert cfg.resolve_artist("DEADMAU5") == "Deadmau5"

    def test_different_alias_target(self, cfg):
        assert cfg.resolve_artist("Jack Back") == "David Guetta"

    def test_unknown_passes_through(self, cfg):
        assert cfg.resolve_artist("Avicii") == "Avicii"

    def test_empty(self, cfg):
        assert cfg.resolve_artist("") == ""

    def test_dj_cache_alias(self, cfg):
        assert cfg.resolve_artist("VER:WEST") == "Tiësto"

    def test_dj_cache_alias_case_insensitive(self, cfg):
        assert cfg.resolve_artist("ver:west") == "Tiësto"

    def test_dj_cache_secondary_alias(self, cfg):
        assert cfg.resolve_artist("YTRAM") == "Martin Garrix"

    def test_manual_artists_json_beats_dj_cache(self, cfg):
        # dj_cache maps "Testpilot" -> "Someone Else" but artists.json maps
        # it to "Deadmau5". Manual config wins.
        assert cfg.resolve_artist("Testpilot") == "Deadmau5"

    def test_diacritics_fallback_via_canonical(self, cfg):
        # Raw tag lacks diacritics; canonical in dj_cache has them.
        assert cfg.resolve_artist("Tiesto") == "Tiësto"

    def test_diacritics_fallback_preserves_unknown(self, cfg):
        # Unknown artist with no near match returns unchanged.
        assert cfg.resolve_artist("Kolsch") == "Kolsch"


class TestLookupMbid:
    def test_direct_hit(self, cfg):
        assert cfg.lookup_mbid("Deadmau5") == "2f9ecbed-27be-40e6-abca-6de49d50299e"

    def test_dict_entry(self, cfg):
        assert cfg.lookup_mbid("David Guetta") == "abc-123"

    def test_case_insensitive(self, cfg):
        assert cfg.lookup_mbid("deadmau5") == "2f9ecbed-27be-40e6-abca-6de49d50299e"

    def test_missing(self, cfg):
        assert cfg.lookup_mbid("Nobody") == ""

    def test_empty(self, cfg):
        assert cfg.lookup_mbid("") == ""


def test_fill_mbids_gap_fills_empties():
    from tracksplit.cratedigger import CrateDiggerConfig
    cfg = CrateDiggerConfig(mbid_cache={
        "Alle Farben": "mbid-af",
        "JOA": "mbid-joa",
    })
    names = ["Armin van Buuren", "Alle Farben", "JOA"]
    mbids = ["mbid-arm", "", ""]
    filled = cfg.fill_mbids(names, mbids)
    assert filled == ["mbid-arm", "mbid-af", "mbid-joa"]


def test_fill_mbids_leaves_unknown_empty():
    from tracksplit.cratedigger import CrateDiggerConfig
    cfg = CrateDiggerConfig(mbid_cache={"A": "mbid-a"})
    filled = cfg.fill_mbids(["A", "B"], ["", ""])
    assert filled == ["mbid-a", ""]


def test_fill_mbids_pads_shorter_mbid_list():
    from tracksplit.cratedigger import CrateDiggerConfig
    cfg = CrateDiggerConfig(mbid_cache={"B": "mbid-b"})
    filled = cfg.fill_mbids(["A", "B", "C"], ["mbid-a"])
    assert filled == ["mbid-a", "mbid-b", ""]


def test_fill_mbids_truncates_longer_mbid_list():
    from tracksplit.cratedigger import CrateDiggerConfig
    cfg = CrateDiggerConfig()
    filled = cfg.fill_mbids(["A"], ["mbid-a", "extra"])
    assert filled == ["mbid-a"]


def test_fill_mbids_does_not_overwrite_existing():
    from tracksplit.cratedigger import CrateDiggerConfig
    cfg = CrateDiggerConfig(mbid_cache={"A": "mbid-cache"})
    filled = cfg.fill_mbids(["A"], ["mbid-existing"])
    assert filled == ["mbid-existing"]


class TestFindCratediggerDirs:
    def test_finds_global(self, cd_home: Path):
        dirs = find_cratedigger_dirs(cd_home / "video.mkv", home_dir=cd_home)
        assert dirs == [cd_home / ".cratedigger"]

    def test_walks_up_to_local(self, tmp_path: Path, cd_home: Path):
        project = tmp_path / "proj"
        local = project / ".cratedigger"
        local.mkdir(parents=True)
        dirs = find_cratedigger_dirs(project / "sub" / "video.mkv", home_dir=cd_home)
        # Global first, then local found by walk-up.
        assert dirs[0] == cd_home / ".cratedigger"
        assert local in dirs

    def test_missing_home_no_crash(self, tmp_path: Path):
        dirs = find_cratedigger_dirs(tmp_path / "video.mkv", home_dir=tmp_path)
        assert dirs == []


class TestApplyCratediggerCanon:
    def test_rewrites_festival_and_artist(self, cd_home: Path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: cd_home)
        tags = {
            "artist": "deadmau5",
            "festival": "TML",
        }
        apply_cratedigger_canon(tags, cd_home / "video.mkv")
        assert tags["artist"] == "Deadmau5"
        assert tags["festival"] == "Tomorrowland"
        assert tags["edition"] == ""

    def test_edition_included_in_display(self, cd_home: Path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: cd_home)
        tags = {"artist": "Armin van Buuren", "festival": "Tomorrowland Winter"}
        apply_cratedigger_canon(tags, cd_home / "video.mkv")
        assert tags["festival"] == "Tomorrowland Winter"
        assert tags["edition"] == "Winter"

    def test_no_config_noop(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        tags = {"artist": "SomeArtist", "festival": "Some Fest"}
        apply_cratedigger_canon(tags, tmp_path / "video.mkv")
        assert tags["artist"] == "SomeArtist"
        assert tags["festival"] == "Some Fest"
        assert tags["edition"] == ""

    def test_malformed_json_survives(self, tmp_path: Path, monkeypatch):
        home = tmp_path / "home"
        cd = home / ".cratedigger"
        cd.mkdir(parents=True)
        (cd / "festivals.json").write_text("{ not valid json")
        monkeypatch.setattr(Path, "home", lambda: home)
        tags = {"artist": "A", "festival": "F"}
        # Should not raise; malformed files are skipped.
        apply_cratedigger_canon(tags, home / "video.mkv")
        assert tags["festival"] == "F"
