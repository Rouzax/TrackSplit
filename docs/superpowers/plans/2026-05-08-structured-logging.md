# Structured Logging Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate TrackSplit from a single rotating log file with freeform messages to per-command log files with structured `prefix.event: key=value` events.

**Architecture:** Extract a new `log.py` module from `cli.py._setup_logging` with per-command file naming, MemoryHandler buffering, and old-log cleanup. Migrate all ~80 log calls across 14 files to structured `prefix.event: key=value` format. Subprocess logging switches to failures-only. CrateDigger config logging switches to once-at-startup.

**Tech Stack:** Python stdlib `logging`, `logging.handlers.MemoryHandler`, Rich `RichHandler`, platformdirs

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/tracksplit/log.py` | Create | `setup_logging()`, `_cleanup_old_logs()` |
| `src/tracksplit/paths.py` | Modify | Replace `log_file()` with `log_dir()` |
| `src/tracksplit/cli.py` | Modify | Remove `_setup_logging`, call `log.setup_logging`, show log path in `--check` |
| `src/tracksplit/subprocess_utils.py` | Modify | Structured events, failures only |
| `src/tracksplit/cratedigger.py` | Modify | Log once at startup, deduplicate festival aliases |
| `src/tracksplit/extract.py` | Modify | Structured events, move codec log to extraction time |
| `src/tracksplit/split.py` | Modify | Structured events |
| `src/tracksplit/tagger.py` | Modify | Structured events |
| `src/tracksplit/cover.py` | Modify | Structured events, add composition/DJ lookup events |
| `src/tracksplit/pipeline.py` | Modify | Structured events, add missing decision events |
| `src/tracksplit/probe.py` | Modify | Structured events, add missing decision events |
| `src/tracksplit/metadata.py` | Modify | Add structured events for title dedup, artist canon, source selection |
| `src/tracksplit/manifest.py` | Modify | Structured events |
| `src/tracksplit/tools.py` | Modify | Structured events |
| `src/tracksplit/update_check.py` | Modify | Structured events |
| `src/tracksplit/opus_patch.py` | Modify | Structured event |
| `tests/test_log.py` | Create | Tests for new `log.py` |
| `tests/test_logging_setup.py` | Modify | Rewrite to test `log.setup_logging` instead of `cli._setup_logging` |
| `tests/test_paths.py` | Modify | Replace `TestLogFile` with `TestLogDir` |
| `tests/test_subprocess_utils.py` | Modify | Update assertions for failures-only logging |
| `docs/troubleshooting.md` | Modify | Per-command log files, new directory layout |

---

### Task 1: Create `log.py` with per-command log files

**Files:**
- Create: `src/tracksplit/log.py`
- Create: `tests/test_log.py`

- [ ] **Step 1: Write failing tests for `_cleanup_old_logs`**

```python
# tests/test_log.py
"""Tests for the log module."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest


class TestCleanupOldLogs:
    def test_deletes_files_older_than_max_age(self, tmp_path: Path):
        old = tmp_path / "old-run.log"
        old.write_text("old")
        eight_days_ago = time.time() - 8 * 86400
        os.utime(old, (eight_days_ago, eight_days_ago))

        fresh = tmp_path / "fresh-run.log"
        fresh.write_text("fresh")

        from tracksplit.log import _cleanup_old_logs
        _cleanup_old_logs(tmp_path, max_age_days=7)

        assert not old.exists()
        assert fresh.exists()

    def test_ignores_non_log_files(self, tmp_path: Path):
        txt = tmp_path / "notes.txt"
        txt.write_text("keep")
        eight_days_ago = time.time() - 8 * 86400
        os.utime(txt, (eight_days_ago, eight_days_ago))

        from tracksplit.log import _cleanup_old_logs
        _cleanup_old_logs(tmp_path, max_age_days=7)

        assert txt.exists()

    def test_ignores_missing_directory(self):
        from tracksplit.log import _cleanup_old_logs
        _cleanup_old_logs(Path("/nonexistent/dir"), max_age_days=7)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src pytest tests/test_log.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tracksplit.log'`

- [ ] **Step 3: Write `_cleanup_old_logs` implementation**

```python
# src/tracksplit/log.py
"""Logging configuration for TrackSplit.

Logging:
    Logger: 'tracksplit' (root for all modules)
    See docs/superpowers/specs/2026-05-08-structured-logging-design.md
    for the full event catalog.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.highlighter import NullHighlighter
from rich.logging import RichHandler

from tracksplit import paths


def _cleanup_old_logs(log_directory: os.PathLike, max_age_days: int = 7) -> None:
    try:
        cutoff = time.time() - max_age_days * 86400
        with os.scandir(log_directory) as entries:
            for entry in entries:
                if entry.name.endswith(".log") and entry.is_file(follow_symlinks=False):
                    try:
                        if entry.stat().st_mtime < cutoff:
                            os.unlink(entry.path)
                    except OSError:
                        pass
    except OSError:
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src pytest tests/test_log.py::TestCleanupOldLogs -v`
Expected: PASS

- [ ] **Step 5: Write failing tests for `setup_logging`**

Add to `tests/test_log.py`:

```python
import logging
import logging.handlers
from unittest.mock import patch


def _reset_handlers():
    for name in (None, "tracksplit"):
        lg = logging.getLogger(name) if name else logging.getLogger()
        for h in list(lg.handlers):
            lg.removeHandler(h)


class TestSetupLogging:
    def test_returns_log_path(self, tmp_path: Path):
        with patch("tracksplit.log.paths") as mock_paths:
            mock_paths.log_dir.return_value = tmp_path
            _reset_handlers()
            result = _setup_logging_call(tmp_path, command="split")
            assert result is not None
            assert result.parent == tmp_path
            assert result.name.startswith("split-")
            assert result.name.endswith(".log")

    def test_per_command_filename_format(self, tmp_path: Path):
        with patch("tracksplit.log.paths") as mock_paths:
            mock_paths.log_dir.return_value = tmp_path
            _reset_handlers()
            result = _setup_logging_call(tmp_path, command="check")
            assert result is not None
            # Format: {command}-{YYYY-MM-DDTHH-MM-SS}-{4hex}.log
            stem = result.stem
            parts = stem.split("-", 1)
            assert parts[0] == "check"

    def test_memory_handler_wraps_file_handler(self, tmp_path: Path):
        with patch("tracksplit.log.paths") as mock_paths:
            mock_paths.log_dir.return_value = tmp_path
            _reset_handlers()
            _setup_logging_call(tmp_path)
            logger = logging.getLogger("tracksplit")
            mem = [h for h in logger.handlers
                   if isinstance(h, logging.handlers.MemoryHandler)]
            assert len(mem) == 1
            assert isinstance(mem[0].target, logging.FileHandler)
            assert mem[0].capacity == 50
            assert mem[0].flushLevel == logging.WARNING

    def test_returns_none_on_os_error(self, tmp_path: Path):
        with patch("tracksplit.log.paths") as mock_paths:
            mock_paths.log_dir.return_value = tmp_path / "nonexistent"
            mock_paths.ensure_parent.side_effect = PermissionError("read-only")
            _reset_handlers()
            from tracksplit.log import setup_logging
            result = setup_logging(verbose=False, debug=False)
            assert result is None

    def test_closes_existing_handlers_including_memory_target(self, tmp_path: Path):
        with patch("tracksplit.log.paths") as mock_paths:
            mock_paths.log_dir.return_value = tmp_path
            _reset_handlers()
            _setup_logging_call(tmp_path)
            logger = logging.getLogger("tracksplit")
            first_mem = next(
                h for h in logger.handlers
                if isinstance(h, logging.handlers.MemoryHandler)
            )
            first_target = first_mem.target
            _setup_logging_call(tmp_path)
            assert first_target.stream is None


