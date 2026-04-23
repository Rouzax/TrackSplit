"""Tests for the CrateDigger config reader and alias resolvers."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tracksplit.cratedigger import (
    CrateDiggerConfig,
    _clear_config_cache,
    apply_cratedigger_canon,
    find_cratedigger_dirs,
    load_config,
)


@pytest.fixture(autouse=True)
def _reset_cratedigger_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.delenv("CRATEDIGGER_DATA_DIR", raising=False)
    cache = tmp_path / "cd_cache"
    cache.mkdir(exist_ok=True)
    monkeypatch.setattr(
        "tracksplit.paths.cratedigger_cache_dir", lambda: cache,
    )
    cd_visible = tmp_path / "cd_visible_data"
    cd_visible.mkdir(exist_ok=True)
    monkeypatch.setattr(
        "tracksplit.paths.cratedigger_data_dir", lambda: cd_visible,
    )
    _clear_config_cache()
    yield
    _clear_config_cache()


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
    cache = tmp_path / "cd_cache"
    cache.mkdir(exist_ok=True)
    (cache / "dj_cache.json").write_text(json.dumps({
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
    (cache / "mbid_cache.json").write_text(json.dumps({
        "Deadmau5": "2f9ecbed-27be-40e6-abca-6de49d50299e",
        "David Guetta": {"mbid": "abc-123"},
    }))
    return home


@pytest.fixture
def cfg(cd_home: Path) -> CrateDiggerConfig:
    return load_config(cd_home / "video.mkv")


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

    def test_canonical_fallback_is_deterministic_on_conflicting_configs(self):
        # Real-world scenario: dj_cache.json has {"name": "AFROJACK"} with
        # aliases NLW/Kapuchon, while artists.json also carries an "Afrojack"
        # canonical via its own alias. Both "AFROJACK" and "Afrojack" end up
        # as canonical values, folding to the same diacritics-insensitive
        # key. load_config inserts dj_cache entries before artists.json, so
        # the first-inserted canonical ("AFROJACK") must win every run.
        # Iterating with set() makes this non-deterministic because string
        # hashing is randomized per-process; the resolver must preserve
        # insertion order instead.
        cfg = CrateDiggerConfig(artist_aliases={
            "NLW": "AFROJACK",
            "Kapuchon": "AFROJACK",
            "SomeOtherAlias": "Afrojack",
        })
        assert cfg.resolve_artist("Afrojack") == "AFROJACK"


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
    def test_walkup_and_visible_both_returned(self, tmp_path: Path, monkeypatch):
        walkup_dir = tmp_path / "library" / ".cratedigger"
        walkup_dir.mkdir(parents=True)
        visible = tmp_path / "visible_cd"
        visible.mkdir()
        monkeypatch.setattr("tracksplit.paths.cratedigger_data_dir", lambda: visible)
        input_file = tmp_path / "library" / "videos" / "file.mkv"
        input_file.parent.mkdir(parents=True)
        input_file.touch()
        dirs = find_cratedigger_dirs(input_file)
        assert dirs == [walkup_dir, visible]

    def test_env_var_overrides_all(self, tmp_path: Path, monkeypatch):
        env_dir = tmp_path / "env_cd"
        env_dir.mkdir()
        monkeypatch.setenv("CRATEDIGGER_DATA_DIR", str(env_dir))
        walkup = tmp_path / "library" / ".cratedigger"
        walkup.mkdir(parents=True)
        input_file = tmp_path / "library" / "file.mkv"
        input_file.touch()
        dirs = find_cratedigger_dirs(input_file)
        assert dirs == [env_dir]

    def test_no_walkup_returns_visible_only(self, tmp_path: Path, monkeypatch):
        visible = tmp_path / "visible_cd"
        visible.mkdir()
        monkeypatch.setattr("tracksplit.paths.cratedigger_data_dir", lambda: visible)
        isolated = tmp_path / "isolated"
        isolated.mkdir()
        input_file = isolated / "file.mkv"
        input_file.touch()
        dirs = find_cratedigger_dirs(input_file)
        assert dirs == [visible]

    def test_deduplicates_when_walkup_equals_visible(self, tmp_path: Path, monkeypatch):
        cd_dir = tmp_path / "library" / ".cratedigger"
        cd_dir.mkdir(parents=True)
        monkeypatch.setattr("tracksplit.paths.cratedigger_data_dir", lambda: cd_dir)
        input_file = tmp_path / "library" / "file.mkv"
        input_file.touch()
        dirs = find_cratedigger_dirs(input_file)
        assert dirs == [cd_dir]

    def test_walk_up_integration(self, tmp_path: Path, monkeypatch):
        monkeypatch.delenv("CRATEDIGGER_DATA_DIR", raising=False)
        library = tmp_path / "library"
        cd_dir = library / ".cratedigger"
        cd_dir.mkdir(parents=True)
        input_file = library / "videos" / "file.mkv"
        input_file.parent.mkdir(parents=True)
        input_file.touch()
        dirs = find_cratedigger_dirs(input_file)
        assert cd_dir in dirs


class TestCacheVsDataSplit:
    """Cache files (dj_cache, mbid_cache) come from CrateDigger's platformdirs
    cache dir, not from the curated data dir."""

    def test_dj_cache_read_from_cache_dir(self, tmp_path: Path, monkeypatch):
        data_dir = tmp_path / "data" / ".cratedigger"
        data_dir.mkdir(parents=True)
        (data_dir / "festivals.json").write_text("{}")
        (data_dir / "artists.json").write_text("{}")
        (data_dir / "dj_cache.json").write_text(json.dumps({
            "wrong": {"name": "ShouldNotAppear", "aliases": [], "member_of": []},
        }))
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        (cache_dir / "dj_cache.json").write_text(json.dumps({
            "right": {"name": "Correct", "aliases": [{"slug": "a", "name": "Alias"}], "member_of": []},
        }))
        monkeypatch.setattr(
            "tracksplit.paths.cratedigger_cache_dir", lambda: cache_dir,
        )
        monkeypatch.setattr(
            "tracksplit.paths.walkup_cratedigger_dir",
            lambda _: data_dir,
        )
        cfg = load_config(tmp_path / "v.mkv")
        assert cfg.artist_aliases.get("Alias") == "Correct"
        assert "ShouldNotAppear" not in cfg.artist_aliases.values()

    def test_mbid_cache_read_from_cache_dir(self, tmp_path: Path, monkeypatch):
        data_dir = tmp_path / "data" / ".cratedigger"
        data_dir.mkdir(parents=True)
        (data_dir / "festivals.json").write_text("{}")
        (data_dir / "artists.json").write_text("{}")
        (data_dir / "mbid_cache.json").write_text(json.dumps({"Wrong": "wrong-mbid"}))
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        (cache_dir / "mbid_cache.json").write_text(json.dumps({"Right": "correct-mbid"}))
        monkeypatch.setattr(
            "tracksplit.paths.cratedigger_cache_dir", lambda: cache_dir,
        )
        monkeypatch.setattr(
            "tracksplit.paths.walkup_cratedigger_dir",
            lambda _: data_dir,
        )
        cfg = load_config(tmp_path / "v.mkv")
        assert cfg.mbid_cache.get("Right") == "correct-mbid"
        assert "Wrong" not in cfg.mbid_cache


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


class TestLoadConfigCache:
    def test_same_dirs_return_same_object(self, cd_home: Path):
        cfg1 = load_config(cd_home / "a.mkv")
        cfg2 = load_config(cd_home / "b.mkv")
        assert cfg1 is cfg2

    def test_different_resolved_dirs_return_different_objects(
        self, cd_home: Path, tmp_path: Path
    ):
        """Different walk-up resolutions map to different cache entries.

        The old signature took ``home_dir=`` per call; post-refactor, differing
        inputs resolve to different ``.cratedigger`` dirs via the walk-up, which
        is what the cache key is built from.
        """
        other_home = tmp_path / "other"
        (other_home / ".cratedigger").mkdir(parents=True)
        cfg1 = load_config(cd_home / "v.mkv")
        cfg2 = load_config(other_home / "v.mkv")
        assert cfg1 is not cfg2

    def test_clear_cache_forces_reload(self, cd_home: Path):
        cfg1 = load_config(cd_home / "v.mkv")
        _clear_config_cache()
        cfg2 = load_config(cd_home / "v.mkv")
        assert cfg1 is not cfg2
        assert cfg1.artist_aliases == cfg2.artist_aliases


class TestLoadJsonNoise:
    def test_missing_files_do_not_log(self, tmp_path: Path, caplog):
        """A .cratedigger dir with no files should produce zero debug logs."""
        import logging
        home = tmp_path / "home"
        (home / ".cratedigger").mkdir(parents=True)
        with caplog.at_level(logging.DEBUG, logger="tracksplit.cratedigger"):
            load_config(home / "video.mkv")
        assert not any(
            "config read failed" in rec.message for rec in caplog.records
        )

    def test_malformed_json_logs_debug(self, tmp_path: Path, caplog):
        import logging
        home = tmp_path / "home"
        cd = home / ".cratedigger"
        cd.mkdir(parents=True)
        (cd / "festivals.json").write_text("{ not json")
        with caplog.at_level(logging.DEBUG, logger="tracksplit.cratedigger"):
            load_config(home / "video.mkv")
        assert any(
            "config read failed" in rec.message and "festivals.json" in rec.message
            for rec in caplog.records
        )
