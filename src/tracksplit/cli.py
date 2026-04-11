"""CLI entry point for TrackSplit."""

import logging
from pathlib import Path
from typing import Optional

import typer
from rich.highlighter import NullHighlighter
from rich.logging import RichHandler

from tracksplit.console import make_console, print_error, status_text, summary_panel
from tracksplit.pipeline import process_directory, process_file
from tracksplit.probe import is_video_file

app = typer.Typer(
    name="tracksplit",
    help="Extract audio from video chapters into FLAC music albums.",
    no_args_is_help=True,
)

console = make_console()

_VALID_FORMATS = {"auto", "flac", "opus"}


def _setup_logging(verbose: bool, debug: bool) -> None:
    """Configure root logger with RichHandler."""
    if debug:
        level = logging.DEBUG
    elif verbose:
        level = logging.INFO
    else:
        level = logging.WARNING

    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[
            RichHandler(
                console=console,
                rich_tracebacks=True,
                show_path=False,
                markup=False,
                highlighter=NullHighlighter(),
            ),
        ],
        force=True,
    )


@app.command()
def main(
    input_path: Path = typer.Argument(
        ...,
        exists=True,
        help="Video file or directory of video files to process.",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output directory. Defaults to current working directory.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Force regeneration even if output is up to date.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose (INFO) logging.",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Enable debug logging.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be done without writing files.",
    ),
    output_format: str = typer.Option(
        "auto",
        "--format",
        "-f",
        help="Output format: auto, flac, or opus.",
    ),
) -> None:
    """Process video files and extract audio chapters into tagged albums."""
    _setup_logging(verbose, debug)

    if output_format not in _VALID_FORMATS:
        print_error(
            f"Invalid format: {output_format}. "
            f"Choose from: {', '.join(sorted(_VALID_FORMATS))}",
            console=console,
        )
        raise typer.Exit(code=1)

    output_dir = output if output is not None else Path.cwd()

    if input_path.is_file():
        if not is_video_file(input_path):
            print_error(
                f"Not a recognized video file: {input_path.name}",
                console=console,
            )
            raise typer.Exit(code=1)

        success = process_file(
            input_path, output_dir, force=force, dry_run=dry_run,
            output_format=output_format,
        )
        if success:
            console.print(status_text("done", input_path.name))
        else:
            console.print(status_text("skipped", input_path.name, "unchanged"))

    elif input_path.is_dir():
        processed, skipped, failed = process_directory(
            input_path, output_dir, force=force, dry_run=dry_run,
            output_format=output_format,
        )
        console.print()
        console.print(summary_panel(processed, skipped, failed))

    else:
        print_error(
            f"Input path is neither a file nor a directory: {input_path}",
            console=console,
        )
        raise typer.Exit(code=1)


def run() -> None:
    """Entry point referenced in pyproject.toml."""
    app()
