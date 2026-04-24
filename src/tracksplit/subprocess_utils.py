"""Cancellation-aware subprocess runner for TrackSplit.

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

    DEBUG log shape:
      - Before invocation: ``subprocess: <argv>``.
      - On success: ``subprocess exit 0: <argv>``.
      - On non-zero exit: ``subprocess exit <n>: <argv>; stderr tail: <tail>``
        before raising CalledProcessError.
      - On timeout: ``subprocess timed out: <argv>``.
      - On cancel_event set before start:
        ``subprocess cancelled before start: <argv>``.
      - On cancel_event set during execution:
        ``subprocess cancelled during execution: <argv>``.
      - On any other exception during communicate() (including
        KeyboardInterrupt): ``subprocess interrupted: <argv>: <exc_type>``
        before re-raising.
    """
    cmd_str = _fmt_cmd(cmd)
    logger.debug("subprocess: %s", cmd_str)

    if cancel_event is not None and cancel_event.is_set():
        logger.debug("subprocess cancelled before start: %s", cmd_str)
        raise CancelledError("Cancelled before start")

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    with _active_processes_lock:
        _active_processes.append(proc)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.debug("subprocess timed out: %s", cmd_str)
        proc.kill()
        proc.wait()
        raise
    except BaseException as exc:
        logger.debug(
            "subprocess interrupted: %s: %s",
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
        logger.debug("subprocess cancelled during execution: %s", cmd_str)
        raise CancelledError("Cancelled during execution")

    if proc.returncode != 0:
        tail = _stderr_tail(stderr)
        if tail:
            logger.debug(
                "subprocess exit %d: %s; stderr tail: %s",
                proc.returncode, cmd_str, tail,
            )
        else:
            logger.debug("subprocess exit %d: %s", proc.returncode, cmd_str)
        raise subprocess.CalledProcessError(
            proc.returncode, cmd, output=stdout, stderr=stderr,
        )

    logger.debug("subprocess exit 0: %s", cmd_str)
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
