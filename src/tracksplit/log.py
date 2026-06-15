"""Per-command logging setup for TrackSplit.

Each CLI invocation gets its own log file, named with the command, a timestamp,
and a random hex suffix to avoid collisions. File output is buffered through a
MemoryHandler so disk writes only happen when a WARNING (or higher) record is
emitted, or when the handler is closed at exit. This keeps the hot path free of
I/O while still capturing a full DEBUG trail for post-mortem analysis.
"""

from __future__ import annotations

import contextlib
import logging
import logging.handlers
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from tracksplit import paths

if TYPE_CHECKING:
    from rich.console import Console

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def _cleanup_old_logs(log_directory: Path, max_age_days: int = 7) -> None:
    """Delete ``.log`` files older than *max_age_days* in *log_directory*.

    Silent on errors (missing directory, permission issues, individual file
    deletions). Non-.log files are left untouched.
    """
    try:
        cutoff = time.time() - max_age_days * 86400
        for entry in log_directory.iterdir():
            if entry.suffix != ".log" or not entry.is_file():
                continue
            try:
                if entry.stat().st_mtime < cutoff:
                    entry.unlink()
            except OSError:
                pass
    except OSError:
        pass


def setup_logging(
    verbose: bool = False,
    debug: bool = False,
    console: Console | None = None,
    command: str = "",
) -> Path | None:
    """Configure the ``tracksplit`` logger with console and per-command file output.

    Parameters
    ----------
    verbose:
        Set the console handler to INFO level.
    debug:
        Set the console handler to DEBUG level (takes precedence over *verbose*).
    console:
        A Rich Console instance. When provided, a ``RichHandler`` is used for
        console output; otherwise a plain ``StreamHandler`` writing to stderr.
    command:
        CLI subcommand name, used as the log filename prefix. Falls back to
        ``"tracksplit"`` when empty.

    Returns
    -------
    Path or None
        Path to the per-run log file, or ``None`` if file logging could not be
        set up (an OSError occurred). A warning is logged in that case.
    """
    logger = logging.getLogger("tracksplit")

    # Close and clear existing handlers, including MemoryHandler targets.
    for handler in list(logger.handlers):
        if isinstance(handler, logging.handlers.MemoryHandler) and handler.target:
            with contextlib.suppress(Exception):
                handler.target.close()
        with contextlib.suppress(Exception):
            handler.close()
    logger.handlers.clear()

    logger.setLevel(logging.DEBUG)

    # -- Console handler ---------------------------------------------------
    console_level = (
        logging.DEBUG if debug else logging.INFO if verbose else logging.WARNING
    )

    if console is not None:
        from rich.highlighter import NullHighlighter
        from rich.logging import RichHandler

        console_handler: logging.Handler = RichHandler(
            console=console,
            rich_tracebacks=True,
            show_path=False,
            markup=False,
            highlighter=NullHighlighter(),
        )
    else:
        console_handler = logging.StreamHandler(sys.stderr)

    console_handler.setLevel(console_level)
    logger.addHandler(console_handler)

    # -- Per-command file handler ------------------------------------------
    prefix = command or "tracksplit"
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
    hex_suffix = os.urandom(2).hex()
    filename = f"{prefix}-{stamp}-{hex_suffix}.log"

    try:
        log_dir = paths.log_dir()
        log_path = paths.ensure_parent(log_dir / filename)

        file_handler = logging.FileHandler(
            log_path,
            encoding="utf-8",
            delay=True,
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))

        memory_handler = logging.handlers.MemoryHandler(
            capacity=50,
            flushLevel=logging.WARNING,
            target=file_handler,
            flushOnClose=True,
        )
        logger.addHandler(memory_handler)
    except OSError as exc:
        logger.warning(
            "Could not open log file (%s: %s). Continuing without file logging.",
            type(exc).__name__,
            exc,
        )
        return None

    _cleanup_old_logs(log_dir)
    return log_path