def _setup_logging_call(tmp_path: Path, command: str = "test"):
    from tracksplit.log import setup_logging
    return setup_logging(verbose=False, debug=False, command=command)
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `PYTHONPATH=src pytest tests/test_log.py::TestSetupLogging -v`
Expected: FAIL with `ImportError` or `AttributeError`

- [ ] **Step 7: Write `setup_logging` implementation**

Add to `src/tracksplit/log.py`:

```python
def setup_logging(
    verbose: bool = False,
    debug: bool = False,
    console: Console | None = None,
    command: str = "",
) -> Path | None:
    """Configure the tracksplit logger.

    Call once at CLI startup. All modules use logging.getLogger(__name__).

    Returns the log file path on success, or None when file logging
    could not be set up.
    """
    logger = logging.getLogger("tracksplit")

    for handler in list(logger.handlers):
        try:
            if isinstance(handler, logging.handlers.MemoryHandler) and handler.target:
                handler.target.close()
            handler.close()
        except Exception:
            pass
    logger.handlers.clear()

    console_level = logging.DEBUG if debug else logging.INFO if verbose else logging.WARNING
    logger.setLevel(logging.DEBUG)

    if console:
        handler = RichHandler(
            console=console,
            rich_tracebacks=True,
            show_path=False,
            markup=False,
            highlighter=NullHighlighter(),
        )
        handler.setLevel(console_level)
        fmt = logging.Formatter("[%(module)s] %(message)s")
    else:
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(console_level)
        fmt = logging.Formatter("        %(levelname)s [%(module)s] %(message)s")

    handler.setFormatter(fmt)
    logger.addHandler(handler)

    log_path = None
    try:
        log_directory = paths.log_dir()
        log_directory.mkdir(parents=True, exist_ok=True)
        _cleanup_old_logs(log_directory)

        prefix = command if command else "tracksplit"
        stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        suffix = os.urandom(2).hex()
        filename = f"{prefix}-{stamp}-{suffix}.log"
        log_path = paths.ensure_parent(log_directory / filename)

        file_handler = logging.FileHandler(
            log_path,
            encoding="utf-8",
            delay=True,
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"
        ))

        memory_handler = logging.handlers.MemoryHandler(
            capacity=50,
            flushLevel=logging.WARNING,
            target=file_handler,
            flushOnClose=True,
        )
        logger.addHandler(memory_handler)
    except OSError as exc:
        log_path = None
        logger.warning(
            "Log file disabled (%s): %s",
            paths.log_dir(), exc,
        )

    return log_path
```

- [ ] **Step 8: Run all log tests**

Run: `PYTHONPATH=src pytest tests/test_log.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add src/tracksplit/log.py tests/test_log.py
git commit -m "feat(log): add per-command log files with MemoryHandler buffer"
```

---

### Task 2: Replace `paths.log_file()` with `paths.log_dir()`

**Files:**
- Modify: `src/tracksplit/paths.py:78-80`
- Modify: `tests/test_paths.py:54-60`

- [ ] **Step 1: Update test**

Replace the `TestLogFile` class in `tests/test_paths.py`:

```python
class TestLogDir:
    def test_uses_platformdirs_user_log_dir(self):
        with patch("tracksplit.paths.platformdirs") as mock_pd:
            mock_pd.user_log_dir.return_value = "/fake/log/TrackSplit"
            result = paths.log_dir()
            mock_pd.user_log_dir.assert_called_once_with("TrackSplit", appauthor=False)
            assert result == Path("/fake/log/TrackSplit")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src pytest tests/test_paths.py::TestLogDir -v`
Expected: FAIL with `AttributeError: module 'tracksplit.paths' has no attribute 'log_dir'`

- [ ] **Step 3: Replace `log_file` with `log_dir` in paths.py**

In `src/tracksplit/paths.py`, replace:
```python
def log_file() -> Path:
    """Return the path to the rotating log file (``tracksplit.log``)."""
    return Path(platformdirs.user_log_dir(APP_NAME, appauthor=False)) / "tracksplit.log"
```
with:
```python
def log_dir() -> Path:
    """Return the directory for per-command log files."""
    return Path(platformdirs.user_log_dir(APP_NAME, appauthor=False))
```

Also update the module docstring: change the Logs line from
`- Logs:                  ``%LOCALAPPDATA%\\TrackSplit\\Logs\\`` / ``~/.local/state/TrackSplit/log/```
to
`- Logs:                  ``%LOCALAPPDATA%\\TrackSplit\\Logs\\`` / ``~/.local/state/TrackSplit/log/`` (per-command files)`

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src pytest tests/test_paths.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/tracksplit/paths.py tests/test_paths.py
git commit -m "refactor(paths): replace log_file() with log_dir()"
```

---

### Task 3: Wire `cli.py` to `log.setup_logging` and update `--check`

**Files:**
- Modify: `src/tracksplit/cli.py:1-10,78-136,325-424,538`
- Modify: `tests/test_logging_setup.py` (full rewrite)

- [ ] **Step 1: Rewrite `tests/test_logging_setup.py`**

```python
"""Tests for CLI logging setup via log.setup_logging."""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path
from unittest.mock import patch

from tracksplit import log


def _reset_root_handlers():
    for name in (None, "tracksplit"):
        lg = logging.getLogger(name) if name else logging.getLogger()
        for h in list(lg.handlers):
            lg.removeHandler(h)


class TestLoggingSetup:
    def test_creates_memory_handler(self, tmp_path: Path):
        with patch("tracksplit.log.paths") as mock_paths:
            mock_paths.log_dir.return_value = tmp_path
            mock_paths.ensure_parent.side_effect = lambda p: (
                p.parent.mkdir(parents=True, exist_ok=True), p,
            )[1]
            _reset_root_handlers()
            result = log.setup_logging(verbose=False, debug=False, command="test")
            handlers = logging.getLogger("tracksplit").handlers
            mem = [h for h in handlers if isinstance(h, logging.handlers.MemoryHandler)]
            assert len(mem) == 1
            assert result is not None
            assert result.parent == tmp_path

    def test_creates_log_parent_dir(self, tmp_path: Path):
        log_dir = tmp_path / "deep" / "nested"
        with patch("tracksplit.log.paths") as mock_paths:
            mock_paths.log_dir.return_value = log_dir
            mock_paths.ensure_parent.side_effect = lambda p: (
                p.parent.mkdir(parents=True, exist_ok=True), p,
            )[1]
            _reset_root_handlers()
            log.setup_logging(verbose=False, debug=False, command="test")
            assert log_dir.is_dir()

    def test_continues_when_log_dir_creation_fails(self, tmp_path: Path):
        captured: list[logging.LogRecord] = []

        class _ListHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(record)

        probe = _ListHandler(level=logging.WARNING)
        try:
            with patch("tracksplit.log.paths") as mock_paths:
                mock_paths.log_dir.return_value = tmp_path / "unwritable"
                mock_paths.ensure_parent.side_effect = PermissionError("read-only")
                _reset_root_handlers()
                logging.getLogger().addHandler(probe)
                result = log.setup_logging(verbose=False, debug=False)
        finally:
            logging.getLogger().removeHandler(probe)

        assert result is None
        assert any("log file" in r.getMessage().lower() or "disabled" in r.getMessage().lower()
                    for r in captured)

    def test_file_handler_captures_debug(self, tmp_path: Path):
        with patch("tracksplit.log.paths") as mock_paths:
            mock_paths.log_dir.return_value = tmp_path
            mock_paths.ensure_parent.side_effect = lambda p: (
                p.parent.mkdir(parents=True, exist_ok=True), p,
            )[1]
            _reset_root_handlers()
            log.setup_logging(verbose=False, debug=False, command="test")
            logger = logging.getLogger("tracksplit")
            mem = next(h for h in logger.handlers
                       if isinstance(h, logging.handlers.MemoryHandler))
            assert mem.target.level == logging.DEBUG
            assert logger.level == logging.DEBUG

    def test_closes_existing_handlers_before_clearing(self, tmp_path: Path):
        with patch("tracksplit.log.paths") as mock_paths:
            mock_paths.log_dir.return_value = tmp_path
            mock_paths.ensure_parent.side_effect = lambda p: (
                p.parent.mkdir(parents=True, exist_ok=True), p,
            )[1]
            _reset_root_handlers()
            log.setup_logging(verbose=False, debug=False, command="test")
            first_mem = next(h for h in logging.getLogger("tracksplit").handlers
                             if isinstance(h, logging.handlers.MemoryHandler))
            first_target = first_mem.target
            log.setup_logging(verbose=False, debug=False, command="test")
            assert first_target.stream is None
