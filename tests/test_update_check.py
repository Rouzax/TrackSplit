"""Unit tests for tracksplit.update_check. No real HTTP is performed."""
from __future__ import annotations


def test_module_imports():
    from tracksplit import update_check
    assert update_check.PACKAGE_NAME == "tracksplit"
    assert update_check.ENV_VAR == "TRACKSPLIT_NO_UPDATE_CHECK"
