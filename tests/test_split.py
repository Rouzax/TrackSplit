from pathlib import Path

from tracksplit.models import TrackMeta
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


class TestBuildTrackFilename:
    def test_basic(self):
        track = TrackMeta(number=3, title="Blah Blah Blah", start=0.0, end=60.0)
        assert build_track_filename(track) == "03 - Blah Blah Blah.flac"

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

        mock_run = mocker.patch("tracksplit.split.subprocess.run")

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