```

- [ ] **Step 2: Run rewritten tests to verify they pass (they should, since log.py exists from Task 1)**

Run: `PYTHONPATH=src pytest tests/test_logging_setup.py -v`
Expected: PASS

- [ ] **Step 3: Update `cli.py` imports and remove `_setup_logging`**

In `src/tracksplit/cli.py`:

Remove these imports (lines 6-7):
```python
import logging.handlers
```

Remove the import of `NullHighlighter` and `RichHandler` (lines 17-18):
```python
from rich.highlighter import NullHighlighter
from rich.logging import RichHandler
```

Add import:
```python
from tracksplit.log import setup_logging
```

Remove the entire `_setup_logging` function (lines 78-135).

Replace the call on line 538:
```python
    _setup_logging(verbose, debug)
```
with:
```python
    _log_path = setup_logging(verbose, debug, console=console, command="split")
```

- [ ] **Step 4: Add log directory to `--check` output**

In `_run_check()`, after the "Update status" section and before "Python packages", add:

```python
    out.print("\n[bold]Log directory[/bold]")
    log_directory = paths.log_dir()
    if log_directory.is_dir():
        log_count = sum(1 for f in log_directory.iterdir() if f.suffix == ".log")
        out.print(f"  [green]✓[/green] {log_directory} ({log_count} file(s))")
    else:
        out.print(f"  [dim]~[/dim] {log_directory} (not yet created)")
```

- [ ] **Step 5: Update `_live_display_enabled` import**

The function references `RichHandler` which we removed from imports. Add a local import:

```python
def _live_display_enabled() -> bool:
    from rich.logging import RichHandler
    logger = logging.getLogger("tracksplit")
    for handler in logger.handlers:
        if isinstance(handler, RichHandler):
            return handler.level > logging.INFO
    return True
```

- [ ] **Step 6: Run CLI tests**

Run: `PYTHONPATH=src pytest tests/test_cli.py tests/test_logging_setup.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/tracksplit/cli.py tests/test_logging_setup.py
git commit -m "refactor(cli): wire to log.setup_logging, show log dir in --check"
```

---

### Task 4: Subprocess logging: failures only, structured format

**Files:**
- Modify: `src/tracksplit/subprocess_utils.py:75-139`
- Modify: `tests/test_subprocess_utils.py`

- [ ] **Step 1: Update tests for failures-only policy**

Rewrite `tests/test_subprocess_utils.py`:

```python
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
    """Timeout logs structured subprocess.timeout event."""
    cmd = [sys.executable, "-c", "import time; time.sleep(5)"]
    with caplog.at_level(logging.DEBUG, logger="tracksplit.subprocess"):
        with pytest.raises(subprocess.TimeoutExpired):
            tracked_run(cmd, timeout=0.2)
    messages = [r.message for r in caplog.records]
    assert any(m.startswith("subprocess.timeout:") for m in messages)


def test_tracked_run_logs_cancel_structured(caplog):
    """Cancel before start logs structured subprocess.cancel event."""
    cmd = [sys.executable, "-c", "pass"]
    ev = threading.Event()
    ev.set()
    with caplog.at_level(logging.DEBUG, logger="tracksplit.subprocess"):
        with pytest.raises(CancelledError):
            tracked_run(cmd, cancel_event=ev, timeout=10)
    messages = [r.message for r in caplog.records]
    assert any(m.startswith("subprocess.cancel:") for m in messages)


