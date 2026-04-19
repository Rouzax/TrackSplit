import subprocess
from pathlib import Path

import pytest

from tracksplit.models import TrackMeta
from tracksplit.opus_patch import read_opus_pre_skip
from tracksplit.split import build_split_command, build_track_filename, split_tracks


class TestBuildSplitCommand:
    def test_middle_track_has_end_time(self):
        cmd = build_split_command(
            input_path=Path("/tmp/full.flac"),
            output_path=Path("/tmp/out/01 - Song.flac"),
            start=60.0,
            end=180.0,
        )
        assert cmd == [
            "ffmpeg",
            "-i", "/tmp/full.flac",
            "-ss", "60.0",
            "-to", "180.0",
            "-c:a", "copy",
            "-y",
            "/tmp/out/01 - Song.flac",
        ]

    def test_last_track_no_end(self):
        cmd = build_split_command(
            input_path=Path("/tmp/full.flac"),
            output_path=Path("/tmp/out/05 - Closer.flac"),
            start=300.0,
            end=None,
        )
        assert cmd == [
            "ffmpeg",
            "-i", "/tmp/full.flac",
            "-ss", "300.0",
            "-c:a", "copy",
            "-y",
            "/tmp/out/05 - Closer.flac",
        ]
        assert "-to" not in cmd

    def test_from_video_adds_vn_flag(self):
        cmd = build_split_command(
            input_path=Path("/tmp/video.mkv"),
            output_path=Path("/tmp/out/01 - Song.opus"),
            start=0.0,
            end=60.0,
            codec_mode="copy",
            from_video=True,
        )
        assert "-vn" in cmd
        assert cmd == [
            "ffmpeg",
            "-i", "/tmp/video.mkv",
            "-ss", "0.0",
            "-to", "60.0",
            "-vn",
            "-c:a", "copy",
            "-y",
            "/tmp/out/01 - Song.opus",
        ]

    def test_libopus_codec_mode(self):
        cmd = build_split_command(
            input_path=Path("/tmp/video.mkv"),
            output_path=Path("/tmp/out/01 - Song.opus"),
            start=0.0,
            end=60.0,
            codec_mode="libopus",
        )
        assert "-c:a" in cmd
        idx = cmd.index("-c:a")
        assert cmd[idx + 1] == "libopus"
        assert "-b:a" in cmd
        assert "256k" in cmd

    def test_libopus_with_from_video(self):
        cmd = build_split_command(
            input_path=Path("/tmp/video.mkv"),
            output_path=Path("/tmp/out/01 - Song.opus"),
            start=10.0,
            end=70.0,
            codec_mode="libopus",
            from_video=True,
        )
        assert "-vn" in cmd
        assert cmd == [
            "ffmpeg",
            "-i", "/tmp/video.mkv",
            "-ss", "10.0",
            "-to", "70.0",
            "-vn",
            "-c:a", "libopus", "-b:a", "256k",
            "-y",
            "/tmp/out/01 - Song.opus",
        ]


class TestBuildTrackFilename:
    def test_basic(self):
        track = TrackMeta(number=3, title="Blah Blah Blah", start=0.0, end=60.0)
        assert build_track_filename(track) == "03 - Blah Blah Blah.flac"

    def test_ogg_extension(self):
        track = TrackMeta(number=3, title="Blah Blah Blah", start=0.0, end=60.0)
        assert build_track_filename(track, ext=".opus") == "03 - Blah Blah Blah.opus"

    def test_unsafe_chars_removed(self):
        track = TrackMeta(
            number=7, title='Live @ "Festival" <2024>', start=0.0, end=60.0
        )
        result = build_track_filename(track)
        assert "/" not in result
        assert '"' not in result
        assert "<" not in result
        assert ">" not in result
        assert result.endswith(".flac")
        assert result.startswith("07 - ")

    def test_track_number_zero(self):
        track = TrackMeta(number=0, title="Intro", start=0.0, end=30.0)
        assert build_track_filename(track) == "00 - Intro.flac"


