"""Cancellation-aware subprocess runner for TrackSplit."""
from __future__ import annotations

import subprocess
import threading

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
    """
    if cancel_event is not None and cancel_event.is_set():
        raise CancelledError("Cancelled before start")

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    with _active_processes_lock:
        _active_processes.append(proc)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise
    except BaseException:
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
        raise CancelledError("Cancelled during execution")

    if proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode, cmd, output=stdout, stderr=stderr,
        )

    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
