"""Tests for the tracked_run subprocess wrapper's DEBUG instrumentation."""
from __future__ import annotations

import logging
import subprocess
import sys
import threading

import pytest

from tracksplit.subprocess_utils import CancelledError, tracked_run


def test_tracked_run_logs_command_and_zero_exit(caplog):
    """Successful run emits DEBUG with argv command and exit 0."""
    cmd = [sys.executable, "-c", "pass"]
    with caplog.at_level(logging.DEBUG, logger="tracksplit.subprocess"):
        result = tracked_run(cmd, timeout=10)
    assert result.returncode == 0
    joined = "\n".join(r.message for r in caplog.records)
    assert sys.executable in joined
    assert "exit 0" in joined


def test_tracked_run_logs_stderr_tail_on_nonzero(caplog):
    """Non-zero exit logs DEBUG with returncode and stderr tail before raising."""
    cmd = [
        sys.executable,
        "-c",
        "import sys; sys.stderr.write('boom-distinct-marker'); sys.exit(3)",
    ]
    with caplog.at_level(logging.DEBUG, logger="tracksplit.subprocess"):
        with pytest.raises(subprocess.CalledProcessError):
            tracked_run(cmd, timeout=10)
    joined = "\n".join(r.message for r in caplog.records)
    assert "exit 3" in joined
    assert "boom-distinct-marker" in joined


def test_tracked_run_logs_timeout(caplog):
    """TimeoutExpired is logged at DEBUG before re-raising."""
    cmd = [sys.executable, "-c", "import time; time.sleep(5)"]
    with caplog.at_level(logging.DEBUG, logger="tracksplit.subprocess"):
        with pytest.raises(subprocess.TimeoutExpired):
            tracked_run(cmd, timeout=0.2)
    joined = "\n".join(r.message for r in caplog.records)
    assert "timed out" in joined


def test_tracked_run_logs_cancel(caplog):
    """CancelledError before start logs DEBUG and raises."""
    cmd = [sys.executable, "-c", "pass"]
    ev = threading.Event()
    ev.set()
    with caplog.at_level(logging.DEBUG, logger="tracksplit.subprocess"):
        with pytest.raises(CancelledError):
            tracked_run(cmd, cancel_event=ev, timeout=10)
    joined = "\n".join(r.message for r in caplog.records)
    assert "cancelled" in joined.lower()


def test_tracked_run_logs_command_with_args_quoted(caplog):
    """Argv with spaces renders as a shell-quoted single line, not a Python
    list repr, so the log reads like a shell command."""
    cmd = [sys.executable, "-c", "import sys; print(sys.argv)"]
    with caplog.at_level(logging.DEBUG, logger="tracksplit.subprocess"):
        tracked_run(cmd, timeout=10)
    joined = "\n".join(r.message for r in caplog.records)
    assert "import sys; print(sys.argv)" in joined or "'import sys" in joined
    # The "subprocess: " prefix line must not contain Python list-repr brackets.
    subprocess_lines = [r.message for r in caplog.records
                        if r.message.startswith("subprocess: ")]
    assert subprocess_lines, "no 'subprocess: ...' DEBUG line found"
    assert "[" not in subprocess_lines[0]


def test_tracked_run_logs_non_timeout_exception_during_communicate(caplog):
    """When communicate() raises a non-Timeout, non-Cancelled exception
    (e.g. OSError on a broken pipe), the BaseException branch must log
    with a descriptive, non-misleading message naming the exception
    class, and the exception must propagate."""
    from unittest.mock import patch as _patch

    cmd = [sys.executable, "-c", "import time; time.sleep(5)"]

    # Patch Popen.communicate to raise OSError, simulating a non-Timeout
    # failure of the wait (not the spawn). The outer tracked_run must log
    # and re-raise, and the log must not claim the process was "cancelled"
    # when it was actually just an exception during I/O.
    def _raise_oserror(self, *args, **kwargs):
        raise OSError("simulated pipe failure")

    with caplog.at_level(logging.DEBUG, logger="tracksplit.subprocess"):
        with _patch("subprocess.Popen.communicate", _raise_oserror):
            with pytest.raises(OSError, match="simulated pipe failure"):
                tracked_run(cmd, timeout=10)
    joined = "\n".join(r.message for r in caplog.records)
    # The message must not claim "cancelled" for a non-cancel exception.
    assert "cancelled (exception)" not in joined
    # It must name the exception class so the log reader knows what hit.
    assert "OSError" in joined
    assert "interrupted" in joined.lower()
