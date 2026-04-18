"""Split a full FLAC into individual tracks at chapter boundaries."""
from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from tracksplit.metadata import safe_filename
from tracksplit.models import TrackMeta
from tracksplit.opus_patch import patch_opus_pre_skip
from tracksplit.subprocess_utils import CancelledError, tracked_run
from tracksplit.tools import get_tool

OPUS_FRAME_SECONDS = 0.020
OPUS_FRAME_SAMPLES = 960  # OPUS_FRAME_SECONDS * 48000 Hz


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
        get_tool("ffmpeg"),
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
    cancel_event: threading.Event | None = None,
    opus_packet_ms: int | None = None,
) -> list[Path]:
    """Split audio into individual track files.

    Creates output_dir if it does not exist. For each track, the end time
    is the next track's start time, or None for the last track. Returns
    the list of output file paths.

    When ``ext == ".opus"``, ``codec_mode == "copy"``, and
    ``opus_packet_ms == 20``, every track after the first is cut 20 ms
    earlier than its ``track.start`` and its OpusHead pre_skip is
    rewritten to 960. The decoder uses the extra prefix packet to warm
    up and discards it via pre_skip, eliminating the short click at
    track boundaries in gapless-aware players.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    apply_opus_prefix = (
        ext == ".opus"
        and codec_mode == "copy"
        and opus_packet_ms == 20
    )

    total = len(tracks)
    output_paths: list[Path] = []
    for i, track in enumerate(tracks):
        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError("Cancelled")

        if on_progress:
            on_progress("Splitting tracks", i + 1, total)

        filename = build_track_filename(track, ext=ext)
        output_path = output_dir / filename

        if i + 1 < len(tracks):
            end = tracks[i + 1].start
        else:
            end = None

        use_prefix = (
            apply_opus_prefix
            and i > 0
            and track.start - OPUS_FRAME_SECONDS >= 0.0
        )
        start = track.start - OPUS_FRAME_SECONDS if use_prefix else track.start

        cmd = build_split_command(
            full_flac, output_path, start, end,
            codec_mode=codec_mode, from_video=from_video,
        )
        tracked_run(cmd, cancel_event=cancel_event)

        if use_prefix:
            patch_opus_pre_skip(output_path, OPUS_FRAME_SAMPLES)

        output_paths.append(output_path)

    return output_paths
