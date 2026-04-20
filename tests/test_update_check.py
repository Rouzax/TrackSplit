"""Unit tests for tracksplit.update_check. No real HTTP is performed."""
from __future__ import annotations

import pytest

from tracksplit.update_check import _is_newer, _is_prerelease_string


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
