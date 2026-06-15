"""Tests for the tracked_run subprocess wrapper."""

from __future__ import annotations

import logging
import subprocess
import sys
import threading

import pytest

from tracksplit.subprocess_utils import CancelledError, tracked_run


def test_tracked_run_no_log_on_success(caplog):
    """Successful runs produce no log output."""
    cmd = [sys.executable, "-c", "pass"]
    with caplog.at_level(logging.DEBUG, logger="tracksplit.subprocess"):
        result = tracked_run(cmd, timeout=10)
    assert result.returncode == 0
    assert len(caplog.records) == 0


def test_tracked_run_logs_nonzero_exit_structured(caplog):
    """Non-zero exit logs structured subprocess.exit event."""
    cmd = [
        sys.executable,
        "-c",
        "import sys; sys.stderr.write('boom-marker'); sys.exit(3)",
    ]
    with caplog.at_level(logging.DEBUG, logger="tracksplit.subprocess"):
        with pytest.raises(subprocess.CalledProcessError):
            tracked_run(cmd, timeout=10)
    assert len(caplog.records) == 1
    msg = caplog.records[0].message
    assert msg.startswith("subprocess.exit:")
    assert "code=3" in msg
    assert "boom-marker" in msg


def test_tracked_run_logs_timeout_structured(caplog):
    """Timeout logs structured subprocess.timeout event at WARNING."""
    cmd = [sys.executable, "-c", "import time; time.sleep(5)"]
    with caplog.at_level(logging.DEBUG, logger="tracksplit.subprocess"):
        with pytest.raises(subprocess.TimeoutExpired):
            tracked_run(cmd, timeout=0.2)
    messages = [r.message for r in caplog.records]
    assert any(m.startswith("subprocess.timeout:") for m in messages)
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_records) >= 1


def test_tracked_run_logs_cancel_before_start_structured(caplog):
    """Cancel before start logs structured subprocess.cancel event."""
    cmd = [sys.executable, "-c", "pass"]
    ev = threading.Event()
    ev.set()
    with caplog.at_level(logging.DEBUG, logger="tracksplit.subprocess"):
        with pytest.raises(CancelledError):
            tracked_run(cmd, cancel_event=ev, timeout=10)
    messages = [r.message for r in caplog.records]
    assert any("subprocess.cancel:" in m and "before_start" in m for m in messages)


def test_tracked_run_logs_interrupted_as_cancel(caplog):
    """Non-cancel exception during communicate logs subprocess.cancel with error type."""
    from unittest.mock import patch as _patch

    cmd = [sys.executable, "-c", "import time; time.sleep(5)"]

    def _raise_oserror(self, *args, **kwargs):
        raise OSError("simulated pipe failure")

    with caplog.at_level(logging.DEBUG, logger="tracksplit.subprocess"):
        with _patch("subprocess.Popen.communicate", _raise_oserror):
            with pytest.raises(OSError, match="simulated pipe failure"):
                tracked_run(cmd, timeout=10)
    messages = [r.message for r in caplog.records]
    assert any("subprocess.cancel:" in m and "OSError" in m for m in messages)
