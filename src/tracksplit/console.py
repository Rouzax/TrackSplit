"""Rich console helpers for TrackSplit terminal output."""
from __future__ import annotations

import sys
import threading

from rich.console import Console, Group
from rich.live import Live
from rich.markup import escape
from rich.panel import Panel
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn
from rich.spinner import Spinner
from rich.text import Text


def make_console(file=None) -> Console:
    """Create a Console with auto-highlighting disabled.

    Prevents Rich from colorizing numbers and UUIDs in user data.
    """
    return Console(file=file or sys.stdout, highlight=False)


def status_text(status: str, name: str, detail: str = "") -> Text:
    """Build a colored status indicator line.

    status: "done", "skipped", or "error".
    """
    text = Text()
    if status == "done":
        text.append("  done  ", style="green")
        text.append(escape(name))
    elif status == "skipped":
        text.append("  skip  ", style="dim")
        text.append(escape(name))
        if detail:
            text.append(f" ({escape(detail)})", style="dim")
    elif status == "error":
        text.append("  fail  ", style="red")
        text.append(escape(name))
        if detail:
            text.append(f" ({escape(detail)})", style="red")
    return text


def summary_panel(processed: int, skipped: int, failed: int) -> Panel:
    """Build a final summary panel for batch runs."""
    body = Text()
    body.append("Processed: ", style="bold")
    body.append(str(processed), style="green")
    if skipped:
        body.append("  skipped: ", style="bold")
        body.append(str(skipped), style="dim")
    if failed:
        body.append("  failed: ", style="bold")
        body.append(str(failed), style="red")
    return Panel(body, title="Summary", expand=True)


def print_error(message: str, console: Console | None = None) -> None:
    """Print a styled error to console, or stderr as fallback."""
    if console:
        console.print(f"[red]Error:[/red] {escape(message)}")
    else:
        print(f"Error: {message}", file=sys.stderr)


class FileProgress:
    """Live progress display for file processing steps.

    Shows a spinner with the current step name and optional sub-progress
    (e.g., "Splitting tracks 3/15"). Thread-safe for use with parallel
    workers.

    Usage::

        with FileProgress(console) as progress:
            process_file(..., on_progress=progress.update)
    """

    def __init__(self, console: Console, enabled: bool = True) -> None:
        self._console = console
        self._enabled = enabled and console.is_terminal
        self._lock = threading.Lock()
        self._step = ""
        self._current = 0
        self._total = 0
        self._filename = ""
        self._live: Live | None = None

    def _render(self) -> Text:
        """Build the spinner + step text for the live display."""
        text = Text()
        step = self._step
        if self._total > 0:
            step = f"{step} {self._current}/{self._total}"
        if self._filename:
            text.append("  ")
            text.append(step, style="cyan")
            text.append(f"  {self._filename}", style="dim")
        else:
            text.append("  ")
            text.append(step, style="cyan")
        return text

    def update(self, step: str, current: int = 0, total: int = 0) -> None:
        """Update the displayed step (implements the progress callback)."""
        if not self._enabled:
            return
        with self._lock:
            self._step = step
            self._current = current
            self._total = total
            if self._live is not None:
                self._live.update(Group(Spinner("dots", text=self._render())))

    def set_filename(self, filename: str) -> None:
        """Set the current filename context."""
        with self._lock:
            self._filename = filename

    def print(self, renderable: Text) -> None:
        """Print through the Live context if active, otherwise direct."""
        if self._live is not None:
            self._live.console.print(renderable)
        else:
            self._console.print(renderable)

    def __enter__(self) -> FileProgress:
        if self._enabled:
            self._live = Live(
                Spinner("dots", text=Text("  Starting...", style="dim")),
                console=self._console,
                refresh_per_second=10,
                transient=True,
            )
            self._live.__enter__()
        return self

    def __exit__(self, exc_type: type[BaseException] | None,
                 exc_val: BaseException | None,
                 exc_tb: object) -> None:
        if self._live is not None:
            self._live.__exit__(exc_type, exc_val, exc_tb)  # type: ignore[arg-type]
            self._live = None


class BatchProgress:
    """Progress display for parallel batch processing.

    Shows an overall progress bar plus per-worker spinner lines.
    Thread-safe: each worker calls ``worker_update`` with its file key.
    """

    def __init__(self, console: Console, total_files: int, enabled: bool = True) -> None:
        self._console = console
        self._enabled = enabled and console.is_terminal
        self._total_files = total_files
        self._lock = threading.Lock()
        self._workers: dict[str, tuple[str, str, int, int]] = {}
        self._completed = 0
        self._live: Live | None = None
        self._progress = Progress(
            TextColumn("[bold blue]Processing"),
            BarColumn(bar_width=30),
            MofNCompleteColumn(),
            console=console,
        )
        self._task_id = self._progress.add_task("files", total=total_files)

    def _render(self) -> Group:
        """Build the full display: progress bar + worker spinners."""
        parts: list[Spinner | Progress] = [self._progress]
        for key in sorted(self._workers):
            step, filename, current, total = self._workers[key]
            line = Text()
            label = step
            if total > 0:
                label = f"{step} {current}/{total}"
            line.append("  ")
            line.append(label, style="cyan")
            line.append(f"  {filename}", style="dim")
            parts.append(Spinner("dots", text=line))
        return Group(*parts)

    def worker_update(
        self, key: str, filename: str, step: str, current: int = 0, total: int = 0,
    ) -> None:
        """Update a specific worker's step display."""
        if not self._enabled:
            return
        with self._lock:
            self._workers[key] = (step, filename, current, total)
            if self._live is not None:
                self._live.update(self._render())

    def file_done(self, key: str, status_line: Text) -> None:
        """Mark a file as complete, remove its worker line, print status."""
        with self._lock:
            self._workers.pop(key, None)
            self._completed += 1
            self._progress.advance(self._task_id)
            if self._live is not None:
                self._live.console.print(status_line)
                self._live.update(self._render())
            else:
                self._console.print(status_line)

    def __enter__(self) -> BatchProgress:
        if self._enabled:
            self._live = Live(
                self._render(),
                console=self._console,
                refresh_per_second=10,
                transient=True,
            )
            self._live.__enter__()
        return self

    def __exit__(self, exc_type: type[BaseException] | None,
                 exc_val: BaseException | None,
                 exc_tb: object) -> None:
        if self._live is not None:
            self._live.__exit__(exc_type, exc_val, exc_tb)  # type: ignore[arg-type]
            self._live = None
