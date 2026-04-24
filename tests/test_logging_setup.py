"""Tests for CLI logging setup."""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path
from unittest.mock import patch

from tracksplit import cli


def _reset_root_handlers():
    for name in (None, "tracksplit"):
        lg = logging.getLogger(name) if name else logging.getLogger()
        for h in list(lg.handlers):
            lg.removeHandler(h)


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
            handlers = logging.getLogger("tracksplit").handlers
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
        emit a single WARNING on the tracksplit logger."""
        log_path = tmp_path / "unwritable" / "tracksplit.log"
        captured: list[logging.LogRecord] = []

        class _ListHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(record)

        probe = _ListHandler(level=logging.WARNING)
        try:
            with patch("tracksplit.cli.paths") as mock_paths:
                mock_paths.log_file.return_value = log_path
                mock_paths.ensure_parent.side_effect = PermissionError("read-only filesystem")
                mock_paths.warn_if_legacy_paths_exist.return_value = None
                _reset_root_handlers()
                # Attach after reset: the warning fires on 'tracksplit' and
                # propagates to root, so the root probe catches it. Attaching
                # to 'tracksplit' directly would be wiped by _setup_logging.
                logging.getLogger().addHandler(probe)
                cli._setup_logging(verbose=False, debug=False)
        finally:
            logging.getLogger().removeHandler(probe)

        handlers = logging.getLogger("tracksplit").handlers
        assert any(type(h).__name__ == "RichHandler" for h in handlers)
        assert not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in handlers)
        assert any("log file" in r.getMessage().lower() for r in captured), (
            f"expected a 'log file' warning, got: {[r.getMessage() for r in captured]}"
        )

    def test_rotating_handler_uses_delayed_open(self, tmp_path: Path):
        """delay=True avoids holding the log file open across the whole run,
        reducing multi-process contention."""
        log_path = tmp_path / "tracksplit.log"
        with patch("tracksplit.cli.paths") as mock_paths:
            mock_paths.log_file.return_value = log_path
            mock_paths.ensure_parent.side_effect = lambda p: p
            mock_paths.warn_if_legacy_paths_exist.return_value = None
            _reset_root_handlers()
            cli._setup_logging(verbose=False, debug=False)
            rot = next(h for h in logging.getLogger("tracksplit").handlers
                       if isinstance(h, logging.handlers.RotatingFileHandler))
            assert rot.delay is True

    def test_continues_when_file_handler_construction_fails(self, tmp_path: Path):
        """If RotatingFileHandler construction raises, same graceful fallback.
        Patches the class to raise directly so the test is independent of delay= semantics."""
        log_path = tmp_path / "tracksplit.log"
        captured: list[logging.LogRecord] = []

        class _ListHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(record)

        probe = _ListHandler(level=logging.WARNING)
        try:
            with patch("tracksplit.cli.paths") as mock_paths, \
                 patch(
                     "tracksplit.cli.logging.handlers.RotatingFileHandler",
                     side_effect=OSError("mock: construction failure"),
                 ):
                mock_paths.log_file.return_value = log_path
                mock_paths.ensure_parent.side_effect = lambda p: p
                mock_paths.warn_if_legacy_paths_exist.return_value = None
                _reset_root_handlers()
                # Attach after reset: warning fires on 'tracksplit' and
                # propagates to the root probe (see sibling test).
                logging.getLogger().addHandler(probe)
                cli._setup_logging(verbose=False, debug=False)
        finally:
            logging.getLogger().removeHandler(probe)

        assert not any(isinstance(h, logging.handlers.RotatingFileHandler)
                       for h in logging.getLogger("tracksplit").handlers)
        assert any("log file" in r.getMessage().lower() for r in captured)

    def test_file_handler_captures_debug_regardless_of_cli_verbosity(self, tmp_path: Path):
        """Rotating file handler always logs at DEBUG so the file is a full
        post-mortem trail regardless of whether the user passed --verbose/--debug.
        Matches festival_organizer.log behaviour (CrateDigger commit 6884d4c)."""
        log_path = tmp_path / "tracksplit.log"
        with patch("tracksplit.cli.paths") as mock_paths:
            mock_paths.log_file.return_value = log_path
            mock_paths.ensure_parent.side_effect = lambda p: (
                p.parent.mkdir(parents=True, exist_ok=True), p,
            )[1]
            mock_paths.warn_if_legacy_paths_exist.return_value = None
            _reset_root_handlers()
            cli._setup_logging(verbose=False, debug=False)
            logger = logging.getLogger("tracksplit")
            rot = next(h for h in logger.handlers
                       if isinstance(h, logging.handlers.RotatingFileHandler))
            assert rot.level == logging.DEBUG, (
                f"file handler must be DEBUG for full post-mortem, got {rot.level}"
            )
            assert logger.level == logging.DEBUG

    def test_setup_logging_closes_existing_handlers_before_clearing(self, tmp_path: Path):
        """Repeated setup_logging calls (tests, subcommand loops) must not leak
        file descriptors. Matches CrateDigger commit 808b57d."""
        log_path = tmp_path / "tracksplit.log"
        with patch("tracksplit.cli.paths") as mock_paths:
            mock_paths.log_file.return_value = log_path
            mock_paths.ensure_parent.side_effect = lambda p: (
                p.parent.mkdir(parents=True, exist_ok=True), p,
            )[1]
            mock_paths.warn_if_legacy_paths_exist.return_value = None
            _reset_root_handlers()
            cli._setup_logging(verbose=False, debug=False)
            first = next(h for h in logging.getLogger("tracksplit").handlers
                         if isinstance(h, logging.handlers.RotatingFileHandler))
            logging.getLogger("tracksplit").debug("trigger open")
            assert first.stream is not None
            cli._setup_logging(verbose=False, debug=False)
            assert first.stream is None
