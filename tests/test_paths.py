"""Tests for tracksplit.paths platform-path resolution."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from tracksplit import paths


class TestDataDir:
    def test_windows_uses_documents_dir(self):
        with patch("tracksplit.paths.sys") as mock_sys, \
             patch("tracksplit.paths.platformdirs") as mock_pd:
            mock_sys.platform = "win32"
            mock_pd.user_documents_dir.return_value = "C:/Users/Name/Documents"
            result = paths.data_dir()
            assert result == Path("C:/Users/Name/Documents/TrackSplit")

    def test_non_windows_uses_home(self, tmp_path: Path):
        with patch("tracksplit.paths.sys") as mock_sys, \
             patch("tracksplit.paths.Path") as mock_path_cls:
            mock_sys.platform = "linux"
            # Path.home() is called only on non-win32
            mock_path_cls.home.return_value = tmp_path
            # Path(...) still constructs real Paths
            mock_path_cls.side_effect = lambda *a, **kw: Path(*a, **kw)
            result = paths.data_dir()
            assert result == tmp_path / "TrackSplit"


class TestConfigFile:
    def test_config_lives_in_data_dir(self, tmp_path: Path):
        with patch("tracksplit.paths.data_dir", return_value=tmp_path):
            assert paths.config_file() == tmp_path / "config.toml"


class TestCacheDir:
    def test_uses_platformdirs_user_cache_dir(self):
        with patch("tracksplit.paths.platformdirs") as mock_pd:
            mock_pd.user_cache_dir.return_value = "/fake/cache/TrackSplit"
            result = paths.cache_dir()
            mock_pd.user_cache_dir.assert_called_once_with("TrackSplit", appauthor=False)
            assert result == Path("/fake/cache/TrackSplit")


class TestLogFile:
    def test_uses_platformdirs_user_log_dir(self):
        with patch("tracksplit.paths.platformdirs") as mock_pd:
            mock_pd.user_log_dir.return_value = "/fake/log/TrackSplit"
            result = paths.log_file()
            mock_pd.user_log_dir.assert_called_once_with("TrackSplit", appauthor=False)
            assert result == Path("/fake/log/TrackSplit/tracksplit.log")


class TestEnsureParent:
    def test_creates_missing_parent_dirs(self, tmp_path: Path):
        target = tmp_path / "a" / "b" / "c" / "file.txt"
        result = paths.ensure_parent(target)
        assert target.parent.is_dir()
        assert result == target

    def test_is_idempotent_when_parent_exists(self, tmp_path: Path):
        target = tmp_path / "file.txt"
        paths.ensure_parent(target)
        paths.ensure_parent(target)
        assert tmp_path.is_dir()


class TestResolveCrateDiggerDataDir:
    def test_env_var_wins(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        cd_dir = tmp_path / "env_cd"
        cd_dir.mkdir()
        monkeypatch.setenv("CRATEDIGGER_DATA_DIR", str(cd_dir))
        result = paths.resolve_cratedigger_data_dir(tmp_path / "some.mkv")
        assert result == cd_dir

    def test_env_var_ignored_when_dir_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CRATEDIGGER_DATA_DIR", str(tmp_path / "does_not_exist"))
        isolated = tmp_path / "isolated"
        isolated.mkdir()
        with patch("tracksplit.paths.sys") as mock_sys, \
             patch.object(Path, "home", return_value=tmp_path):
            mock_sys.platform = "linux"
            result = paths.resolve_cratedigger_data_dir(isolated / "file.mkv")
            # env var pointing at missing dir is ignored; fallback to CrateDigger's visible data dir
            assert result == tmp_path / "CrateDigger"

    def test_walk_up_finds_library_local_cratedigger(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("CRATEDIGGER_DATA_DIR", raising=False)
        library_root = tmp_path / "library"
        cd_dir = library_root / ".cratedigger"
        cd_dir.mkdir(parents=True)
        input_file = library_root / "artist" / "album" / "show.mkv"
        input_file.parent.mkdir(parents=True)
        input_file.touch()
        result = paths.resolve_cratedigger_data_dir(input_file)
        assert result == cd_dir

    def test_walk_up_finds_at_exact_limit(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """`.cratedigger` at the 10th walked directory IS found (inclusive boundary)."""
        monkeypatch.delenv("CRATEDIGGER_DATA_DIR", raising=False)
        # input_file is 10 levels deep: tmp_path/l0/l1/.../l9/file.mkv
        # input.parent = l9, walk visits l9, l8, l7, ..., l0 = 10 dirs.
        deep = tmp_path
        for i in range(10):
            deep = deep / f"l{i}"
        deep.mkdir(parents=True)
        input_file = deep / "file.mkv"
        input_file.touch()
        # Place .cratedigger at l0 = the 10th (last) directory in the walk.
        cd_dir = tmp_path / "l0" / ".cratedigger"
        cd_dir.mkdir()
        result = paths.resolve_cratedigger_data_dir(input_file)
        assert result == cd_dir

    def test_walk_up_stops_beyond_limit(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """`.cratedigger` one level beyond the walk-up limit is NOT found."""
        monkeypatch.delenv("CRATEDIGGER_DATA_DIR", raising=False)
        # Same depth as above but .cratedigger is at tmp_path (11th walk position, not visited).
        deep = tmp_path
        for i in range(10):
            deep = deep / f"l{i}"
        deep.mkdir(parents=True)
        input_file = deep / "file.mkv"
        input_file.touch()
        cd_dir = tmp_path / ".cratedigger"
        cd_dir.mkdir()
        with patch("tracksplit.paths.sys") as mock_sys, \
             patch.object(Path, "home", return_value=tmp_path / "elsewhere"):
            mock_sys.platform = "linux"
            (tmp_path / "elsewhere").mkdir()
            result = paths.resolve_cratedigger_data_dir(input_file)
            assert result != cd_dir  # walk-up limit exceeded
            assert result == tmp_path / "elsewhere" / "CrateDigger"

    def test_platformdirs_fallback_windows_uses_documents(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("CRATEDIGGER_DATA_DIR", raising=False)
        isolated = tmp_path / "isolated"
        isolated.mkdir()
        input_file = isolated / "file.mkv"
        input_file.touch()
        with patch("tracksplit.paths.sys") as mock_sys, \
             patch("tracksplit.paths.platformdirs") as mock_pd:
            mock_sys.platform = "win32"
            mock_pd.user_documents_dir.return_value = "C:/Users/Name/Documents"
            result = paths.resolve_cratedigger_data_dir(input_file)
            assert result == Path("C:/Users/Name/Documents/CrateDigger")

    def test_platformdirs_fallback_linux_uses_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("CRATEDIGGER_DATA_DIR", raising=False)
        isolated = tmp_path / "isolated"
        isolated.mkdir()
        input_file = isolated / "file.mkv"
        input_file.touch()
        with patch("tracksplit.paths.sys") as mock_sys, \
             patch.object(Path, "home", return_value=tmp_path):
            mock_sys.platform = "linux"
            result = paths.resolve_cratedigger_data_dir(input_file)
            assert result == tmp_path / "CrateDigger"


class TestLegacyPathDetection:
    def test_detects_legacy_cache_home(self, tmp_path: Path):
        legacy = tmp_path / ".cache" / "tracksplit"
        legacy.mkdir(parents=True)
        (legacy / "update-check.json").write_text("{}")
        found = paths._legacy_paths_present(home=tmp_path)
        assert legacy in found

    def test_detects_legacy_tracksplit_toml_in_home(self, tmp_path: Path):
        legacy = tmp_path / "tracksplit.toml"
        legacy.write_text("")
        found = paths._legacy_paths_present(home=tmp_path)
        assert legacy in found

    def test_detects_legacy_dot_tracksplit_toml_in_home(self, tmp_path: Path):
        legacy = tmp_path / ".tracksplit.toml"
        legacy.write_text("")
        found = paths._legacy_paths_present(home=tmp_path)
        assert legacy in found

    def test_detects_legacy_config_tracksplit(self, tmp_path: Path):
        legacy = tmp_path / ".config" / "tracksplit" / "config.toml"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("")
        found = paths._legacy_paths_present(home=tmp_path)
        assert legacy in found

    def test_detects_legacy_cratedigger_home(self, tmp_path: Path):
        legacy = tmp_path / ".cratedigger"
        legacy.mkdir()
        found = paths._legacy_paths_present(home=tmp_path)
        assert legacy in found

    def test_empty_when_nothing_legacy(self, tmp_path: Path):
        assert paths._legacy_paths_present(home=tmp_path) == []

    def test_detects_legacy_windows_appdata_config(self, tmp_path: Path, monkeypatch):
        appdata = tmp_path / "AppData" / "Roaming"
        legacy = appdata / "tracksplit" / "config.toml"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("")
        monkeypatch.setenv("APPDATA", str(appdata))
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        with patch("tracksplit.paths.sys") as mock_sys:
            mock_sys.platform = "win32"
            found = paths._legacy_paths_present(home=tmp_path)
        assert legacy in found

    def test_detects_legacy_windows_appdata_tracksplit_toml(self, tmp_path: Path, monkeypatch):
        appdata = tmp_path / "AppData" / "Roaming"
        legacy = appdata / "tracksplit" / "tracksplit.toml"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("")
        monkeypatch.setenv("APPDATA", str(appdata))
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        with patch("tracksplit.paths.sys") as mock_sys:
            mock_sys.platform = "win32"
            found = paths._legacy_paths_present(home=tmp_path)
        assert legacy in found

    def test_detects_legacy_windows_localappdata_cache(self, tmp_path: Path, monkeypatch):
        localappdata = tmp_path / "AppData" / "Local"
        legacy = localappdata / "tracksplit"
        legacy.mkdir(parents=True)
        (legacy / "update-check.json").write_text("{}")
        monkeypatch.delenv("APPDATA", raising=False)
        monkeypatch.setenv("LOCALAPPDATA", str(localappdata))
        with patch("tracksplit.paths.sys") as mock_sys:
            mock_sys.platform = "win32"
            found = paths._legacy_paths_present(home=tmp_path)
        assert legacy in found

    def test_windows_paths_not_checked_on_linux(self, tmp_path: Path, monkeypatch):
        """APPDATA/LOCALAPPDATA env vars on Linux must not be treated as legacy."""
        monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
        (tmp_path / "appdata" / "tracksplit").mkdir(parents=True)
        (tmp_path / "appdata" / "tracksplit" / "config.toml").write_text("")
        with patch("tracksplit.paths.sys") as mock_sys:
            mock_sys.platform = "linux"
            found = paths._legacy_paths_present(home=tmp_path)
        assert not any("appdata" in str(p).lower() for p in found)


class TestWarnIfLegacyPathsExist:
    def test_warns_once_when_legacy_present(self, tmp_path: Path, caplog):
        legacy = tmp_path / ".cache" / "tracksplit"
        legacy.mkdir(parents=True)
        (legacy / "update-check.json").write_text("{}")
        with caplog.at_level("WARNING", logger="tracksplit.paths"):
            paths.warn_if_legacy_paths_exist(home=tmp_path)
        messages = [r.getMessage() for r in caplog.records]
        assert any(
            "legacy" in m.lower() or "old location" in m.lower()
            for m in messages
        )

    def test_silent_when_nothing_legacy(self, tmp_path: Path, caplog):
        with caplog.at_level("WARNING", logger="tracksplit.paths"):
            paths.warn_if_legacy_paths_exist(home=tmp_path)
        # Filter to only our logger's records so unrelated logs from module import don't trip us
        ours = [r for r in caplog.records if r.name == "tracksplit.paths"]
        assert ours == []
