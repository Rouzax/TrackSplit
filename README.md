# TrackSplit

Extract audio from video chapters into FLAC music albums for Jellyfin and Lyrion.

## Features

- Splits video audio into individual tracks at chapter boundaries
- Codec-aware output: FLAC for lossless sources, Opus stream-copy or re-encode for lossy
- Gapless playback (sample-accurate splitting)
- Rich metadata tagging (Vorbis comments)
- Album and artist cover art generation (1:1, embedded + folder)
- Two-tier metadata: basic (any video with chapters) or enriched (CrateDigger tags)
- Re-run detection: only regenerates when chapters change

## Requirements

- Python 3.11+
- ffmpeg / ffprobe
- mkvextract (optional, for MKV cover art)

## Install

```bash
pip install -e .
```

## Usage

```bash
# Single video
tracksplit video.mkv

# Directory of videos
tracksplit /path/to/videos/

# Specify output directory
tracksplit video.mkv --output /path/to/music/library/

# Force regeneration
tracksplit video.mkv --force

# Choose output format (auto, flac, or opus)
tracksplit video.mkv --format opus

# Dry run
tracksplit video.mkv --dry-run --verbose
```

## Output Structure

```
Artist/
  folder.jpg
  artist.jpg
  Artist @ Festival Year (Stage)/
    00 - Intro.flac (or .opus)
    01 - Track Title.flac
    02 - Track Title.flac
    cover.jpg
    .tracksplit_chapters.json
```

## Tags Written

TITLE, ARTIST, ALBUMARTIST, ALBUM, TRACKNUMBER, TRACKTOTAL, DISCNUMBER,
DATE, GENRE, PUBLISHER, COMMENT, MUSICBRAINZ_ARTISTID, FESTIVAL, STAGE, VENUE

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

Run integration tests with a real video file:

```bash
TRACKSPLIT_TEST_VIDEO=/path/to/video.mkv pytest tests/test_integration.py -v
```
