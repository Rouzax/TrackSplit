# Getting Started

This guide takes you from a fresh machine to a first successful album extraction.

## Prerequisites

TrackSplit is a thin, fast orchestrator around well-known media tools. Make sure these are installed first:

- **Python 3.11 or newer.** [python.org downloads](https://www.python.org/downloads/).
- **FFmpeg.** Provides `ffmpeg` (splitting, re-encoding) and `ffprobe` (chapter and stream inspection).
    - Linux: `sudo apt install ffmpeg` (Debian/Ubuntu), `sudo dnf install ffmpeg` (Fedora).
    - macOS: `brew install ffmpeg`.
    - Windows: `choco install ffmpeg`, `scoop install ffmpeg`, or grab a build from [ffmpeg.org](https://ffmpeg.org/download.html) and add the `bin/` folder to `PATH`.
- **MKVToolNix** (optional). Only needed if you want TrackSplit to extract cover art from MKV attachments. Install `mkvtoolnix` from your package manager.

## Install

```bash
pip install -e .
```

That registers the `tracksplit` command.

## Verify your setup

```bash
tracksplit --check
```

You should see something like:

```
✓ ffmpeg     ffmpeg version 7.0.2 ...
✓ ffprobe    ffprobe version 7.0.2 ...
✓ mkvextract mkvextract v82.0 ...
```

If any required tool is missing, TrackSplit prints an install hint and exits non-zero. Fix the missing tool (or point TrackSplit at a custom path via a [config file](configuration.md)) and run the check again.

## First run

Point TrackSplit at a chaptered video:

```bash
tracksplit ~/videos/your-set.mkv --output ~/music/library/
```

What happens:

1. TrackSplit probes the file with `ffprobe` to read chapters, tags, and duration.
2. It decides on a codec (FLAC stays FLAC; Opus stream-copies when safe, re-encodes otherwise; change it with `--format`).
3. It splits the audio at chapter boundaries with sample accuracy.
4. It generates album cover art and (if the source has DJ artwork) an artist folder image.
5. It writes all tracks into `Artist/Artist @ Festival Year (Stage)/`, tags them, and drops a `.tracksplit_chapters.json` manifest.
6. It prints a one-line summary naming the album directory and track count.

Run it again on the same file and it will skip instantly: TrackSplit compares the manifest to the source and only regenerates when something actually changed. Pass `--force` to override.

## Next

- [Usage](usage.md): every flag explained, with examples.
- [Configuration](configuration.md): using a TOML config for custom tool paths.
- [Output Structure](output.md): what TrackSplit writes and where.
