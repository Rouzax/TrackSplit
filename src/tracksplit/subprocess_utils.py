"""Cancellation-aware subprocess runner for TrackSplit.

tracked_run is the single entry point for all subprocess invocations
(ffmpeg, ffprobe, mkvmerge, etc.). Only failures are logged to keep
the debug log readable:

    subprocess.exit: code=N cmd="..." tail="..."   (non-zero only)
    subprocess.timeout: cmd="..."
    subprocess.cancel: cmd="..." reason=...

Successful invocations produce no log output.
"""
from __future__ import annotations

import logging
import shlex
import subprocess
import threading

logger = logging.getLogger("tracksplit.subprocess")

_STDERR_TAIL_CHARS = 500

# Global process tracking for clean shutdown on Ctrl+C
_active_processes: list[subprocess.Popen[bytes]] = []
_active_processes_lock = threading.Lock()


def kill_active_processes() -> None:
    """Kill all tracked subprocesses."""
    with _active_processes_lock:
        for proc in _active_processes:
            try:
                proc.kill()
            except OSError:
                pass


class CancelledError(Exception):
    """Raised when processing is cancelled via cancel_event."""


def _fmt_cmd(cmd: list[str]) -> str:
    """Render a command list as a shell-quoted single line."""
    return " ".join(shlex.quote(str(a)) for a in cmd)


def _stderr_tail(stderr: bytes | None) -> str:
    """Return the last _STDERR_TAIL_CHARS chars of stderr as a string."""
    if not stderr:
        return ""
    text = stderr.decode("utf-8", errors="replace").strip()
    if len(text) > _STDERR_TAIL_CHARS:
        return "..." + text[-_STDERR_TAIL_CHARS:]
    return text


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

    Only failures are logged; successful runs (exit 0) produce no output:

      subprocess.cancel:  cancel_event was set before or during execution.
      subprocess.timeout: the process exceeded the timeout (WARNING level).
      subprocess.exit:    non-zero exit with code and stderr tail.
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
