# Usage

TrackSplit is a single command. You point it at a video file or a folder of videos, and it produces a tagged music album (or a batch of albums) in your output directory.

## Synopsis

```
tracksplit [OPTIONS] INPUT_PATH
```

`INPUT_PATH` can be one video file or a directory. Recognised video extensions: `.mkv`, `.mp4`, `.webm`, `.avi`, `.mov`, `.m2ts`, `.ts`, `.flv`.

## Single file or directory?

**Single file:** use this when you want to process one video and check the result before committing to a full batch.

```bash
tracksplit video.mkv --output ~/music/library/
```

**Directory:** use this when you have a folder of videos and want them all turned into albums in one go. TrackSplit scans the folder for recognised video files and processes them in parallel.

```bash
tracksplit ~/videos/ --output ~/music/library/
```

Both modes write the same output structure. The difference is that directory mode shows a progress bar and processes multiple files at once.

## Options explained

### `--output` / `-o`

Where to write the albums. TrackSplit creates an `Artist/Album/` folder structure inside this directory.

```bash
tracksplit video.mkv --output ~/music/library/
```

If you leave this out, TrackSplit writes into your current working directory. On a first run you almost always want to set this explicitly so your music ends up where your server can find it.

### `--format` / `-f`

What audio format to use for the output files. Your choices are `auto`, `flac`, or `opus`.

- **`auto` (default):** TrackSplit inspects the audio inside the video and picks the best format automatically. Lossless sources (FLAC, ALAC, uncompressed PCM) are extracted as `.flac` files. Opus audio is copied directly to `.opus`. Everything else (AAC, MP3, and other lossy formats) is converted to `.opus`. Use `auto` unless you have a specific reason to override it.
- **`flac`:** always produce `.flac` files, regardless of the source. Use this if your music server or listening setup requires lossless files.
- **`opus`:** always produce `.opus` files. Use this if you want smaller files and do not need lossless quality.

```bash
# Let TrackSplit decide (recommended)
tracksplit video.mkv --format auto

# Always lossless
tracksplit video.mkv --format flac

# Always Opus
tracksplit video.mkv --format opus
```

### `--force`

Normally TrackSplit skips an album if it already processed it and nothing changed. `--force` tells it to rebuild the album from scratch, no matter what.

Use this when:
- you changed a setting (like `--format`) and want to regenerate with the new choice,
- you manually edited or deleted some output files and want a clean rebuild,
- something went wrong mid-run and you want to start fresh.

```bash
tracksplit video.mkv --output ~/music/library/ --force
```

### `--dry-run`

Probes the video and shows you what TrackSplit *would* do, without writing any files. No tracks, no artwork, and no manifest are created.

Use this to preview the album name, track count, and output path before committing.

```bash
tracksplit video.mkv --dry-run --verbose
```

Pair it with `--verbose` to see each step printed out.

### `--workers` / `-w`

How many videos to process at the same time in directory mode. Only relevant when you pass a directory.

The default scales with your CPU: `logical_cores / 4`, with a minimum of 2 and a maximum of 12. On a typical 8-core laptop this is 2; on a 16-thread workstation it is 4.

- **Raise it** if your source files use Opus audio (the output is a fast copy, not a re-encode, so CPU is nearly idle and you can run more at once).
- **Lower it to 1** if your disk is slow, you are on a network share, or you see hangs and want to rule out contention.

```bash
# Sequential, one file at a time
tracksplit ~/videos/ --workers 1

# More parallel for a fast SSD with Opus sources
tracksplit ~/videos/ --workers 8
```

### `--verbose` / `-v` and `--debug`

- `--verbose`: prints each pipeline step as it happens (probing, splitting, tagging, saving). Good for following along or confirming a dry run.
- `--debug`: prints the full command lines sent to FFmpeg and all subprocess output. Use this when something fails and you want to see exactly what went wrong.

### `--check`

Verify your environment before processing any files. TrackSplit checks that all required external tools are installed, config files are present, and Python packages are available, then exits without processing any video files.

```bash
tracksplit --check
```

TrackSplit prints a grouped report with a status marker for each item:

- `✓` the item is present and working
- `!` the item is missing or unconfigured, but optional
- `✗` the item is missing and required
- `~` informational (using built-in defaults, such as when no config file is present)

A summary line at the end reports `All checks passed.` when nothing is wrong, or counts the errors and warnings otherwise.

The command exits with code 0 if all required checks pass. Warnings (optional items missing) do not affect the exit code. The command exits with code 1 if any required tool or Python package is absent.

Use this after installing TrackSplit to confirm your setup is complete, or after changing a [config file](configuration.md) to verify the new paths work.

### `--version`

Print the installed version and exit.

```bash
tracksplit --version
```

### `--help` / `-h`

Prints the built-in help text and exits.

## What you see while it runs

### Single file

A spinner shows the current step (probing, extracting, tagging, saving artwork). When it finishes, a single summary line appears:

```
  done  your-set.mkv: Artist/Festival Year (Stage), 14 tracks
```

If the file was skipped because nothing changed:

```
  skip  your-set.mkv (unchanged)
```

### Directory

