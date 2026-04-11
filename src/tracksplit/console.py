"""Rich console helpers for TrackSplit terminal output."""
import sys

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
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
