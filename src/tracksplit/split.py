"""Split a full FLAC into individual tracks at chapter boundaries."""
import subprocess
from pathlib import Path

from tracksplit.metadata import safe_filename
from tracksplit.models import TrackMeta


def build_split_command(
    input_path: Path,
    output_path: Path,
    start: float,
    end: float | None,
) -> list[str]:
    """Build an ffmpeg command to extract a single track.

    When end is None (last track), the -to flag is omitted so ffmpeg
    reads to end of file.
    """
    cmd = [
        "ffmpeg",
        "-i", str(input_path),
        "-ss", str(start),
    ]
    if end is not None:
        cmd.extend(["-to", str(end)])
    cmd.extend(["-c:a", "copy", "-y", str(output_path)])
    return cmd


def build_track_filename(track: TrackMeta) -> str:
    """Build a sanitized filename for a track.

    Format: {number:02d} - {artist} - {title}.flac
    Or:     {number:02d} - {title}.flac (when no track artist)
    """
    if track.artist:
        name = f"{track.artist} - {track.title}"
    else:
        name = track.title
    return f"{track.number:02d} - {safe_filename(name)}.flac"


def split_tracks(
    full_flac: Path,
    tracks: list[TrackMeta],
    output_dir: Path,
) -> list[Path]:
    """Split a full FLAC into individual track files.

    Creates output_dir if it does not exist. For each track, the end time
    is the next track's start time, or None for the last track.
    Returns the list of output file paths.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    output_paths: list[Path] = []
    for i, track in enumerate(tracks):
        filename = build_track_filename(track)
        output_path = output_dir / filename

        # End time is next track's start, or None for the last track
        if i + 1 < len(tracks):
            end = tracks[i + 1].start
        else:
            end = None

        cmd = build_split_command(full_flac, output_path, track.start, end)
        subprocess.run(cmd, check=True)
        output_paths.append(output_path)

    return output_paths
