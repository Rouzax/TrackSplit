"""Tests for tracksplit.log.setup_logging (CLI integration contract)."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path
from unittest.mock import patch

from tracksplit import log


def _reset_logger() -> None:
    """Remove all handlers from the tracksplit logger."""
    logger = logging.getLogger("tracksplit")
    for h in list(logger.handlers):
        try:
            h.close()
        except Exception:
            pass
    logger.handlers.clear()


class TestSetupLogging:
    def setup_method(self) -> None:
        _reset_logger()

    def teardown_method(self) -> None:
        _reset_logger()

    def test_creates_memory_handler(self, tmp_path: Path) -> None:
        with patch("tracksplit.log.paths") as mock_paths:
            mock_paths.log_dir.return_value = tmp_path
            mock_paths.ensure_parent.side_effect = lambda p: (
                p.parent.mkdir(parents=True, exist_ok=True),
                p,
            )[1]
            log.setup_logging(command="split")

        logger = logging.getLogger("tracksplit")
        mem_handlers = [
            h for h in logger.handlers if isinstance(h, logging.handlers.MemoryHandler)
        ]
        assert len(mem_handlers) == 1

    def test_creates_log_parent_directory(self, tmp_path: Path) -> None:
        nested = tmp_path / "deep" / "nested"
        with patch("tracksplit.log.paths") as mock_paths:
            mock_paths.log_dir.return_value = nested
            mock_paths.ensure_parent.side_effect = lambda p: (
                p.parent.mkdir(parents=True, exist_ok=True),
                p,
            )[1]
            log.setup_logging(command="split")

        assert nested.is_dir()

    def test_continues_when_log_dir_creation_fails(self, tmp_path: Path) -> None:
        """Returns None and logs warning when ensure_parent raises."""
        with patch("tracksplit.log.paths") as mock_paths:
            mock_paths.log_dir.return_value = tmp_path
            mock_paths.ensure_parent.side_effect = PermissionError(
                "read-only filesystem"
            )
            result = log.setup_logging(command="fail")

        assert result is None
        # Console handler should still be configured
        logger = logging.getLogger("tracksplit")
        stream_handlers = [
            h
            for h in logger.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, (logging.FileHandler, logging.handlers.MemoryHandler))
        ]
        assert len(stream_handlers) == 1

    def test_file_handler_captures_debug_level(self, tmp_path: Path) -> None:
        with patch("tracksplit.log.paths") as mock_paths:
            mock_paths.log_dir.return_value = tmp_path
            mock_paths.ensure_parent.side_effect = lambda p: (
                p.parent.mkdir(parents=True, exist_ok=True),
                p,
            )[1]
            log.setup_logging(command="split")

        logger = logging.getLogger("tracksplit")
        mh = next(
            h for h in logger.handlers if isinstance(h, logging.handlers.MemoryHandler)
        )
        assert mh.target.level == logging.DEBUG
        assert logger.level == logging.DEBUG

    def test_closes_existing_handlers_before_clearing(self, tmp_path: Path) -> None:
        """Repeated calls must not leak file descriptors."""
        with patch("tracksplit.log.paths") as mock_paths:
            mock_paths.log_dir.return_value = tmp_path
            mock_paths.ensure_parent.side_effect = lambda p: (
                p.parent.mkdir(parents=True, exist_ok=True),
                p,
            )[1]

            log.setup_logging(command="first")
            logger = logging.getLogger("tracksplit")
            first_handlers = list(logger.handlers)
            assert len(first_handlers) > 0

            log.setup_logging(command="second")

        # First-call memory handler's target should be closed
        for h in first_handlers:
            if isinstance(h, logging.handlers.MemoryHandler) and h.target:
                target = h.target
                if hasattr(target, "stream") and target.stream is not None:
                    assert target.stream.closed
