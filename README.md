![TrackSplit](docs/assets/hero-banner.jpg)

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/license-GPL--3.0-green" alt="GPL-3.0">
  <img src="https://img.shields.io/badge/version-v0.6.1-orange" alt="v0.6.1">
</p>

<p align="center"><em>Chapter-based audio extractor for music servers. Turn your chaptered video library into gapless, tagged FLAC or Opus albums ready for Jellyfin and Lyrion.</em></p>

## What is TrackSplit?

TrackSplit is a Python CLI that reads chapter markers from video files (MKV, MP4, WebM, and more), splits the audio into individual tracks at sample-accurate boundaries, and writes a fully tagged music album with embedded cover art and an artist folder picture. FLAC sources stay lossless; Opus and other lossy sources are stream-copied when possible. Re-runs are skipped automatically unless the chapters actually changed.

It pairs naturally with [CrateDigger](https://github.com/Rouzax/CrateDigger), which embeds chapter markers, canonical metadata, and DJ artwork into your MKV library. Together the two tools keep artist names, festival spellings, and MusicBrainz IDs consistent across your video and music libraries. TrackSplit also works on any chaptered video without CrateDigger.

## Cover Gallery

**Album covers** generated for each set (embedded in every track and saved as `cover.jpg` / `folder.jpg`):

<table>
  <tr>
    <td><img src="docs/assets/posters/album-01.jpg" width="200"></td>
    <td><img src="docs/assets/posters/album-02.jpg" width="200"></td>
    <td><img src="docs/assets/posters/album-03.jpg" width="200"></td>
    <td><img src="docs/assets/posters/album-04.jpg" width="200"></td>
    <td><img src="docs/assets/posters/album-05.jpg" width="200"></td>
  </tr>
</table>

**Artist folder images** (`artist.jpg`) composed from DJ artwork and name:

<table>
  <tr>
    <td><img src="docs/assets/posters/artist-01.jpg" width="200"></td>
    <td><img src="docs/assets/posters/artist-02.jpg" width="200"></td>
    <td><img src="docs/assets/posters/artist-03.jpg" width="200"></td>
    <td><img src="docs/assets/posters/artist-04.jpg" width="200"></td>
    <td><img src="docs/assets/posters/artist-05.jpg" width="200"></td>
  </tr>
</table>

## Features

- **Chapter-accurate splitting.** Sample-accurate cuts at chapter boundaries, gapless playback across tracks.
- **Codec-aware output.** FLAC for lossless sources, Opus stream-copy when safe, transparent re-encode when not. Pick with `--format`.
- **Rich metadata.** Writes TITLE, ARTIST, ARTISTS, ALBUMARTIST, ALBUMARTISTS, ALBUM, TRACKNUMBER, TRACKTOTAL, DISCNUMBER, DATE, GENRE, PUBLISHER, COMMENT, MUSICBRAINZ_ARTISTID, MUSICBRAINZ_ALBUMARTISTID, FESTIVAL, STAGE, VENUE as Vorbis comments.
- **Multi-artist aware.** Writes Picard-standard `ARTISTS` and aligned per-artist `MUSICBRAINZ_ARTISTID` so Lyrion and Jellyfin link every collaborator and remixer, not just the headliner.
- **Album and artist artwork.** Generates 1:1 cover art (embedded in every track and written to `cover.jpg` / `folder.jpg`) and an artist folder image.
- **Two metadata tiers.** Basic tagging for any chaptered video. Full enrichment when CrateDigger-style tags are present.
- **Re-run detection.** A manifest in each album folder tracks chapter hashes and source mtime, so repeat runs on the same library are near-instant.
- **Parallel batch mode.** Process a directory of videos with multiple workers and a live progress display.
- **Update notifications.** Interactive runs check GitHub for newer releases and show a one-line upgrade hint. See [Update Notifications](#update-notifications).

## Quick Start

### Prerequisites

- [Python 3.11+](https://www.python.org/downloads/)
- [FFmpeg](https://ffmpeg.org/download.html) (ships `ffmpeg` and `ffprobe`)
- [MKVToolNix](https://mkvtoolnix.download/downloads.html) (optional, provides `mkvextract` and `mkvmerge` for cover extraction from MKV attachments; TrackSplit falls back to FFmpeg if not installed)

### Install

Choose the path that fits how you use TrackSplit:

**pipx (recommended for end users):** installs TrackSplit into its own isolated environment and puts the `tracksplit` command on your PATH without affecting other Python projects.

```bash
pipx install git+https://github.com/Rouzax/TrackSplit.git
```

Upgrade later with:

```bash
pipx upgrade tracksplit
```

**pip (user site or venv):** use this if you prefer pip or are installing into an active virtual environment.

```bash
pip install git+https://github.com/Rouzax/TrackSplit.git
```

Upgrade later with:

```bash
pip install --upgrade git+https://github.com/Rouzax/TrackSplit.git
```

**From source (contributors):** clone the repository, then install in editable mode:

```bash
pip install -e .
```

After installing, verify your setup:

```bash
tracksplit --check
```

`tracksplit --check` probes `ffmpeg`, `ffprobe`, and `mkvextract` and prints their versions (or an install hint if something is missing).

### Usage

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

## Configuration

TrackSplit works out of the box if `ffmpeg`, `ffprobe`, and (optionally) the MKVToolNix tools are on your `PATH`. If they are installed elsewhere, point TrackSplit at them via a TOML config. Copy [`tracksplit.toml.example`](tracksplit.toml.example) and uncomment the keys you need.

Place your config file at the location for your platform:

| Platform | Config file location |
|---|---|
| Linux | `~/TrackSplit/config.toml` |
| macOS | `~/TrackSplit/config.toml` |
| Windows | `Documents\TrackSplit\config.toml` |

```toml
[tools]
ffmpeg     = "/usr/local/bin/ffmpeg"
ffprobe    = "/usr/local/bin/ffprobe"
mkvextract = "/usr/bin/mkvextract"
mkvmerge   = "/usr/bin/mkvmerge"
```

See [`docs/troubleshooting.md`](docs/troubleshooting.md) if something goes wrong on first run.

## Update Notifications

When you run TrackSplit interactively and a newer stable release is available on GitHub, it prints a one-line notice showing the new version and the upgrade command for your install method:

```
! TrackSplit 0.6.9 is available. Run: pipx upgrade tracksplit
```

The check runs in the background with a 2-second timeout, never delays your run, and is silent on any network failure. Results are cached locally for 24 hours.

**Automatic suppression.** The notice is suppressed whenever stdout is not a terminal, including pipes, redirects, cron jobs, and CI environments.

**Disable explicitly.** Set `TRACKSPLIT_NO_UPDATE_CHECK=1` before running. The values `true` and `yes` are also accepted, case-insensitively.

No telemetry: the check is a read-only request to the GitHub Releases API. See [`docs/usage.md#update-notifications`](docs/usage.md#update-notifications) for the full reference, including cache location and the failed-check interval.

## Output Structure

```
Artist/
  folder.jpg
  artist.jpg
  Festival Year (Stage)/
    00 - Intro.flac (or .opus)
    01 - Track Title.flac
    02 - Track Title.flac
    cover.jpg
    .tracksplit_manifest.json
```

(Tier 2, CrateDigger-tagged source.) Tier 1 sources without festival metadata get `Artist/<filename-stem>/` instead.

`.tracksplit_manifest.json` is a record TrackSplit uses to detect whether a source file has changed since the last run. Safe to delete if you want to force one album to rebuild; safe to ignore in version control.

## Related projects

**[CrateDigger](https://github.com/Rouzax/CrateDigger)** is the sibling CLI that matches festival sets and concert recordings against 1001Tracklists, embeds chapter markers and metadata into MKV files, generates artwork and posters, and syncs your video library into Kodi. TrackSplit consumes the chapters and metadata CrateDigger writes, so the two tools share canonical artist names, festival spellings, and MusicBrainz IDs across your video and music libraries.

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

Run integration tests with a real video file:

```bash
TRACKSPLIT_TEST_VIDEO=/path/to/video.mkv pytest tests/test_integration.py -v
```

## Disclaimer

Artwork displayed in this project is generated from DJ source images and chapter metadata that originates with CrateDigger and public festival/event material. All artwork, logos, and trademarks belong to their respective owners. TrackSplit is not affiliated with any festival, artist, or platform shown.

## License

This project is licensed under the GPL-3.0 License. See [LICENSE](LICENSE) for details.
