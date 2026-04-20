"""Unit tests for tracksplit.update_check. No real HTTP is performed."""
from __future__ import annotations

import json
import time

import pytest

from tracksplit.update_check import (
    SCHEMA_VERSION,
    _cache_is_fresh,
    _cache_path,
    _is_newer,
    _is_prerelease_string,
    _read_cache,
    _write_cache,
)


def test_module_imports():
    from tracksplit import update_check
    assert update_check.PACKAGE_NAME == "tracksplit"
    assert update_check.ENV_VAR == "TRACKSPLIT_NO_UPDATE_CHECK"


class TestIsNewer:
    def test_patch_bump(self):
        assert _is_newer(installed="0.6.7", candidate="0.6.8")

    def test_minor_bump(self):
        assert _is_newer(installed="0.6.7", candidate="0.7.0")

    def test_major_bump(self):
        assert _is_newer(installed="0.6.7", candidate="1.0.0")

    def test_equal(self):
        assert not _is_newer(installed="0.6.7", candidate="0.6.7")

    def test_older(self):
        assert not _is_newer(installed="0.6.7", candidate="0.6.6")

    def test_numeric_not_lexicographic(self):
        assert _is_newer(installed="0.6.7", candidate="0.6.10")
        assert _is_newer(installed="0.9.0", candidate="0.10.0")

    def test_malformed_returns_false(self):
        assert not _is_newer(installed="0.6.7", candidate="weird")
        assert not _is_newer(installed="weird", candidate="0.6.7")


class TestIsPrereleaseString:
    @pytest.mark.parametrize("v", ["0.7.0rc1", "0.7.0a1", "0.7.0b2",
                                   "0.7.0.dev1", "0.7.0-rc.1", "0.7.0.post1"])
    def test_prerelease(self, v):
        assert _is_prerelease_string(v)

    @pytest.mark.parametrize("v", ["0.7.0", "1.0.0", "0.6.7"])
    def test_stable(self, v):
        assert not _is_prerelease_string(v)


class TestCachePath:
    def test_linux_uses_xdg(self, monkeypatch, tmp_path):
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        p = _cache_path()
        assert p == tmp_path / "tracksplit" / "update-check.json"

    def test_linux_fallback_home_cache(self, monkeypatch, tmp_path):
        monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        p = _cache_path()
        assert p == tmp_path / ".cache" / "tracksplit" / "update-check.json"

    def test_windows_uses_localappdata(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        p = _cache_path()
        assert p == tmp_path / "tracksplit" / "update-check.json"


class TestReadWriteCache:
    def test_write_then_read(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        _write_cache(latest_version="0.7.0", ttl_seconds=86400)
        entry = _read_cache()
        assert entry is not None
        assert entry["latest_version"] == "0.7.0"
        assert entry["ttl_seconds"] == 86400
        assert entry["schema"] == SCHEMA_VERSION
        assert "checked_at" in entry

    def test_read_missing_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        assert _read_cache() is None

    def test_read_corrupt_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        p = _cache_path()
        p.parent.mkdir(parents=True)
        p.write_text("not json {{{")
        assert _read_cache() is None

    def test_read_unknown_schema_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        p = _cache_path()
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({"schema": 999, "latest_version": "0.7.0"}))
        assert _read_cache() is None

    def test_write_is_atomic(self, tmp_path, monkeypatch):
        """_write_cache must write to a temp file and rename; a crash mid-write
        must never leave the final file in a corrupted state."""
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        _write_cache(latest_version="0.7.0", ttl_seconds=86400)
        p = _cache_path()
        assert p.exists()
        leftovers = [x for x in p.parent.iterdir() if x.name != p.name]
        assert leftovers == []


class TestCacheIsFresh:
    def test_fresh_recent(self):
        entry = {"checked_at": int(time.time()) - 1000, "ttl_seconds": 86400}
        assert _cache_is_fresh(entry)

    def test_stale_expired(self):
        entry = {"checked_at": int(time.time()) - 100_000, "ttl_seconds": 86400}
        assert not _cache_is_fresh(entry)

    def test_missing_fields_not_fresh(self):
        assert not _cache_is_fresh({"ttl_seconds": 86400})
        assert not _cache_is_fresh({"checked_at": 0})
        assert not _cache_is_fresh({})


class TestFetchLatestRelease:
    def _fake_response(self, body: bytes):
        from io import BytesIO
        r = BytesIO(body)
        return r

    def test_success(self):
        from unittest.mock import patch

        from tracksplit.update_check import _fetch_latest_release
        payload = b'{"tag_name": "v0.7.0"}'
        with patch("tracksplit.update_check.urlopen", return_value=self._fake_response(payload)):
            assert _fetch_latest_release() == "0.7.0"

    def test_strips_single_leading_v(self):
        from unittest.mock import patch

        from tracksplit.update_check import _fetch_latest_release
        payload = b'{"tag_name": "v1.0.0"}'
        with patch("tracksplit.update_check.urlopen", return_value=self._fake_response(payload)):
            assert _fetch_latest_release() == "1.0.0"

    def test_no_leading_v(self):
        from unittest.mock import patch

        from tracksplit.update_check import _fetch_latest_release
        payload = b'{"tag_name": "0.7.0"}'
        with patch("tracksplit.update_check.urlopen", return_value=self._fake_response(payload)):
            assert _fetch_latest_release() == "0.7.0"

    def test_timeout_returns_none(self):
        from unittest.mock import patch

        from tracksplit.update_check import _fetch_latest_release
        with patch("tracksplit.update_check.urlopen", side_effect=TimeoutError()):
            assert _fetch_latest_release() is None

    def test_url_error_returns_none(self):
        from unittest.mock import patch
        from urllib.error import URLError

        from tracksplit.update_check import _fetch_latest_release
        with patch("tracksplit.update_check.urlopen", side_effect=URLError("dns")):
            assert _fetch_latest_release() is None

    def test_http_error_returns_none(self):
        from unittest.mock import patch
        from urllib.error import HTTPError

        from tracksplit.update_check import _fetch_latest_release
        err = HTTPError("u", 500, "boom", {}, None)  # type: ignore[arg-type]
        with patch("tracksplit.update_check.urlopen", side_effect=err):
            assert _fetch_latest_release() is None

    def test_malformed_json_returns_none(self):
        from unittest.mock import patch

        from tracksplit.update_check import _fetch_latest_release
        with patch("tracksplit.update_check.urlopen", return_value=self._fake_response(b"not json")):
            assert _fetch_latest_release() is None

    def test_missing_tag_returns_none(self):
        from unittest.mock import patch

        from tracksplit.update_check import _fetch_latest_release
        with patch("tracksplit.update_check.urlopen", return_value=self._fake_response(b"{}")):
            assert _fetch_latest_release() is None

    def test_prerelease_returns_none(self):
        from unittest.mock import patch

        from tracksplit.update_check import _fetch_latest_release
        payload = b'{"tag_name": "v0.7.0rc1"}'
        with patch("tracksplit.update_check.urlopen", return_value=self._fake_response(payload)):
            assert _fetch_latest_release() is None

    def test_malformed_tag_returns_none(self):
        from unittest.mock import patch

        from tracksplit.update_check import _fetch_latest_release
        payload = b'{"tag_name": "bogus"}'
        with patch("tracksplit.update_check.urlopen", return_value=self._fake_response(payload)):
            assert _fetch_latest_release() is None