class TestSplitTracks:
    def test_creates_output_dir_and_runs_ffmpeg(self, tmp_path, mocker):
        full_flac = tmp_path / "full.flac"
        full_flac.touch()
        output_dir = tmp_path / "output" / "album"

        tracks = [
            TrackMeta(number=1, title="First", start=0.0, end=60.0),
            TrackMeta(number=2, title="Second", start=60.0, end=180.0),
            TrackMeta(number=3, title="Third", start=180.0, end=300.0),
        ]

        mock_run = mocker.patch("tracksplit.split.tracked_run")

        results = split_tracks(full_flac, tracks, output_dir)

        assert output_dir.exists()
        assert len(results) == 3
        assert results[0] == output_dir / "01 - First.flac"
        assert results[1] == output_dir / "02 - Second.flac"
        assert results[2] == output_dir / "03 - Third.flac"

        # First track: end = next track's start (60.0)
        first_call = mock_run.call_args_list[0]
        cmd = first_call[0][0]
        assert "-to" in cmd
        assert "60.0" in cmd

        # Last track: no end
        last_call = mock_run.call_args_list[2]
        cmd = last_call[0][0]
        assert "-to" not in cmd

        assert mock_run.call_count == 3

    def test_split_tracks_with_ogg_extension(self, tmp_path, mocker):
        full_audio = tmp_path / "video.mkv"
        full_audio.touch()
        output_dir = tmp_path / "output" / "album"

        tracks = [
            TrackMeta(number=1, title="First", start=0.0, end=60.0),
            TrackMeta(number=2, title="Second", start=60.0, end=180.0),
        ]

        mock_run = mocker.patch("tracksplit.split.tracked_run")

        results = split_tracks(
            full_audio, tracks, output_dir,
            ext=".opus", codec_mode="copy", from_video=True,
        )

        assert len(results) == 2
        assert results[0] == output_dir / "01 - First.opus"
        assert results[1] == output_dir / "02 - Second.opus"

        # Check from_video flag produces -vn
        first_cmd = mock_run.call_args_list[0][0][0]
        assert "-vn" in first_cmd


def _ss_arg(cmd: list[str]) -> float:
    """Extract the float passed to -ss in an ffmpeg command."""
    return float(cmd[cmd.index("-ss") + 1])


class TestSplitTracksOpusPrefix:
    def _tracks(self):
        return [
            TrackMeta(number=1, title="One", start=0.0, end=60.0),
            TrackMeta(number=2, title="Two", start=60.0, end=180.0),
            TrackMeta(number=3, title="Three", start=180.0, end=300.0),
        ]

    def test_prefix_offset_for_tracks_two_and_three(self, tmp_path, mocker):
        from tracksplit.split import split_tracks

        audio = tmp_path / "src.mkv"
        audio.touch()
        mock_run = mocker.patch("tracksplit.split.tracked_run")
        mock_patch = mocker.patch("tracksplit.split.patch_opus_pre_skip")

        split_tracks(
            audio, self._tracks(), tmp_path / "out",
            ext=".opus", codec_mode="copy", from_video=True,
            opus_packet_ms=20,
        )

        cmds = [c.args[0] for c in mock_run.call_args_list]
        assert _ss_arg(cmds[0]) == pytest.approx(0.0)
        assert _ss_arg(cmds[1]) == pytest.approx(59.98)
        assert _ss_arg(cmds[2]) == pytest.approx(179.98)

        assert mock_patch.call_count == 2
        for c in mock_patch.call_args_list:
            assert c.args[1] == 960

    def test_no_offset_when_packet_ms_is_none(self, tmp_path, mocker):
        from tracksplit.split import split_tracks

        audio = tmp_path / "src.mkv"
        audio.touch()
        mock_run = mocker.patch("tracksplit.split.tracked_run")
        mock_patch = mocker.patch("tracksplit.split.patch_opus_pre_skip")

        split_tracks(
            audio, self._tracks(), tmp_path / "out",
            ext=".opus", codec_mode="copy", from_video=True,
            opus_packet_ms=None,
        )

        cmds = [c.args[0] for c in mock_run.call_args_list]
        assert _ss_arg(cmds[1]) == pytest.approx(60.0)
        assert _ss_arg(cmds[2]) == pytest.approx(180.0)
        assert mock_patch.call_count == 0

    def test_no_offset_when_packet_ms_not_twenty(self, tmp_path, mocker):
        from tracksplit.split import split_tracks

        audio = tmp_path / "src.mkv"
        audio.touch()
        mock_run = mocker.patch("tracksplit.split.tracked_run")
        mock_patch = mocker.patch("tracksplit.split.patch_opus_pre_skip")

        split_tracks(
            audio, self._tracks(), tmp_path / "out",
            ext=".opus", codec_mode="copy", from_video=True,
            opus_packet_ms=60,
        )

        assert mock_patch.call_count == 0

    def test_no_offset_for_libopus_mode(self, tmp_path, mocker):
        from tracksplit.split import split_tracks

        audio = tmp_path / "src.mkv"
        audio.touch()
        mock_run = mocker.patch("tracksplit.split.tracked_run")
        mock_patch = mocker.patch("tracksplit.split.patch_opus_pre_skip")

        split_tracks(
            audio, self._tracks(), tmp_path / "out",
            ext=".opus", codec_mode="libopus", from_video=True,
            opus_packet_ms=20,
        )

        assert mock_patch.call_count == 0

    def test_no_offset_for_flac(self, tmp_path, mocker):
        from tracksplit.split import split_tracks

        audio = tmp_path / "src.flac"
        audio.touch()
        mock_run = mocker.patch("tracksplit.split.tracked_run")
        mock_patch = mocker.patch("tracksplit.split.patch_opus_pre_skip")

        split_tracks(
            audio, self._tracks(), tmp_path / "out",
            ext=".flac", codec_mode="copy",
            opus_packet_ms=20,
        )

        assert mock_patch.call_count == 0

    def test_defensive_guard_negative_start(self, tmp_path, mocker):
        from tracksplit.split import split_tracks

        audio = tmp_path / "src.mkv"
        audio.touch()
        mock_run = mocker.patch("tracksplit.split.tracked_run")
        mock_patch = mocker.patch("tracksplit.split.patch_opus_pre_skip")

        tracks = [
            TrackMeta(number=1, title="One", start=0.0, end=0.01),
            TrackMeta(number=2, title="Two", start=0.01, end=60.0),
        ]

        split_tracks(
            audio, tracks, tmp_path / "out",
            ext=".opus", codec_mode="copy", from_video=True,
            opus_packet_ms=20,
        )

        cmds = [c.args[0] for c in mock_run.call_args_list]
        assert _ss_arg(cmds[1]) == pytest.approx(0.01)
        assert mock_patch.call_count == 0


