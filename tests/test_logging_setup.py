"""Tests for CLI logging setup."""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path
from unittest.mock import patch

from tracksplit import cli


def _reset_root_handlers():
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)


class TestLoggingSetup:
    def test_adds_rotating_file_handler(self, tmp_path: Path):
        log_path = tmp_path / "tracksplit.log"
        with patch("tracksplit.cli.paths") as mock_paths:
            mock_paths.log_file.return_value = log_path
            mock_paths.ensure_parent.side_effect = lambda p: (
                p.parent.mkdir(parents=True, exist_ok=True),
                p,
            )[1]
            _reset_root_handlers()
            cli._setup_logging(verbose=False, debug=False)
            handlers = logging.getLogger().handlers
            rot = [h for h in handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
            assert len(rot) == 1
            assert rot[0].baseFilename == str(log_path)
            assert rot[0].maxBytes == 5 * 1024 * 1024
            assert rot[0].backupCount == 5

    def test_creates_log_parent_dir(self, tmp_path: Path):
        log_path = tmp_path / "deep" / "nested" / "tracksplit.log"
        with patch("tracksplit.cli.paths") as mock_paths:
            mock_paths.log_file.return_value = log_path
            mock_paths.ensure_parent.side_effect = lambda p: (
                p.parent.mkdir(parents=True, exist_ok=True),
                p,
            )[1]
            _reset_root_handlers()
            cli._setup_logging(verbose=False, debug=False)
            assert log_path.parent.is_dir()

    def test_continues_when_log_dir_creation_fails(self, tmp_path: Path):
        """If ensure_parent raises, CLI must still configure console logging and
        emit a single WARNING on tracksplit.cli."""
        log_path = tmp_path / "unwritable" / "tracksplit.log"
        captured: list[logging.LogRecord] = []

        class _ListHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(record)

        probe = _ListHandler(level=logging.WARNING)
        logging.getLogger("tracksplit.cli").addHandler(probe)
        try:
            with patch("tracksplit.cli.paths") as mock_paths:
                mock_paths.log_file.return_value = log_path
                mock_paths.ensure_parent.side_effect = PermissionError("read-only filesystem")
                mock_paths.warn_if_legacy_paths_exist.return_value = None
                _reset_root_handlers()
                cli._setup_logging(verbose=False, debug=False)
        finally:
            logging.getLogger("tracksplit.cli").removeHandler(probe)

        handlers = logging.getLogger().handlers
        assert any(type(h).__name__ == "RichHandler" for h in handlers)
        assert not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in handlers)
        assert any("log file" in r.getMessage().lower() for r in captured), (
            f"expected a 'log file' warning, got: {[r.getMessage() for r in captured]}"
        )

    def test_continues_when_file_handler_construction_fails(self, tmp_path: Path):
        """If RotatingFileHandler raises (path is a directory), same graceful fallback."""
        log_path = tmp_path / "tracksplit.log"
        log_path.mkdir()  # path is a directory, so RotatingFileHandler will fail
        captured: list[logging.LogRecord] = []

        class _ListHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(record)

        probe = _ListHandler(level=logging.WARNING)
        logging.getLogger("tracksplit.cli").addHandler(probe)
        try:
            with patch("tracksplit.cli.paths") as mock_paths:
                mock_paths.log_file.return_value = log_path
                mock_paths.ensure_parent.side_effect = lambda p: p
                mock_paths.warn_if_legacy_paths_exist.return_value = None
                _reset_root_handlers()
                cli._setup_logging(verbose=False, debug=False)
        finally:
            logging.getLogger("tracksplit.cli").removeHandler(probe)

        assert not any(isinstance(h, logging.handlers.RotatingFileHandler)
                       for h in logging.getLogger().handlers)
        assert any("log file" in r.getMessage().lower() for r in captured)
