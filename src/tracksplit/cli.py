"""CLI entry point for TrackSplit."""
from __future__ import annotations

import errno
import logging
import os
import signal
import subprocess
import threading
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
from tracksplit.subprocess_utils import CancelledError, kill_active_processes
from tracksplit.tools import install_hint, verify_required_tools, verify_tool

app = typer.Typer(
    name="tracksplit",
    help="Extract audio from video chapters into FLAC music albums.",
    no_args_is_help=True,
    add_completion=False,
)

console = make_console()

_VALID_FORMATS = {"auto", "flac", "opus"}

_FATAL_DISK_ERRNOS = {errno.ENOSPC, errno.EDQUOT, errno.EROFS}

# Shared cancellation state
_cancel_event = threading.Event()


def _friendly_error(exc: BaseException) -> str:
    """Translate known exceptions into a short, user-facing reason."""
    if isinstance(exc, FileNotFoundError):
        target = getattr(exc, "filename", None) or str(exc)
        return f"not found: {target}"
    if isinstance(exc, OSError) and exc.errno in _FATAL_DISK_ERRNOS:
        return f"disk error: {exc.strerror or 'write failed'}"
    if isinstance(exc, subprocess.CalledProcessError):
        raw = exc.stderr
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        text = (raw or "").strip()
        tail = text.splitlines()[-1] if text else f"exit {exc.returncode}"
        cmd = exc.cmd[0] if isinstance(exc.cmd, (list, tuple)) and exc.cmd else "subprocess"
        return f"{Path(str(cmd)).name} failed: {tail}"
    return f"{type(exc).__name__}: {exc}"


def _report_failure(name: str, exc: BaseException) -> str:
    """Log full traceback at debug, return a short one-liner for display."""
    detail = _friendly_error(exc)
    logger = logging.getLogger(__name__)
    logger.debug("Full traceback for %s", name, exc_info=exc)
    logger.error("Failed to process %s: %s", name, detail)
    return detail


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
    result: dict[str, object] = {}

    def _capture(album_dir: Path, track_count: int) -> None:
        result["album_dir"] = album_dir
        result["track_count"] = track_count

    try:
        with FileProgress(console, enabled=use_live) as progress:
            progress.set_filename(input_path.name)
            success = process_file(
                input_path, output_dir,
                force=force, dry_run=dry_run,
                output_format=output_format,
                on_progress=progress.update,
                cancel_event=_cancel_event,
                on_complete=_capture,
            )
    except (CancelledError, KeyboardInterrupt):
        _cancel_event.set()
        console.print(status_text("cancelled", input_path.name))
        raise typer.Exit(code=130)
    except Exception as exc:
        detail = _report_failure(input_path.name, exc)
        console.print(status_text("error", input_path.name, detail))
        raise typer.Exit(code=1) from exc

    if success:
        console.print(status_text("done", input_path.name))
        album_dir = result.get("album_dir")
        track_count = result.get("track_count")
        if isinstance(album_dir, Path) and isinstance(track_count, int):
            verb = "Would create" if dry_run else "Created"
            console.print(
                f"[green]\u2713[/green] {verb} {track_count} track(s) in {album_dir}",
            )
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
    cancelled = 0

    if workers <= 1:
        # Sequential mode with simple spinner
        with FileProgress(console, enabled=use_live) as progress:
            for video_file in video_files:
                if _cancel_event.is_set():
                    cancelled += 1
                    progress.print(status_text("cancelled", video_file.name))
                    continue
                progress.set_filename(video_file.name)
                try:
                    if process_file(
                        video_file, output_dir,
                        force=force, dry_run=dry_run,
                        output_format=output_format,
                        on_progress=progress.update,
                        cancel_event=_cancel_event,
                    ):
                        processed += 1
                        progress.print(status_text("done", video_file.name))
                    else:
                        skipped += 1
                        progress.print(status_text("skipped", video_file.name, "unchanged"))
                except (CancelledError, KeyboardInterrupt):
                    _cancel_event.set()
                    cancelled += 1
                    progress.print(status_text("cancelled", video_file.name))
                except Exception as exc:
                    if _cancel_event.is_set():
                        cancelled += 1
                        progress.print(status_text("cancelled", video_file.name))
                    else:
                        detail = _report_failure(video_file.name, exc)
                        failed += 1
                        progress.print(status_text("error", video_file.name, detail))
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
                        cancel_event=_cancel_event,
                    )
                    futures[future] = (video_file, key)

                try:
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
                        except CancelledError:
                            cancelled += 1
                            batch.file_done(key, status_text("cancelled", video_file.name))
                        except Exception as exc:
                            if _cancel_event.is_set():
                                cancelled += 1
                                batch.file_done(key, status_text("cancelled", video_file.name))
                            else:
                                detail = _report_failure(video_file.name, exc)
                                failed += 1
                                batch.file_done(key, status_text("error", video_file.name, detail))
                except KeyboardInterrupt:
                    _cancel_event.set()
                    kill_active_processes()
                    for f in futures:
                        f.cancel()

    console.print()
    console.print(summary_panel(processed, skipped, failed, cancelled))


