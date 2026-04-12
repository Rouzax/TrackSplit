# Usage

TrackSplit takes a video file or a directory of video files and writes one tagged album per input.

## Synopsis

```
tracksplit [OPTIONS] INPUT_PATH
```

`INPUT_PATH` is either a video file or a directory. Recognised video extensions: `.mkv`, `.mp4`, `.webm`, `.avi`, `.mov`, `.m2ts`, `.ts`, `.flv`.

## Options

| Flag | Description |
|------|-------------|
| `--output`, `-o PATH` | Output directory. Defaults to the current working directory. |
| `--force` | Regenerate even if the per-album manifest matches. |
| `--format`, `-f {auto,flac,opus}` | Output codec. `auto` picks FLAC for lossless sources and Opus for lossy. |
| `--workers`, `-w N` | Parallel workers for directory mode. Default `min(4, CPU count)`. Set `1` for sequential; raise for fast disks. |
| `--dry-run` | Probe and plan without writing anything. Pairs well with `--verbose`. |
| `--verbose`, `-v` | INFO-level logging. Shows the current step and file. |
| `--debug` | DEBUG-level logging. Includes full command lines and subprocess details. |
| `--check` | Probe `ffmpeg`/`ffprobe`/`mkvextract` and exit. |
| `--help`, `-h` | Show the auto-generated help. |

## Examples

**Single file, sensible defaults:**

```bash
tracksplit video.mkv
```

**Batch a folder into a music library:**

```bash
tracksplit ~/videos/ --output ~/music/library/
```

**Force Opus output regardless of source:**

```bash
tracksplit video.mkv --format opus
```

**Preview what would happen without writing anything:**

```bash
tracksplit video.mkv --dry-run --verbose
```

**Rebuild an album even if nothing changed:**

```bash
tracksplit video.mkv --force
```

**Serial processing on a slow disk:**

```bash
tracksplit ~/videos/ --workers 1
```

## Progress display

- **Single file:** a spinner shows the current pipeline step (probing, extracting, splitting, tagging, saving) and ends with a one-line summary naming the album directory and track count.
- **Directory:** a live progress bar shows `completed/total`, with one spinner line per active worker. A summary panel at the end breaks down processed / skipped / failed / cancelled counts.

## Errors and cancellation

Failures that have a known cause (missing tool, disk full, FFmpeg subprocess error) are printed as a one-line reason. Full tracebacks are kept behind `--debug`.

Pressing `Ctrl+C` sets a cancellation flag, kills in-flight FFmpeg subprocesses, and reports any in-flight files as `cancelled` in the summary.
