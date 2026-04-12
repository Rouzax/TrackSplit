"""Extract full audio stream from a video file into a temporary FLAC."""
from __future__ import annotations

import logging
import tempfile
import threading
from pathlib import Path

from tracksplit.probe import get_audio_codec, is_lossless_codec
from tracksplit.subprocess_utils import tracked_run
from tracksplit.tools import get_tool

logger = logging.getLogger(__name__)


def build_extract_command(input_path: Path, output_path: Path) -> list[str]:
    """Build the ffmpeg command to extract audio as FLAC."""
    return [
        get_tool("ffmpeg"),
        "-i",
        str(input_path),
        "-vn",
        "-c:a",
        "flac",
        "-y",
        str(output_path),
    ]


def extract_audio(
    input_path: Path,
    temp_dir: Path | None = None,
    cancel_event: threading.Event | None = None,
) -> Path:
    """Extract full audio from a video file to a temporary FLAC.

    Args:
        input_path: Path to the source video file.
        temp_dir: Directory for the temporary FLAC. Uses the system
            temp directory when not provided.
        cancel_event: Threading event to signal cancellation.

    Returns:
        Path to the extracted FLAC file.

    Raises:
        subprocess.CalledProcessError: If ffmpeg exits with a non-zero code.
        CancelledError: If cancel_event is set.
    """
    if temp_dir is None:
        temp_dir = Path(tempfile.gettempdir())

    output_path = temp_dir / f"{input_path.stem}_tracksplit_full.flac"

    cmd = build_extract_command(input_path, output_path)

    logger.info("Extracting audio from %s", input_path.name)
    logger.debug("Running command: %s", " ".join(cmd))

    tracked_run(cmd, cancel_event=cancel_event)

    logger.info("Audio extracted to %s", output_path)
    return output_path


def decide_codec(ffprobe_data: dict, output_format: str) -> tuple[str, str]:
    """Decide output extension and codec_mode without performing extraction.

    Returns (ext, codec_mode) where codec_mode is 'copy' or 'libopus'.
    """
    codec = get_audio_codec(ffprobe_data)
    if output_format == "auto":
        if codec == "opus":
            return (".opus", "copy")
        if is_lossless_codec(codec):
            return (".flac", "copy")
        return (".opus", "libopus")
    if output_format == "flac":
        return (".flac", "copy")
    if output_format == "opus":
        if codec == "opus":
            return (".opus", "copy")
        return (".opus", "libopus")
    raise ValueError(f"Unknown output format: {output_format}")


def prepare_audio(
    input_path: Path,
    ext: str,
    codec_mode: str,
    temp_dir: Path,
    cancel_event: threading.Event | None = None,
) -> tuple[Path, str, str]:
    """Prepare audio source for splitting using an already-resolved codec decision.

    Returns (audio_path, ext, codec_mode). Extracts to a temporary FLAC only
    when (ext, codec_mode) == (".flac", "copy"); otherwise passes input_path
    through. Caller must have obtained (ext, codec_mode) from `decide_codec`.
    """
    if ext == ".flac" and codec_mode == "copy":
        flac_path = extract_audio(
            input_path, temp_dir=temp_dir, cancel_event=cancel_event,
        )
        return (flac_path, ext, codec_mode)
    return (input_path, ext, codec_mode)