def _run_check() -> int:
    """Probe configured tools and print their versions. Returns exit code."""
    any_fail = False
    for name in ("ffmpeg", "ffprobe", "mkvextract"):
        ok, detail = verify_tool(name)
        if ok:
            console.print(f"[green]\u2713[/green] {name:<10} {detail}")
        else:
            required = name in ("ffmpeg", "ffprobe")
            marker = "[red]\u2717[/red]" if required else "[yellow]![/yellow]"
            label = "missing" if required else "missing (optional)"
            console.print(f"{marker} {name:<10} {label}: {detail}")
            console.print(f"  Install: [cyan]{install_hint(name)}[/cyan]")
            if required:
                any_fail = True
    return 1 if any_fail else 0


@app.command()
def main(
    input_path: Optional[Path] = typer.Argument(
        None,
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
        help=(
            "Parallel workers for directory mode. Default min(4, CPU count). "
            "Use 1 for sequential; raise for fast disks."
        ),
    ),
    check: bool = typer.Option(
        False,
        "--check",
        help="Verify ffmpeg/ffprobe/mkvextract are reachable, then exit.",
    ),
) -> None:
    """Process video files and extract audio chapters into tagged albums."""
    _setup_logging(verbose, debug)

    if check:
        raise typer.Exit(code=_run_check())

    if input_path is None:
        print_error(
            "Missing argument 'INPUT_PATH'. Pass a video file or directory, "
            "or run 'tracksplit --check' to verify your setup.",
            console=console,
        )
        raise typer.Exit(code=2)
    assert input_path is not None

    if output_format not in _VALID_FORMATS:
        print_error(
            f"Invalid format: {output_format}. "
            f"Choose from: {', '.join(sorted(_VALID_FORMATS))}",
            console=console,
        )
        raise typer.Exit(code=1)

    # Pre-flight: fail fast if required tools are missing
    tool_errors = verify_required_tools()
    if tool_errors:
        for name, detail in tool_errors:
            print_error(f"{name}: {detail}", console=console)
            console.print(f"  Install: [cyan]{install_hint(name)}[/cyan]")
        console.print(
            "  Or set tool paths in tracksplit.toml "
            "(see [cyan]tracksplit.toml.example[/cyan]).",
        )
        raise typer.Exit(code=1)

    output_dir = output if output is not None else Path.cwd()

    # Install signal handler for clean Ctrl+C
    is_main_thread = threading.current_thread() is threading.main_thread()
    original_handler = signal.getsignal(signal.SIGINT) if is_main_thread else None

    def _sigint_handler(signum: int, frame: object) -> None:
        _cancel_event.set()
        kill_active_processes()
        console.print("\n[yellow]Interrupted, stopping...[/yellow]")

    try:
        if is_main_thread:
            signal.signal(signal.SIGINT, _sigint_handler)

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

    except KeyboardInterrupt:
        _cancel_event.set()
        kill_active_processes()
    finally:
        if is_main_thread and original_handler is not None:
            signal.signal(signal.SIGINT, original_handler)


def run() -> None:
    """Entry point referenced in pyproject.toml."""
    app()
