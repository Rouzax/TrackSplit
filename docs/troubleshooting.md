# Troubleshooting

**First step for any issue:** run `tracksplit --check`. It tests whether `ffmpeg`, `ffprobe`, and `mkvextract` are reachable and prints their versions or an install hint. Most setup problems show up here.

If the check passes but something still goes wrong, re-run your command with `--debug`. This prints the exact FFmpeg commands TrackSplit runs and all subprocess output, which usually points straight at the cause.

---

## TrackSplit says ffmpeg or ffprobe is missing

**What you see:** `tracksplit --check` prints a red `✗` next to `ffmpeg` or `ffprobe`, with an install hint.

**What is happening:** TrackSplit cannot find one or both tools on your `PATH`. Both are required and come together in a single FFmpeg install.

**Fix:**

- **Linux (Debian/Ubuntu):** `sudo apt install ffmpeg`
- **Linux (Fedora):** `sudo dnf install ffmpeg`
- **macOS:** `brew install ffmpeg`
- **Windows:** `choco install ffmpeg` or `scoop install ffmpeg`. If you installed manually, make sure the `bin/` folder is added to your `PATH`.

After installing, run `tracksplit --check` again to confirm the green `✓` appears for both tools.

If FFmpeg is installed but in a non-standard location, see [Configuration](configuration.md) to point TrackSplit at the exact path.

---

## TrackSplit says mkvextract is missing

**What you see:** `tracksplit --check` prints a yellow `!` next to `mkvextract`.

**What is happening:** MKVToolNix is not installed. This is optional. TrackSplit will still run and still generate cover art, but it uses a fallback method (reading from the video stream) rather than extracting MKV attachment covers directly.

**Fix:** Install MKVToolNix from your package manager (`mkvtoolnix`) if you want the best cover extraction for MKV files. Otherwise you can ignore this warning.

---

## The video was skipped with no output

**What you see:** A `skip` line in the terminal but no album folder appeared.

**Two common causes:**

1. **The album already exists and nothing changed.** TrackSplit detected that it already processed this file and the output is up to date. This is normal behaviour on repeat runs. To force a rebuild, add `--force` to your command.

