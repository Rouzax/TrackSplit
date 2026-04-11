"""Extract full audio stream from a video file into a temporary FLAC."""

import logging
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def build_extract_command(input_path: Path, output_path: Path) -> list[str]:
    """Build the ffmpeg command to extract audio as FLAC."""
    return [
        "ffmpeg",
        "-i",
        str(input_path),
        "-vn",
        "-c:a",
        "flac",
        "-y",
        str(output_path),
    ]


def extract_audio(input_path: Path, temp_dir: Path | None = None) -> Path:
    """Extract full audio from a video file to a temporary FLAC.

    Args:
        input_path: Path to the source video file.
        temp_dir: Directory for the temporary FLAC. Uses the system
            temp directory when not provided.

    Returns:
        Path to the extracted FLAC file.

    Raises:
        subprocess.CalledProcessError: If ffmpeg exits with a non-zero code.
    """
    if temp_dir is None:
        temp_dir = Path(tempfile.gettempdir())

    output_path = temp_dir / f"{input_path.stem}_tracksplit_full.flac"

    cmd = build_extract_command(input_path, output_path)

    logger.info("Extracting audio from %s", input_path.name)
    logger.debug("Running command: %s", " ".join(cmd))

    subprocess.run(cmd, capture_output=True, check=True)

    logger.info("Audio extracted to %s", output_path)
    return output_path
