"""Tests for tracksplit.log (per-command log files with MemoryHandler buffer)."""
from __future__ import annotations

import logging
import logging.handlers
import re
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from tracksplit.log import _cleanup_old_logs, setup_logging


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_logger() -> None:
    """Remove all handlers from the tracksplit logger."""
    logger = logging.getLogger("tracksplit")
    for h in list(logger.handlers):
        try:
            h.close()
        except Exception:
            pass
    logger.handlers.clear()


def _mock_paths(tmp_path: Path):
    """Return a patch context that mocks tracksplit.log.paths.

    The mock provides:
    - log_dir() returning tmp_path
    - ensure_parent as a passthrough (creates parent dirs)
    """
    patcher = patch("tracksplit.log.paths")
    mock = patcher.start()
    mock.log_dir.return_value = tmp_path
    mock.ensure_parent.side_effect = lambda p: (
        p.parent.mkdir(parents=True, exist_ok=True),
        p,
    )[1]
    return patcher, mock


# ---------------------------------------------------------------------------
# _cleanup_old_logs
# ---------------------------------------------------------------------------

class TestCleanupOldLogs:
    def test_deletes_old_log_files(self, tmp_path: Path) -> None:
        old_log = tmp_path / "tracksplit-old.log"
        old_log.write_text("old data")
        # Back-date the file by 10 days
        ten_days_ago = time.time() - 10 * 86400
        import os
        os.utime(old_log, (ten_days_ago, ten_days_ago))

        _cleanup_old_logs(tmp_path, max_age_days=7)
        assert not old_log.exists()

    def test_keeps_recent_log_files(self, tmp_path: Path) -> None:
        recent_log = tmp_path / "tracksplit-recent.log"
        recent_log.write_text("recent data")

        _cleanup_old_logs(tmp_path, max_age_days=7)
        assert recent_log.exists()

    def test_ignores_non_log_files(self, tmp_path: Path) -> None:
        txt_file = tmp_path / "notes.txt"
        txt_file.write_text("keep me")
        ten_days_ago = time.time() - 10 * 86400
        import os
        os.utime(txt_file, (ten_days_ago, ten_days_ago))

        _cleanup_old_logs(tmp_path, max_age_days=7)
        assert txt_file.exists()

    def test_ignores_missing_directory(self) -> None:
        """Should not raise when the directory does not exist."""
        _cleanup_old_logs(Path("/nonexistent/path/that/does/not/exist"))


# ---------------------------------------------------------------------------
# setup_logging
# ---------------------------------------------------------------------------

class TestSetupLogging:
    def setup_method(self) -> None:
        _reset_logger()

    def teardown_method(self) -> None:
        _reset_logger()

    def test_returns_path(self, tmp_path: Path) -> None:
        patcher, mock = _mock_paths(tmp_path)
        try:
            result = setup_logging(command="split")
            assert result is not None
            assert isinstance(result, Path)
        finally:
            patcher.stop()

    def test_per_command_filename_format(self, tmp_path: Path) -> None:
        patcher, mock = _mock_paths(tmp_path)
        try:
            result = setup_logging(command="split")
            assert result is not None
            # Expected: split-YYYY-MM-DDTHH-MM-SS-XXXX.log
            pattern = r"^split-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-[0-9a-f]{4}\.log$"
            assert re.match(pattern, result.name), (
                f"Filename {result.name!r} does not match expected pattern"
            )
        finally:
            patcher.stop()

    def test_default_command_uses_tracksplit(self, tmp_path: Path) -> None:
        patcher, mock = _mock_paths(tmp_path)
        try:
            result = setup_logging()
            assert result is not None
            assert result.name.startswith("tracksplit-")
        finally:
            patcher.stop()

    def test_memory_handler_wraps_file_handler(self, tmp_path: Path) -> None:
        patcher, mock = _mock_paths(tmp_path)
        try:
            setup_logging(command="test")
            logger = logging.getLogger("tracksplit")
            mem_handlers = [
                h for h in logger.handlers
                if isinstance(h, logging.handlers.MemoryHandler)
            ]
            assert len(mem_handlers) == 1
            mh = mem_handlers[0]
            assert mh.capacity == 50
            assert mh.flushLevel == logging.WARNING
            assert mh.flushOnClose is True
            assert isinstance(mh.target, logging.FileHandler)
        finally:
            patcher.stop()

    def test_file_handler_uses_delayed_open(self, tmp_path: Path) -> None:
        patcher, mock = _mock_paths(tmp_path)
        try:
            setup_logging(command="test")
            logger = logging.getLogger("tracksplit")
            mh = next(
                h for h in logger.handlers
                if isinstance(h, logging.handlers.MemoryHandler)
            )
            assert mh.target.delay is True
        finally:
            patcher.stop()

    def test_returns_none_on_oserror(self, tmp_path: Path) -> None:
        patcher, mock = _mock_paths(tmp_path)
        mock.ensure_parent.side_effect = PermissionError("read-only filesystem")
        try:
            result = setup_logging(command="fail")
            assert result is None
        finally:
            patcher.stop()

    def test_closes_existing_handlers_on_repeated_calls(self, tmp_path: Path) -> None:
        patcher, mock = _mock_paths(tmp_path)
        try:
            setup_logging(command="first")
            logger = logging.getLogger("tracksplit")
            first_handlers = list(logger.handlers)
            assert len(first_handlers) > 0

            setup_logging(command="second")
            # All first-call handlers should have been closed
            for h in first_handlers:
                if isinstance(h, logging.handlers.MemoryHandler):
                    # MemoryHandler.target should be closed
                    target = h.target
                    if hasattr(target, "stream") and target.stream is not None:
                        assert target.stream.closed
        finally:
            patcher.stop()

    def test_console_level_debug(self, tmp_path: Path) -> None:
        patcher, mock = _mock_paths(tmp_path)
        try:
            setup_logging(debug=True, command="test")
            logger = logging.getLogger("tracksplit")
            console_handler = next(
                h for h in logger.handlers
                if isinstance(h, logging.StreamHandler)
                and not isinstance(h, (logging.FileHandler, logging.handlers.MemoryHandler))
            )
            assert console_handler.level == logging.DEBUG
        finally:
            patcher.stop()

    def test_console_level_info_when_verbose(self, tmp_path: Path) -> None:
        patcher, mock = _mock_paths(tmp_path)
        try:
            setup_logging(verbose=True, command="test")
            logger = logging.getLogger("tracksplit")
            console_handler = next(
                h for h in logger.handlers
                if isinstance(h, logging.StreamHandler)
                and not isinstance(h, (logging.FileHandler, logging.handlers.MemoryHandler))
            )
            assert console_handler.level == logging.INFO
        finally:
            patcher.stop()

    def test_console_level_warning_default(self, tmp_path: Path) -> None:
        patcher, mock = _mock_paths(tmp_path)
        try:
            setup_logging(command="test")
            logger = logging.getLogger("tracksplit")
            console_handler = next(
                h for h in logger.handlers
                if isinstance(h, logging.StreamHandler)
                and not isinstance(h, (logging.FileHandler, logging.handlers.MemoryHandler))
            )
            assert console_handler.level == logging.WARNING
        finally:
            patcher.stop()

    def test_logger_level_always_debug(self, tmp_path: Path) -> None:
        patcher, mock = _mock_paths(tmp_path)
        try:
            setup_logging(command="test")
            logger = logging.getLogger("tracksplit")
            assert logger.level == logging.DEBUG
        finally:
            patcher.stop()
