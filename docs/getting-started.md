# Getting Started

This page walks you from a fresh machine to your first successful album extraction.

## TrackSplit and CrateDigger: better together

TrackSplit works on any chaptered video file. But it works best when those files were prepared by **[CrateDigger](https://github.com/Rouzax/CrateDigger)**.

CrateDigger is a companion CLI that identifies festival sets and concert recordings, embeds chapter markers at every track boundary, and writes rich metadata directly into your MKV files: canonical artist names, festival and venue details, MusicBrainz IDs, and DJ artwork. TrackSplit reads all of that and uses it to produce a music library that is consistently named, properly linked, and ready for music servers like Jellyfin and Lyrion.

Without CrateDigger, TrackSplit still splits your video into tracks and tags them with whatever it can find in the file. With CrateDigger, every album comes out with the exact artist spelling, festival name, date, and MusicBrainz IDs that your music server needs to link artists, albums, and collaborators correctly. That is the 1+1=3.

If you already have a CrateDigger library, point TrackSplit at it and you are done. If you are starting fresh, consider setting up CrateDigger first.

## Before you start

TrackSplit is a command-line tool that relies on a few external programs. Check each category below before installing.

### Required: FFmpeg

FFmpeg is the tool TrackSplit uses to read your video files and split the audio. You need both `ffmpeg` and `ffprobe` (they come together in one install).

- **Linux (Debian/Ubuntu):** `sudo apt install ffmpeg`
- **Linux (Fedora):** `sudo dnf install ffmpeg`
- **macOS:** `brew install ffmpeg`
- **Windows:** `choco install ffmpeg` or `scoop install ffmpeg`. If you prefer a manual install, download a build from [ffmpeg.org](https://ffmpeg.org/download.html) and add its `bin/` folder to your `PATH`.

### Required: Python 3.11 or newer

Check what you have: `python3 --version`. If you need to upgrade, download from [python.org](https://www.python.org/downloads/).

### Optional: MKVToolNix

MKVToolNix provides `mkvextract` and `mkvmerge`, which TrackSplit uses to pull cover art out of MKV video attachments. Without it, TrackSplit falls back to extracting cover art from the video stream directly. You still get cover art either way; MKVToolNix just gives a more reliable result for MKV files that store artwork as attachments.

- **Linux:** `sudo apt install mkvtoolnix` (Debian/Ubuntu) or your distro's equivalent.
- **macOS:** `brew install mkvtoolnix`.
- **Windows:** download the installer from [mkvtoolnix.download](https://mkvtoolnix.download/downloads.html).

## Install TrackSplit

From the TrackSplit directory, run:

```bash
pip install -e .
```

This installs TrackSplit and its Python dependencies, and registers the `tracksplit` command. You do not need to install any extra Python packages manually.

## Verify your setup

Run the built-in check to confirm TrackSplit can find its tools:

```bash
tracksplit --check
```

You should see something like:

```
✓ ffmpeg     ffmpeg version 7.0.2 ...
✓ ffprobe    ffprobe version 7.0.2 ...
✓ mkvextract mkvextract v82.0 ...
```

What the symbols mean:

- `✓` (green): tool found and working.
- `✗` (red): required tool missing. TrackSplit will not run without it.
- `!` (yellow): optional tool missing. TrackSplit will still work, with reduced cover art extraction for MKV files.

If a required tool is missing, the check prints an install hint. Fix the missing tool and run `tracksplit --check` again before continuing. If the tool is installed but TrackSplit cannot find it, see [Configuration](configuration.md) to point TrackSplit at a custom path.

## Your first run

Point TrackSplit at a chaptered video file:

```bash
tracksplit ~/videos/your-set.mkv --output ~/music/library/
```

Replace `~/videos/your-set.mkv` with your file and `~/music/library/` with wherever you want the music to go.

If you leave out `--output`, TrackSplit writes into your current working directory.

### What TrackSplit does

1. Reads the video file to find chapters, tags, and audio format. Nothing is written yet.
2. Decides on an audio format for the output (FLAC for lossless sources, Opus for others). You can override this with `--format`.
3. Splits the audio at chapter boundaries into one file per chapter.
4. Generates album cover art. If the source has DJ artwork, it also generates an artist folder image.
5. Tags every track with the album, artist, date, and other metadata from the source file.
6. Writes everything into a folder like `Artist/Festival Year (Stage)/` inside your output directory.
7. Saves a small record file (`.tracksplit_manifest.json`) in the album folder so future runs can detect whether anything changed.
8. Prints a one-line summary: the album folder name and how many tracks were written.

## What success looks like

After a successful run you will see a summary line in the terminal, such as:

```
Done: Afrojack/Tomorrowland 2024 (Mainstage), 14 tracks
```

And your output directory will contain:

```
~/music/library/
  Afrojack/
    folder.jpg
    artist.jpg
    Tomorrowland 2024 (Mainstage)/
      01 - Track Title.flac
      02 - Track Title.flac
      ...
      cover.jpg
      .tracksplit_manifest.json
```

- `*.flac` (or `*.opus`): one audio file per chapter, tagged and ready for your music server.
- `cover.jpg`: album cover image, also embedded inside every track file.
- `folder.jpg` and `artist.jpg`: artist-level images that Jellyfin, Lyrion, and Kodi pick up automatically.
- `.tracksplit_manifest.json`: a small record TrackSplit uses internally to avoid repeating work. You can delete it if you want to force a full rebuild; you do not need to back it up.

If the source has simpler metadata (no CrateDigger tags), the album folder will be named after the source filename instead of a festival name. You still get the same tracks, tags, and artwork.

## What does NOT change

TrackSplit only reads your source video files. It never modifies, moves, or deletes them. All output goes to the directory you specify (or your current working directory).

## Running it a second time

Run the same command again and TrackSplit will finish almost instantly:

```bash
tracksplit ~/videos/your-set.mkv --output ~/music/library/
```

TrackSplit checks the `.tracksplit_manifest.json` record against the source file. If nothing meaningful changed (chapters, tags, audio format), it skips the album entirely. This makes it safe and fast to run TrackSplit regularly against a large video library.

To force a full rebuild even when nothing changed, add `--force`:

```bash
tracksplit ~/videos/your-set.mkv --output ~/music/library/ --force
```

## What to do next

- [Usage](usage.md): all command-line options explained, with examples for common situations.
- [Configuration](configuration.md): how to set custom tool paths if TrackSplit cannot find them automatically.
- [Output Structure](output.md): a detailed breakdown of every file and tag TrackSplit creates.
- [Troubleshooting](troubleshooting.md): what to do when something goes wrong.
