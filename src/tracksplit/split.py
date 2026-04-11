"""Split a full FLAC into individual tracks at chapter boundaries."""
from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from tracksplit.metadata import safe_filename
from tracksplit.models import TrackMeta


def build_split_command(
    input_path: Path,
    output_path: Path,
    start: float,
    end: float | None,
    codec_mode: str = "copy",
    from_video: bool = False,
) -> list[str]:
    """Build an ffmpeg command to extract a single track.

    When end is None (last track), the -to flag is omitted so ffmpeg
    reads to end of file.

    codec_mode controls the audio codec:
      - "copy": stream copy (-c:a copy)
      - "libopus": re-encode to Opus (-c:a libopus -b:a 256k)
      - "flac": copy from FLAC intermediate (-c:a copy)

    from_video adds -vn to strip any video stream.
    """
    cmd = [
        "ffmpeg",
        "-i", str(input_path),
        "-ss", str(start),
    ]
    if end is not None:
        cmd.extend(["-to", str(end)])
    if from_video:
        cmd.append("-vn")
    if codec_mode == "libopus":
        cmd.extend(["-c:a", "libopus", "-b:a", "256k"])
    else:
        cmd.extend(["-c:a", "copy"])
    cmd.extend(["-y", str(output_path)])
    return cmd


def build_track_filename(track: TrackMeta, ext: str = ".flac") -> str:
    """Build a sanitized filename for a track.

    Format: {number:02d} - {artist} - {title}{ext}
    Or:     {number:02d} - {title}{ext} (when no track artist)
    """
    if track.artist:
        name = f"{track.artist} - {track.title}"
    else:
        name = track.title
    return f"{track.number:02d} - {safe_filename(name)}{ext}"


def split_tracks(
    full_flac: Path,
    tracks: list[TrackMeta],
    output_dir: Path,
    ext: str = ".flac",
    codec_mode: str = "copy",
    from_video: bool = False,
    on_progress: Callable[[str, int, int], None] | None = None,
) -> list[Path]:
    """Split audio into individual track files.

    Creates output_dir if it does not exist. For each track, the end time
    is the next track's start time, or None for the last track.
    Returns the list of output file paths.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    total = len(tracks)
    output_paths: list[Path] = []
    for i, track in enumerate(tracks):
        if on_progress:
            on_progress("Splitting tracks", i + 1, total)

        filename = build_track_filename(track, ext=ext)
        output_path = output_dir / filename

        # End time is next track's start, or None for the last track
        if i + 1 < len(tracks):
            end = tracks[i + 1].start
        else:
            end = None

        cmd = build_split_command(
            full_flac, output_path, track.start, end,
            codec_mode=codec_mode, from_video=from_video,
        )
        subprocess.run(cmd, capture_output=True, check=True)
        output_paths.append(output_path)

    return output_paths