def test_tracked_run_logs_interrupted_structured(caplog):
    """Non-cancel exception during communicate logs subprocess.exit with error info."""
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src pytest tests/test_subprocess_utils.py -v`
Expected: FAIL (old format doesn't match new assertions)

- [ ] **Step 3: Rewrite `tracked_run` logging**

Replace the body of `tracked_run` in `src/tracksplit/subprocess_utils.py` from the docstring onward:

```python
def tracked_run(
    cmd: list[str],
    cancel_event: threading.Event | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run a subprocess with cancellation support and process tracking.

    The process is registered in a global list so it can be killed
    immediately when Ctrl+C is pressed (via kill_active_processes).

    Raises CancelledError if cancel_event is set before or during execution.
    Raises subprocess.CalledProcessError on non-zero exit.
    Raises subprocess.TimeoutExpired on timeout.

    Only logs on failure:
      - subprocess.exit: code=N cmd="<cmd>" tail="<stderr>"
      - subprocess.timeout: cmd="<cmd>"
      - subprocess.cancel: cmd="<cmd>"
    """
    cmd_str = _fmt_cmd(cmd)

    if cancel_event is not None and cancel_event.is_set():
        logger.debug("subprocess.cancel: cmd=%s reason=before_start", cmd_str)
        raise CancelledError("Cancelled before start")

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    with _active_processes_lock:
        _active_processes.append(proc)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.warning("subprocess.timeout: cmd=%s", cmd_str)
        proc.kill()
        proc.wait()
        raise
    except BaseException as exc:
        logger.debug(
            "subprocess.cancel: cmd=%s error=%s",
            cmd_str, type(exc).__name__,
        )
        proc.kill()
        proc.wait()
        raise
    finally:
        with _active_processes_lock:
            try:
                _active_processes.remove(proc)
            except ValueError:
                pass

    if cancel_event is not None and cancel_event.is_set():
        logger.debug("subprocess.cancel: cmd=%s reason=during_execution", cmd_str)
        raise CancelledError("Cancelled during execution")

    if proc.returncode != 0:
        tail = _stderr_tail(stderr)
        logger.debug(
            "subprocess.exit: code=%d cmd=%s tail=%s",
            proc.returncode, cmd_str, tail,
        )
        raise subprocess.CalledProcessError(
            proc.returncode, cmd, output=stdout, stderr=stderr,
        )

    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
```

Also update the module docstring at the top of the file. Replace:
```
tracked_run is the single entry point for all subprocess invocations
(ffmpeg, ffprobe, mkvmerge, etc.) so the rotating log file captures a
full post-mortem trail: the argv command, the exit code on success,
and a tail of stderr on non-zero exit, timeout, or cancellation.

Cross-repo note: CrateDigger has a parallel tracked_run at
festival_organizer/subprocess_utils.py. CrateDigger is single-threaded
in its per-file loop and uses a thinner pass-through wrapper; this
version carries cancel_event plumbing for TrackSplit's
ThreadPoolExecutor worker pool (see cli.py). The DEBUG log shape
(command + exit N + stderr tail) stays symmetric across both repos so
rotating logs read the same.
```
with:
```
tracked_run is the single entry point for all subprocess invocations
(ffmpeg, ffprobe, mkvmerge, etc.). Only failures are logged to keep
the debug log readable:

    subprocess.exit: code=N cmd="..." tail="..."   (non-zero only)
    subprocess.timeout: cmd="..."
    subprocess.cancel: cmd="..." reason=...

Successful invocations produce no log output.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src pytest tests/test_subprocess_utils.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/tracksplit/subprocess_utils.py tests/test_subprocess_utils.py
git commit -m "refactor(subprocess): structured events, failures only"
```

---

### Task 5: CrateDigger noise reduction

**Files:**
- Modify: `src/tracksplit/cratedigger.py:42-93,343-365`

- [ ] **Step 1: Fix `find_cratedigger_dirs` to not log per call**

In `src/tracksplit/cratedigger.py`, in `find_cratedigger_dirs`, remove line 72:
```python
    logger.debug("CrateDigger candidate dirs: %s", [str(d) for d in dirs])
```

- [ ] **Step 2: Add once-at-startup logging in `load_config`**

In the `load_config` function, after the line `cfg = CrateDiggerConfig()` (line 294), add:
```python
    logger.debug("cratedigger.config: data_dirs=%s", [str(d) for d in dirs])
```

- [ ] **Step 3: Deduplicate festival alias logging**

Add a module-level set to track logged aliases, and update `apply_cratedigger_canon_with`:

At module level (after `_config_cache_lock`):
```python
_logged_festival_aliases: set[str] = set()
_logged_festival_aliases_lock = threading.Lock()


def _clear_logged_aliases() -> None:
    """Reset the logged-alias set. Intended for tests."""
    with _logged_festival_aliases_lock:
        _logged_festival_aliases.clear()
```

In `apply_cratedigger_canon_with`, replace the festival debug log:
```python
        if display != raw_festival:
            logger.debug(
                "Festival: %r -> %r (edition=%r)", raw_festival, display, edition,
            )
```
with:
```python
        if display != raw_festival:
            with _logged_festival_aliases_lock:
                if raw_festival not in _logged_festival_aliases:
                    _logged_festival_aliases.add(raw_festival)
                    logger.debug(
                        'cratedigger.festival_alias: raw="%s" short="%s" edition="%s"',
                        raw_festival, display, edition,
                    )
```

- [ ] **Step 4: Structure the remaining log calls**

In `find_cratedigger_dirs`, replace the env-var log (line 57):
```python
            logger.debug("CrateDigger data: $CRATEDIGGER_DATA_DIR -> %s", env_path)
```
with:
```python
            logger.debug("cratedigger.config: data_dir=%s source=env", env_path)
```

In `_load_json`, replace the error log (line 82):
```python
        logger.debug("CrateDigger config read failed: %s (%s)", path, exc)
```
with:
```python
        logger.debug("cratedigger.load_fail: path=%s error=%s", path, exc)
```

In `_find_json`, replace the success log (line 91):
```python
            logger.debug("Loading %s from %s", filename, d)
```
with:
```python
            logger.debug("cratedigger.load: file=%s path=%s", filename, d)
```

In `apply_cratedigger_canon_with`, replace the artist debug log:
```python
            logger.debug("Artist: %r -> %r", raw_artist, resolved)
```
with:
```python
            logger.debug('cratedigger.artist_alias: raw="%s" canonical="%s"', raw_artist, resolved)
```

- [ ] **Step 5: Run tests**

Run: `PYTHONPATH=src pytest tests/test_cratedigger.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/tracksplit/cratedigger.py
git commit -m "refactor(cratedigger): structured events, log once at startup"
```

---

### Task 6: Structured events in extract, split, tagger, opus_patch

**Files:**
- Modify: `src/tracksplit/extract.py`
- Modify: `src/tracksplit/split.py`
- Modify: `src/tracksplit/tagger.py`
- Modify: `src/tracksplit/opus_patch.py`

- [ ] **Step 1: Structure extract.py log calls**

In `src/tracksplit/extract.py`:

In `extract_audio`, replace lines 57-61:
```python
    logger.info("Extracting audio from %s", input_path.name)

    tracked_run(cmd, cancel_event=cancel_event)

    logger.info("Audio extracted to %s", output_path)
```
with:
```python
    logger.debug("extract.start: file=%s", input_path.name)
    tracked_run(cmd, cancel_event=cancel_event)
    logger.debug("extract.done: file=%s", input_path.name)
```

In `decide_codec`, replace lines 92-95:
```python
    logger.info(
        "Codec decision: input=%s, format=%s, output=%s (%s)",
        codec, output_format, ext, codec_mode,
    )
```
with:
```python
    logger.info(
        "extract.codec: file=- input=%s format=%s output=%s mode=%s",
        codec, output_format, ext, codec_mode,
    )
```

Note: `decide_codec` doesn't have access to the filename. It will be called by `pipeline.py` which has the filename. We keep the existing call site but change the format. The `file=-` placeholder is fine since this is an INFO-level message about the global decision.

Actually, looking at the spec and the code more carefully: the spec says "Log `extract.codec` only when extraction actually proceeds." Currently `decide_codec` is called for every file, including skipped ones. The fix is to not call `decide_codec` for skipped files, but that's a pipeline.py change. For now, just structure the message format. The pipeline task (Task 8) will handle moving the call.

- [ ] **Step 2: Structure split.py log calls**

In `src/tracksplit/split.py`:

Replace line 121:
```python
        logger.debug("splitting %d/%d: %s", i + 1, total, track.title)
```
with:
```python
        logger.debug(
            'split.track: num=%d/%d title="%s" start=%.3f end=%s prefix=%s',
            i + 1, total, track.title, start,
            f"{end:.3f}" if end is not None else "eof",
            use_prefix if (apply_opus_prefix and i > 0) else "n/a",
        )
```

Note: `use_prefix` is computed after this log line currently. Move the log call to after the `use_prefix` computation. Specifically, the log line should go after line 136 (after `start` is computed) and replace the existing debug line at 121. Remove the existing opus prefix debug lines at 139-148.

Full replacement for the loop body (lines 114-158):

```python
    for i, track in enumerate(tracks):
        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError("Cancelled")

        if on_progress:
            on_progress("Splitting tracks", i + 1, total)

        filename = build_track_filename(track, ext=ext)
        output_path = output_dir / filename

        if i + 1 < len(tracks):
            end = tracks[i + 1].start
        else:
            end = None

        use_prefix = (
            apply_opus_prefix
            and i > 0
            and track.start - OPUS_PREFIX_SECONDS >= 0.0
        )
        start = track.start - OPUS_PREFIX_SECONDS if use_prefix else track.start

        logger.debug(
            'split.track: num=%d/%d title="%s" start=%.3f end=%s prefix=%s',
            i + 1, total, track.title, start,
            f"{end:.3f}" if end is not None else "eof",
            use_prefix if (apply_opus_prefix and i > 0) else "n/a",
        )

        cmd = build_split_command(
            full_flac, output_path, start, end,
            codec_mode=codec_mode, from_video=from_video,
        )
        tracked_run(cmd, cancel_event=cancel_event)

        if use_prefix:
            patch_opus_pre_skip(output_path, OPUS_PREFIX_SAMPLES)

        output_paths.append(output_path)
```

Add start/done events around the loop. Before the loop (after `output_paths: list[Path] = []`):
```python
    logger.debug(
        "split.start: file=%s tracks=%d codec_mode=%s",
        full_flac.name, total, codec_mode,
    )
```

After the loop (before `return output_paths`):
```python
    logger.debug("split.done: file=%s tracks=%d", full_flac.name, total)
```

- [ ] **Step 3: Structure tagger.py log calls**

In `src/tracksplit/tagger.py`:

Replace both tag delta log lines (in `tag_flac` lines 130-133 and `tag_ogg` lines 159-162). Both currently say:
```python
        logger.debug(
            "Tags for %s: +%d -%d ~%d",
            Path(path).name, added, removed, changed,
        )
```
Replace with:
```python
        logger.debug(
            "tagger.write: file=%s added=%d removed=%d changed=%d",
            Path(path).name, added, removed, changed,
        )
```

Replace the warning in `tag_all` (lines 204-207):
```python
            logger.warning(
                "Failed to tag %s: %s: %s",
                p.name, type(exc).__name__, exc,
            )
```
with:
```python
            logger.warning(
                'tagger.fail: file=%s error="%s: %s"',
                p.name, type(exc).__name__, exc,
            )
```

- [ ] **Step 4: Structure opus_patch.py log call**

In `src/tracksplit/opus_patch.py`, replace line 93:
```python
    logger.debug("Opus pre_skip patched for %s -> %d samples", path.name, new_pre_skip)
```
with:
```python
    logger.debug("opus_patch.applied: file=%s samples=%d", path.name, new_pre_skip)
```

- [ ] **Step 5: Run tests**

Run: `PYTHONPATH=src pytest tests/test_extract.py tests/test_split.py tests/test_tagger.py tests/test_opus_patch.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/tracksplit/extract.py src/tracksplit/split.py src/tracksplit/tagger.py src/tracksplit/opus_patch.py
git commit -m "refactor: structured events in extract, split, tagger, opus_patch"
```

---

### Task 7: Structured events in probe, metadata, manifest, tools, update_check

**Files:**
- Modify: `src/tracksplit/probe.py`
- Modify: `src/tracksplit/metadata.py`
- Modify: `src/tracksplit/manifest.py`
- Modify: `src/tracksplit/tools.py`
- Modify: `src/tracksplit/update_check.py`

- [ ] **Step 1: Structure probe.py log calls and add new events**

In `src/tracksplit/probe.py`:

In `parse_chapters`, replace the warning (lines 58-59):
```python
            logger.warning(
                "Skipping zero-duration chapter %r at %.3f s", title, start
            )
```
with:
```python
            logger.warning(
                'probe.skip_zero: file=- title="%s" start=%.3f', title, start,
            )
```

After the chapter filter loop and before `return chapters`, add a chapters-parsed event and title-synthesized events. Replace the end of `parse_chapters` (the title assignment + the rest of the loop):

In the `if not title:` block (line 65), add logging:
```python
        if not title:
            title = f"Track {len(chapters) + 1:02d}"
            logger.debug("probe.title_synthesized: track=%d", len(chapters) + 1)
```

After the loop, before `return chapters`:
```python
    logger.debug("probe.chapters: count=%d", len(chapters))
```

In `get_opus_packet_duration_ms`, replace the three debug log calls:

Replace lines 197-199:
```python
            logger.debug(
                "Opus packet duration parse failed for %s: %r", path.name, line,
            )
```
with:
```python
            logger.debug(
                'probe.opus_packet: file=%s error="parse failed: %s"', path.name, line,
            )
```

Replace lines 203-205:
```python
        logger.debug(
            "No Opus packets found for %s, skipping prefix fix", path.name,
        )
```
with:
```python
        logger.debug("probe.opus_packet: file=%s error=no_packets", path.name)
```

Replace lines 208-211:
```python
        logger.debug(
            "Opus packet durations disagree for %s: %s ms, skipping prefix fix",
            path.name, sorted(durations_ms),
        )
```
with:
```python
        logger.debug("probe.opus_disagree: file=%s durations_ms=%s", path.name, sorted(durations_ms))
```

After the final `return` at line 213, the successful case should also log. Add before the return:
```python
    result = next(iter(durations_ms))
    logger.debug("probe.opus_packet: file=%s duration_ms=%d", path.name, result)
    return result
```
And change the existing `return next(iter(durations_ms))` to just `return result` (but actually restructure the end of the function):

Replace lines 207-213:
```python
    if len(durations_ms) != 1:
        logger.debug(
            "Opus packet durations disagree for %s: %s ms, skipping prefix fix",
            path.name, sorted(durations_ms),
        )
        return None
    return next(iter(durations_ms))
```
with:
```python
    if len(durations_ms) != 1:
        logger.debug("probe.opus_disagree: file=%s durations_ms=%s", path.name, sorted(durations_ms))
        return None
    result = next(iter(durations_ms))
    logger.debug("probe.opus_packet: file=%s duration_ms=%d", path.name, result)
    return result
```

- [ ] **Step 2: Add logging to metadata.py**

`metadata.py` currently has no logger. Add one and add events:

At the top of `src/tracksplit/metadata.py`, after the imports:
```python
import logging

logger = logging.getLogger(__name__)
```

In `build_album_meta`, after the `has_structured` check (after line 232), add:
```python
        if i == 0:
            logger.debug(
                "metadata.source: file=%s structured=%s cratedigger=%s",
                filename_stem, has_structured, tier == 2,
            )
```

In `build_album_meta`, after the artist canonicalization in the `else` branch (lines 259-264), change:
```python
            if (
                track_artist
                and artist
                and track_artist.casefold() == artist.casefold()
            ):
                track_artist = artist
```
to:
```python
            if (
                track_artist
                and artist
                and track_artist.casefold() == artist.casefold()
            ):
                if track_artist != artist:
                    logger.debug(
                        'metadata.artist_canon: file=%s track=%d original="%s" canonical="%s"',
                        filename_stem, i + 1, track_artist, artist,
                    )
                track_artist = artist
```

After `clean_titles = deduplicate_titles(clean_titles)` (line 277), check if any titles changed:
```python
    dedup_count = sum(1 for a, b in zip(clean_titles, [ch.title for ch in chapters]) if a != b)
    if dedup_count:
        logger.debug("metadata.title_dedup: file=%s count=%d", filename_stem, dedup_count)
```

Note: This comparison isn't quite right because `clean_titles` are already processed through `strip_label` and `split_track_artist`. A simpler approach: count duplicates before deduplication:

Actually, replace the dedup logging with a check based on what `deduplicate_titles` does:
```python
    pre_dedup = list(clean_titles)
    clean_titles = deduplicate_titles(clean_titles)
    dedup_count = sum(1 for a, b in zip(pre_dedup, clean_titles) if a != b)
    if dedup_count:
        logger.debug("metadata.title_dedup: file=%s count=%d", filename_stem, dedup_count)
```

- [ ] **Step 3: Structure manifest.py log calls**

In `src/tracksplit/manifest.py`:

In `load_album_manifest`, replace lines 219-222:
```python
            logger.debug(
                "Manifest schema mismatch at %s: got %r, expected %r",
                path, data.get("schema"), MANIFEST_SCHEMA,
            )
```
with:
```python
            logger.debug(
                "manifest.schema_mismatch: file=%s found=%s expected=%d",
                path.name, data.get("schema"), MANIFEST_SCHEMA,
            )
```

Replace the warning at line 226:
```python
        logger.warning("Manifest unreadable at %s: %s", path, exc)
```
with:
```python
        logger.warning('manifest.unreadable: file=%s error="%s"', path.name, exc)
```

In `load_artist_manifest`, replace lines 248-250:
```python
            logger.debug(
                "Artist manifest schema mismatch at %s: got %r, expected %r",
                path, d.get("schema"), MANIFEST_SCHEMA,
            )
```
with:
```python
            logger.debug(
                "manifest.schema_mismatch: file=%s found=%s expected=%d",
                path.name, d.get("schema"), MANIFEST_SCHEMA,
            )
```

Replace line 257:
```python
        logger.warning("Artist manifest unreadable at %s: %s", path, exc)
```
with:
```python
        logger.warning('manifest.unreadable: file=%s error="%s"', path.name, exc)
```

- [ ] **Step 4: Structure tools.py log calls**

In `src/tracksplit/tools.py`:

Replace line 50:
```python
        logger.debug("No tracksplit config found at %s; using defaults", path)
```
with:
```python
        logger.debug("tools.config: path=%s status=not_found", path)
```

Replace line 56:
```python
        logger.warning("Failed to read config %s: %s", path, exc)
```
with:
```python
        logger.warning('tools.config: path=%s error="%s"', path, exc)
```

Replace lines 61-64:
```python
        logger.warning(
            "Config %s: [tools] must be a table, got %s. Using defaults.",
            path, type(tools_section).__name__,
        )
```
with:
```python
        logger.warning(
            "tools.config: path=%s error=\"[tools] must be a table, got %s\"",
            path, type(tools_section).__name__,
        )
```

Replace line 67:
```python
        logger.info("Loaded tool config from %s: %s", path, sorted(resolved))
```
with:
```python
        logger.info("tools.config: path=%s status=loaded tools=%s", path, "|".join(sorted(resolved)))
```

Replace lines 69-72:
```python
                if tool_path != name and not Path(tool_path).is_file():
                    logger.warning(
                        "Configured %s path does not exist: %s", name, tool_path,
                    )
```
with:
```python
                if tool_path != name and not Path(tool_path).is_file():
                    logger.warning("tools.missing: tool=%s path=%s", name, tool_path)
```

Replace line 74:
```python
        logger.info("Config at %s has no [tools] section", path)
```
with:
```python
        logger.info("tools.config: path=%s status=empty", path)
```

- [ ] **Step 5: Structure update_check.py log calls**

In `src/tracksplit/update_check.py`:

Replace line 74:
```python
        logger.debug("Update cache unreadable at %s: %s", p, e)
```
with:
```python
        logger.debug('update.cache_error: error="%s: %s"', p, e)
```

Replace line 154:
```python
        logger.debug("Update check suppressed: env var %s set", ENV_VAR)
```
with:
```python
        logger.debug("update.suppressed: reason=env_%s", ENV_VAR)
```

Replace lines 158-159:
```python
            logger.debug("Update check suppressed: stdout is not a tty")
```
with:
```python
            logger.debug("update.suppressed: reason=not_tty")
```

Replace lines 161-162:
```python
        logger.debug("Update check suppressed: isatty raised: %s", e)
```
with:
```python
        logger.debug('update.suppressed: reason="isatty_error: %s"', e)
```

Replace line 174 (in `_is_suppressed_explicit`):
```python
        logger.debug("Update check suppressed: env var %s set", ENV_VAR)
```
with:
```python
        logger.debug("update.suppressed: reason=env_%s", ENV_VAR)
```

Replace line 199:
```python
        logger.debug("Update check HTTP failed: %s", e, exc_info=True)
```
with:
```python
        logger.debug('update.fetch: status=failed error="%s"', e, exc_info=True)
```

Replace line 241:
```python
        logger.debug("update-check notice failed", exc_info=True)
```
with:
```python
        logger.debug("update.notice_failed:", exc_info=True)
```

Replace line 271:
```python
        logger.debug("update-check refresh failed", exc_info=True)
```
with:
```python
        logger.debug("update.refresh_failed:", exc_info=True)
```

- [ ] **Step 6: Run tests**

Run: `PYTHONPATH=src pytest tests/test_probe.py tests/test_metadata.py tests/test_manifest.py tests/test_tools.py tests/test_update_check.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/tracksplit/probe.py src/tracksplit/metadata.py src/tracksplit/manifest.py src/tracksplit/tools.py src/tracksplit/update_check.py
git commit -m "refactor: structured events in probe, metadata, manifest, tools, update_check"
```

---

### Task 8: Structured events in pipeline.py and cover.py

**Files:**
- Modify: `src/tracksplit/pipeline.py`
- Modify: `src/tracksplit/cover.py`

- [ ] **Step 1: Structure pipeline.py log calls**

In `src/tracksplit/pipeline.py`:

**prune_orphan_tracks** - replace lines 118-122:
```python
        except OSError as exc:
            logger.warning("Could not remove orphan %s: %s", p, exc)
    if removed:
        logger.info(
            "Pruned %d orphan track file(s) from %s", len(removed), album_dir,
        )
```
with:
```python
        except OSError as exc:
            logger.warning('pipeline.orphan_prune_fail: file=%s error="%s"', p.name, exc)
    if removed:
        logger.info("pipeline.orphan_prune: dir=%s count=%d", album_dir.name, len(removed))
```

**_apply_intro_track** - add logging for the start-move case. Replace lines 159-160:
```python
    if chapters and chapters[0].start > 0.0 and album.tracks:
        album.tracks[0].start = 0.0
```
with:
```python
    if chapters and chapters[0].start > 0.0 and album.tracks:
        logger.debug(
            "pipeline.intro_adjust: file=- first_start=%.3fs",
            chapters[0].start,
        )
        album.tracks[0].start = 0.0
```

**_remove_stale_album_dirs** - replace lines 208-213:
```python
        logger.info(
            "Removing renamed album dir: %s -> %s", stale, new_album_dir,
        )
```
with:
```python
        logger.info(
            "pipeline.stale_dir_remove: old=%s new=%s", stale.name, new_album_dir.name,
        )
```

Replace the warning at line 214:
```python
            logger.warning("Could not remove %s: %s", stale, exc)
```
with:
```python
            logger.warning('pipeline.stale_dir_remove_fail: dir=%s error="%s"', stale.name, exc)
```

**refresh_artist_cover** - replace line 253:
```python
        logger.info("Refreshed artist cover: %s", artist_dir.name)
```
with:
```python
        logger.info("pipeline.cover_refresh: artist=%s", artist_dir.name)
```

Replace lines 257-259:
```python
        logger.warning(
            "Could not refresh artist cover for %s: %s", artist_dir, exc,
        )
```
with:
```python
        logger.warning('pipeline.cover_refresh_fail: artist=%s error="%s"', artist_dir.name, exc)
```

**rebuild_cover_only** - replace lines 285-289:
```python
        logger.debug(
            "rebuild_cover_only: no embedded cover in %s; "
            "composing with gradient fallback",
            source_path.name,
        )
```
with:
```python
        logger.debug("pipeline.cover_rebuild: file=%s reason=no_embedded_cover", source_path.name)
```

Replace lines 306-309:
```python
        logger.info(
            "Cover already current for %s; schema version bumped to %d",
            album_dir.name, COVER_SCHEMA_VERSION,
        )
```
with:
```python
        logger.info(
            "pipeline.cover_rebuild: file=%s reason=schema_bump version=%d",
            album_dir.name, COVER_SCHEMA_VERSION,
        )
```

Replace lines 326-330:
```python
        logger.warning(
            "rebuild_cover_only: %d track file(s) in manifest not on disk "
            "for %s: %s",
            len(missing), album_dir.name, ", ".join(missing),
        )
```
with:
```python
        logger.warning(
            "pipeline.cover_rebuild_missing: dir=%s count=%d",
            album_dir.name, len(missing),
        )
```

Replace lines 338-341:
```python
        logger.info(
            "Cover-only rebuild for %s: %d track(s) re-embedded",
            album_dir.name, len(manifest.track_filenames),
        )
```
with:
```python
        logger.info(
            "pipeline.cover_rebuild: file=%s tracks=%d",
            album_dir.name, len(manifest.track_filenames),
        )
```

**should_regenerate** - replace all debug lines with structured format. Replace each `logger.debug("regenerate %s: ..."` pattern. Examples:

Replace line 367:
```python
        logger.debug("regenerate %s: force=True", name)
```
with:
```python
        logger.debug("pipeline.regenerate: file=%s reason=force", name)
```

Replace line 370:
```python
        logger.debug("regenerate %s: album dir does not exist (%s)", name, album_dir)
```
with:
```python
        logger.debug("pipeline.regenerate: file=%s reason=no_album_dir", name)
```

Replace line 376:
```python
        logger.debug("regenerate %s: no/unreadable manifest at %s", name, album_dir)
```
with:
```python
        logger.debug("pipeline.regenerate: file=%s reason=no_manifest", name)
```

Replace line 382:
```python
        logger.debug("regenerate %s: source fingerprint failed: %s", name, exc)
```
with:
```python
        logger.debug('pipeline.regenerate: file=%s reason=fingerprint_failed error="%s"', name, exc)
```

Replace lines 386-390:
```python
        logger.debug(
            "regenerate %s: source.path changed (%r -> %r)",
            name, manifest.source.path, current_source.path,
        )
```
with:
```python
        logger.debug("pipeline.regenerate: file=%s reason=source_path_changed", name)
```

Replace lines 397-400:
```python
                logger.debug(
                    "regenerate %s: source.audio.%s changed (%r -> %r)",
                    name, field, old, new,
                )
```
with:
```python
                logger.debug(
                    "pipeline.regenerate: file=%s reason=audio_changed field=%s old=%r new=%r",
                    name, field, old, new,
                )
```

Replace lines 403-406:
```python
        logger.debug(
            "regenerate %s: artist folder changed (%r -> %r)",
            name, manifest.resolved_artist_folder, artist_folder,
        )
```
with:
```python
        logger.debug(
            'pipeline.regenerate: file=%s reason=artist_folder_changed old="%s" new="%s"',
            name, manifest.resolved_artist_folder, artist_folder,
        )
```

Replace lines 409-412:
```python
        logger.debug(
            "regenerate %s: album folder changed (%r -> %r)",
            name, manifest.resolved_album_folder, album_folder,
        )
```
with:
```python
        logger.debug(
            'pipeline.regenerate: file=%s reason=album_folder_changed old="%s" new="%s"',
            name, manifest.resolved_album_folder, album_folder,
        )
```

Replace lines 415-418:
```python
        logger.debug(
            "regenerate %s: output_format changed (%r -> %r)",
            name, manifest.output_format, output_format,
        )
```
with:
```python
        logger.debug(
            "pipeline.regenerate: file=%s reason=output_format_changed old=%s new=%s",
            name, manifest.output_format, output_format,
        )
```

Replace lines 421-424:
```python
        logger.debug(
            "regenerate %s: codec_mode changed (%r -> %r)",
            name, manifest.codec_mode, codec_mode,
        )
```
with:
```python
        logger.debug(
            "pipeline.regenerate: file=%s reason=codec_mode_changed old=%s new=%s",
            name, manifest.codec_mode, codec_mode,
        )
```

Replace lines 430-434:
```python
            logger.debug(
                "regenerate %s: intro policy upgraded, stored gap %.3fs is under new %.1fs",
                name, first_start, INTRO_MIN_SECONDS,
            )
```
with:
```python
            logger.debug(
                "pipeline.regenerate: file=%s reason=intro_policy_upgrade gap=%.3f threshold=%.1f",
                name, first_start, INTRO_MIN_SECONDS,
            )
```

Replace lines 436-439:
```python
        logger.debug(
            "regenerate %s: intro_min_seconds changed (%r -> %r)",
            name, stored_intro, INTRO_MIN_SECONDS,
        )
```
with:
```python
        logger.debug(
            "pipeline.regenerate: file=%s reason=intro_min_changed old=%s new=%.1f",
            name, stored_intro, INTRO_MIN_SECONDS,
        )
```

Replace lines 442-445:
```python
        logger.debug(
            "regenerate %s: chapters differ (%d stored, %d current)",
            name, len(manifest.chapters), len(chapter_dicts),
        )
```
with:
```python
        logger.debug(
            "pipeline.regenerate: file=%s reason=chapters_changed stored=%d current=%d",
            name, len(manifest.chapters), len(chapter_dicts),
        )
```

Replace lines 449-451:
```python
                    logger.debug(
                        "regenerate %s: chapter[%d] %r -> %r", name, i, old, new,
                    )
```
with:
```python
                    logger.debug(
                        "pipeline.regenerate: file=%s reason=chapter_detail index=%d",
                        name, i,
                    )
```

Replace lines 458-461:
```python
            logger.debug(
                "regenerate %s: tag %r changed (%r -> %r)",
                name, k, old, new,
            )
```
with:
```python
            logger.debug(
                "pipeline.regenerate: file=%s reason=tag_changed tag=%s",
                name, k,
            )
```

**process_file** - replace the skip/process info lines:

Replace line 519:
```python
        logger.warning("No audio stream found in %s, skipping", _safe_log_name(input_path))
```
with:
```python
        logger.warning("pipeline.skip: file=%s reason=no_audio", _safe_log_name(input_path))
```

Replace lines 540-543:
```python
            logger.warning(
                "No chapters and no duration in %s, skipping",
                _safe_log_name(input_path),
            )
```
with:
```python
            logger.warning("pipeline.skip: file=%s reason=no_chapters_no_duration", _safe_log_name(input_path))
```

Replace the cover-only rebuild warnings (lines 582-586 and 590-596) - replace both:
```python
                logger.warning(
                    "Cover-only rebuild failed for %s (%s); "
                    "falling through to full regen",
                    _safe_log_name(input_path), exc,
                )
```
with:
```python
                logger.warning(
                    'pipeline.cover_rebuild: file=%s reason=failed error="%s"',
                    _safe_log_name(input_path), exc,
                )
```

Replace lines 606-609:
```python
        logger.info(
            "Skipping %s, output unchanged since last run",
            _safe_log_name(input_path),
        )
```
with:
```python
        logger.info("pipeline.skip: file=%s reason=unchanged", _safe_log_name(input_path))
```

Replace lines 614-618:
```python
        logger.info(
            "Dry run: would process %s -> %s (%d tracks)",
            _safe_log_name(input_path),
            album_dir,
            len(album.tracks),
        )
```
with:
```python
        logger.info(
            "pipeline.process_start: file=%s dir=%s tracks=%d dry_run=true",
            _safe_log_name(input_path), album_dir.name, len(album.tracks),
        )
```

Replace line 482-487 (the opus fallback warning):
```python
    logger.warning(
        "Unusual Opus frame duration %r on %s, re-encoding with libopus "
        "for safe gapless output",
        packet_ms, audio_path.name,
    )
```
with:
```python
    logger.warning(
        "pipeline.opus_fallback: file=%s packet_ms=%s mode=libopus",
        audio_path.name, packet_ms,
    )
```

Replace line 709:
```python
    logger.info("Processed %s -> %s", _safe_log_name(input_path), album_dir)
```
with:
```python
    logger.info("pipeline.process_done: file=%s dir=%s", _safe_log_name(input_path), album_dir.name)
```

- [ ] **Step 2: Structure cover.py log calls**

In `src/tracksplit/cover.py`, structure the existing log calls. These are spread across the file. The key changes:

Replace line 301 (gradient fallback warning):
```python
            logger.warning("Could not decode background image, using gradient: %s", exc)
```
with:
```python
            logger.warning('cover.source_fail: method=decode error="%s"', exc)
```

Replace line 376:
```python
            logger.warning("Failed to open set artwork for fade photo; skipping")
```
with:
```python
            logger.warning("cover.source_fail: method=fade_photo error=open_failed")
```

Replace line 630:
```python
                logger.debug("DJ artwork found: %s", candidate)
```
with:
```python
                logger.debug("cover.dj_lookup: artist=%s found=true path=%s", artist, candidate.name)
```

Replace line 699:
```python
            logger.warning("Failed to process DJ artwork, skipping photo")
```
with:
```python
            logger.warning("cover.dj_artwork_fail: error=processing_failed")
```

Replace line 789:
```python
            logger.debug("ffprobe failed for cover lookup on %s: %s", input_path.name, exc)
```
with:
```python
            logger.debug('cover.source_fail: file=%s method=ffprobe error="%s"', input_path.name, exc)
```

Replace line 794:
```python
        logger.debug("No cover art stream found in %s", input_path.name)
```
with:
```python
        logger.debug("cover.source_fail: file=%s method=ffprobe error=no_cover_stream", input_path.name)
```

Replace line 815:
```python
        logger.debug("Extracting cover via ffmpeg stream map: %s", " ".join(cmd))
```
with:
```python
        logger.debug("cover.source: file=%s method=ffmpeg_stream", input_path.name)
```

Replace lines 820-822:
```python
            logger.info(
                "Extracted cover art via ffmpeg from %s", input_path.name
            )
```
with:
```python
            logger.info("cover.source: file=%s method=ffmpeg", input_path.name)
```

Replace line 825:
```python
        logger.debug("ffmpeg cover stream extraction failed: %s", exc)
```
with:
```python
        logger.debug('cover.source_fail: file=%s method=ffmpeg error="%s"', input_path.name, exc)
```

Replace line 863:
```python
        logger.debug("Trying mkvmerge identify: %s", " ".join(identify_cmd))
```
with:
```python
        logger.debug("cover.source: file=%s method=mkvmerge_identify", input_path.name)
```

Replace line 872:
```python
            logger.debug("No image attachments found in %s", input_path.name)
```
with:
```python
            logger.debug("cover.source_fail: file=%s method=mkvextract error=no_attachments", input_path.name)
```

Replace line 889:
```python
        logger.debug("Extracting attachment: %s", " ".join(extract_cmd))
```
with:
```python
        logger.debug("cover.source: file=%s method=mkvextract", input_path.name)
```

Replace lines 894-896:
```python
            logger.info(
                "Extracted cover art via mkvextract from %s", input_path.name
            )
```
with:
```python
            logger.info("cover.source: file=%s method=mkvextract", input_path.name)
```

Replace line 903:
```python
        logger.debug("mkvmerge/mkvextract failed: %s", exc)
```
with:
```python
        logger.debug('cover.source_fail: file=%s method=mkvtools error="%s"', input_path.name, exc)
```

- [ ] **Step 3: Move codec decision logging**

In `src/tracksplit/pipeline.py`, the `decide_codec` call on line 558 happens before `should_regenerate`. Move the INFO log to happen only when processing proceeds. The `decide_codec` function in extract.py still computes the result, but we suppress its log for skipped files.

In `src/tracksplit/extract.py`, change the `decide_codec` log level from INFO to DEBUG:
```python
    logger.debug(
        "extract.codec: input=%s format=%s output=%s mode=%s",
        codec, output_format, ext, codec_mode,
    )
```

In `src/tracksplit/pipeline.py`, after the `_progress("Extracting audio")` call (line 633), add:
```python
    logger.info(
        "extract.codec: file=%s input=%s format=%s output=%s mode=%s",
        _safe_log_name(input_path),
        get_audio_codec(ffprobe_data) or "unknown",
        ext.lstrip("."), ext, codec_mode,
    )
```

Wait, this requires importing `get_audio_codec` which is already indirectly available. Actually, `ext` and `codec_mode` are already computed. Let's just add a single process_start event instead of duplicating the codec log:

After the `album_dir.mkdir(parents=True, exist_ok=True)` line (627), add:
```python
    logger.debug(
        "pipeline.process_start: file=%s tracks=%d codec=%s",
        _safe_log_name(input_path), len(album.tracks), ext.lstrip("."),
    )
```

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=src pytest tests/test_pipeline.py tests/test_cover.py -v`
Expected: PASS

- [ ] **Step 5: Run the full test suite**

Run: `PYTHONPATH=src pytest -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/tracksplit/pipeline.py src/tracksplit/cover.py src/tracksplit/extract.py
git commit -m "refactor: structured events in pipeline and cover, move codec log to processing time"
```

---

### Task 9: Update documentation

**Files:**
- Modify: `docs/troubleshooting.md:200-214,254-257`

- [ ] **Step 1: Update the "Where are my logs?" section**

In `docs/troubleshooting.md`, replace the "Where are my logs?" section (lines 200-214) with:

```markdown
## Where are my logs?

TrackSplit creates a new log file for each CLI invocation, named with the timestamp and a short random suffix (for example, `split-2026-05-08T14-22-01-a3f2.log`). Log files are stored in:

| OS | Path |
|----|------|
| Linux | `~/.local/state/TrackSplit/log/` |
| macOS | `~/Library/Logs/TrackSplit/` |
| Windows | `$env:LOCALAPPDATA\TrackSplit\Logs\` |

Log files older than seven days are automatically deleted at the start of each run. Each log file contains the same information as `--debug` output, so it is the first place to look if something went wrong during an unattended run. You do not need to re-run with `--debug` to retrieve it.

Per-command log files eliminate the multi-process log corruption issue that affected the previous rotating log design. Each concurrent TrackSplit invocation writes to its own file.
```

- [ ] **Step 2: Update the bug report section**

Replace the log file paths in the bug report section (lines 254-257) with:

```markdown
- The log file for the run. TrackSplit creates a per-run log file in the log directory. Find it at:
  - Linux: `~/.local/state/TrackSplit/log/`
  - macOS: `~/Library/Logs/TrackSplit/`
  - Windows: `$env:LOCALAPPDATA\TrackSplit\Logs\`
```

- [ ] **Step 3: Commit**

```bash
git add docs/troubleshooting.md
git commit -m "docs(troubleshooting): update for per-command log files"
```

---

### Task 10: Final cleanup and verification

**Files:**
- Review all modified files

- [ ] **Step 1: Remove dead import `logging.handlers` from cli.py if still present**

Check `src/tracksplit/cli.py` for any remaining references to `logging.handlers`, `NullHighlighter`, `RichHandler` at module level, or `paths.log_file`.

- [ ] **Step 2: Run full test suite**

Run: `PYTHONPATH=src pytest -v --tb=short`
Expected: All tests PASS

- [ ] **Step 3: Run a quick manual smoke test**

Run: `PYTHONPATH=src python -m tracksplit --check`
Expected: Shows "Log directory" section with the path and file count.

- [ ] **Step 4: Verify log file is not created for --help**

Run: `PYTHONPATH=src python -m tracksplit --help`
Then check the log directory. No new file should appear (MemoryHandler buffer never flushed because no WARNING was emitted).

- [ ] **Step 5: Commit any final fixups**

Only if changes were needed from steps 1-4.
