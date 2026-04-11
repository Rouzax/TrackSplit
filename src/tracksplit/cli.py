"""CLI entry point for TrackSplit."""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import typer
from rich.highlighter import NullHighlighter
from rich.logging import RichHandler

from tracksplit.console import (
    BatchProgress,
    FileProgress,
    make_console,
    print_error,
    status_text,
    summary_panel,
)
from tracksplit.pipeline import find_video_files, process_file
from tracksplit.probe import is_video_file

app = typer.Typer(
    name="tracksplit",
    help="Extract audio from video chapters into FLAC music albums.",
    no_args_is_help=True,
    add_completion=False,
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


def _live_display_enabled() -> bool:
    """Check whether the live progress display should be active."""
    return logging.getLogger().level > logging.INFO


def _process_single_file(
    input_path: Path,
    output_dir: Path,
    force: bool,
    dry_run: bool,
    output_format: str,
) -> None:
    """Process a single file with a live spinner display."""
    use_live = _live_display_enabled()

    with FileProgress(console, enabled=use_live) as progress:
        progress.set_filename(input_path.name)
        success = process_file(
            input_path, output_dir,
            force=force, dry_run=dry_run,
            output_format=output_format,
            on_progress=progress.update,
        )

    if success:
        console.print(status_text("done", input_path.name))
    else:
        console.print(status_text("skipped", input_path.name, "unchanged"))


def _process_directory(
    input_dir: Path,
    output_dir: Path,
    force: bool,
    dry_run: bool,
    output_format: str,
    workers: int,
) -> None:
    """Process a directory of video files with parallel workers."""
    video_files = find_video_files(input_dir)

    if not video_files:
        logging.getLogger(__name__).warning("No video files found in %s", input_dir)
        return

    use_live = _live_display_enabled()
    processed = 0
    skipped = 0
    failed = 0

    if workers <= 1:
        # Sequential mode with simple spinner
        with FileProgress(console, enabled=use_live) as progress:
            for video_file in video_files:
                progress.set_filename(video_file.name)
                try:
                    if process_file(
                        video_file, output_dir,
                        force=force, dry_run=dry_run,
                        output_format=output_format,
                        on_progress=progress.update,
                    ):
                        processed += 1
                        progress.print(status_text("done", video_file.name))
                    else:
                        skipped += 1
                        progress.print(status_text("skipped", video_file.name, "unchanged"))
                except Exception:
                    logging.getLogger(__name__).exception(
                        "Failed to process %s", video_file.name,
                    )
                    failed += 1
                    progress.print(status_text("error", video_file.name))
    else:
        # Parallel mode with batch progress display
        with BatchProgress(console, total_files=len(video_files), enabled=use_live) as batch:

            def _make_callback(key: str, filename: str):  # noqa: ANN202
                """Create a progress callback bound to a specific worker key."""
                def _cb(step: str, current: int = 0, total: int = 0) -> None:
                    batch.worker_update(key, filename, step, current, total)
                return _cb

            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {}
                for i, video_file in enumerate(video_files):
                    key = f"worker-{i}"
                    cb = _make_callback(key, video_file.name)
                    future = executor.submit(
                        process_file,
                        video_file, output_dir,
                        force=force, dry_run=dry_run,
                        output_format=output_format,
                        on_progress=cb,
                    )
                    futures[future] = (video_file, key)

                for future in as_completed(futures):
                    video_file, key = futures[future]
                    try:
                        result = future.result()
                        if result:
                            processed += 1
                            batch.file_done(key, status_text("done", video_file.name))
                        else:
                            skipped += 1
                            batch.file_done(key, status_text("skipped", video_file.name, "unchanged"))
                    except Exception:
                        logging.getLogger(__name__).exception(
                            "Failed to process %s", video_file.name,
                        )
                        failed += 1
                        batch.file_done(key, status_text("error", video_file.name))

    console.print()
    console.print(summary_panel(processed, skipped, failed))


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
    workers: int = typer.Option(
        min(4, os.cpu_count() or 4),
        "--workers",
        "-w",
        help="Number of parallel workers for directory processing.",
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

        _process_single_file(
            input_path, output_dir,
            force=force, dry_run=dry_run,
            output_format=output_format,
        )

    elif input_path.is_dir():
        _process_directory(
            input_path, output_dir,
            force=force, dry_run=dry_run,
            output_format=output_format,
            workers=workers,
        )

    else:
        print_error(
            f"Input path is neither a file nor a directory: {input_path}",
            console=console,
        )
        raise typer.Exit(code=1)


def run() -> None:
    """Entry point referenced in pyproject.toml."""
    app()