def _make_opus_mkv(tmp_path: Path, chapter_starts: list[float], total: float) -> Path:
    """Synthesize a stereo Opus-in-MKV with explicit chapter starts (seconds)."""
    opus_file = tmp_path / "audio.opus"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi",
            "-i", f"sine=frequency=440:duration={total}:sample_rate=48000",
            "-ac", "2", "-c:a", "libopus", "-b:a", "64k",
            str(opus_file),
        ],
        check=True,
    )
    lines = [";FFMETADATA1"]
    for i, start in enumerate(chapter_starts):
        end = chapter_starts[i + 1] if i + 1 < len(chapter_starts) else total
        lines.append("[CHAPTER]")
        lines.append("TIMEBASE=1/1000")
        lines.append(f"START={int(start * 1000)}")
        lines.append(f"END={int(end * 1000)}")
        lines.append(f"title=Track {i + 1}")
    meta_file = tmp_path / "meta.txt"
    meta_file.write_text("\n".join(lines) + "\n")
    mkv_file = tmp_path / "source.mkv"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(opus_file),
            "-i", str(meta_file),
            "-map_metadata", "1",
            "-c:a", "copy",
            str(mkv_file),
        ],
        check=True,
    )
    return mkv_file


class TestSplitTracksOpusEndToEnd:
    def test_split_writes_expected_pre_skip_values(self, tmp_path):
        mkv = _make_opus_mkv(tmp_path, [0.0, 0.5, 1.0], total=1.5)
        tracks = [
            TrackMeta(number=1, title="One", start=0.0, end=0.5),
            TrackMeta(number=2, title="Two", start=0.5, end=1.0),
            TrackMeta(number=3, title="Three", start=1.0, end=1.5),
        ]
        out_dir = tmp_path / "out"

        split_tracks(
            mkv, tracks, out_dir,
            ext=".opus", codec_mode="copy", from_video=True,
            opus_packet_ms=20,
        )

        written = sorted(out_dir.glob("*.opus"))
        assert len(written) == 3

        assert read_opus_pre_skip(written[0]) == 312
        assert read_opus_pre_skip(written[1]) == 960
        assert read_opus_pre_skip(written[2]) == 960

    def test_split_without_prefix_leaves_source_pre_skip(self, tmp_path):
        mkv = _make_opus_mkv(tmp_path, [0.0, 0.5, 1.0], total=1.5)
        tracks = [
            TrackMeta(number=1, title="One", start=0.0, end=0.5),
            TrackMeta(number=2, title="Two", start=0.5, end=1.0),
            TrackMeta(number=3, title="Three", start=1.0, end=1.5),
        ]
        out_dir = tmp_path / "out"

        split_tracks(
            mkv, tracks, out_dir,
            ext=".opus", codec_mode="copy", from_video=True,
            opus_packet_ms=None,
        )

        written = sorted(out_dir.glob("*.opus"))
        assert len(written) == 3
        for path in written:
            assert read_opus_pre_skip(path) == 312
