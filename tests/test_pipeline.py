"""Tests for the pipeline module."""
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from tracksplit.models import AlbumMeta, Chapter, TrackMeta
from tracksplit.pipeline import (
    _apply_intro_track,
    build_intro_track,
    should_regenerate,
    _safe_log_name,
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
# should_regenerate
# ---------------------------------------------------------------------------

class TestShouldRegenerate:
    def _write_manifest(self, album_dir, **overrides):
        from tracksplit.manifest import (
            ALBUM_MANIFEST_FILENAME, MANIFEST_SCHEMA,
        )
        data = {
            "schema": MANIFEST_SCHEMA,
            "source": {"path": overrides.get("source_path", "/x.mkv"),
                       "mtime_ns": overrides.get("mtime_ns", 1),
                       "size": overrides.get("size", 10),
                       "enriched_at": overrides.get("enriched_at", "")},
            "resolved_artist_folder": overrides.get("artist_folder", "A"),
            "resolved_album_folder": overrides.get("album_folder", "B"),
            "output_format": overrides.get("output_format", "flac"),
            "codec_mode": overrides.get("codec_mode", "copy"),
            "chapters": overrides.get("chapters",
                [{"index": 1, "title": "T", "start": 0.0, "end": 60.0}]),
            "tags": overrides.get("tags",
                {"artist": "A", "album": "", "festival": "", "date": "",
                 "stage": "", "venue": "", "mbid": "",
                 "enriched_at": ""}),
            "track_filenames": overrides.get("track_filenames", ["01 - T.flac"]),
            "cover_sha256": overrides.get("cover_sha256", "a" * 64),
        }
        if "intro_min_seconds" in overrides:
            data["intro_min_seconds"] = overrides["intro_min_seconds"]
        (album_dir / ALBUM_MANIFEST_FILENAME).write_text(json.dumps(data))

    def _mk_source(self, tmp_path, size=10):
        p = tmp_path / "src.mkv"
        p.write_bytes(b"x" * size)
        return p

    def _fingerprint(self, src):
        return {"source_path": str(src), "mtime_ns": src.stat().st_mtime_ns,
                "size": src.stat().st_size}

    def test_no_existing_dir(self, tmp_path):
        from tracksplit.pipeline import should_regenerate
        src = self._mk_source(tmp_path)
        assert should_regenerate(
            tmp_path / "nope", src, {}, [], "A", "B", "flac", "copy",
            force=False,
        ) is True

    def test_force_always_true(self, tmp_path):
        from tracksplit.pipeline import should_regenerate
        src = self._mk_source(tmp_path)
        album = tmp_path / "album"
        album.mkdir()
        self._write_manifest(album, **self._fingerprint(src))
        assert should_regenerate(
            album, src, {}, [], "A", "B", "flac", "copy", force=True,
        ) is True

    def test_unchanged_everything(self, tmp_path):
        from tracksplit.pipeline import should_regenerate
        src = self._mk_source(tmp_path)
        album = tmp_path / "album"
        album.mkdir()
        fp = self._fingerprint(src)
        self._write_manifest(album, **fp)
        tags = {"artist": "A", "album": "", "festival": "", "date": "",
                "stage": "", "venue": "", "mbid": "",
                "enriched_at": ""}
        assert should_regenerate(
            album, src, tags,
            [{"index": 1, "title": "T", "start": 0.0, "end": 60.0}],
            "A", "B", "flac", "copy", force=False,
        ) is False

    def test_chapter_change_regenerates(self, tmp_path):
        from tracksplit.pipeline import should_regenerate
        src = self._mk_source(tmp_path)
        album = tmp_path / "album"
        album.mkdir()
        self._write_manifest(album, **self._fingerprint(src))
        new_chapters = [{"index": 1, "title": "T2", "start": 0.0, "end": 90.0}]
        assert should_regenerate(
            album, src, {}, new_chapters, "A", "B", "flac", "copy",
            force=False,
        ) is True

    def test_metadata_only_change_regenerates(self, tmp_path):
        from tracksplit.pipeline import should_regenerate
        src = self._mk_source(tmp_path)
        album = tmp_path / "album"
        album.mkdir()
        fp = self._fingerprint(src)
        self._write_manifest(album, **fp)
        tags = {"artist": "A", "album": "", "festival": "NEW-FESTIVAL",
                "date": "", "stage": "", "venue": "", "mbid": "",
                "enriched_at": ""}
        assert should_regenerate(
            album, src, tags,
            [{"index": 1, "title": "T", "start": 0.0, "end": 60.0}],
            "A", "B", "flac", "copy", force=False,
        ) is True

    def test_source_mtime_change_regenerates(self, tmp_path):
        from tracksplit.pipeline import should_regenerate
        src = self._mk_source(tmp_path)
        album = tmp_path / "album"
        album.mkdir()
        self._write_manifest(
            album, source_path=str(src), mtime_ns=1, size=src.stat().st_size,
        )
        assert should_regenerate(
            album, src, {}, [], "A", "B", "flac", "copy", force=False,
        ) is True

    def test_format_change_regenerates(self, tmp_path):
        from tracksplit.pipeline import should_regenerate
        src = self._mk_source(tmp_path)
        album = tmp_path / "album"
        album.mkdir()
        self._write_manifest(
            album, **self._fingerprint(src), output_format="flac",
        )
        assert should_regenerate(
            album, src, {}, [], "A", "B", "opus", "libopus", force=False,
        ) is True

    def test_missing_manifest_triggers_regenerate_even_with_legacy_cache(self, tmp_path):
        from tracksplit.pipeline import should_regenerate
        src = self._mk_source(tmp_path)
        album = tmp_path / "album"
        album.mkdir()
        (album / ".tracksplit_chapters.json").write_text(json.dumps([
            {"index": 1, "title": "T", "start": 0.0, "end": 60.0}
        ]))
        assert should_regenerate(
            album, src, {}, [], "A", "B", "flac", "copy", force=False,
        ) is True

    def test_corrupt_manifest_regenerates(self, tmp_path):
        from tracksplit.pipeline import should_regenerate
        from tracksplit.manifest import ALBUM_MANIFEST_FILENAME
        src = self._mk_source(tmp_path)
        album = tmp_path / "album"
        album.mkdir()
        (album / ALBUM_MANIFEST_FILENAME).write_text("{not json")
        assert should_regenerate(
            album, src, {}, [], "A", "B", "flac", "copy", force=False,
        ) is True

    def test_should_regenerate_skips_when_intro_policy_matches(self, tmp_path):
        """Current manifest with matching intro_min_seconds returns False."""
        from tracksplit.pipeline import should_regenerate, INTRO_MIN_SECONDS
        src = self._mk_source(tmp_path)
        album = tmp_path / "album"
        album.mkdir()
        fp = self._fingerprint(src)
        self._write_manifest(
            album, intro_min_seconds=INTRO_MIN_SECONDS, **fp,
        )
        tags = {"artist": "A", "album": "", "festival": "", "date": "",
                "stage": "", "venue": "", "mbid": "",
                "enriched_at": ""}
        assert should_regenerate(
            album, src, tags,
            [{"index": 1, "title": "T", "start": 0.0, "end": 60.0}],
            "A", "B", "flac", "copy", force=False,
        ) is False

    def test_should_regenerate_skips_legacy_manifest_with_zero_gap(self, tmp_path):
        """Old manifest (intro_min_seconds=None) with first chapter at 0 returns False."""
        from tracksplit.pipeline import should_regenerate
        src = self._mk_source(tmp_path)
        album = tmp_path / "album"
        album.mkdir()
        fp = self._fingerprint(src)
        # No intro_min_seconds key: simulates a pre-policy manifest on disk.
        self._write_manifest(album, **fp)
        tags = {"artist": "A", "album": "", "festival": "", "date": "",
                "stage": "", "venue": "", "mbid": "",
                "enriched_at": ""}
        assert should_regenerate(
            album, src, tags,
            [{"index": 1, "title": "T", "start": 0.0, "end": 60.0}],
            "A", "B", "flac", "copy", force=False,
        ) is False

    def test_should_regenerate_rebuilds_legacy_manifest_with_short_gap(self, tmp_path):
        """Old manifest, first chapter gap 2.0s (under threshold) returns True."""
        from tracksplit.pipeline import should_regenerate
        src = self._mk_source(tmp_path)
        album = tmp_path / "album"
        album.mkdir()
        fp = self._fingerprint(src)
        chapters = [{"index": 1, "title": "T", "start": 2.0, "end": 60.0}]
        # Stored chapters match observed chapters, so the plain chapter check
        # does not fire; only the legacy intro-policy upgrade can trigger.
        self._write_manifest(album, chapters=chapters, **fp)
        tags = {"artist": "A", "album": "", "festival": "", "date": "",
                "stage": "", "venue": "", "mbid": "",
                "enriched_at": ""}
        assert should_regenerate(
            album, src, tags, chapters,
            "A", "B", "flac", "copy", force=False,
        ) is True

    def test_should_regenerate_skips_legacy_manifest_with_long_intro(self, tmp_path):
        """Old manifest, first chapter gap 15.0s (above threshold) returns False."""
        from tracksplit.pipeline import should_regenerate
        src = self._mk_source(tmp_path)
        album = tmp_path / "album"
        album.mkdir()
        fp = self._fingerprint(src)
        chapters = [{"index": 1, "title": "T", "start": 15.0, "end": 60.0}]
        self._write_manifest(album, chapters=chapters, **fp)
        tags = {"artist": "A", "album": "", "festival": "", "date": "",
                "stage": "", "venue": "", "mbid": "",
                "enriched_at": ""}
        assert should_regenerate(
            album, src, tags, chapters,
            "A", "B", "flac", "copy", force=False,
        ) is False

    def test_should_regenerate_rebuilds_when_stored_threshold_differs(self, tmp_path):
        """Manifest records a different intro_min_seconds than the current constant."""
        from tracksplit.pipeline import should_regenerate, INTRO_MIN_SECONDS
        src = self._mk_source(tmp_path)
        album = tmp_path / "album"
        album.mkdir()
        fp = self._fingerprint(src)
        chapters = [{"index": 1, "title": "T", "start": 0.0, "end": 60.0}]
        # Stored threshold (3.0) disagrees with the current INTRO_MIN_SECONDS,
        # so only the stored-threshold-mismatch branch can trigger.
        assert INTRO_MIN_SECONDS != 3.0
        self._write_manifest(
            album, chapters=chapters, intro_min_seconds=3.0, **fp,
        )
        tags = {"artist": "A", "album": "", "festival": "", "date": "",
                "stage": "", "venue": "", "mbid": "",
                "enriched_at": ""}
        assert should_regenerate(
            album, src, tags, chapters,
            "A", "B", "flac", "copy", force=False,
        ) is True


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
            "format": {"tags": {"ARTIST": "DJ X",
                                 "CRATEDIGGER_1001TL_FESTIVAL": "Show",
                                 "CRATEDIGGER_1001TL_DATE": "2025"},
                       "duration": "600.0"},
            "chapters": [
                {"start_time": "0.0", "end_time": "300.0",
                 "tags": {"title": "Track 1"}},
                {"start_time": "300.0", "end_time": "600.0",
                 "tags": {"title": "Track 2"}},
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
        self, mock_probe, mock_cover_mkv, mock_dj, mock_artist_cover,
        mock_compose, mock_prepare, mock_split, mock_tag, tmp_path,
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
        assert m.source.size == src.stat().st_size
        assert m.output_format == "flac"
        assert m.codec_mode == "copy"
        assert len(m.chapters) == 2
        assert m.cover_sha256  # non-empty
        assert m.track_filenames == [
            "01 - DJ X - Track 1.flac", "02 - DJ X - Track 2.flac",
        ]

    @patch("tracksplit.pipeline.run_ffprobe")
    def test_process_file_skips_when_manifest_matches(
        self, mock_probe, tmp_path,
    ):
        from tracksplit.manifest import (
            build_album_manifest, save_album_manifest,
        )
        from tracksplit.pipeline import process_file

        src = tmp_path / "src.mkv"
        src.write_bytes(b"data" * 64)
        mock_probe.return_value = {
            "streams": [{"codec_type": "audio", "codec_name": "flac"}],
            "format": {"tags": {"ARTIST": "DJ X",
                                 "CRATEDIGGER_1001TL_FESTIVAL": "Show",
                                 "CRATEDIGGER_1001TL_DATE": "2025"},
                       "duration": "600.0"},
            "chapters": [
                {"start_time": "0.0", "end_time": "600.0",
                 "tags": {"title": "Track 1"}},
            ],
        }
        album_dir = tmp_path / "out" / "DJ X" / "Show 2025"
        album_dir.mkdir(parents=True)
        from tracksplit.manifest import TAG_KEYS
        tags = {k: "" for k in TAG_KEYS}
        tags["artist"] = "DJ X"
        tags["festival"] = "Show"
        tags["date"] = "2025"
        manifest = build_album_manifest(
            source_path=src,
            chapters=[{"index": 1, "title": "Track 1", "start": 0.0, "end": 600.0}],
            tags=tags,
            artist_folder="DJ X",
            album_folder="Show 2025",
            output_format="flac", codec_mode="copy",
            track_filenames=["01 - DJ X - Track 1.flac"],
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
        self, mock_probe, mock_cover_mkv, mock_dj, mock_artist_cover,
        mock_compose, mock_prepare, mock_split, mock_tag, tmp_path,
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
        mock_split.return_value = [album_dir / "01 - t.flac"]

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
        self, mock_probe, mock_cover_mkv, mock_dj, mock_artist_cover,
        mock_compose, mock_prepare, mock_split, mock_tag, tmp_path,
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
    def test_process_file_deletes_old_album_dir_on_rename(
        self, mock_canon, mock_probe, mock_cover_mkv, mock_dj,
        mock_artist_cover, mock_compose, mock_prepare, mock_split, mock_tag,
        tmp_path,
    ):
        from tracksplit.manifest import (
            ALBUM_MANIFEST_FILENAME, MANIFEST_SCHEMA,
        )
        from tracksplit.pipeline import process_file

        src = tmp_path / "src.mkv"
        src.write_bytes(b"x" * 100)
        out = tmp_path / "out"
        old_album = out / "DJ X" / "Old Name"
        old_album.mkdir(parents=True)
        (old_album / "01 - stale.flac").write_bytes(b"stale")
        (old_album / ALBUM_MANIFEST_FILENAME).write_text(json.dumps({
            "schema": MANIFEST_SCHEMA,
            "source": {
                "path": str(src),
                "mtime_ns": src.stat().st_mtime_ns,
                "size": src.stat().st_size,
                "enriched_at": "",
            },
            "resolved_artist_folder": "DJ X",
            "resolved_album_folder": "Old Name",
            "output_format": "flac",
            "codec_mode": "copy",
            "chapters": [],
            "tags": {},
            "track_filenames": ["01 - stale.flac"],
            "cover_sha256": "",
        }))

        # Probe yields CrateDigger tags that resolve album_folder to "New Name 2025".
        mock_probe.return_value = {
            "streams": [{"codec_type": "audio", "codec_name": "flac"}],
            "format": {"tags": {
                "ARTIST": "DJ X",
                "TITLE": "New Name",
                "CRATEDIGGER_1001TL_FESTIVAL": "New Name",
                "CRATEDIGGER_1001TL_DATE": "2025",
            }, "duration": "600.0"},
            "chapters": [
                {"start_time": "0.0", "end_time": "600.0",
                 "tags": {"title": "T1"}},
            ],
        }
        mock_cover_mkv.return_value = None
        mock_dj.return_value = None
        mock_compose.return_value = b"JPEG"
        mock_artist_cover.return_value = b"JPEG2"
        mock_prepare.return_value = (src, ".flac", "copy")
        mock_split.return_value = [
            out / "DJ X" / "New Name 2025" / "01 - DJ X - T1.flac",
        ]

        assert process_file(src, out) is True
        assert not old_album.exists(), "old album dir should be deleted"
        assert (out / "DJ X" / "New Name 2025").exists()

    @patch("tracksplit.pipeline.compose_artist_cover")
    @patch("tracksplit.pipeline.find_dj_artwork")
    @patch("tracksplit.pipeline.run_ffprobe")
    def test_process_file_refreshes_artist_cover_on_skip(
        self, mock_probe, mock_dj, mock_artist_cover, tmp_path,
    ):
        """When the album is unchanged but DJ artwork bytes differ, artist
        cover is rewritten during the skip path."""
        from tracksplit.manifest import (
            ArtistManifest, MANIFEST_SCHEMA, artwork_sha256,
            build_album_manifest, save_album_manifest, save_artist_manifest,
        )
        from tracksplit.pipeline import process_file

        src = tmp_path / "src.mkv"
        src.write_bytes(b"data" * 64)
        mock_probe.return_value = self._probe()
        out = tmp_path / "out"
        artist_dir = out / "DJ X"
        album_dir = artist_dir / "Show 2025"
        album_dir.mkdir(parents=True)
        from tracksplit.manifest import TAG_KEYS
        tags = {k: "" for k in TAG_KEYS}
        tags["artist"] = "DJ X"
        tags["festival"] = "Show"
        tags["date"] = "2025"
        chapter_dicts = [
            {"index": 1, "title": "Track 1", "start": 0.0, "end": 300.0},
            {"index": 2, "title": "Track 2", "start": 300.0, "end": 600.0},
        ]
        save_album_manifest(album_dir, build_album_manifest(
            source_path=src, chapters=chapter_dicts, tags=tags,
            artist_folder="DJ X", album_folder="Show 2025",
            output_format="flac", codec_mode="copy",
            track_filenames=["01 - DJ X - Track 1.flac",
                             "02 - DJ X - Track 2.flac"],
            cover_bytes=b"",
        ))
        artist_dir.mkdir(exist_ok=True)
        (artist_dir / "folder.jpg").write_bytes(b"OLD")
        (artist_dir / "artist.jpg").write_bytes(b"OLD")
        save_artist_manifest(artist_dir, ArtistManifest(
            schema=MANIFEST_SCHEMA, artist="DJ X",
            dj_artwork_sha256=artwork_sha256(b"OLD_ARTWORK"),
        ))

        mock_dj.return_value = b"NEW_ARTWORK"
        mock_artist_cover.return_value = b"NEW_COVER"

        assert process_file(src, out) is False
        assert (artist_dir / "folder.jpg").read_bytes() == b"NEW_COVER"
        assert (artist_dir / "artist.jpg").read_bytes() == b"NEW_COVER"


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


class TestFindPriorAlbumDirs:
    def _write_manifest(self, album_dir, source_path, size, mtime_ns,
                         artist_folder=None, album_folder=None):
        from tracksplit.manifest import (
            ALBUM_MANIFEST_FILENAME, MANIFEST_SCHEMA,
        )
        album_dir.mkdir(parents=True, exist_ok=True)
        (album_dir / ALBUM_MANIFEST_FILENAME).write_text(json.dumps({
            "schema": MANIFEST_SCHEMA,
            "source": {
                "path": str(source_path),
                "mtime_ns": mtime_ns,
                "size": size,
                "enriched_at": "",
            },
            "resolved_artist_folder": artist_folder or album_dir.parent.name,
            "resolved_album_folder": album_folder or album_dir.name,
            "output_format": "flac",
            "codec_mode": "copy",
            "chapters": [],
            "tags": {},
            "track_filenames": [],
            "cover_sha256": "",
        }))

    def test_finds_prior_album_dir_same_source(self, tmp_path):
        from tracksplit.pipeline import find_prior_album_dirs
        src = tmp_path / "src.mkv"
        src.write_bytes(b"x" * 10)
        out = tmp_path / "out"
        self._write_manifest(out / "ArtistA" / "Old Name", src,
                             src.stat().st_size, src.stat().st_mtime_ns)
        self._write_manifest(out / "ArtistA" / "Other Album",
                             tmp_path / "other.mkv", 99, 99)

        found = find_prior_album_dirs(
            out, src, new_album_dir=out / "ArtistA" / "New Name",
        )
        assert found == [out / "ArtistA" / "Old Name"]

    def test_skips_when_path_unchanged(self, tmp_path):
        from tracksplit.pipeline import find_prior_album_dirs
        src = tmp_path / "src.mkv"
        src.write_bytes(b"x" * 10)
        out = tmp_path / "out"
        album = out / "ArtistA" / "Same Name"
        self._write_manifest(album, src, src.stat().st_size,
                             src.stat().st_mtime_ns)

        assert find_prior_album_dirs(out, src, new_album_dir=album) == []

    def test_handles_artist_rename_too(self, tmp_path):
        from tracksplit.pipeline import find_prior_album_dirs
        src = tmp_path / "src.mkv"
        src.write_bytes(b"x" * 10)
        out = tmp_path / "out"
        old = out / "OldArtist" / "Album"
        self._write_manifest(old, src, src.stat().st_size,
                             src.stat().st_mtime_ns)

        found = find_prior_album_dirs(
            out, src, new_album_dir=out / "NewArtist" / "Album",
        )
        assert found == [old]

    def test_missing_output_root_returns_empty(self, tmp_path):
        from tracksplit.pipeline import find_prior_album_dirs
        src = tmp_path / "src.mkv"
        src.write_bytes(b"x")
        assert find_prior_album_dirs(
            tmp_path / "nope", src, new_album_dir=tmp_path / "whatever",
        ) == []

    def test_ignores_manifest_with_different_size(self, tmp_path):
        from tracksplit.pipeline import find_prior_album_dirs
        src = tmp_path / "src.mkv"
        src.write_bytes(b"x" * 10)
        out = tmp_path / "out"
        other = out / "Artist" / "Album"
        # Same path, different size, should not match.
        self._write_manifest(other, src, size=999,
                             mtime_ns=src.stat().st_mtime_ns)

        assert find_prior_album_dirs(
            out, src, new_album_dir=out / "Artist" / "Other",
        ) == []

    def test_does_not_match_different_path_same_size(self, tmp_path):
        from tracksplit.pipeline import find_prior_album_dirs
        srcA = tmp_path / "a.mkv"
        srcA.write_bytes(b"x" * 10)
        srcB = tmp_path / "b.mkv"
        srcB.write_bytes(b"y" * 10)  # same size as srcA, different content/path
        out = tmp_path / "out"
        self._write_manifest(
            out / "ArtistA" / "AlbA", srcA,
            srcA.stat().st_size, srcA.stat().st_mtime_ns,
        )
        self._write_manifest(
            out / "ArtistB" / "AlbB", srcB,
            srcB.stat().st_size, srcB.stat().st_mtime_ns,
        )

        found = find_prior_album_dirs(
            out, srcA, new_album_dir=out / "Something" / "Else",
        )
        assert found == [out / "ArtistA" / "AlbA"]

    def test_skips_symlinked_album_dir(self, tmp_path):
        from tracksplit.pipeline import find_prior_album_dirs
        src = tmp_path / "src.mkv"
        src.write_bytes(b"x" * 10)
        # Real album dir outside the output tree.
        real = tmp_path / "outside" / "Artist" / "Album"
        self._write_manifest(
            real, src, src.stat().st_size, src.stat().st_mtime_ns,
        )
        # Symlink under the output root pointing at the real dir.
        out = tmp_path / "out"
        (out / "Artist").mkdir(parents=True)
        link = out / "Artist" / "Album"
        try:
            link.symlink_to(real, target_is_directory=True)
        except (OSError, NotImplementedError):
            import pytest
            pytest.skip("symlink creation not supported on this filesystem")

        found = find_prior_album_dirs(
            out, src, new_album_dir=out / "Artist" / "New Album",
        )
        assert found == []


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
            artist, artist_name="A", dj_artwork_data=b"jpg1",
            compose=_compose,
        )
        assert (artist / "folder.jpg").read_bytes() == b"COVER"
        assert (artist / "artist.jpg").read_bytes() == b"COVER"
        assert calls and calls[0]["artist"] == "A"

    def test_skips_when_artwork_hash_unchanged(self, tmp_path):
        from tracksplit.manifest import (
            ArtistManifest, MANIFEST_SCHEMA, artwork_sha256, save_artist_manifest,
        )
        from tracksplit.pipeline import refresh_artist_cover
        artist = tmp_path / "A"
        artist.mkdir()
        (artist / "folder.jpg").write_bytes(b"OLD")
        (artist / "artist.jpg").write_bytes(b"OLD")
        save_artist_manifest(
            artist,
            ArtistManifest(
                schema=MANIFEST_SCHEMA, artist="A",
                dj_artwork_sha256=artwork_sha256(b"jpg1"),
            ),
        )
        calls = []
        def _compose(**kw):
            calls.append(kw)
            return b"NEW"
        refresh_artist_cover(
            artist, artist_name="A", dj_artwork_data=b"jpg1",
            compose=_compose,
        )
        assert calls == []
        assert (artist / "folder.jpg").read_bytes() == b"OLD"
        assert (artist / "artist.jpg").read_bytes() == b"OLD"

    def test_rewrites_when_artwork_hash_changes(self, tmp_path):
        from tracksplit.manifest import (
            ArtistManifest, MANIFEST_SCHEMA, artwork_sha256,
            load_artist_manifest, save_artist_manifest,
        )
        from tracksplit.pipeline import refresh_artist_cover
        artist = tmp_path / "A"
        artist.mkdir()
        (artist / "folder.jpg").write_bytes(b"OLD")
        save_artist_manifest(
            artist,
            ArtistManifest(
                schema=MANIFEST_SCHEMA, artist="A",
                dj_artwork_sha256=artwork_sha256(b"old"),
            ),
        )
        refresh_artist_cover(
            artist, artist_name="A", dj_artwork_data=b"new",
            compose=lambda **kw: b"NEW",
        )
        assert (artist / "folder.jpg").read_bytes() == b"NEW"
        m = load_artist_manifest(artist)
        assert m.dj_artwork_sha256 == artwork_sha256(b"new")

    def test_rewrites_when_jpg_missing_even_if_hash_matches(self, tmp_path):
        from tracksplit.manifest import (
            ArtistManifest, MANIFEST_SCHEMA, artwork_sha256, save_artist_manifest,
        )
        from tracksplit.pipeline import refresh_artist_cover
        artist = tmp_path / "A"
        artist.mkdir()
        save_artist_manifest(
            artist,
            ArtistManifest(
                schema=MANIFEST_SCHEMA, artist="A",
                dj_artwork_sha256=artwork_sha256(b"jpg1"),
            ),
        )
        refresh_artist_cover(
            artist, artist_name="A", dj_artwork_data=b"jpg1",
            compose=lambda **kw: b"REGEN",
        )
        assert (artist / "folder.jpg").read_bytes() == b"REGEN"
        assert (artist / "artist.jpg").read_bytes() == b"REGEN"

    def test_no_dj_artwork_still_writes_on_first_run(self, tmp_path):
        from tracksplit.pipeline import refresh_artist_cover
        artist = tmp_path / "A"
        artist.mkdir()
        refresh_artist_cover(
            artist, artist_name="A", dj_artwork_data=None,
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
            artist, artist_name="A", dj_artwork_data=None,
            compose=lambda **kw: b"PLAIN",
        )
        m = load_artist_manifest(artist)
        assert m is not None
        assert m.dj_artwork_sha256 == ""

    def test_enospc_propagates(self, tmp_path, monkeypatch):
        """Disk-full errors must not be swallowed."""
        import errno
        from tracksplit.pipeline import refresh_artist_cover
        from tracksplit import manifest as mf
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
                artist, artist_name="A", dj_artwork_data=b"x",
                compose=lambda **kw: b"IGNORED",
            )


class TestResolveOpusCopyPacketMs:
    def test_20ms_source_keeps_copy_mode(self, mocker):
        from tracksplit import pipeline

        mocker.patch.object(
            pipeline, "get_opus_packet_duration_ms", return_value=20,
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
            pipeline, "get_opus_packet_duration_ms", return_value=60,
        )
        with caplog.at_level("WARNING", logger="tracksplit.pipeline"):
            codec_mode, packet_ms = pipeline._resolve_opus_copy_packet_ms(
                audio_path=Path("/tmp/src.mkv"),
                ext=".opus",
                codec_mode="copy",
            )
        assert codec_mode == "libopus"
        assert packet_ms is None
        assert any("frame duration" in r.message for r in caplog.records)

    def test_probe_returns_none_escalates(self, mocker):
        from tracksplit import pipeline

        mocker.patch.object(
            pipeline, "get_opus_packet_duration_ms", return_value=None,
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
            pipeline, "get_opus_packet_duration_ms",
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
            pipeline, "get_opus_packet_duration_ms",
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
            ["ffmpeg", "-y", "-f", "lavfi",
             "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
             "-t", "0.2", "-c:a", "flac", str(path)],
            check=True, capture_output=True,
        )

    def _make_manifest(
        self, *, album_dir: Path, track_filename: str,
        cover_sha: str, schema_version: int = 0,
    ):
        from tracksplit.manifest import (
            AlbumManifest, SourceFingerprint, save_album_manifest,
        )
        manifest = AlbumManifest(
            schema=2,
            source=SourceFingerprint(
                path="/fake.mkv", mtime_ns=1, size=1, enriched_at="",
            ),
            resolved_artist_folder="Artist",
            resolved_album_folder="Album",
            output_format="flac",
            codec_mode="copy",
            chapters=[],
            tags={"artist": "A", "album": "B", "festival": "F"},
            track_filenames=[track_filename],
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
            album_dir=album_dir, track_filename=track.name,
            cover_sha=hashlib.sha256(b"old").hexdigest(),
        )

        new_cover = b"\xff\xd8new"
        rebuild_cover_only(
            album_dir=album_dir, manifest=manifest,
            source_path=Path("/fake.mkv"), ffprobe_data={},
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
            album_dir=album_dir, track_filename=track.name,
            cover_sha=hashlib.sha256(existing_cover).hexdigest(),
            schema_version=0,
        )

        rebuild_cover_only(
            album_dir=album_dir, manifest=manifest,
            source_path=Path("/fake.mkv"), ffprobe_data={},
            extract=lambda src, *, ffprobe_data: None,
            compose=lambda **kw: existing_cover,
        )

        assert (album_dir / "cover.jpg").stat().st_mtime_ns == existing_cover_mtime
        assert track.stat().st_mtime_ns == existing_track_mtime
        updated = load_album_manifest(album_dir)
        assert updated.cover_schema_version == COVER_SCHEMA_VERSION
        assert updated.cover_sha256 == hashlib.sha256(existing_cover).hexdigest()


class TestSkipBranchCoverRebuild:
    """process_file's skip branch should trigger a cover-only rebuild
    when the stored cover_schema_version is older than the current
    COVER_SCHEMA_VERSION, and fall through to a full regen when that
    rebuild raises.
    """

    def _probe(self):
        return {
            "streams": [{"codec_type": "audio", "codec_name": "flac"}],
            "format": {"tags": {"ARTIST": "DJ X",
                                 "CRATEDIGGER_1001TL_FESTIVAL": "Show",
                                 "CRATEDIGGER_1001TL_DATE": "2025"},
                       "duration": "600.0"},
            "chapters": [
                {"start_time": "0.0", "end_time": "600.0",
                 "tags": {"title": "Track 1"}},
            ],
        }

    def _write_manifest_with_stale_cover_version(self, src, album_dir):
        from tracksplit.manifest import (
            TAG_KEYS, build_album_manifest, save_album_manifest,
        )
        from dataclasses import replace as _replace
        tags = {k: "" for k in TAG_KEYS}
        tags["artist"] = "DJ X"
        tags["festival"] = "Show"
        tags["date"] = "2025"
        m = build_album_manifest(
            source_path=src,
            chapters=[{"index": 1, "title": "Track 1", "start": 0.0, "end": 600.0}],
            tags=tags,
            artist_folder="DJ X",
            album_folder="Show 2025",
            output_format="flac", codec_mode="copy",
            track_filenames=["01 - DJ X - Track 1.flac"],
            cover_bytes=b"",
        )
        m = _replace(m, cover_schema_version=0)
        save_album_manifest(album_dir, m)

    @patch("tracksplit.pipeline.prepare_audio")
    @patch("tracksplit.pipeline.refresh_artist_cover")
    @patch("tracksplit.pipeline.rebuild_cover_only")
    @patch("tracksplit.pipeline.run_ffprobe")
    def test_triggers_rebuild_on_version_mismatch(
        self, mock_probe, mock_rebuild, mock_refresh_artist,
        mock_prepare, tmp_path,
    ):
        from tracksplit.pipeline import process_file
        mock_probe.return_value = self._probe()
        src = tmp_path / "src.mkv"
        src.write_bytes(b"data" * 64)
        album_dir = tmp_path / "out" / "DJ X" / "Show 2025"
        album_dir.mkdir(parents=True)
        self._write_manifest_with_stale_cover_version(src, album_dir)

        assert process_file(src, tmp_path / "out") is False
        assert mock_rebuild.call_count == 1
        kwargs = mock_rebuild.call_args.kwargs
        assert kwargs["album_dir"] == album_dir
        assert kwargs["source_path"] == src
        assert mock_refresh_artist.call_count == 1, (
            "skip path after cover rebuild should still refresh artist cover"
        )
        assert mock_prepare.call_count == 0, (
            "audio prep must NOT run on a clean skip"
        )

    @patch("tracksplit.pipeline.tag_all")
    @patch("tracksplit.pipeline.split_tracks")
    @patch("tracksplit.pipeline.prepare_audio")
    @patch("tracksplit.pipeline.compose_cover")
    @patch("tracksplit.pipeline.compose_artist_cover")
    @patch("tracksplit.pipeline.find_dj_artwork")
    @patch("tracksplit.pipeline.extract_cover_from_mkv")
    @patch("tracksplit.pipeline.rebuild_cover_only")
    @patch("tracksplit.pipeline.run_ffprobe")
    def test_falls_through_to_full_regen_when_rebuild_fails(
        self, mock_probe, mock_rebuild, mock_cover_mkv, mock_dj,
        mock_artist_cover, mock_compose, mock_prepare, mock_split,
        mock_tag, tmp_path,
    ):
        from tracksplit.cover import COVER_SCHEMA_VERSION
        from tracksplit.manifest import (
            ALBUM_MANIFEST_FILENAME, load_album_manifest,
        )
        from tracksplit.pipeline import process_file

        mock_probe.return_value = self._probe()
        mock_rebuild.side_effect = RuntimeError("simulated rebuild failure")
        mock_cover_mkv.return_value = None
        mock_dj.return_value = None
        mock_compose.return_value = b"NEW-JPEG"
        mock_artist_cover.return_value = b"NEW-JPEG2"

        src = tmp_path / "src.mkv"
        src.write_bytes(b"data" * 64)
        out = tmp_path / "out"
        album_dir = out / "DJ X" / "Show 2025"
        album_dir.mkdir(parents=True)
        self._write_manifest_with_stale_cover_version(src, album_dir)

        mock_prepare.return_value = (src, ".flac", "copy")
        mock_split.return_value = [
            album_dir / "01 - DJ X - Track 1.flac",
        ]

        assert process_file(src, out) is True
        assert mock_rebuild.call_count == 1
        assert mock_prepare.called, "full regen prepare_audio was not reached"

        fresh = load_album_manifest(album_dir)
        assert fresh is not None, f"manifest missing after full regen at {album_dir}"
        assert fresh.cover_schema_version == COVER_SCHEMA_VERSION

    @patch("tracksplit.pipeline.rebuild_cover_only")
    @patch("tracksplit.pipeline.run_ffprobe")
    def test_clean_skip_when_version_current(
        self, mock_probe, mock_rebuild, tmp_path,
    ):
        from tracksplit.pipeline import process_file
        mock_probe.return_value = self._probe()
        src = tmp_path / "src.mkv"
        src.write_bytes(b"data" * 64)
        album_dir = tmp_path / "out" / "DJ X" / "Show 2025"
        album_dir.mkdir(parents=True)
        from tracksplit.manifest import (
            TAG_KEYS, build_album_manifest, save_album_manifest,
        )
        tags = {k: "" for k in TAG_KEYS}
        tags["artist"] = "DJ X"
        tags["festival"] = "Show"
        tags["date"] = "2025"
        m = build_album_manifest(
            source_path=src,
            chapters=[{"index": 1, "title": "Track 1", "start": 0.0, "end": 600.0}],
            tags=tags,
            artist_folder="DJ X",
            album_folder="Show 2025",
            output_format="flac", codec_mode="copy",
            track_filenames=["01 - DJ X - Track 1.flac"],
            cover_bytes=b"",
        )
        save_album_manifest(album_dir, m)

        assert process_file(src, tmp_path / "out") is False
        assert mock_rebuild.call_count == 0
