"""Tests for the pipeline module."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tracksplit.models import AlbumMeta, Chapter, TrackMeta
from tracksplit.pipeline import (
    _apply_intro_track,
    _safe_log_name,
    build_intro_track,
)

# ---------------------------------------------------------------------------
# build_intro_track
# ---------------------------------------------------------------------------


class TestBuildIntroTrack:
    def test_intro_track_created(self):
        """First chapter starts after 0.0, so an intro track is created."""
        chapters = [
            Chapter(index=1, title="Track 1", start=30.0, end=120.0),
            Chapter(index=2, title="Track 2", start=120.0, end=240.0),
        ]
        result = build_intro_track(chapters)
        assert result is not None
        assert result.number == 0
        assert result.title == "Intro"
        assert result.start == 0.0
        assert result.end == 30.0

    def test_no_intro_when_starts_at_zero(self):
        """First chapter starts at 0.0, no intro needed."""
        chapters = [
            Chapter(index=1, title="Track 1", start=0.0, end=120.0),
        ]
        result = build_intro_track(chapters)
        assert result is None

    def test_empty_chapters(self):
        """Empty chapter list returns None."""
        result = build_intro_track([])
        assert result is None

    def test_build_intro_track_returns_none_for_short_gap(self):
        """First chapter starts at 2.0s (below 5s threshold), no intro."""
        chapters = [Chapter(index=1, title="Track A", start=2.0, end=60.0)]
        assert build_intro_track(chapters) is None

    def test_build_intro_track_returns_none_just_under_threshold(self):
        """First chapter starts at 4.999s (just below threshold), no intro."""
        chapters = [Chapter(index=1, title="Track A", start=4.999, end=60.0)]
        assert build_intro_track(chapters) is None

    def test_build_intro_track_creates_intro_at_threshold_boundary(self):
        """First chapter starts exactly at 5.0s (boundary is exclusive), intro created."""
        chapters = [Chapter(index=1, title="Track A", start=5.0, end=60.0)]
        intro = build_intro_track(chapters)
        assert intro is not None
        assert intro.start == 0.0
        assert intro.end == 5.0
        assert intro.title == "Intro"


# ---------------------------------------------------------------------------
# _apply_intro_track
# ---------------------------------------------------------------------------


class TestApplyIntroTrack:
    def test_apply_intro_track_inserts_intro_when_gap_meets_threshold(self):
        """Gap of 10s meets the threshold, so an Intro track is prepended."""
        album = AlbumMeta(
            artist="DJ X",
            album="Set",
            tracks=[TrackMeta(number=1, title="Track A", start=10.0, end=60.0)],
        )
        chapters = [Chapter(index=1, title="Track A", start=10.0, end=60.0)]
        _apply_intro_track(album, chapters)
        assert len(album.tracks) == 2
        assert album.tracks[0].title == "Intro"
        assert album.tracks[0].start == 0.0
        assert album.tracks[0].end == 10.0
        assert album.tracks[1].start == 10.0

    def test_apply_intro_track_slides_track_one_for_short_gap(self):
        """Gap of 2s is under threshold: no intro, but track 1 slides to 0.0."""
        album = AlbumMeta(
            artist="DJ X",
            album="Set",
            tracks=[TrackMeta(number=1, title="Track A", start=2.0, end=60.0)],
        )
        chapters = [Chapter(index=1, title="Track A", start=2.0, end=60.0)]
        _apply_intro_track(album, chapters)
        assert len(album.tracks) == 1
        assert album.tracks[0].start == 0.0
        assert album.tracks[0].title == "Track A"

    def test_apply_intro_track_is_noop_for_zero_gap(self):
        """First chapter starts at 0.0: no intro, no slide."""
        album = AlbumMeta(
            artist="DJ X",
            album="Set",
            tracks=[TrackMeta(number=1, title="Track A", start=0.0, end=60.0)],
        )
        chapters = [Chapter(index=1, title="Track A", start=0.0, end=60.0)]
        _apply_intro_track(album, chapters)
        assert len(album.tracks) == 1
        assert album.tracks[0].start == 0.0

    def test_apply_intro_track_handles_empty_chapters(self):
        """No chapters: album is untouched."""
        album = AlbumMeta(
            artist="DJ X",
            album="Set",
            tracks=[TrackMeta(number=1, title="Whole album", start=0.0, end=60.0)],
        )
        _apply_intro_track(album, chapters=[])
        assert len(album.tracks) == 1
        assert album.tracks[0].start == 0.0


# ---------------------------------------------------------------------------
# retag_album
# ---------------------------------------------------------------------------


class TestRetagAlbum:
    @patch("tracksplit.pipeline.tag_all")
    @patch("tracksplit.pipeline.compose_cover")
    @patch("tracksplit.pipeline.extract_cover_from_mkv")
    def test_retag_album_retags_and_rebuilds_cover(
        self,
        mock_extract,
        mock_compose,
        mock_tag,
        tmp_path,
    ):
        from tests._manifest_helpers import (
            default_tags,
            make_audio_fp,
            make_ffprobe,
            make_manifest_dict,
        )
        from tracksplit.manifest import (
            ALBUM_MANIFEST_FILENAME,
            load_album_manifest,
        )
        from tracksplit.pipeline import retag_album
        from tracksplit.tagger import TAG_SCHEMA_VERSION

        src = tmp_path / "src.mkv"
        src.write_bytes(b"x" * 10)
        album_dir = tmp_path / "album"
        album_dir.mkdir()

        (album_dir / "01 - T.flac").write_bytes(b"audio")

        data = make_manifest_dict(
            source_path=str(src),
            track_filenames=["01 - T.flac"],
            tag_schema_version=0,
        )
        (album_dir / ALBUM_MANIFEST_FILENAME).write_text(json.dumps(data))

        mock_extract.return_value = None
        mock_compose.return_value = b"NEW-COVER"

        new_tags = {**default_tags(), "festival": "Updated Fest"}
        album = AlbumMeta(
            artist="A",
            album="B",
            festival="Updated Fest",
            tracks=[TrackMeta(number=1, title="T", start=0.0, end=60.0)],
        )
        ffprobe = make_ffprobe(make_audio_fp())

        retag_album(
            album_dir=album_dir,
            album=album,
            source_path=src,
            ffprobe_data=ffprobe,
            tags=new_tags,
            chapter_dicts=[
                {"index": 1, "title": "T", "start": 0.0, "end": 60.0, "tags": {}}
            ],
            artist_folder="A",
            album_folder="B",
            codec_mode="copy",
        )

        mock_tag.assert_called_once()
        call_paths = mock_tag.call_args[0][0]
        assert [p.name for p in call_paths] == ["01 - T.flac"]

        assert (album_dir / "cover.jpg").read_bytes() == b"NEW-COVER"

        m = load_album_manifest(album_dir)
        assert m is not None
        assert m.tag_schema_version == TAG_SCHEMA_VERSION
        assert m.album_tags["festival"] == "Updated Fest"

    def test_retag_album_raises_on_missing_track(self, tmp_path):
        from tests._manifest_helpers import (
            default_tags,
            make_audio_fp,
            make_ffprobe,
            make_manifest_dict,
        )
        from tracksplit.manifest import ALBUM_MANIFEST_FILENAME
        from tracksplit.pipeline import retag_album

        src = tmp_path / "src.mkv"
        src.write_bytes(b"x" * 10)
        album_dir = tmp_path / "album"
        album_dir.mkdir()

        data = make_manifest_dict(
            source_path=str(src),
            track_filenames=["01 - T.flac"],
        )
        (album_dir / ALBUM_MANIFEST_FILENAME).write_text(json.dumps(data))

        album = AlbumMeta(
            artist="A",
            album="B",
            tracks=[TrackMeta(number=1, title="T", start=0.0, end=60.0)],
        )
        with pytest.raises(FileNotFoundError):
            retag_album(
                album_dir=album_dir,
                album=album,
                source_path=src,
                ffprobe_data=make_ffprobe(make_audio_fp()),
                tags=default_tags(),
                chapter_dicts=[
                    {"index": 1, "title": "T", "start": 0.0, "end": 60.0, "tags": {}}
                ],
                artist_folder="A",
                album_folder="B",
                codec_mode="copy",
            )

    @patch("tracksplit.pipeline.tag_all")
    @patch("tracksplit.pipeline.compose_cover")
    @patch("tracksplit.pipeline.extract_cover_from_mkv")
    def test_retag_album_reuses_cover_when_schema_current(
        self,
        mock_extract,
        mock_compose,
        mock_tag,
        tmp_path,
    ):
        """reuse_cover=True with current cover schema reads cover.jpg
        from disk instead of extracting from MKV and recomposing."""
        from tests._manifest_helpers import (
            default_tags,
            make_audio_fp,
            make_ffprobe,
            make_manifest_dict,
        )
        from tracksplit.cover import COVER_SCHEMA_VERSION
        from tracksplit.manifest import ALBUM_MANIFEST_FILENAME
        from tracksplit.pipeline import retag_album

        src = tmp_path / "src.mkv"
        src.write_bytes(b"x" * 10)
        album_dir = tmp_path / "album"
        album_dir.mkdir()
        (album_dir / "01 - T.flac").write_bytes(b"audio")
        (album_dir / "cover.jpg").write_bytes(b"EXISTING-COVER")

        data = make_manifest_dict(
            source_path=str(src),
            track_filenames=["01 - T.flac"],
            tag_schema_version=0,
            cover_schema_version=COVER_SCHEMA_VERSION,
        )
        (album_dir / ALBUM_MANIFEST_FILENAME).write_text(json.dumps(data))

        album = AlbumMeta(
            artist="A",
            album="B",
            tracks=[TrackMeta(number=1, title="T", start=0.0, end=60.0)],
        )
        retag_album(
            album_dir=album_dir,
            album=album,
            source_path=src,
            ffprobe_data=make_ffprobe(make_audio_fp()),
            tags=default_tags(),
            chapter_dicts=[
                {"index": 1, "title": "T", "start": 0.0, "end": 60.0, "tags": {}}
            ],
            artist_folder="A",
            album_folder="B",
            codec_mode="copy",
            reuse_cover=True,
        )

        mock_extract.assert_not_called()
        mock_compose.assert_not_called()
        call_kwargs = mock_tag.call_args
        assert call_kwargs[1]["cover_data"] == b"EXISTING-COVER"

    @patch("tracksplit.pipeline.tag_all")
    @patch("tracksplit.pipeline.compose_cover")
    @patch("tracksplit.pipeline.extract_cover_from_mkv")
    def test_retag_album_recomposes_cover_when_cover_schema_outdated(
        self,
        mock_extract,
        mock_compose,
        mock_tag,
        tmp_path,
    ):
        """reuse_cover=True but cover_schema_version is outdated: must
        recompose from MKV, not reuse cover.jpg."""
        from tests._manifest_helpers import (
            default_tags,
            make_audio_fp,
            make_ffprobe,
            make_manifest_dict,
        )
        from tracksplit.manifest import ALBUM_MANIFEST_FILENAME
        from tracksplit.pipeline import retag_album

        src = tmp_path / "src.mkv"
        src.write_bytes(b"x" * 10)
        album_dir = tmp_path / "album"
        album_dir.mkdir()
        (album_dir / "01 - T.flac").write_bytes(b"audio")
        (album_dir / "cover.jpg").write_bytes(b"OLD-COVER")

        data = make_manifest_dict(
            source_path=str(src),
            track_filenames=["01 - T.flac"],
            cover_schema_version=0,
        )
        (album_dir / ALBUM_MANIFEST_FILENAME).write_text(json.dumps(data))

        mock_extract.return_value = None
        mock_compose.return_value = b"NEW-COVER"

        album = AlbumMeta(
            artist="A",
            album="B",
            tracks=[TrackMeta(number=1, title="T", start=0.0, end=60.0)],
        )
        retag_album(
            album_dir=album_dir,
            album=album,
            source_path=src,
            ffprobe_data=make_ffprobe(make_audio_fp()),
            tags=default_tags(),
            chapter_dicts=[
                {"index": 1, "title": "T", "start": 0.0, "end": 60.0, "tags": {}}
            ],
            artist_folder="A",
            album_folder="B",
            codec_mode="copy",
            reuse_cover=True,
        )

        mock_extract.assert_called_once()
        mock_compose.assert_called_once()
        assert (album_dir / "cover.jpg").read_bytes() == b"NEW-COVER"

    @patch("tracksplit.pipeline.tag_all")
    @patch("tracksplit.pipeline.compose_cover")
    @patch("tracksplit.pipeline.extract_cover_from_mkv")
    def test_retag_album_recomposes_cover_when_cover_jpg_missing(
        self,
        mock_extract,
        mock_compose,
        mock_tag,
        tmp_path,
    ):
        """reuse_cover=True but cover.jpg does not exist on disk:
        must recompose."""
        from tests._manifest_helpers import (
            default_tags,
            make_audio_fp,
            make_ffprobe,
            make_manifest_dict,
        )
        from tracksplit.cover import COVER_SCHEMA_VERSION
        from tracksplit.manifest import ALBUM_MANIFEST_FILENAME
        from tracksplit.pipeline import retag_album

        src = tmp_path / "src.mkv"
        src.write_bytes(b"x" * 10)
        album_dir = tmp_path / "album"
        album_dir.mkdir()
        (album_dir / "01 - T.flac").write_bytes(b"audio")
        # No cover.jpg on disk

        data = make_manifest_dict(
            source_path=str(src),
            track_filenames=["01 - T.flac"],
            cover_schema_version=COVER_SCHEMA_VERSION,
        )
        (album_dir / ALBUM_MANIFEST_FILENAME).write_text(json.dumps(data))

        mock_extract.return_value = None
        mock_compose.return_value = b"COMPOSED-COVER"

        album = AlbumMeta(
            artist="A",
            album="B",
            tracks=[TrackMeta(number=1, title="T", start=0.0, end=60.0)],
        )
        retag_album(
            album_dir=album_dir,
            album=album,
            source_path=src,
            ffprobe_data=make_ffprobe(make_audio_fp()),
            tags=default_tags(),
            chapter_dicts=[
                {"index": 1, "title": "T", "start": 0.0, "end": 60.0, "tags": {}}
            ],
            artist_folder="A",
            album_folder="B",
            codec_mode="copy",
            reuse_cover=True,
        )

        mock_extract.assert_called_once()
        mock_compose.assert_called_once()
        assert (album_dir / "cover.jpg").read_bytes() == b"COMPOSED-COVER"

    @pytest.mark.skipif(
        __import__("shutil").which("ffmpeg") is None,
        reason="ffmpeg required",
    )
    @patch("tracksplit.pipeline.compose_cover")
    @patch("tracksplit.pipeline.extract_cover_from_mkv")
    def test_retag_album_writes_new_tags_to_real_flac(
        self,
        mock_extract,
        mock_compose,
        tmp_path,
    ):
        """End-to-end: create a real FLAC with old-style tags (no
        ORIGINALDATE/RELEASEDATE/DISCTOTAL), run retag_album, and
        verify the new Vorbis comments appear on disk."""
        import subprocess

        from mutagen.flac import FLAC

        from tests._manifest_helpers import (
            default_tags,
            make_audio_fp,
            make_ffprobe,
            make_manifest_dict,
        )
        from tracksplit.manifest import ALBUM_MANIFEST_FILENAME
        from tracksplit.pipeline import retag_album

        src = tmp_path / "src.mkv"
        src.write_bytes(b"x" * 10)
        album_dir = tmp_path / "album"
        album_dir.mkdir()
        flac_path = album_dir / "01 - T.flac"

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=44100",
                "-t",
                "0.5",
                "-c:a",
                "flac",
                str(flac_path),
            ],
            check=True,
            capture_output=True,
        )

        # Simulate old TrackSplit output: write tags WITHOUT the new ones
        audio = FLAC(flac_path)
        audio.clear()
        audio["TITLE"] = ["T"]
        audio["ARTIST"] = ["DJ X"]
        audio["ALBUMARTIST"] = ["DJ X"]
        audio["ALBUM"] = ["Fest 2025"]
        audio["TRACKNUMBER"] = ["1"]
        audio["DISCNUMBER"] = ["1"]
        audio["DATE"] = ["2025-06-15"]
        audio.save()

        audio = FLAC(flac_path)
        assert audio["DATE"] == ["2025-06-15"]
        assert "ORIGINALDATE" not in audio
        assert "RELEASEDATE" not in audio
        assert "DISCTOTAL" not in audio

        data = make_manifest_dict(
            source_path=str(src),
            track_filenames=["01 - T.flac"],
            tag_schema_version=0,
        )
        (album_dir / ALBUM_MANIFEST_FILENAME).write_text(json.dumps(data))

        mock_extract.return_value = None
        mock_compose.return_value = b"COVER"

        new_album = AlbumMeta(
            artist="DJ X",
            album="Fest 2025",
            date="2025-06-15",
            tracks=[TrackMeta(number=1, title="T", start=0.0, end=30.0)],
        )
        retag_album(
            album_dir=album_dir,
            album=new_album,
            source_path=src,
            ffprobe_data=make_ffprobe(make_audio_fp()),
            tags={**default_tags(), "artist": "DJ X", "date": "2025-06-15"},
            chapter_dicts=[
                {"index": 1, "title": "T", "start": 0.0, "end": 30.0, "tags": {}}
            ],
            artist_folder="DJ X",
            album_folder="Fest 2025",
            codec_mode="copy",
        )

        reread = FLAC(flac_path)
        assert reread["DATE"] == ["2025-06-15"]
        assert reread["ORIGINALDATE"] == ["2025-06-15"]
        assert reread["RELEASEDATE"] == ["2025-06-15"]
        assert reread["DISCTOTAL"] == ["1"]
        assert reread["ARTIST"] == ["DJ X"]
        assert reread["ALBUM"] == ["Fest 2025"]


# ---------------------------------------------------------------------------
# _safe_log_name
# ---------------------------------------------------------------------------


class TestSafeLogName:
    def test_normal_path(self):
        assert _safe_log_name(Path("/tmp/test.mkv")) == "test.mkv"

    def test_surrogate_path(self):
        """Should not raise even with surrogate bytes."""
        result = _safe_log_name(Path("/tmp/test\udceb.mkv"))
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# process_file: no chapters, no duration
# ---------------------------------------------------------------------------


class TestProcessFileNoChapters:
    @patch("tracksplit.pipeline.run_ffprobe")
    def test_no_chapters_no_duration_skips(self, mock_probe, tmp_path):
        """File with no chapters and no duration should be skipped."""
        mock_probe.return_value = {
            "streams": [{"codec_type": "audio", "codec_name": "aac"}],
            "format": {"tags": {}},
            "chapters": [],
        }
        input_file = tmp_path / "empty.mkv"
        input_file.touch()

        from tracksplit.pipeline import process_file

        result = process_file(input_file, tmp_path / "out")
        assert result is False


class TestProcessFileManifest:
    def _probe(self):
        return {
            "streams": [{"codec_type": "audio", "codec_name": "flac"}],
            "format": {
                "tags": {
                    "ARTIST": "DJ X",
                    "CRATEDIGGER_1001TL_FESTIVAL": "Show",
                    "CRATEDIGGER_1001TL_DATE": "2025",
                },
                "duration": "600.0",
            },
            "chapters": [
                {
                    "start_time": "0.0",
                    "end_time": "300.0",
                    "tags": {"title": "Track 1"},
                },
                {
                    "start_time": "300.0",
                    "end_time": "600.0",
                    "tags": {"title": "Track 2"},
                },
            ],
        }

    @patch("tracksplit.pipeline.tag_all")
    @patch("tracksplit.pipeline.split_tracks")
    @patch("tracksplit.pipeline.prepare_audio")
    @patch("tracksplit.pipeline.compose_cover")
    @patch("tracksplit.pipeline.compose_artist_cover")
    @patch("tracksplit.pipeline.find_dj_artwork")
    @patch("tracksplit.pipeline.extract_cover_from_mkv")
    @patch("tracksplit.pipeline.run_ffprobe")
    def test_process_file_writes_manifest(
        self,
        mock_probe,
        mock_cover_mkv,
        mock_dj,
        mock_artist_cover,
        mock_compose,
        mock_prepare,
        mock_split,
        mock_tag,
        tmp_path,
    ):
        from tracksplit.manifest import load_album_manifest
        from tracksplit.pipeline import process_file

        mock_probe.return_value = self._probe()
        mock_cover_mkv.return_value = None
        mock_dj.return_value = None
        mock_compose.return_value = b"JPEG"
        mock_artist_cover.return_value = b"JPEG2"

        src = tmp_path / "src.mkv"
        src.write_bytes(b"data" * 64)
        out = tmp_path / "out"
        album_dir = out / "DJ X" / "Show 2025"

        mock_prepare.return_value = (src, ".flac", "copy")
        mock_split.return_value = [
            album_dir / "01 - DJ X - Track 1.flac",
            album_dir / "02 - DJ X - Track 2.flac",
        ]

        assert process_file(src, out) is True
        m = load_album_manifest(album_dir)
        assert m is not None
        assert m.source_path == str(src)
        assert m.identity.audio.codec_name == "flac"
        assert m.output_format == "flac"
        assert m.codec_mode == "copy"
        assert len(m.tracks) == 2
        assert m.cover_sha256  # non-empty
        assert [t.filename for t in m.tracks] == [
            "01 - DJ X - Track 1.flac",
            "02 - DJ X - Track 2.flac",
        ]

    @patch("tracksplit.pipeline.run_ffprobe")
    def test_process_file_skips_when_manifest_matches(
        self,
        mock_probe,
        tmp_path,
    ):
        from tracksplit.pipeline import process_file

        src = tmp_path / "src.mkv"
        src.write_bytes(b"data" * 64)
        ffprobe_data = {
            "streams": [{"codec_type": "audio", "codec_name": "flac"}],
            "format": {
                "tags": {
                    "ARTIST": "DJ X",
                    "CRATEDIGGER_1001TL_FESTIVAL": "Show",
                    "CRATEDIGGER_1001TL_DATE": "2025",
                },
                "duration": "600.0",
            },
            "chapters": [
                {
                    "start_time": "0.0",
                    "end_time": "600.0",
                    "tags": {"title": "Track 1"},
                },
            ],
        }
        mock_probe.return_value = ffprobe_data
        album_dir = tmp_path / "out" / "DJ X" / "Show 2025"
        album_dir.mkdir(parents=True)

        # Build the manifest using build_album_manifest so album_tags match
        # what _album_tags_from_meta(album) produces during reconciliation.
        from tracksplit.manifest import build_album_manifest, save_album_manifest
        from tracksplit.metadata import build_album_meta
        from tracksplit.models import TrackMeta
        from tracksplit.probe import detect_tier, parse_chapters, parse_tags

        probe_tags = parse_tags(ffprobe_data)
        probe_chapters = parse_chapters(ffprobe_data)
        tier = detect_tier(probe_tags)
        album_obj = build_album_meta(probe_tags, probe_chapters, src.stem, tier)
        album_obj.tracks = [TrackMeta(number=1, title="Track 1", start=0.0, end=600.0)]
        manifest = build_album_manifest(
            source_path=src,
            ffprobe_data=ffprobe_data,
            album=album_obj,
            track_filenames=["01 - Track 1.flac"],
            artist_folder="DJ X",
            album_folder="Show 2025",
            output_format="flac",
            codec_mode="copy",
            source_id=None,
            cover_bytes=b"",
        )
        save_album_manifest(album_dir, manifest)
        assert process_file(src, tmp_path / "out") is False

    @patch("tracksplit.pipeline.tag_all")
    @patch("tracksplit.pipeline.split_tracks")
    @patch("tracksplit.pipeline.prepare_audio")
    @patch("tracksplit.pipeline.compose_cover")
    @patch("tracksplit.pipeline.compose_artist_cover")
    @patch("tracksplit.pipeline.find_dj_artwork")
    @patch("tracksplit.pipeline.extract_cover_from_mkv")
    @patch("tracksplit.pipeline.run_ffprobe")
    def test_process_file_removes_legacy_chapter_cache(
        self,
        mock_probe,
        mock_cover_mkv,
        mock_dj,
        mock_artist_cover,
        mock_compose,
        mock_prepare,
        mock_split,
        mock_tag,
        tmp_path,
    ):
        from tracksplit.manifest import LEGACY_CHAPTER_CACHE_FILENAME
        from tracksplit.pipeline import process_file

        mock_probe.return_value = self._probe()
        mock_cover_mkv.return_value = None
        mock_dj.return_value = None
        mock_compose.return_value = b"JPEG"
        mock_artist_cover.return_value = b"JPEG2"

        src = tmp_path / "src.mkv"
        src.write_bytes(b"data" * 64)
        out = tmp_path / "out"
        album_dir = out / "DJ X" / "Show 2025"
        album_dir.mkdir(parents=True)
        (album_dir / LEGACY_CHAPTER_CACHE_FILENAME).write_text("[]")
        mock_prepare.return_value = (src, ".flac", "copy")
        # probe has 2 chapters -> album has 2 tracks; split must return 2 paths
        mock_split.return_value = [
            album_dir / "01 - DJ X - Track 1.flac",
            album_dir / "02 - DJ X - Track 2.flac",
        ]

        assert process_file(src, out) is True
        assert not (album_dir / LEGACY_CHAPTER_CACHE_FILENAME).exists()

    @patch("tracksplit.pipeline.tag_all")
    @patch("tracksplit.pipeline.split_tracks")
    @patch("tracksplit.pipeline.prepare_audio")
    @patch("tracksplit.pipeline.compose_cover")
    @patch("tracksplit.pipeline.compose_artist_cover")
    @patch("tracksplit.pipeline.find_dj_artwork")
    @patch("tracksplit.pipeline.extract_cover_from_mkv")
    @patch("tracksplit.pipeline.run_ffprobe")
    def test_process_file_prunes_orphan_tracks(
        self,
        mock_probe,
        mock_cover_mkv,
        mock_dj,
        mock_artist_cover,
        mock_compose,
        mock_prepare,
        mock_split,
        mock_tag,
        tmp_path,
    ):
        from tracksplit.pipeline import process_file

        mock_probe.return_value = self._probe()
        mock_cover_mkv.return_value = None
        mock_dj.return_value = None
        mock_compose.return_value = b"JPEG"
        mock_artist_cover.return_value = b"JPEG2"

        src = tmp_path / "src.mkv"
        src.write_bytes(b"data" * 64)
        out = tmp_path / "out"
        album_dir = out / "DJ X" / "Show 2025"
        album_dir.mkdir(parents=True)

        (album_dir / "01 - old track.flac").write_bytes(b"stale")
        (album_dir / "99 - extra.opus").write_bytes(b"stale")
        (album_dir / "notes.txt").write_bytes(b"keep")

        mock_prepare.return_value = (src, ".flac", "copy")
        new_tracks = [
            album_dir / "01 - DJ X - Track 1.flac",
            album_dir / "02 - DJ X - Track 2.flac",
        ]
        mock_split.return_value = new_tracks

        assert process_file(src, out) is True
        assert not (album_dir / "01 - old track.flac").exists()
        assert not (album_dir / "99 - extra.opus").exists()
        assert (album_dir / "notes.txt").exists()

    @patch("tracksplit.pipeline.tag_all")
    @patch("tracksplit.pipeline.split_tracks")
    @patch("tracksplit.pipeline.prepare_audio")
    @patch("tracksplit.pipeline.compose_cover")
    @patch("tracksplit.pipeline.compose_artist_cover")
    @patch("tracksplit.pipeline.find_dj_artwork")
    @patch("tracksplit.pipeline.extract_cover_from_mkv")
    @patch("tracksplit.pipeline.run_ffprobe")
    @patch("tracksplit.pipeline.apply_cratedigger_canon_with")
    def test_process_file_moves_old_album_dir_on_rename(
        self,
        mock_canon,
        mock_probe,
        mock_cover_mkv,
        mock_dj,
        mock_artist_cover,
        mock_compose,
        mock_prepare,
        mock_split,
        mock_tag,
        tmp_path,
    ):
        """When the album folder changes but identity (source_id) matches,
        reconciliation moves the old directory and retags without resplitting."""
        from tracksplit.manifest import build_album_manifest, save_album_manifest
        from tracksplit.metadata import build_album_meta
        from tracksplit.models import TrackMeta
        from tracksplit.pipeline import process_file
        from tracksplit.probe import detect_tier, parse_chapters, parse_tags

        src = tmp_path / "src.mkv"
        src.write_bytes(b"x" * 100)
        out = tmp_path / "out"
        old_album = out / "DJ X" / "Old Name"
        old_album.mkdir(parents=True)
        old_track = old_album / "01 - DJ X - T1.flac"
        old_track.write_bytes(b"audio")

        # Old probe data (same audio fingerprint, same track boundary).
        old_ffprobe = {
            "streams": [
                {
                    "codec_type": "audio",
                    "codec_name": "flac",
                    "sample_rate": "44100",
                    "channels": 2,
                    "time_base": "1/44100",
                }
            ],
            "format": {
                "tags": {
                    "ARTIST": "DJ X",
                    "CRATEDIGGER_1001TL_ID": "abc-123",
                    "CRATEDIGGER_1001TL_FESTIVAL": "Old Name",
                    "CRATEDIGGER_1001TL_DATE": "2025",
                },
                "duration": "600.0",
            },
            "chapters": [
                {"start_time": "0.0", "end_time": "600.0", "tags": {"title": "T1"}},
            ],
        }
        old_tags = parse_tags(old_ffprobe)
        old_chapters = parse_chapters(old_ffprobe)
        old_tier = detect_tier(old_tags)
        old_album_obj = build_album_meta(old_tags, old_chapters, src.stem, old_tier)
        old_album_obj.tracks = [TrackMeta(number=1, title="T1", start=0.0, end=600.0)]
        save_album_manifest(
            old_album,
            build_album_manifest(
                source_path=src,
                ffprobe_data=old_ffprobe,
                album=old_album_obj,
                track_filenames=["01 - DJ X - T1.flac"],
                artist_folder="DJ X",
                album_folder="Old Name",
                output_format="flac",
                codec_mode="copy",
                source_id="abc-123",
                cover_bytes=b"",
            ),
        )

        # New probe: same audio, same boundary, different album_folder.
        new_ffprobe = {
            "streams": [
                {
                    "codec_type": "audio",
                    "codec_name": "flac",
                    "sample_rate": "44100",
                    "channels": 2,
                    "time_base": "1/44100",
                }
            ],
            "format": {
                "tags": {
                    "ARTIST": "DJ X",
                    "CRATEDIGGER_1001TL_ID": "abc-123",
                    "CRATEDIGGER_1001TL_FESTIVAL": "New Name",
                    "CRATEDIGGER_1001TL_DATE": "2025",
                },
                "duration": "600.0",
            },
            "chapters": [
                {"start_time": "0.0", "end_time": "600.0", "tags": {"title": "T1"}},
            ],
        }
        mock_probe.return_value = new_ffprobe
        mock_cover_mkv.return_value = None
        mock_dj.return_value = None
        mock_compose.return_value = b"JPEG"
        mock_artist_cover.return_value = b"JPEG2"

        result = process_file(src, out)
        assert result is True
        assert not old_album.exists(), "old album dir should be moved"
        assert (out / "DJ X" / "New Name 2025").exists()
        # split_tracks must NOT have been called (no full regen).
        mock_split.assert_not_called()
        mock_prepare.assert_not_called()

    @patch("tracksplit.pipeline.compose_artist_cover")
    @patch("tracksplit.pipeline.find_dj_artwork")
    @patch("tracksplit.pipeline.run_ffprobe")
    def test_process_file_refreshes_artist_cover_on_skip(
        self,
        mock_probe,
        mock_dj,
        mock_artist_cover,
        tmp_path,
    ):
        """When the album is unchanged but DJ artwork bytes differ, artist
        cover is rewritten during the skip path."""
        from tracksplit.manifest import (
            MANIFEST_SCHEMA,
            ArtistManifest,
            artwork_sha256,
            save_artist_manifest,
        )
        from tracksplit.pipeline import process_file

        src = tmp_path / "src.mkv"
        src.write_bytes(b"data" * 64)
        mock_probe.return_value = self._probe()
        out = tmp_path / "out"
        artist_dir = out / "DJ X"
        album_dir = artist_dir / "Show 2025"
        album_dir.mkdir(parents=True)

        # Build the stored manifest from the same probe data so the desired
        # state reconciles to SKIP (identity, boundaries, tags all match).
        from tracksplit.manifest import build_album_manifest, save_album_manifest
        from tracksplit.metadata import build_album_meta
        from tracksplit.models import TrackMeta
        from tracksplit.probe import detect_tier, parse_chapters, parse_tags

        probe_tags = parse_tags(self._probe())
        probe_chapters = parse_chapters(self._probe())
        tier = detect_tier(probe_tags)
        album_obj = build_album_meta(probe_tags, probe_chapters, src.stem, tier)
        album_obj.tracks = [
            TrackMeta(number=1, title="Track 1", start=0.0, end=300.0),
            TrackMeta(number=2, title="Track 2", start=300.0, end=600.0),
        ]
        save_album_manifest(
            album_dir,
            build_album_manifest(
                source_path=src,
                ffprobe_data=self._probe(),
                album=album_obj,
                track_filenames=["01 - Track 1.flac", "02 - Track 2.flac"],
                artist_folder="DJ X",
                album_folder="Show 2025",
                output_format="flac",
                codec_mode="copy",
                source_id=None,
                cover_bytes=b"",
            ),
        )

        artist_dir.mkdir(exist_ok=True)
        (artist_dir / "folder.jpg").write_bytes(b"OLD")
        (artist_dir / "artist.jpg").write_bytes(b"OLD")
        save_artist_manifest(
            artist_dir,
            ArtistManifest(
                schema=MANIFEST_SCHEMA,
                artist="DJ X",
                dj_artwork_sha256=artwork_sha256(b"OLD_ARTWORK"),
            ),
        )

        mock_dj.return_value = b"NEW_ARTWORK"
        mock_artist_cover.return_value = b"NEW_COVER"

        assert process_file(src, out) is False
        assert (artist_dir / "folder.jpg").read_bytes() == b"NEW_COVER"
        assert (artist_dir / "artist.jpg").read_bytes() == b"NEW_COVER"

    @patch("tracksplit.pipeline.tag_all")
    @patch("tracksplit.pipeline.split_tracks")
    @patch("tracksplit.pipeline.prepare_audio")
    @patch("tracksplit.pipeline.compose_cover")
    @patch("tracksplit.pipeline.compose_artist_cover")
    @patch("tracksplit.pipeline.find_dj_artwork")
    @patch("tracksplit.pipeline.extract_cover_from_mkv")
    @patch("tracksplit.pipeline.run_ffprobe")
    def test_rerun_after_reorder_does_not_resplit(
        self,
        mock_probe,
        mock_cover_mkv,
        mock_dj,
        mock_artist_cover,
        mock_compose,
        mock_prepare,
        mock_split,
        mock_tag,
        tmp_path,
    ):
        """A second run with a moved source path and a renamed album folder
        (identity unchanged) moves the directory and retags without
        re-encoding: split is never called and the audio bytes are preserved."""
        from tracksplit.manifest import (
            build_album_manifest,
            load_album_manifest,
            save_album_manifest,
        )
        from tracksplit.metadata import build_album_meta
        from tracksplit.models import TrackMeta
        from tracksplit.pipeline import process_file
        from tracksplit.probe import detect_tier, parse_chapters, parse_tags

        out = tmp_path / "out"
        old_album = out / "DJ X" / "Old Name 2025"
        old_album.mkdir(parents=True)
        track_bytes = b"ORIGINAL-AUDIO-BYTES"
        old_track = old_album / "01 - Track 1.flac"
        old_track.write_bytes(track_bytes)

        def _probe_for(festival):
            return {
                "streams": [
                    {
                        "codec_type": "audio",
                        "codec_name": "flac",
                        "sample_rate": "44100",
                        "channels": 2,
                        "time_base": "1/44100",
                    }
                ],
                "format": {
                    "tags": {
                        "ARTIST": "DJ X",
                        "CRATEDIGGER_1001TL_ID": "set-42",
                        "CRATEDIGGER_1001TL_FESTIVAL": festival,
                        "CRATEDIGGER_1001TL_DATE": "2025",
                    },
                    "duration": "600.0",
                },
                "chapters": [
                    {
                        "start_time": "0.0",
                        "end_time": "600.0",
                        "tags": {"title": "Track 1"},
                    },
                ],
            }

        # Seed a schema-4 manifest as if the first run wrote it.
        old_src = tmp_path / "old" / "src.mkv"
        old_src.parent.mkdir(parents=True)
        old_src.write_bytes(b"x" * 100)
        old_probe = _probe_for("Old Name")
        ptags = parse_tags(old_probe)
        pchapters = parse_chapters(old_probe)
        album_obj = build_album_meta(ptags, pchapters, old_src.stem, detect_tier(ptags))
        album_obj.tracks = [TrackMeta(number=1, title="Track 1", start=0.0, end=600.0)]
        save_album_manifest(
            old_album,
            build_album_manifest(
                source_path=old_src,
                ffprobe_data=old_probe,
                album=album_obj,
                track_filenames=["01 - Track 1.flac"],
                artist_folder="DJ X",
                album_folder="Old Name 2025",
                output_format="flac",
                codec_mode="copy",
                source_id="set-42",
                cover_bytes=b"",
            ),
        )

        # Second run: source moved to a new path, festival renamed.
        new_src = tmp_path / "new" / "src.mkv"
        new_src.parent.mkdir(parents=True)
        new_src.write_bytes(b"x" * 100)
        mock_probe.return_value = _probe_for("New Name")
        mock_cover_mkv.return_value = None
        mock_dj.return_value = None
        mock_compose.return_value = b"JPEG"
        mock_artist_cover.return_value = b"JPEG2"

        assert process_file(new_src, out) is True

        # Audio was not re-encoded: no split, no extract, bytes intact.
        mock_split.assert_not_called()
        mock_prepare.assert_not_called()

        new_album = out / "DJ X" / "New Name 2025"
        assert new_album.exists()
        assert not old_album.exists()
        moved_track = new_album / "01 - Track 1.flac"
        assert moved_track.read_bytes() == track_bytes

        m = load_album_manifest(new_album)
        assert m is not None
        assert m.schema == 4
        assert m.source_path == str(new_src)


class TestProcessFileRetag:
    @patch("tracksplit.pipeline.retag_album")
    @patch("tracksplit.pipeline.run_ffprobe")
    def test_process_file_retags_on_tag_change(
        self,
        mock_probe,
        mock_retag,
        tmp_path,
    ):
        """When only tags changed, process_file calls retag_album
        instead of the full extract+split pipeline."""
        from tests._manifest_helpers import default_tags
        from tracksplit.pipeline import process_file

        src = tmp_path / "src.mkv"
        src.write_bytes(b"data" * 64)

        ffprobe_data = {
            "streams": [{"codec_type": "audio", "codec_name": "flac"}],
            "format": {
                "tags": {
                    "ARTIST": "DJ X",
                    "CRATEDIGGER_1001TL_FESTIVAL": "New Fest",
                    "CRATEDIGGER_1001TL_DATE": "2025",
                },
                "duration": "600.0",
            },
            "chapters": [
                {
                    "start_time": "0.0",
                    "end_time": "600.0",
                    "tags": {"title": "Track 1"},
                },
            ],
        }
        mock_probe.return_value = ffprobe_data

        album_dir = tmp_path / "out" / "DJ X" / "New Fest 2025"
        album_dir.mkdir(parents=True)
        (album_dir / "01 - Track 1.flac").write_bytes(b"audio")

        # Write manifest with an old festival tag so reconciliation sees an
        # album-tag change and plans a RETAG (audio/boundaries unchanged).
        import json

        from tests._manifest_helpers import make_manifest_dict
        from tracksplit.cover import COVER_SCHEMA_VERSION
        from tracksplit.manifest import ALBUM_MANIFEST_FILENAME
        from tracksplit.tagger import TAG_SCHEMA_VERSION

        old_tags = {
            **default_tags(),
            "artist": "DJ X",
            "festival": "Old Fest",
            "date": "2025",
        }
        audio_fp = {
            "codec_name": "flac",
            "sample_rate": 0,
            "channels": 0,
            "duration_ts": 0,
            "time_base": "",
            "bit_rate": 0,
        }
        data = make_manifest_dict(
            source_path=str(src),
            audio_fp=audio_fp,
            album_tags=old_tags,
            track_filenames=["01 - Track 1.flac"],
            chapters=[
                {"index": 1, "title": "Track 1", "start": 0.0, "end": 600.0, "tags": {}}
            ],
            artist_folder="DJ X",
            album_folder="New Fest 2025",
            output_format="flac",
            codec_mode="copy",
            cover_sha256="",
            cover_schema_version=COVER_SCHEMA_VERSION,
            tag_schema_version=TAG_SCHEMA_VERSION,
        )
        (album_dir / ALBUM_MANIFEST_FILENAME).write_text(json.dumps(data))

        result = process_file(src, tmp_path / "out")
        assert result is True
        mock_retag.assert_called_once()

    @patch("tracksplit.pipeline.retag_album")
    @patch("tracksplit.pipeline.run_ffprobe")
    def test_process_file_retags_on_tag_schema_bump(
        self,
        mock_probe,
        mock_retag,
        tmp_path,
    ):
        """Skip path: source tags unchanged, but tag_schema_version is
        outdated. Should trigger retag_album."""
        from tests._manifest_helpers import default_tags
        from tracksplit.manifest import (
            ALBUM_MANIFEST_FILENAME,
        )
        from tracksplit.pipeline import process_file

        src = tmp_path / "src.mkv"
        src.write_bytes(b"data" * 64)
        ffprobe_data = {
            "streams": [{"codec_type": "audio", "codec_name": "flac"}],
            "format": {
                "tags": {
                    "ARTIST": "DJ X",
                    "CRATEDIGGER_1001TL_FESTIVAL": "Show",
                    "CRATEDIGGER_1001TL_DATE": "2025",
                },
                "duration": "600.0",
            },
            "chapters": [
                {
                    "start_time": "0.0",
                    "end_time": "600.0",
                    "tags": {"title": "Track 1"},
                },
            ],
        }
        mock_probe.return_value = ffprobe_data

        album_dir = tmp_path / "out" / "DJ X" / "Show 2025"
        album_dir.mkdir(parents=True)
        (album_dir / "01 - Track 1.flac").write_bytes(b"audio")

        from tests._manifest_helpers import make_manifest_dict
        from tracksplit.cover import COVER_SCHEMA_VERSION

        tags = {**default_tags(), "artist": "DJ X", "festival": "Show", "date": "2025"}
        audio_fp = {
            "codec_name": "flac",
            "sample_rate": 0,
            "channels": 0,
            "duration_ts": 0,
            "time_base": "",
            "bit_rate": 0,
        }
        data = make_manifest_dict(
            source_path=str(src),
            audio_fp=audio_fp,
            album_tags=tags,
            track_filenames=["01 - Track 1.flac"],
            chapters=[
                {"index": 1, "title": "Track 1", "start": 0.0, "end": 600.0, "tags": {}}
            ],
            artist_folder="DJ X",
            album_folder="Show 2025",
            output_format="flac",
            codec_mode="copy",
            cover_sha256="",
            cover_schema_version=COVER_SCHEMA_VERSION,
            tag_schema_version=0,  # stale - triggers retag
        )
        (album_dir / ALBUM_MANIFEST_FILENAME).write_text(json.dumps(data))

        result = process_file(src, tmp_path / "out")
        assert result is True
        mock_retag.assert_called_once()

    @patch("tracksplit.pipeline.tag_all")
    @patch("tracksplit.pipeline.split_tracks")
    @patch("tracksplit.pipeline.prepare_audio")
    @patch("tracksplit.pipeline.compose_cover")
    @patch("tracksplit.pipeline.compose_artist_cover")
    @patch("tracksplit.pipeline.find_dj_artwork")
    @patch("tracksplit.pipeline.extract_cover_from_mkv")
    @patch("tracksplit.pipeline.retag_album")
    @patch("tracksplit.pipeline.run_ffprobe")
    def test_process_file_falls_through_on_retag_failure(
        self,
        mock_probe,
        mock_retag,
        mock_cover_mkv,
        mock_dj,
        mock_artist_cover,
        mock_compose,
        mock_prepare,
        mock_split,
        mock_tag,
        tmp_path,
    ):
        """If retag_album raises, process_file deletes the manifest
        and falls through to the full pipeline."""
        from tests._manifest_helpers import default_tags
        from tracksplit.pipeline import process_file

        src = tmp_path / "src.mkv"
        src.write_bytes(b"data" * 64)
        ffprobe_data = {
            "streams": [{"codec_type": "audio", "codec_name": "flac"}],
            "format": {
                "tags": {
                    "ARTIST": "DJ X",
                    "CRATEDIGGER_1001TL_FESTIVAL": "New Fest",
                    "CRATEDIGGER_1001TL_DATE": "2025",
                },
                "duration": "600.0",
            },
            "chapters": [
                {
                    "start_time": "0.0",
                    "end_time": "600.0",
                    "tags": {"title": "Track 1"},
                },
            ],
        }
        mock_probe.return_value = ffprobe_data
        mock_retag.side_effect = FileNotFoundError("missing track")

        album_dir = tmp_path / "out" / "DJ X" / "New Fest 2025"
        album_dir.mkdir(parents=True)

        from tests._manifest_helpers import make_manifest_dict
        from tracksplit.cover import COVER_SCHEMA_VERSION
        from tracksplit.manifest import ALBUM_MANIFEST_FILENAME
        from tracksplit.tagger import TAG_SCHEMA_VERSION

        old_tags = {
            **default_tags(),
            "artist": "DJ X",
            "festival": "Old Fest",
            "date": "2025",
        }
        audio_fp = {
            "codec_name": "flac",
            "sample_rate": 0,
            "channels": 0,
            "duration_ts": 0,
            "time_base": "",
            "bit_rate": 0,
        }
        data = make_manifest_dict(
            source_path=str(src),
            audio_fp=audio_fp,
            album_tags=old_tags,
            track_filenames=["01 - Track 1.flac"],
            chapters=[
                {"index": 1, "title": "Track 1", "start": 0.0, "end": 600.0, "tags": {}}
            ],
            artist_folder="DJ X",
            album_folder="New Fest 2025",
            output_format="flac",
            codec_mode="copy",
            cover_sha256="",
            cover_schema_version=COVER_SCHEMA_VERSION,
            tag_schema_version=TAG_SCHEMA_VERSION,
        )
        (album_dir / ALBUM_MANIFEST_FILENAME).write_text(json.dumps(data))

        mock_cover_mkv.return_value = None
        mock_dj.return_value = None
        mock_compose.return_value = b"JPEG"
        mock_artist_cover.return_value = b"JPEG2"
        mock_prepare.return_value = (src, ".flac", "copy")
        mock_split.return_value = [
            album_dir / "01 - DJ X - Track 1.flac",
        ]

        result = process_file(src, tmp_path / "out")
        assert result is True
        mock_split.assert_called_once()


class TestPruneOrphans:
    def _album(self, tmp_path):
        d = tmp_path / "album"
        d.mkdir()
        return d

    def test_prunes_unexpected_flac(self, tmp_path):
        from tracksplit.pipeline import prune_orphan_tracks

        album = self._album(tmp_path)
        (album / "01 - old.flac").write_bytes(b"x")
        (album / "02 - keep.flac").write_bytes(b"x")
        (album / "cover.jpg").write_bytes(b"c")
        (album / ".tracksplit_manifest.json").write_text("{}")

        removed = prune_orphan_tracks(album, expected={"02 - keep.flac"})

        assert "01 - old.flac" in removed
        assert not (album / "01 - old.flac").exists()
        assert (album / "02 - keep.flac").exists()
        assert (album / "cover.jpg").exists()
        assert (album / ".tracksplit_manifest.json").exists()

    def test_prunes_across_extensions(self, tmp_path):
        from tracksplit.pipeline import prune_orphan_tracks

        album = self._album(tmp_path)
        (album / "01 - old.flac").write_bytes(b"x")
        (album / "01 - old.opus").write_bytes(b"x")
        (album / "01 - new.opus").write_bytes(b"x")

        prune_orphan_tracks(album, expected={"01 - new.opus"})

        assert not (album / "01 - old.flac").exists()
        assert not (album / "01 - old.opus").exists()
        assert (album / "01 - new.opus").exists()

    def test_leaves_non_audio_files_alone(self, tmp_path):
        from tracksplit.pipeline import prune_orphan_tracks

        album = self._album(tmp_path)
        (album / "notes.txt").write_bytes(b"x")
        (album / "folder.jpg").write_bytes(b"x")

        removed = prune_orphan_tracks(album, expected=set())

        assert removed == []
        assert (album / "notes.txt").exists()
        assert (album / "folder.jpg").exists()

    def test_ignores_subdirectories(self, tmp_path):
        from tracksplit.pipeline import prune_orphan_tracks

        album = self._album(tmp_path)
        sub = album / "sub"
        sub.mkdir()
        (sub / "01 - nested.flac").write_bytes(b"x")

        prune_orphan_tracks(album, expected=set())

        assert (sub / "01 - nested.flac").exists()

    def test_empty_expected_set_preserves_everything(self, tmp_path):
        from tracksplit.pipeline import prune_orphan_tracks

        album = self._album(tmp_path)
        (album / "01 - keep.flac").write_bytes(b"x")
        (album / "02 - keep.opus").write_bytes(b"x")

        removed = prune_orphan_tracks(album, expected=set())

        assert removed == []
        assert (album / "01 - keep.flac").exists()
        assert (album / "02 - keep.opus").exists()


class TestRefreshArtistCover:
    def test_writes_when_missing(self, tmp_path):
        from tracksplit.pipeline import refresh_artist_cover

        artist = tmp_path / "A"
        artist.mkdir()
        calls = []

        def _compose(**kw):
            calls.append(kw)
            return b"COVER"

        refresh_artist_cover(
            artist,
            artist_name="A",
            dj_artwork_data=b"jpg1",
            compose=_compose,
        )
        assert (artist / "folder.jpg").read_bytes() == b"COVER"
        assert (artist / "artist.jpg").read_bytes() == b"COVER"
        assert calls and calls[0]["artist"] == "A"

    def test_skips_when_artwork_hash_unchanged(self, tmp_path):
        from tracksplit.cover import COVER_SCHEMA_VERSION
        from tracksplit.manifest import (
            MANIFEST_SCHEMA,
            ArtistManifest,
            artwork_sha256,
            save_artist_manifest,
        )
        from tracksplit.pipeline import refresh_artist_cover

        artist = tmp_path / "A"
        artist.mkdir()
        (artist / "folder.jpg").write_bytes(b"OLD")
        (artist / "artist.jpg").write_bytes(b"OLD")
        save_artist_manifest(
            artist,
            ArtistManifest(
                schema=MANIFEST_SCHEMA,
                artist="A",
                dj_artwork_sha256=artwork_sha256(b"jpg1"),
                cover_schema_version=COVER_SCHEMA_VERSION,
            ),
        )
        calls = []

        def _compose(**kw):
            calls.append(kw)
            return b"NEW"

        refresh_artist_cover(
            artist,
            artist_name="A",
            dj_artwork_data=b"jpg1",
            compose=_compose,
        )
        assert calls == []
        assert (artist / "folder.jpg").read_bytes() == b"OLD"
        assert (artist / "artist.jpg").read_bytes() == b"OLD"

    def test_rewrites_when_cover_schema_outdated(self, tmp_path):
        """A stale cover_schema_version rebuilds the card even if the artwork
        hash is unchanged, so cover-rendering changes reach existing libraries."""
        from tracksplit.cover import COVER_SCHEMA_VERSION
        from tracksplit.manifest import (
            MANIFEST_SCHEMA,
            ArtistManifest,
            artwork_sha256,
            load_artist_manifest,
            save_artist_manifest,
        )
        from tracksplit.pipeline import refresh_artist_cover

        assert COVER_SCHEMA_VERSION > 0
        artist = tmp_path / "A"
        artist.mkdir()
        (artist / "folder.jpg").write_bytes(b"OLD")
        (artist / "artist.jpg").write_bytes(b"OLD")
        save_artist_manifest(
            artist,
            ArtistManifest(
                schema=MANIFEST_SCHEMA,
                artist="A",
                dj_artwork_sha256=artwork_sha256(b"jpg1"),
                cover_schema_version=0,
            ),
        )
        refresh_artist_cover(
            artist,
            artist_name="A",
            dj_artwork_data=b"jpg1",
            compose=lambda **kw: b"NEW",
        )
        assert (artist / "folder.jpg").read_bytes() == b"NEW"
        m = load_artist_manifest(artist)
        assert m.cover_schema_version == COVER_SCHEMA_VERSION

    def test_rewrites_when_artwork_hash_changes(self, tmp_path):
        from tracksplit.manifest import (
            MANIFEST_SCHEMA,
            ArtistManifest,
            artwork_sha256,
            load_artist_manifest,
            save_artist_manifest,
        )
        from tracksplit.pipeline import refresh_artist_cover

        artist = tmp_path / "A"
        artist.mkdir()
        (artist / "folder.jpg").write_bytes(b"OLD")
        save_artist_manifest(
            artist,
            ArtistManifest(
                schema=MANIFEST_SCHEMA,
                artist="A",
                dj_artwork_sha256=artwork_sha256(b"old"),
            ),
        )
        refresh_artist_cover(
            artist,
            artist_name="A",
            dj_artwork_data=b"new",
            compose=lambda **kw: b"NEW",
        )
        assert (artist / "folder.jpg").read_bytes() == b"NEW"
        m = load_artist_manifest(artist)
        assert m.dj_artwork_sha256 == artwork_sha256(b"new")

    def test_rewrites_when_jpg_missing_even_if_hash_matches(self, tmp_path):
        from tracksplit.manifest import (
            MANIFEST_SCHEMA,
            ArtistManifest,
            artwork_sha256,
            save_artist_manifest,
        )
        from tracksplit.pipeline import refresh_artist_cover

        artist = tmp_path / "A"
        artist.mkdir()
        save_artist_manifest(
            artist,
            ArtistManifest(
                schema=MANIFEST_SCHEMA,
                artist="A",
                dj_artwork_sha256=artwork_sha256(b"jpg1"),
            ),
        )
        refresh_artist_cover(
            artist,
            artist_name="A",
            dj_artwork_data=b"jpg1",
            compose=lambda **kw: b"REGEN",
        )
        assert (artist / "folder.jpg").read_bytes() == b"REGEN"
        assert (artist / "artist.jpg").read_bytes() == b"REGEN"

    def test_no_dj_artwork_still_writes_on_first_run(self, tmp_path):
        from tracksplit.pipeline import refresh_artist_cover

        artist = tmp_path / "A"
        artist.mkdir()
        refresh_artist_cover(
            artist,
            artist_name="A",
            dj_artwork_data=None,
            compose=lambda **kw: b"PLAIN",
        )
        assert (artist / "folder.jpg").read_bytes() == b"PLAIN"

    def test_writes_sidecar_hash_for_no_artwork(self, tmp_path):
        """dj_artwork_data=None results in an empty-hash sidecar entry."""
        from tracksplit.manifest import load_artist_manifest
        from tracksplit.pipeline import refresh_artist_cover

        artist = tmp_path / "A"
        artist.mkdir()
        refresh_artist_cover(
            artist,
            artist_name="A",
            dj_artwork_data=None,
            compose=lambda **kw: b"PLAIN",
        )
        m = load_artist_manifest(artist)
        assert m is not None
        assert m.dj_artwork_sha256 == ""

    def test_enospc_propagates(self, tmp_path, monkeypatch):
        """Disk-full errors must not be swallowed."""
        import errno

        from tracksplit import manifest as mf
        from tracksplit.pipeline import refresh_artist_cover

        artist = tmp_path / "A"
        artist.mkdir()

        def _boom(path, data):
            raise OSError(errno.ENOSPC, "no space")

        monkeypatch.setattr(mf, "atomic_write_bytes", _boom)
        from tracksplit import pipeline as pl

        monkeypatch.setattr(pl, "atomic_write_bytes", _boom)
        import pytest

        with pytest.raises(OSError):
            refresh_artist_cover(
                artist,
                artist_name="A",
                dj_artwork_data=b"x",
                compose=lambda **kw: b"IGNORED",
            )


class TestResolveOpusCopyPacketMs:
    def test_20ms_source_keeps_copy_mode(self, mocker):
        from tracksplit import pipeline

        mocker.patch.object(
            pipeline,
            "get_opus_packet_duration_ms",
            return_value=20,
        )
        codec_mode, packet_ms = pipeline._resolve_opus_copy_packet_ms(
            audio_path=Path("/tmp/src.mkv"),
            ext=".opus",
            codec_mode="copy",
        )
        assert codec_mode == "copy"
        assert packet_ms == 20

    def test_60ms_source_escalates_to_libopus(self, mocker, caplog):
        from tracksplit import pipeline

        mocker.patch.object(
            pipeline,
            "get_opus_packet_duration_ms",
            return_value=60,
        )
        with caplog.at_level("WARNING", logger="tracksplit.pipeline"):
            codec_mode, packet_ms = pipeline._resolve_opus_copy_packet_ms(
                audio_path=Path("/tmp/src.mkv"),
                ext=".opus",
                codec_mode="copy",
            )
        assert codec_mode == "libopus"
        assert packet_ms is None
        assert any("pipeline.opus_fallback" in r.message for r in caplog.records)

    def test_probe_returns_none_escalates(self, mocker):
        from tracksplit import pipeline

        mocker.patch.object(
            pipeline,
            "get_opus_packet_duration_ms",
            return_value=None,
        )
        codec_mode, packet_ms = pipeline._resolve_opus_copy_packet_ms(
            audio_path=Path("/tmp/src.mkv"),
            ext=".opus",
            codec_mode="copy",
        )
        assert codec_mode == "libopus"
        assert packet_ms is None

    def test_flac_passthrough_skips_probe(self, mocker):
        from tracksplit import pipeline

        mock_probe = mocker.patch.object(
            pipeline,
            "get_opus_packet_duration_ms",
        )
        codec_mode, packet_ms = pipeline._resolve_opus_copy_packet_ms(
            audio_path=Path("/tmp/src.flac"),
            ext=".flac",
            codec_mode="copy",
        )
        assert codec_mode == "copy"
        assert packet_ms is None
        mock_probe.assert_not_called()

    def test_libopus_mode_passthrough_skips_probe(self, mocker):
        from tracksplit import pipeline

        mock_probe = mocker.patch.object(
            pipeline,
            "get_opus_packet_duration_ms",
        )
        codec_mode, packet_ms = pipeline._resolve_opus_copy_packet_ms(
            audio_path=Path("/tmp/src.mkv"),
            ext=".opus",
            codec_mode="libopus",
        )
        assert codec_mode == "libopus"
        assert packet_ms is None
        mock_probe.assert_not_called()


class TestRebuildCoverOnly:
    @staticmethod
    def _silent_flac(path: Path) -> None:
        import shutil
        import subprocess

        if shutil.which("ffmpeg") is None:
            pytest.skip("ffmpeg required")
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=44100",
                "-t",
                "0.2",
                "-c:a",
                "flac",
                str(path),
            ],
            check=True,
            capture_output=True,
        )

    def _make_manifest(
        self,
        *,
        album_dir: Path,
        track_filename: str,
        cover_sha: str,
        schema_version: int = 0,
    ):
        from tracksplit.manifest import (
            MANIFEST_SCHEMA,
            AlbumManifest,
            AudioFingerprint,
            SourceIdentity,
            TrackEntry,
            save_album_manifest,
        )

        manifest = AlbumManifest(
            schema=MANIFEST_SCHEMA,
            identity=SourceIdentity(
                source_id=None,
                audio=AudioFingerprint(
                    codec_name="flac",
                    sample_rate=44100,
                    channels=2,
                    time_base="1/44100",
                ),
            ),
            source_path="/fake.mkv",
            resolved_artist_folder="Artist",
            resolved_album_folder="Album",
            output_format="flac",
            codec_mode="copy",
            album_tags={"artist": "A", "festival": "F"},
            tracks=[
                TrackEntry(
                    index=1,
                    filename=track_filename,
                    start=0.0,
                    end=60.0,
                    title="Song",
                )
            ],
            cover_sha256=cover_sha,
            cover_schema_version=schema_version,
        )
        save_album_manifest(album_dir, manifest)
        return manifest

    def test_rewrites_cover_and_embeds_in_tracks(self, tmp_path):
        import hashlib

        from mutagen.flac import FLAC

        from tracksplit.cover import COVER_SCHEMA_VERSION
        from tracksplit.manifest import load_album_manifest
        from tracksplit.pipeline import rebuild_cover_only

        album_dir = tmp_path / "Artist" / "Album"
        album_dir.mkdir(parents=True)
        track = album_dir / "01 - Song.flac"
        self._silent_flac(track)

        old_cover = b"old-jpg-bytes"
        (album_dir / "cover.jpg").write_bytes(old_cover)
        manifest = self._make_manifest(
            album_dir=album_dir,
            track_filename=track.name,
            cover_sha=hashlib.sha256(old_cover).hexdigest(),
            schema_version=0,
        )

        new_cover = b"\xff\xd8\xff\xe0new-cover-bytes"
        compose_calls = []

        def _compose(**kw):
            compose_calls.append(kw)
            return new_cover

        rebuild_cover_only(
            album_dir=album_dir,
            manifest=manifest,
            source_path=Path("/fake.mkv"),
            ffprobe_data={},
            extract=lambda src, *, ffprobe_data: b"bg",
            compose=_compose,
        )

        assert (album_dir / "cover.jpg").read_bytes() == new_cover
        reread = FLAC(str(track))
        assert len(reread.pictures) == 1
        assert reread.pictures[0].data == new_cover

        updated = load_album_manifest(album_dir)
        assert updated.cover_schema_version == COVER_SCHEMA_VERSION
        assert updated.cover_sha256 == hashlib.sha256(new_cover).hexdigest()

        assert compose_calls and compose_calls[0]["artist"] == "A"
        assert compose_calls[0]["festival"] == "F"

    def test_updates_folder_jpg_when_present(self, tmp_path):
        import hashlib

        from tracksplit.pipeline import rebuild_cover_only

        album_dir = tmp_path / "Artist" / "Album"
        album_dir.mkdir(parents=True)
        track = album_dir / "01.flac"
        self._silent_flac(track)
        (album_dir / "cover.jpg").write_bytes(b"old")
        (album_dir / "folder.jpg").write_bytes(b"old")
        manifest = self._make_manifest(
            album_dir=album_dir,
            track_filename=track.name,
            cover_sha=hashlib.sha256(b"old").hexdigest(),
        )

        new_cover = b"\xff\xd8new"
        rebuild_cover_only(
            album_dir=album_dir,
            manifest=manifest,
            source_path=Path("/fake.mkv"),
            ffprobe_data={},
            extract=lambda src, *, ffprobe_data: None,
            compose=lambda **kw: new_cover,
        )
        assert (album_dir / "folder.jpg").read_bytes() == new_cover

    def test_short_circuits_when_hash_unchanged(self, tmp_path):
        """If compose produces the same bytes as the stored cover_sha256,
        only bump the schema version; do not rewrite files."""
        import hashlib

        from tracksplit.cover import COVER_SCHEMA_VERSION
        from tracksplit.manifest import load_album_manifest
        from tracksplit.pipeline import rebuild_cover_only

        album_dir = tmp_path / "Artist" / "Album"
        album_dir.mkdir(parents=True)
        track = album_dir / "01.flac"
        self._silent_flac(track)

        existing_cover = b"same-cover-bytes"
        (album_dir / "cover.jpg").write_bytes(existing_cover)
        existing_track_mtime = track.stat().st_mtime_ns
        existing_cover_mtime = (album_dir / "cover.jpg").stat().st_mtime_ns
        manifest = self._make_manifest(
            album_dir=album_dir,
            track_filename=track.name,
            cover_sha=hashlib.sha256(existing_cover).hexdigest(),
            schema_version=0,
        )

        rebuild_cover_only(
            album_dir=album_dir,
            manifest=manifest,
            source_path=Path("/fake.mkv"),
            ffprobe_data={},
            extract=lambda src, *, ffprobe_data: None,
            compose=lambda **kw: existing_cover,
        )

        assert (album_dir / "cover.jpg").stat().st_mtime_ns == existing_cover_mtime
        assert track.stat().st_mtime_ns == existing_track_mtime
        updated = load_album_manifest(album_dir)
        assert updated.cover_schema_version == COVER_SCHEMA_VERSION
        assert updated.cover_sha256 == hashlib.sha256(existing_cover).hexdigest()


class TestSkipBranchCoverRebuild:
    """process_file's reconciliation should retag (recomposing the cover)
    when the stored cover_schema_version is older than the current
    COVER_SCHEMA_VERSION, and fall through to a full regen when that
    retag raises. A current cover schema with no other change is a clean
    SKIP (no retag, no split).
    """

    def _probe(self):
        return {
            "streams": [{"codec_type": "audio", "codec_name": "flac"}],
            "format": {
                "tags": {
                    "ARTIST": "DJ X",
                    "CRATEDIGGER_1001TL_FESTIVAL": "Show",
                    "CRATEDIGGER_1001TL_DATE": "2025",
                },
                "duration": "600.0",
            },
            "chapters": [
                {
                    "start_time": "0.0",
                    "end_time": "600.0",
                    "tags": {"title": "Track 1"},
                },
            ],
        }

    def _stored_album(self, src):
        from tracksplit.metadata import build_album_meta
        from tracksplit.models import TrackMeta
        from tracksplit.probe import detect_tier, parse_chapters, parse_tags

        probe_tags = parse_tags(self._probe())
        probe_chapters = parse_chapters(self._probe())
        tier = detect_tier(probe_tags)
        album = build_album_meta(probe_tags, probe_chapters, src.stem, tier)
        album.tracks = [TrackMeta(number=1, title="Track 1", start=0.0, end=600.0)]
        return album

    def _write_manifest(self, src, album_dir, *, cover_schema_version):
        from dataclasses import replace as _replace

        from tracksplit.manifest import build_album_manifest, save_album_manifest

        manifest = build_album_manifest(
            source_path=src,
            ffprobe_data=self._probe(),
            album=self._stored_album(src),
            track_filenames=["01 - Track 1.flac"],
            artist_folder="DJ X",
            album_folder="Show 2025",
            output_format="flac",
            codec_mode="copy",
            source_id=None,
            cover_bytes=b"",
        )
        manifest = _replace(manifest, cover_schema_version=cover_schema_version)
        save_album_manifest(album_dir, manifest)

    @patch("tracksplit.pipeline.prepare_audio")
    @patch("tracksplit.pipeline.refresh_artist_cover")
    @patch("tracksplit.pipeline.retag_album")
    @patch("tracksplit.pipeline.run_ffprobe")
    def test_retags_on_cover_version_mismatch(
        self,
        mock_probe,
        mock_retag,
        mock_refresh_artist,
        mock_prepare,
        tmp_path,
    ):
        """A stale cover_schema_version reconciles to RETAG (which recomposes
        the cover), not a full resplit."""
        from tracksplit.pipeline import process_file

        mock_probe.return_value = self._probe()
        src = tmp_path / "src.mkv"
        src.write_bytes(b"data" * 64)
        out = tmp_path / "out"
        album_dir = out / "DJ X" / "Show 2025"
        album_dir.mkdir(parents=True)
        (album_dir / "01 - Track 1.flac").write_bytes(b"audio")
        self._write_manifest(src, album_dir, cover_schema_version=0)

        assert process_file(src, out) is True
        assert mock_retag.call_count == 1
        kwargs = mock_retag.call_args.kwargs
        assert kwargs["album_dir"] == album_dir
        assert kwargs["source_path"] == src
        assert mock_refresh_artist.call_count == 1, (
            "retag path should still refresh artist cover"
        )
        assert mock_prepare.call_count == 0, "audio prep must NOT run on a retag"

    @patch("tracksplit.pipeline.tag_all")
    @patch("tracksplit.pipeline.split_tracks")
    @patch("tracksplit.pipeline.prepare_audio")
    @patch("tracksplit.pipeline.compose_cover")
    @patch("tracksplit.pipeline.compose_artist_cover")
    @patch("tracksplit.pipeline.find_dj_artwork")
    @patch("tracksplit.pipeline.extract_cover_from_mkv")
    @patch("tracksplit.pipeline.retag_album")
    @patch("tracksplit.pipeline.run_ffprobe")
    def test_falls_through_to_full_regen_when_retag_fails(
        self,
        mock_probe,
        mock_retag,
        mock_cover_mkv,
        mock_dj,
        mock_artist_cover,
        mock_compose,
        mock_prepare,
        mock_split,
        mock_tag,
        tmp_path,
    ):
        from tracksplit.cover import COVER_SCHEMA_VERSION
        from tracksplit.manifest import load_album_manifest
        from tracksplit.pipeline import process_file

        mock_probe.return_value = self._probe()
        mock_retag.side_effect = RuntimeError("simulated retag failure")
        mock_cover_mkv.return_value = None
        mock_dj.return_value = None
        mock_compose.return_value = b"NEW-JPEG"
        mock_artist_cover.return_value = b"NEW-JPEG2"

        src = tmp_path / "src.mkv"
        src.write_bytes(b"data" * 64)
        out = tmp_path / "out"
        album_dir = out / "DJ X" / "Show 2025"
        album_dir.mkdir(parents=True)
        (album_dir / "01 - Track 1.flac").write_bytes(b"audio")
        self._write_manifest(src, album_dir, cover_schema_version=0)

        mock_prepare.return_value = (src, ".flac", "copy")
        mock_split.return_value = [
            album_dir / "01 - DJ X - Track 1.flac",
        ]

        assert process_file(src, out) is True
        assert mock_retag.call_count == 1
        assert mock_prepare.called, "full regen prepare_audio was not reached"

        fresh = load_album_manifest(album_dir)
        assert fresh is not None, f"manifest missing after full regen at {album_dir}"
        assert fresh.cover_schema_version == COVER_SCHEMA_VERSION

    @patch("tracksplit.pipeline.retag_album")
    @patch("tracksplit.pipeline.run_ffprobe")
    def test_clean_skip_when_version_current(
        self,
        mock_probe,
        mock_retag,
        tmp_path,
    ):
        from tracksplit.cover import COVER_SCHEMA_VERSION
        from tracksplit.pipeline import process_file

        mock_probe.return_value = self._probe()
        src = tmp_path / "src.mkv"
        src.write_bytes(b"data" * 64)
        out = tmp_path / "out"
        album_dir = out / "DJ X" / "Show 2025"
        album_dir.mkdir(parents=True)
        (album_dir / "01 - Track 1.flac").write_bytes(b"audio")
        self._write_manifest(src, album_dir, cover_schema_version=COVER_SCHEMA_VERSION)

        assert process_file(src, out) is False
        assert mock_retag.call_count == 0


class TestRebuildCoverPassesAlbumartists:
    def test_genuine_list_is_passed_to_compose(self, tmp_path):
        import hashlib
        import json
        from unittest.mock import MagicMock

        from tests._manifest_helpers import default_tags, make_manifest_dict
        from tracksplit.manifest import ALBUM_MANIFEST_FILENAME, load_album_manifest
        from tracksplit.pipeline import rebuild_cover_only

        fake = b"FAKECOVERBYTES"
        sha = hashlib.sha256(fake).hexdigest()
        tags = default_tags()
        tags["artist"] = "Above & Beyond"
        tags["albumartists"] = ["Above & Beyond"]
        md = make_manifest_dict(tags=tags, cover_sha256=sha)
        (tmp_path / ALBUM_MANIFEST_FILENAME).write_text(json.dumps(md))
        manifest = load_album_manifest(tmp_path)

        compose = MagicMock(
            return_value=fake
        )  # sha matches -> short-circuits, no track files needed
        extract = MagicMock(return_value=None)

        rebuild_cover_only(
            album_dir=tmp_path,
            manifest=manifest,
            source_path=tmp_path / "x.mkv",
            ffprobe_data={},
            extract=extract,
            compose=compose,
        )

        assert compose.call_args.kwargs["albumartists"] == ["Above & Beyond"]


# ---------------------------------------------------------------------------
# rename_track_files / move_album_dir / sweep_temp_renames
# ---------------------------------------------------------------------------


class TestRenameTrackFiles:
    def test_rename_track_files_case_only(self, tmp_path):
        from tracksplit.pipeline import rename_track_files

        d = tmp_path / "album"
        d.mkdir()
        (d / "02 - A - Culture.opus").write_bytes(b"x")
        rename_track_files(d, [("02 - A - Culture.opus", "02 - a - culture.opus")])
        names = {p.name for p in d.iterdir()}
        assert "02 - a - culture.opus" in names
        assert (d / "02 - a - culture.opus").read_bytes() == b"x"

    def test_rename_track_files_regular(self, tmp_path):
        from tracksplit.pipeline import rename_track_files

        d = tmp_path / "album"
        d.mkdir()
        (d / "01 - Old.opus").write_bytes(b"y")
        rename_track_files(d, [("01 - Old.opus", "01 - New.opus")])
        assert (d / "01 - New.opus").read_bytes() == b"y"
        assert not (d / "01 - Old.opus").exists()

    def test_rename_track_files_skips_missing(self, tmp_path):
        from tracksplit.pipeline import rename_track_files

        d = tmp_path / "album"
        d.mkdir()
        # Should not raise even though source does not exist
        rename_track_files(d, [("nonexistent.opus", "other.opus")])

    def test_rename_track_files_skip_when_already_correct(self, tmp_path):
        from tracksplit.pipeline import rename_track_files

        d = tmp_path / "album"
        d.mkdir()
        (d / "track.opus").write_bytes(b"z")
        rename_track_files(d, [("track.opus", "track.opus")])
        assert (d / "track.opus").read_bytes() == b"z"

    def test_rename_track_files_collision_warns_keeps_both(self, tmp_path):
        from tracksplit.pipeline import rename_track_files

        d = tmp_path / "album"
        d.mkdir()
        (d / "old.opus").write_bytes(b"src")
        (d / "new.opus").write_bytes(b"different")
        rename_track_files(d, [("old.opus", "new.opus")])
        # Both must still exist; source not overwritten
        assert (d / "old.opus").read_bytes() == b"src"
        assert (d / "new.opus").read_bytes() == b"different"


class TestMoveAlbumDir:
    def test_move_album_dir_renames_and_prunes_empty_artist(self, tmp_path):
        from tracksplit.pipeline import move_album_dir

        old = tmp_path / "ArtistA" / "OldName"
        old.mkdir(parents=True)
        (old / "t.opus").write_bytes(b"x")
        new = tmp_path / "ArtistA" / "NewName"
        final = move_album_dir(old, new)
        assert final == new
        assert (new / "t.opus").read_bytes() == b"x"
        assert not old.exists()

    def test_move_album_dir_prunes_empty_old_artist(self, tmp_path):
        from tracksplit.pipeline import move_album_dir

        old = tmp_path / "ArtistOld" / "Album"
        old.mkdir(parents=True)
        (old / "t.opus").write_bytes(b"a")
        new = tmp_path / "ArtistNew" / "Album"
        final = move_album_dir(old, new)
        assert final == new
        assert not (tmp_path / "ArtistOld").exists()

    def test_move_album_dir_keeps_nonempty_old_artist(self, tmp_path):
        from tracksplit.pipeline import move_album_dir

        artist_dir = tmp_path / "ArtistX"
        old = artist_dir / "AlbumA"
        old.mkdir(parents=True)
        sibling = artist_dir / "AlbumB"
        sibling.mkdir()
        (old / "t.opus").write_bytes(b"a")
        new = tmp_path / "ArtistY" / "AlbumA"
        move_album_dir(old, new)
        # Sibling still present; artist dir should not have been pruned
        assert sibling.exists()

    def test_move_album_dir_conflict_warns_and_returns_old(self, tmp_path):
        from tracksplit.pipeline import move_album_dir

        old = tmp_path / "Artist" / "Album"
        old.mkdir(parents=True)
        new = tmp_path / "Artist" / "AlbumNew"
        new.mkdir(parents=True)
        final = move_album_dir(old, new)
        assert final == old
        assert old.exists()
        assert new.exists()

    def test_move_album_dir_same_dir_noop(self, tmp_path):
        from tracksplit.pipeline import move_album_dir

        d = tmp_path / "Artist" / "Album"
        d.mkdir(parents=True)
        final = move_album_dir(d, d)
        assert final == d
        assert d.exists()


class TestSweepTempRenames:
    def test_sweep_removes_temp_files(self, tmp_path):
        from tracksplit.pipeline import TEMP_RENAME_SUFFIX, sweep_temp_renames

        d = tmp_path / "album"
        d.mkdir()
        temp = d / ("track.opus" + TEMP_RENAME_SUFFIX)
        temp.write_bytes(b"stray")
        (d / "real.opus").write_bytes(b"keep")
        sweep_temp_renames(d)
        assert not temp.exists()
        assert (d / "real.opus").exists()

    def test_sweep_noop_when_no_temps(self, tmp_path):
        from tracksplit.pipeline import sweep_temp_renames

        d = tmp_path / "album"
        d.mkdir()
        (d / "track.opus").write_bytes(b"a")
        sweep_temp_renames(d)
        assert (d / "track.opus").exists()


# ---------------------------------------------------------------------------
# Identity index: once-per-run and passed-in index behavior
# ---------------------------------------------------------------------------


class TestIdentityIndexRunBehavior:
    """Verify that process_file respects the index parameter.

    The batch entry point (_process_directory in cli.py) builds the index
    once and passes it in, so individual process_file calls should not
    rebuild it.  These tests confirm:
    - process_file with index=None builds the index lazily (1 call).
    - process_file with index=<value> does NOT call build_identity_index.
    """

    def _probe(self):
        return {
            "streams": [{"codec_type": "audio", "codec_name": "flac"}],
            "format": {
                "tags": {
                    "ARTIST": "DJ X",
                    "CRATEDIGGER_1001TL_FESTIVAL": "Show",
                    "CRATEDIGGER_1001TL_DATE": "2025",
                },
                "duration": "600.0",
            },
            "chapters": [
                {
                    "start_time": "0.0",
                    "end_time": "300.0",
                    "tags": {"title": "Track 1"},
                },
                {
                    "start_time": "300.0",
                    "end_time": "600.0",
                    "tags": {"title": "Track 2"},
                },
            ],
        }

    @patch("tracksplit.pipeline.tag_all")
    @patch("tracksplit.pipeline.split_tracks")
    @patch("tracksplit.pipeline.prepare_audio")
    @patch("tracksplit.pipeline.compose_cover")
    @patch("tracksplit.pipeline.compose_artist_cover")
    @patch("tracksplit.pipeline.find_dj_artwork")
    @patch("tracksplit.pipeline.extract_cover_from_mkv")
    @patch("tracksplit.pipeline.run_ffprobe")
    def test_process_file_without_index_calls_build_identity_index(
        self,
        mock_probe,
        mock_cover_mkv,
        mock_dj,
        mock_artist_cover,
        mock_compose,
        mock_prepare,
        mock_split,
        mock_tag,
        tmp_path,
        monkeypatch,
    ):
        """When index is not provided, process_file should build one lazily."""
        import tracksplit.pipeline as P
        from tracksplit.pipeline import process_file

        call_count = {"n": 0}
        real_build = P.build_identity_index

        def spy(*a, **k):
            call_count["n"] += 1
            return real_build(*a, **k)

        monkeypatch.setattr(P, "build_identity_index", spy)

        out = tmp_path / "out"
        album_dir = out / "DJ X" / "Show 2025"
        src = tmp_path / "src.mkv"
        src.write_bytes(b"data" * 64)

        mock_probe.return_value = self._probe()
        mock_cover_mkv.return_value = None
        mock_dj.return_value = None
        mock_compose.return_value = b"JPEG"
        mock_artist_cover.return_value = b"JPEG2"
        mock_prepare.return_value = (src, ".flac", "copy")
        mock_split.return_value = [
            album_dir / "01 - DJ X - Track 1.flac",
            album_dir / "02 - DJ X - Track 2.flac",
        ]

        process_file(src, out)

        assert call_count["n"] == 1, "Expected build_identity_index called once"

    @patch("tracksplit.pipeline.tag_all")
    @patch("tracksplit.pipeline.split_tracks")
    @patch("tracksplit.pipeline.prepare_audio")
    @patch("tracksplit.pipeline.compose_cover")
    @patch("tracksplit.pipeline.compose_artist_cover")
    @patch("tracksplit.pipeline.find_dj_artwork")
    @patch("tracksplit.pipeline.extract_cover_from_mkv")
    @patch("tracksplit.pipeline.run_ffprobe")
    def test_process_file_with_index_skips_build_identity_index(
        self,
        mock_probe,
        mock_cover_mkv,
        mock_dj,
        mock_artist_cover,
        mock_compose,
        mock_prepare,
        mock_split,
        mock_tag,
        tmp_path,
        monkeypatch,
    ):
        """When a pre-built index is passed in, build_identity_index is not called."""
        import tracksplit.pipeline as P
        from tracksplit.pipeline import process_file
        from tracksplit.reconcile import IdentityIndex

        call_count = {"n": 0}

        def spy(*a, **k):
            call_count["n"] += 1
            return IdentityIndex({}, {})

        monkeypatch.setattr(P, "build_identity_index", spy)

        out = tmp_path / "out"
        album_dir = out / "DJ X" / "Show 2025"
        src = tmp_path / "src.mkv"
        src.write_bytes(b"data" * 64)

        mock_probe.return_value = self._probe()
        mock_cover_mkv.return_value = None
        mock_dj.return_value = None
        mock_compose.return_value = b"JPEG"
        mock_artist_cover.return_value = b"JPEG2"
        mock_prepare.return_value = (src, ".flac", "copy")
        mock_split.return_value = [
            album_dir / "01 - DJ X - Track 1.flac",
            album_dir / "02 - DJ X - Track 2.flac",
        ]

        # Pass a pre-built (empty) index: build_identity_index must not be called.
        pre_built_index = IdentityIndex({}, {})
        process_file(src, out, index=pre_built_index)

        assert call_count["n"] == 0, (
            "build_identity_index should not be called when index is provided"
        )

    @patch("tracksplit.pipeline.tag_all")
    @patch("tracksplit.pipeline.split_tracks")
    @patch("tracksplit.pipeline.prepare_audio")
    @patch("tracksplit.pipeline.compose_cover")
    @patch("tracksplit.pipeline.compose_artist_cover")
    @patch("tracksplit.pipeline.find_dj_artwork")
    @patch("tracksplit.pipeline.extract_cover_from_mkv")
    @patch("tracksplit.pipeline.run_ffprobe")
    def test_identity_index_built_once_per_run(
        self,
        mock_probe,
        mock_cover_mkv,
        mock_dj,
        mock_artist_cover,
        mock_compose,
        mock_prepare,
        mock_split,
        mock_tag,
        tmp_path,
        monkeypatch,
    ):
        """A two-source batch via _process_directory builds the index once."""
        import tracksplit.pipeline as P
        from tracksplit.cli import _process_directory  # type: ignore[attr-defined]

        call_count = {"n": 0}
        real_build = P.build_identity_index

        def spy(*a, **k):
            call_count["n"] += 1
            return real_build(*a, **k)

        # Patch on the pipeline module so _process_directory's _pipeline reference
        # picks up the spy (it accesses build_identity_index via the module object).
        monkeypatch.setattr(P, "build_identity_index", spy)

        out = tmp_path / "out"
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        # Two fake video files (content irrelevant; probe is mocked).
        src1 = input_dir / "file1.mkv"
        src2 = input_dir / "file2.mkv"
        src1.write_bytes(b"x")
        src2.write_bytes(b"x")

        album_dir1 = out / "DJ X" / "Show 2025"
        album_dir2 = out / "DJ X" / "Show 2026"

        mock_probe.return_value = self._probe()
        mock_cover_mkv.return_value = None
        mock_dj.return_value = None
        mock_compose.return_value = b"JPEG"
        mock_artist_cover.return_value = b"JPEG2"
        mock_prepare.return_value = (src1, ".flac", "copy")
        mock_split.side_effect = [
            [album_dir1 / "01 - DJ X - Track 1.flac", album_dir1 / "02 - DJ X - Track 2.flac"],
            [album_dir2 / "01 - DJ X - Track 1.flac", album_dir2 / "02 - DJ X - Track 2.flac"],
        ]

        _process_directory(
            input_dir=input_dir,
            output_dir=out,
            force=False,
            dry_run=False,
            output_format="auto",
            workers=1,
        )

        assert call_count["n"] == 1, (
            f"Expected build_identity_index called once for a 2-file batch, got {call_count['n']}"
        )