2. **The file has no chapters and no readable duration.** TrackSplit splits audio at chapter boundaries. If a file has no chapters and FFprobe cannot determine its duration, there is nothing to work with and the file is skipped with a warning.

   - If you expected chapters but there are none, the source may have had them stripped. Tools like MKVToolNix can add chapter markers, or [CrateDigger](https://github.com/Rouzax/CrateDigger) can embed them automatically.
   - If you want a single-track album from a file with no chapters, make sure the file has a readable duration. TrackSplit will then produce one track covering the whole file.

**To see exactly which reason triggered**, re-run with `--verbose`.

---

## A run failed partway through

**What you see:** An error message mid-run, possibly with a traceback.

**FFmpeg returned an error:**

The underlying FFmpeg command failed. Common causes: corrupt input file, an unusual codec, or the disk filling up mid-write.

Fix: re-run with `--debug` to see the exact FFmpeg command and its error output. That usually identifies the cause immediately.

**A tool is no longer found:**

A tool was found during `--check` but is now missing or was moved. Re-run `tracksplit --check` to see which tool is affected, then reinstall or update your [config file](configuration.md).

**`No space left on device` or similar disk error:**

Free up space on your output volume and re-run. TrackSplit will skip albums that completed cleanly and only redo the ones that did not finish.

---

## Output appeared in the wrong place

**What you see:** An album folder appeared somewhere unexpected, not where you intended.

**What is happening:** If you did not pass `--output`, TrackSplit writes into your current working directory, whatever that is when you run the command.

**Fix:** Always pass `--output` explicitly:

```bash
tracksplit ~/videos/set.mkv --output ~/music/library/
```

The full output path for an album is: `<output>/<Artist>/<Festival Year (Stage)>/` for CrateDigger-tagged festival sets, `<output>/<Artist>/<Venue Year>/` for CrateDigger-tagged venue recordings without a festival tag, or `<output>/<Artist>/<filename-stem>/` for plain chaptered videos.

---

## Files are rebuilt every run even though nothing changed

**What you see:** TrackSplit processes the same files repeatedly instead of skipping them.

**What is happening:** TrackSplit uses a `.tracksplit_manifest.json` file in each album folder to detect whether a rebuild is needed. If that file is missing, unreadable, or was written by an older version with a different format, TrackSplit rebuilds the album.

**Fix:**

- Check that the album folder contains a `.tracksplit_manifest.json` file after a run. If it does not appear, TrackSplit may be writing to a different output directory than you expect.
- If the manifest exists but rebuilds keep happening, re-run with `--verbose` to see what changed.
- If you changed `--format` or `--output` since the last run, a rebuild is expected and correct.

---

## Files are never rebuilt even after I changed something

**What you see:** TrackSplit skips an album you know needs updating.

**Fix:** Pass `--force` to rebuild everything, or delete the `.tracksplit_manifest.json` in the specific album folder to rebuild just that one album.

```bash
# Rebuild one album
tracksplit ~/videos/set.mkv --output ~/music/library/ --force
```

---

## Batch processing is slow or hanging

**What you see:** Directory mode is making slow progress, or individual workers appear stuck.

**Start here:** set `--workers 1` to process files sequentially. If that fixes the hang, the problem is contention between workers (common on spinning disks and network shares).

**If it is just slow:**

The default worker count is tuned for re-encode workloads (FLAC output or Opus-from-AAC). If your sources are Opus audio (common with CrateDigger MKVs), the output is a fast copy and CPU usage per worker is near zero. You can run many more workers safely:

| Workload | CPU per worker | Suggested `--workers` |
|---|---|---|
| Opus source to Opus output (copy) | Near zero | 2-3x the default; bottleneck becomes disk I/O |
| FLAC output or Opus re-encode | High | Stick with the default |
| Mixed batch | Varies | Default is a safe compromise |

Quick check: watch CPU while a batch runs. Near idle means you can raise `--workers`. Near 100% means you should not.

On spinning disks or network shares, `--workers 1` is usually faster than the default regardless of codec, because disk seeks between parallel writes cost more than any CPU saving.

---

## Short click or gap between tracks

**What you see:** A brief click at the start of each non-first track, or a gap of 1-2 seconds, when playing Opus output.

**Step 1: Check whether your player supports gapless playback.**

The Jellyfin mobile app decodes tracks independently and does not support gapless playback. A 1-2s gap between tracks in that app is a player architecture limitation that no file-level change can remove. Use Symfonium, mpv, or another gapless-aware player if seamless playback matters to you. FLAC output is inherently gapless in any player that handles FLAC correctly.

**Step 2: If your player is gapless-aware and a click is still audible, check whether the files were produced by version 0.6.5 or later.**

Earlier versions did not insert the warmup frame, so the first window of each non-first track could lose audio and sometimes decoded as silence. Re-run TrackSplit on the source video to trigger a rebuild; the manifest staleness check will detect the outdated output and replace it.

**Step 3: If the click persists on a gapless-aware player after rebuilding, gather diagnostic information.**

Run `opusinfo` on a few consecutive output tracks and open an issue, including the `opusinfo` output, the exact player and version, and the output of `tracksplit --check`.

---

## Album covers look outdated after upgrading TrackSplit

**What you see:** `cover.jpg`, `folder.jpg`, and embedded track artwork still show the old cover layout after upgrading TrackSplit, even though audio tracks are correct.

**What is happening:** Earlier versions had no way to detect that the cover renderer had changed, so existing albums kept their old cover files until you forced a full rebuild. Since version 0.6.7, TrackSplit tracks which cover layout was used for each album and detects the mismatch automatically on the next normal run.

**What to do:** Nothing. On the first run after upgrading, TrackSplit recomposes and re-embeds the cover for each affected album and logs either `Cover-only rebuild for <album>: N track(s) re-embedded` or `Cover already current for <album>; schema version bumped`. Audio is not re-extracted or re-encoded during this refresh, so it completes quickly. You do not need to pass `--force`.

---

## Cover art looks wrong or fonts are missing

**What you see:** An error mentioning a missing font file, or generated artwork looks broken.

**What is happening:** A font file bundled with TrackSplit is missing or corrupt.

**Fix:** Reinstall the package:

```bash
pip install -e . --force-reinstall
```

---

## Where are my logs?

TrackSplit writes a rotating log file on every run, in addition to what it prints in the terminal. The log file is at:

| Platform | Path |
|---|---|
| Linux | `~/.local/state/TrackSplit/log/tracksplit.log` |
| macOS | `~/Library/Logs/TrackSplit/tracksplit.log` |
| Windows | `%LOCALAPPDATA%\TrackSplit\Logs\tracksplit.log` |

The log rotates when it reaches 5 MB, and TrackSplit keeps the five most recent files (`tracksplit.log`, `tracksplit.log.1`, up to `tracksplit.log.5`). Older backups are deleted automatically.

The log file contains the same information as `--debug` output, so it is the first place to look if something went wrong during an unattended run. You do not need to re-run with `--debug` to retrieve it.

**Running multiple tracksplit invocations at once.** The log file is shared across concurrent runs. Python's rotating handler is not multi-process safe: two tracksplit processes rotating the file simultaneously can lose recent log lines on Linux, or produce a transient `PermissionError` on Windows. This does not affect processing of your video files; only the log output is at risk. If you regularly run tracksplit in parallel, stagger the runs or use separate `HOME` directories.

---

## "Legacy TrackSplit or CrateDigger files detected" warning

**What you see:** A `WARNING` line on startup listing one or more old paths.

**What is happening:** TrackSplit found files or directories at locations used by a version before 0.7.0. These paths are no longer read:

- `~/.config/tracksplit/config.toml` (old Linux/macOS config location)
- `~/.cache/tracksplit/` (old Linux/macOS cache location)
- `~/tracksplit.toml` or `~/.tracksplit.toml` (old home-directory config locations)

TrackSplit does not migrate them automatically.

**Fix:** For each listed path, choose one of:

- **Move it** to the new location. For a config file, copy it to `~/TrackSplit/config.toml` (Linux/macOS) or `Documents\TrackSplit\config.toml` (Windows).
- **Delete it** if you no longer need it.

The warning disappears on the next run once none of the old paths exist.

---

## Still stuck?

Re-run with `--debug` and save the full output. Then open an issue and include:

- The exact command you ran.
- The full `--debug` output.
- The output of `ffmpeg -version` and `ffprobe -version`.
- Your OS and how you installed TrackSplit.