A progress bar shows how many files are done out of the total. Below it, one spinner line appears per active worker, each showing which file it is currently working on. When all files finish, a summary panel appears:

```
Processed  12
Skipped     3
Failed      0
Cancelled   0
```

## What it means when a file is skipped

TrackSplit keeps a small record file (`.tracksplit_manifest.json`) in each album folder. On subsequent runs it compares the source file and its settings against that record. If nothing meaningful has changed (same audio stream, same chapters, same embedded tags, same output format), it skips the album without redoing any work. Surface-level file edits that do not touch the audio or embedded tags, such as a `touch` command or a re-import that only updates the file's modification time, do not cause a rebuild.

A skipped file is not an error. It means the output is already up to date.

To force a rebuild for everything, pass `--force`. To rebuild a single album, delete its `.tracksplit_manifest.json` and re-run.

## What Ctrl+C does

Pressing `Ctrl+C` while TrackSplit is running:

1. Sets a stop signal so no new files start processing.
2. Kills any FFmpeg processes that are currently running.
3. Prints `Interrupted, stopping...`
4. Reports any in-progress files as `cancelled` in the final summary.

Partially-written output files may be left behind. Re-running without `--force` will complete files that finished cleanly; cancelled files will be rebuilt from scratch.

## Update notifications

When you run TrackSplit interactively and a newer stable release is available on GitHub, it prints a short notice at the top of its output. The notice shows the new version number and the upgrade command for your install method (pipx, uv, or pip). It looks like this:

```
! TrackSplit 0.6.9 is available. Run: pipx upgrade tracksplit
```

The check is unobtrusive by design. It runs in the background with a 2-second network timeout, never delays or blocks your run, and is silent on any network failure. Results are cached locally for 24 hours (1 hour after a failed check), so the check happens at most once per day.

**When it stays silent automatically:** the notice is suppressed whenever stdout is not a terminal, including pipes, redirects, cron jobs, and CI environments. Nothing extra is needed in those contexts.

**To disable it explicitly:** set the environment variable `TRACKSPLIT_NO_UPDATE_CHECK=1` before running. The values `true` and `yes` are also accepted, case-insensitively.

```bash
TRACKSPLIT_NO_UPDATE_CHECK=1 tracksplit ~/videos/ --output ~/music/library/
```

**Cache location:**

| Platform | Path |
|---|---|
| Linux | `~/.cache/TrackSplit/update-check.json` |
| macOS | `~/Library/Caches/TrackSplit/update-check.json` |
| Windows | `$env:LOCALAPPDATA\TrackSplit\Cache\update-check.json` |

To force a fresh check, delete the cache file. TrackSplit will check GitHub again on the next run.

## Examples

**Turn a single video into an album:**

```bash
tracksplit ~/videos/set.mkv --output ~/music/library/
```

TrackSplit reads the file, splits the audio at chapter boundaries, tags everything, generates cover art, and writes the album into `~/music/library/Artist/Album/`.

**Process a whole folder of videos into a music library:**

```bash
tracksplit ~/videos/ --output ~/music/library/
```

Every recognised video in `~/videos/` becomes an album. Already-processed files are skipped automatically on repeat runs.

**Preview without writing anything:**

```bash
tracksplit ~/videos/set.mkv --dry-run --verbose
```

Shows what album name, track count, and output path would be produced. Nothing is written to disk.

**Rebuild after changing format or when something looks wrong:**

```bash
tracksplit ~/videos/set.mkv --output ~/music/library/ --force --format flac
```

Ignores the existing album and regenerates everything from scratch as FLAC files.

## Advanced details

### How `--format auto` picks the output codec

TrackSplit reads the codec of the first audio stream inside the video:

- **Opus input:** copied directly to `.opus` without re-encoding.
- **Lossless input** (FLAC, ALAC, or uncompressed PCM): extracted to `.flac` without re-encoding.
- **Any other lossy input** (AAC, MP3, etc.): encoded to `.opus` using libopus.

The decision is based on the audio codec inside the video, not the video container. An MKV file with Opus audio produces `.opus`; an MKV file with FLAC audio produces `.flac`.

### Tuning `--workers` by workload

The default (`logical_cores / 4`, clamped to 2-12) is sized for re-encode workloads where FFmpeg is CPU-intensive. For stream-copy workloads (Opus source to Opus output), CPU usage per worker is near zero and you can safely run more in parallel:

| Workload | CPU per worker | Suggested `--workers` |
|---|---|---|
| Opus source (copy, no re-encode) | Near zero | 2-3x the default; bottleneck becomes disk I/O |
| FLAC output or forced Opus re-encode | High | Stick with the default |
| Mixed batch | Varies | Default is a safe compromise |

A quick way to check: watch CPU usage while a batch runs. If it sits near idle, you have headroom to raise `--workers`. If it sits near 100%, do not raise it further.

## Related pages

- [Getting Started](getting-started.md): install and first run.
- [Configuration](configuration.md): set custom tool paths when TrackSplit cannot find them automatically.
- [Output Structure](output.md): every file and tag TrackSplit creates.
- [Troubleshooting](troubleshooting.md): what to do when something goes wrong.
