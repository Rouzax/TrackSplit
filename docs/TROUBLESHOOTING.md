# Troubleshooting

First step for any issue: run `tracksplit --check`. It probes `ffmpeg`, `ffprobe`, and `mkvextract` and prints their versions or an install hint.

## `ffmpeg` / `ffprobe` not found

TrackSplit needs both on your `PATH`, or at a path you configure.

- **Linux:** `sudo apt install ffmpeg` (Debian/Ubuntu), `sudo dnf install ffmpeg` (Fedora), or your distro's package.
- **macOS:** `brew install ffmpeg`.
- **Windows:** `choco install ffmpeg`, `scoop install ffmpeg`, or download from ffmpeg.org and add the `bin/` folder to `PATH`.

If you must use a non-standard install path, copy `tracksplit.toml.example` to one of the config locations (see README "Configuration") and set the absolute paths under `[tools]`.

## `mkvextract` not found (warning only)

Optional. Only used to extract embedded cover art from MKV attachments. Install with `mkvtoolnix` from your package manager if you want cover extraction from MKV attachments rather than video streams.

## Video is skipped with "No chapters and no duration"

TrackSplit splits at chapter boundaries. If a file has no chapters and `ffprobe` can't read its duration, there's nothing to split. Options:

- Re-author the source with chapter markers (for example, via MKVToolNix).
- If you want one big track anyway, make sure the video at least has a readable duration. TrackSplit will then emit a single-track album.

## Run failed mid-file with a stack trace

- **`CalledProcessError` from `ffmpeg`:** the underlying `ffmpeg` run failed. Re-run with `--debug` to see the exact command and `ffmpeg`'s stderr. Common causes: corrupt input, unusual codec, or disk full.
- **`FileNotFoundError`** naming a tool: the tool moved or was uninstalled since you last ran. Re-check with `tracksplit --check`.
- **`OSError: [Errno 28] No space left on device`** or similar: free space on the output volume.

## Output went to the wrong directory

TrackSplit writes under the current working directory unless you pass `--output`. If batch-processing, double-check: output is `<output_dir>/<Artist>/<Artist @ Festival Year (Stage)>/`.

## Files are re-generated every run (or never)

TrackSplit tracks re-run state via `.tracksplit_chapters.json` (a manifest) inside each album directory. Delete that file to force a full regeneration for that album; pass `--force` to regenerate everything. The manifest is safe to commit, ignore, or delete at will: it's metadata only, not part of your music library.

## Parallel mode is slow or hanging

- Set `--workers 1` to rule out contention.
- Fast SSDs can go higher than the default; try `--workers 8`.
- On spinning disks or network shares, sequential (`--workers 1`) is usually faster.

## Cover art looks wrong or fonts are missing

Fonts are bundled with the package. If you see a `FileNotFoundError` about a weight, reinstall the package: `pip install -e . --force-reinstall`.

## Still stuck?

Re-run with `--debug` and capture the full output. Open an issue with:

- The failing command line.
- The `--debug` log.
- `ffmpeg -version` and `ffprobe -version` output.
- The OS and how you installed TrackSplit.
